"""Scoring, timing, metadata, and artifact helpers for the infer-loop benchmark."""

# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import statistics
import subprocess
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any

from .models import (
    CATEGORIES,
    SUITE_VERSION,
    AttemptResult,
    BenchmarkCase,
    BenchmarkConfig,
    CaseResult,
    LLMCallResult,
)


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _numeric(value)
    return int(number) if number is not None else None


def _percent(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100.0) if denominator else 0.0, 3)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def _distribution(values: list[float]) -> dict[str, float | int]:
    """Return stable latency statistics in milliseconds."""
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "count": 0,
            "total_ms": 0.0,
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
        }
    return {
        "count": len(clean),
        "total_ms": round(sum(clean), 3),
        "mean_ms": round(statistics.fmean(clean), 3),
        "median_ms": round(statistics.median(clean), 3),
        "p95_ms": _percentile(clean, 0.95),
        "min_ms": round(min(clean), 3),
        "max_ms": round(max(clean), 3),
    }


def _speedup_percent(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return round((before - after) / before * 100.0, 3)


def _cache_probe(
    case_results: list[CaseResult],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare retry-free strict first attempts across adjacent repetitions."""
    first_by_case: dict[str, dict[int, AttemptResult]] = {}
    for result in case_results:
        if result.attempts:
            first_by_case.setdefault(result.case_id, {})[result.repetition] = result.attempts[0]

    e2e_speedups: list[float] = []
    llm_speedups: list[float] = []
    first_llm_speedups: list[float] = []
    prompt_eval_speedups: list[float] = []
    first_prompt_eval_speedups: list[float] = []
    pairs = 0
    excluded_retry_pairs = 0
    for repetitions in first_by_case.values():
        for repetition in sorted(repetitions):
            if repetition <= 1 or repetition - 1 not in repetitions:
                continue
            before = repetitions[repetition - 1]
            after = repetitions[repetition]
            if not before.strict_pass or not after.strict_pass or before.llm_calls != after.llm_calls:
                continue
            if (
                not before.timing_complete
                or not after.timing_complete
                or before.provider_retries
                or after.provider_retries
                or before.provider_attempts != before.completed_provider_attempts
                or after.provider_attempts != after.completed_provider_attempts
            ):
                excluded_retry_pairs += 1
                continue
            pairs += 1
            e2e = _speedup_percent(before.latency_ms, after.latency_ms)
            llm = _speedup_percent(before.llm_latency_ms, after.llm_latency_ms)
            first_llm = _speedup_percent(
                before.first_llm_latency_ms,
                after.first_llm_latency_ms,
            )
            prompt_eval = _speedup_percent(
                before.provider_prompt_eval_ms,
                after.provider_prompt_eval_ms,
            )
            before_first_prompt = _numeric(
                before.llm_call_timings[0].get("provider_prompt_eval_ms") if before.llm_call_timings else None
            )
            after_first_prompt = _numeric(
                after.llm_call_timings[0].get("provider_prompt_eval_ms") if after.llm_call_timings else None
            )
            first_prompt_eval = (
                _speedup_percent(before_first_prompt, after_first_prompt)
                if before_first_prompt is not None and after_first_prompt is not None
                else None
            )
            if e2e is not None:
                e2e_speedups.append(e2e)
            if llm is not None:
                llm_speedups.append(llm)
            if first_llm is not None:
                first_llm_speedups.append(first_llm)
            if prompt_eval is not None:
                prompt_eval_speedups.append(prompt_eval)
            if first_prompt_eval is not None:
                first_prompt_eval_speedups.append(first_prompt_eval)

    explicit_cache_calls = [
        call
        for call in calls
        if call.get("cached_input_tokens") is not None or call.get("cache_write_input_tokens") is not None
    ]
    return {
        "method": "paired_adjacent_case_repetitions",
        "interpretation": (
            "first-call timing compares equivalent initial provider inputs; whole-attempt timing also includes "
            "model-generated action history. Neither proves a provider cache hit"
        ),
        "eligible_strict_pairs": pairs,
        "excluded_retry_or_incomplete_pairs": excluded_retry_pairs,
        "median_e2e_speedup_percent": (round(statistics.median(e2e_speedups), 3) if e2e_speedups else None),
        "median_llm_speedup_percent": (round(statistics.median(llm_speedups), 3) if llm_speedups else None),
        "median_first_llm_speedup_percent": (
            round(statistics.median(first_llm_speedups), 3) if first_llm_speedups else None
        ),
        "median_prompt_eval_speedup_percent": (
            round(statistics.median(prompt_eval_speedups), 3) if prompt_eval_speedups else None
        ),
        "median_first_prompt_eval_speedup_percent": (
            round(statistics.median(first_prompt_eval_speedups), 3) if first_prompt_eval_speedups else None
        ),
        "explicit_cache_metrics_available": bool(explicit_cache_calls),
        "explicit_cache_metric_calls": len(explicit_cache_calls),
        "cached_input_tokens": sum(int(call.get("cached_input_tokens") or 0) for call in explicit_cache_calls),
        "cache_write_input_tokens": sum(int(call.get("cache_write_input_tokens") or 0) for call in calls),
    }


def _timing_summary(
    *,
    case_results: list[CaseResult],
    attempts: list[AttemptResult],
    warmups: list[dict[str, Any]],
    lifecycle: dict[str, float],
) -> dict[str, Any]:
    first_attempts = [result.attempts[0] for result in case_results if result.attempts]
    strict_first_attempts = [result for result in first_attempts if result.strict_pass]
    selected_attempts = [result.selected_attempt for result in case_results]
    calls = [
        {
            **call,
            "case_id": attempt.case_id,
            "repetition": attempt.repetition,
            "attempt": attempt.attempt,
            "task_id": attempt.task_id,
        }
        for attempt in attempts
        for call in attempt.llm_call_timings
    ]

    by_repetition: list[dict[str, Any]] = []
    for repetition in sorted({result.repetition for result in case_results}):
        selected = [
            result.attempts[0] for result in case_results if result.repetition == repetition and result.attempts
        ]
        by_repetition.append(
            {
                "repetition": repetition,
                "first_attempt_e2e_ms": _distribution([result.latency_ms for result in selected]),
                "first_attempt_llm_ms": _distribution([result.llm_latency_ms for result in selected]),
                "strict_first_attempts": sum(result.strict_pass for result in selected),
            }
        )

    by_llm_step: list[dict[str, Any]] = []
    for step in sorted({int(call["step"]) for call in calls}):
        selected = [call for call in calls if int(call["step"]) == step]
        by_llm_step.append(
            {
                "step": step,
                "latency_ms": _distribution([float(call["latency_ms"]) for call in selected]),
                "prompt_eval_ms": _distribution(
                    [
                        float(call["provider_prompt_eval_ms"])
                        for call in selected
                        if call.get("provider_prompt_eval_ms") is not None
                    ]
                ),
                "input_tokens": sum(int(call.get("input_tokens") or 0) for call in selected),
                "output_tokens": sum(int(call.get("output_tokens") or 0) for call in selected),
            }
        )

    prompt_tokens = sum(int(call.get("provider_prompt_tokens") or 0) for call in calls)
    prompt_eval_ms = sum(float(call.get("provider_prompt_eval_ms") or 0.0) for call in calls)
    output_tokens = sum(int(call.get("provider_output_tokens") or 0) for call in calls)
    generation_ms = sum(float(call.get("provider_generation_ms") or 0.0) for call in calls)
    warmup_latencies = [float(item["latency_ms"]) for item in warmups]
    return {
        "clock": "time.perf_counter",
        "unit": "ms",
        **{name: round(value, 3) for name, value in lifecycle.items()},
        "attempt_e2e_ms": _distribution([result.latency_ms for result in attempts]),
        "first_attempt_e2e_ms": _distribution([result.latency_ms for result in first_attempts]),
        "strict_first_attempt_e2e_ms": _distribution([result.latency_ms for result in strict_first_attempts]),
        "selected_attempt_e2e_ms": _distribution([result.latency_ms for result in selected_attempts]),
        "llm_per_attempt_ms": _distribution([result.llm_latency_ms for result in attempts]),
        "non_llm_per_attempt_ms": _distribution(
            [result.non_llm_latency_ms for result in attempts if result.non_llm_latency_ms is not None]
        ),
        "llm_calls": {
            "count": len(calls),
            "latency_ms": _distribution([float(call["latency_ms"]) for call in calls]),
            "input_tokens": sum(int(call.get("input_tokens") or 0) for call in calls),
            "output_tokens": sum(int(call.get("output_tokens") or 0) for call in calls),
            "total_tokens": sum(int(call.get("total_tokens") or 0) for call in calls),
            "estimated_usage_calls": sum(call.get("usage_estimated") is True for call in calls),
        },
        "provider": {
            "timing_available_calls": sum(
                any(
                    call.get(name) is not None
                    for name in (
                        "provider_total_ms",
                        "provider_load_ms",
                        "provider_prompt_eval_ms",
                        "provider_generation_ms",
                    )
                )
                for call in calls
            ),
            "total_ms": round(
                sum(float(call.get("provider_total_ms") or 0.0) for call in calls),
                3,
            ),
            "load_ms": round(
                sum(float(call.get("provider_load_ms") or 0.0) for call in calls),
                3,
            ),
            "prompt_eval_ms": round(prompt_eval_ms, 3),
            "generation_ms": round(generation_ms, 3),
            "prompt_tokens_per_second": (
                round(prompt_tokens / (prompt_eval_ms / 1000), 3) if prompt_tokens and prompt_eval_ms > 0 else None
            ),
            "output_tokens_per_second": (
                round(output_tokens / (generation_ms / 1000), 3) if output_tokens and generation_ms > 0 else None
            ),
        },
        "warmup": {
            "requested": len(warmups),
            "completed": sum(item["completed"] for item in warmups),
            "failed": sum(not item["completed"] for item in warmups),
            "e2e_ms": _distribution(warmup_latencies),
            "runs": warmups,
        },
        "by_repetition": by_repetition,
        "by_llm_step": by_llm_step,
        "cache_probe": _cache_probe(case_results, calls),
    }


def _aggregate_scores(
    case_results: list[CaseResult],
    attempts: list[AttemptResult],
) -> dict[str, Any]:
    total = len(case_results)
    strict = sum(result.strict_pass for result in case_results)
    functional = sum(result.functional_pass for result in case_results)
    first_try = sum(result.first_attempt_strict for result in case_results)
    rescued = sum(result.strict_pass and not result.first_attempt_strict for result in case_results)
    categories: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        selected = [result for result in case_results if result.category == category]
        if not selected:
            continue
        category_strict = sum(result.strict_pass for result in selected)
        category_functional = sum(result.functional_pass for result in selected)
        categories[category] = {
            "total": len(selected),
            "strict": category_strict,
            "strict_percent": _percent(category_strict, len(selected)),
            "functional": category_functional,
            "functional_percent": _percent(category_functional, len(selected)),
        }

    steps = [float(result.llm_steps) for result in attempts]
    latencies = [result.latency_ms for result in attempts]
    return {
        "total": total,
        "strict": strict,
        "strict_percent": _percent(strict, total),
        "functional": functional,
        "functional_percent": _percent(functional, total),
        "first_attempt_strict": first_try,
        "first_attempt_strict_percent": _percent(first_try, total),
        "rescued_on_later_attempt": rescued,
        "failed": total - strict,
        "attempts_executed": len(attempts),
        "timed_out_attempts": sum(result.timed_out for result in attempts),
        "crashed_attempts": sum(result.crashed for result in attempts),
        "hallucinated_action_attempts": sum(result.hallucinated_action for result in attempts),
        "parse_recovery_attempts": sum(result.parse_errors > 0 for result in attempts),
        "provider_retry_attempts": sum(result.provider_retries > 0 for result in attempts),
        "average_llm_steps": (round(sum(steps) / len(steps), 3) if steps else 0.0),
        "p95_llm_steps": _percentile(steps, 0.95),
        "average_latency_ms": (round(sum(latencies) / len(latencies), 3) if latencies else 0.0),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "categories": categories,
    }


def _suite_hash(cases: list[BenchmarkCase]) -> str:
    payload = {
        "suite_version": SUITE_VERSION,
        "cases": [case.to_dict() for case in cases],
    }
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def _repository_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "protolink").is_dir():
            return parent
    return None


def _prompt_source_hash() -> str:
    repository_root = _repository_root()
    package_root = repository_root / "protolink" if repository_root is not None else Path(__file__).resolve().parents[2]
    candidates = sorted((package_root / "llms" / "prompts").glob("*.py"))
    candidates.append(package_root / "llms" / "base.py")
    digest = hashlib.sha256()
    for path in candidates:
        if path.exists():
            digest.update(str(path.relative_to(package_root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_metadata() -> dict[str, Any]:
    repository_root = _repository_root()
    if repository_root is None:
        return {"commit": None, "dirty": None}
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:80] or "run"


def _create_output_dir(config: BenchmarkConfig) -> Path:
    root = config.output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default_name = f"{timestamp}-{_safe_slug(config.provider)}-{_safe_slug(config.model or 'default')}"
    path = root / _safe_slug(config.run_name or default_name)
    if path.exists():
        suffix = 2
        while path.with_name(f"{path.name}-{suffix}").exists():
            suffix += 1
        path = path.with_name(f"{path.name}-{suffix}")
    path.mkdir(parents=False)
    return path


def _redact_config(value: Any) -> Any:
    secret_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    )
    if isinstance(value, dict):
        return {
            str(key): (
                "***REDACTED***"
                if any(fragment in str(key).casefold() for fragment in secret_fragments)
                else _redact_config(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_config(item) for item in value]
    return value


def _attempt_row(
    *,
    run_id: str,
    suite_hash: str,
    provider: str,
    model: str,
    result: AttemptResult,
) -> dict[str, Any]:
    row = result.to_dict()
    row.update(
        {
            "run_id": run_id,
            "suite_hash": suite_hash,
            "provider": provider,
            "model": model,
            "failure_codes": "|".join(result.failure_codes),
            "expected_actions": json.dumps(
                result.expected_actions,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "observed_actions": json.dumps(
                result.observed_actions,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "trace_actions": json.dumps(
                result.trace_actions,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "model_actions": json.dumps(
                result.model_actions,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "llm_call_timings": json.dumps(
                result.llm_call_timings,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
    )
    return row


def _llm_call_rows(
    *,
    run_id: str,
    suite_hash: str,
    provider: str,
    model: str,
    attempts: list[AttemptResult],
) -> list[dict[str, Any]]:
    return [
        {
            "case_id": result.case_id,
            "category": result.category,
            "repetition": result.repetition,
            "attempt": result.attempt,
            "task_id": result.task_id,
            "strict_pass": result.strict_pass,
            "functional_pass": result.functional_pass,
            "run_id": run_id,
            "suite_hash": suite_hash,
            "provider": provider,
            "model": model,
            **call,
        }
        for result in attempts
        for call in result.llm_call_timings
    ]


def _llm_call_fieldnames() -> list[str]:
    return [
        "case_id",
        "category",
        "repetition",
        "attempt",
        "task_id",
        "strict_pass",
        "functional_pass",
        "run_id",
        "suite_hash",
        "provider",
        "model",
        *(item.name for item in dataclass_fields(LLMCallResult)),
    ]


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str] | None = None,
) -> None:
    resolved_fieldnames = list(fieldnames or ())
    for row in rows:
        for key in row:
            if key not in resolved_fieldnames:
                resolved_fieldnames.append(key)
    if not resolved_fieldnames:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=resolved_fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _paired_performance_metric(
    pairs: list[tuple[dict[str, Any], AttemptResult]],
    field: str,
    *,
    require_same_call_count: bool = False,
    require_provider_timing: bool = False,
) -> dict[str, Any]:
    baseline_values: list[float] = []
    current_values: list[float] = []
    deltas: list[float] = []
    delta_percents: list[float] = []
    for old, new in pairs:
        if require_same_call_count and _integer(old.get("llm_calls")) != new.llm_calls:
            continue
        if require_provider_timing and (
            (_integer(old.get("provider_timing_calls")) or 0) < 1 or new.provider_timing_calls < 1
        ):
            continue
        old_value = _numeric(old.get(field))
        new_value = _numeric(getattr(new, field, None))
        if old_value is None or new_value is None:
            continue
        baseline_values.append(old_value)
        current_values.append(new_value)
        deltas.append(new_value - old_value)
        if old_value > 0:
            delta_percents.append((new_value - old_value) / old_value * 100.0)
    return {
        "field": field,
        "matched_pairs": len(baseline_values),
        "baseline_ms": _distribution(baseline_values),
        "current_ms": _distribution(current_values),
        "median_paired_delta_ms": (round(statistics.median(deltas), 3) if deltas else None),
        "median_paired_delta_percent": (round(statistics.median(delta_percents), 3) if delta_percents else None),
        "median_paired_speedup_percent": (round(-statistics.median(delta_percents), 3) if delta_percents else None),
    }


def compare_with_baseline(
    *,
    current_cases: list[CaseResult],
    current_suite_hash: str,
    baseline_path: Path,
    current_timing: dict[str, Any] | None = None,
    current_performance_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare correctness and paired timing against a previous summary."""
    baseline = json.loads(baseline_path.expanduser().read_text(encoding="utf-8"))
    baseline_hash = baseline.get("suite", {}).get("hash")
    if baseline_hash != current_suite_hash:
        raise ValueError(
            "Baseline suite hash does not match this run. Use the same suite, seed, filters, and generated case count."
        )
    old_case_items = {
        str(item["key"]): item for item in baseline.get("case_results", []) if isinstance(item, dict) and "key" in item
    }
    old_cases = {
        item["key"]: bool(item["strict_pass"])
        for item in baseline.get("case_results", [])
        if isinstance(item, dict) and "key" in item
    }
    current = {result.key: result.strict_pass for result in current_cases}
    if set(old_cases) != set(current):
        raise ValueError("Baseline logical case keys do not match this run")
    transitions = {
        "fixed": [],
        "regressed": [],
        "stable_pass": [],
        "stable_fail": [],
    }
    for key, passed in current.items():
        old_passed = old_cases[key]
        if old_passed and passed:
            transitions["stable_pass"].append(key)
        elif old_passed and not passed:
            transitions["regressed"].append(key)
        elif not old_passed and passed:
            transitions["fixed"].append(key)
        else:
            transitions["stable_fail"].append(key)
    previous_strict = sum(old_cases.values())
    current_strict = sum(current.values())
    strict_first_pairs: list[tuple[dict[str, Any], AttemptResult]] = []
    excluded_retry_or_incomplete_pairs = 0
    for result in current_cases:
        old_item = old_case_items[result.key]
        old_attempts = old_item.get("attempts")
        if not isinstance(old_attempts, list) or not old_attempts or not result.attempts:
            continue
        old_first = old_attempts[0]
        new_first = result.attempts[0]
        if isinstance(old_first, dict) and bool(old_first.get("strict_pass")) and new_first.strict_pass:
            if (
                (_integer(old_first.get("provider_retries")) or 0) > 0
                or new_first.provider_retries > 0
                or not new_first.timing_complete
            ):
                excluded_retry_or_incomplete_pairs += 1
                continue
            strict_first_pairs.append((old_first, new_first))

    baseline_fingerprint = baseline.get("performance_fingerprint")
    fingerprint_match = (
        baseline_fingerprint == current_performance_fingerprint
        if baseline_fingerprint is not None and current_performance_fingerprint is not None
        else None
    )
    performance = {
        "available": bool(strict_first_pairs),
        "fingerprint_match": fingerprint_match,
        "warning": (
            "Provider or performance settings differ; timing deltas are not directly comparable."
            if fingerprint_match is False
            else None
        ),
        "matched_strict_first_attempts": len(strict_first_pairs),
        "excluded_retry_or_incomplete_pairs": (excluded_retry_or_incomplete_pairs),
        "e2e": _paired_performance_metric(
            strict_first_pairs,
            "latency_ms",
        ),
        "llm": _paired_performance_metric(
            strict_first_pairs,
            "llm_latency_ms",
            require_same_call_count=True,
        ),
        "provider_prompt_eval": _paired_performance_metric(
            strict_first_pairs,
            "provider_prompt_eval_ms",
            require_same_call_count=True,
            require_provider_timing=True,
        ),
        "scored_wall_ms": {
            "baseline": _numeric(baseline.get("timing", {}).get("scored_wall_ms")),
            "current": _numeric((current_timing or {}).get("scored_wall_ms")),
        },
        "cache_probe": {
            "baseline": baseline.get("timing", {}).get("cache_probe"),
            "current": (current_timing or {}).get("cache_probe"),
        },
    }
    return {
        "path": str(baseline_path.expanduser().resolve()),
        "previous_strict": previous_strict,
        "current_strict": current_strict,
        "delta": current_strict - previous_strict,
        "performance": performance,
        **transitions,
    }


def _write_html_report(path: Path, summary: dict[str, Any]) -> None:
    """Write a self-contained visual report for one completed benchmark run."""

    def mapping(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def items(value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def escape(value: Any, *, fallback: str = "—") -> str:
        text = fallback if value is None or value == "" else str(value)
        return html.escape(text, quote=True)

    def finite(value: Any) -> float | None:
        number = _numeric(value)
        return number if number is not None and math.isfinite(number) else None

    def percent(value: Any) -> str:
        number = finite(value)
        return "—" if number is None else f"{number:.1f}%"

    def width(value: Any, *, scale: float = 100.0) -> str:
        number = finite(value)
        if number is None or scale <= 0:
            return "0"
        return f"{max(0.0, min(number / scale * 100.0, 100.0)):.3f}"

    def duration(value: Any) -> str:
        number = finite(value)
        if number is None:
            return "—"
        if number >= 1000:
            return f"{number / 1000:.2f}s"
        return f"{number:.1f}ms"

    def pretty(value: Any, *, fallback: str = "—") -> str:
        if value is None or value == "" or value == []:
            return fallback
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)

    def selected_attempt(case: dict[str, Any]) -> dict[str, Any]:
        attempts = items(case.get("attempts"))
        selected_number = _integer(case.get("selected_attempt"))
        if selected_number is not None:
            for attempt in attempts:
                if _integer(attempt.get("attempt")) == selected_number:
                    return attempt
        return attempts[-1] if attempts else {}

    def status_for(case: dict[str, Any]) -> tuple[str, str]:
        if bool(case.get("strict_pass")):
            return "Strict", "strict"
        if bool(case.get("functional_pass")):
            return "Functional", "functional"
        return "Failed", "failed"

    scores = mapping(summary.get("scores"))
    timing = mapping(summary.get("timing"))
    provider = mapping(summary.get("provider"))
    suite = mapping(summary.get("suite"))
    git = mapping(summary.get("git"))
    case_results = items(summary.get("case_results"))
    case_definitions = {
        str(definition.get("id")): definition
        for definition in items(summary.get("case_definitions"))
        if definition.get("id")
    }
    total = _integer(scores.get("total")) or 0

    score_specs = (
        (
            "Strict",
            scores.get("strict"),
            scores.get("strict_percent"),
            "Exact result, actions, and clean protocol",
            "strict",
        ),
        (
            "Functional",
            scores.get("functional"),
            scores.get("functional_percent"),
            "Correct after possible self-correction",
            "functional",
        ),
        (
            "First try",
            scores.get("first_attempt_strict"),
            scores.get("first_attempt_strict_percent"),
            "Strict on the first fresh attempt",
            "first",
        ),
    )
    score_cards = []
    for label, count, rate, description, css_class in score_specs:
        count_text = "—" if total == 0 else f"{_integer(count) or 0} / {total}"
        rate_text = "—" if total == 0 else percent(rate)
        score_cards.append(
            f"""
            <article class="metric metric--{css_class}">
              <div class="metric-label">{escape(label)}</div>
              <div class="metric-value">{escape(count_text)}</div>
              <div class="metric-rate">{escape(rate_text)}</div>
              <div class="meter" role="img" aria-label="{escape(label)} {escape(rate_text)}">
                <span style="width:{width(rate) if total else "0"}%"></span>
              </div>
              <p>{escape(description)}</p>
            </article>
            """
        )

    strict_latency = mapping(timing.get("strict_first_attempt_e2e_ms"))
    score_cards.append(
        f"""
        <article class="metric metric--time">
          <div class="metric-label">Strict first-try latency</div>
          <div class="metric-value">{escape(duration(strict_latency.get("median_ms")))}</div>
          <div class="metric-rate">p95 {escape(duration(strict_latency.get("p95_ms")))}</div>
          <div class="metric-rule"></div>
          <p>Scored wall time {escape(duration(timing.get("scored_wall_ms")))}</p>
        </article>
        """
    )

    category_rows = []
    categories = mapping(scores.get("categories"))
    for category, raw_values in categories.items():
        values = mapping(raw_values)
        category_total = _integer(values.get("total")) or 0
        strict_count = _integer(values.get("strict")) or 0
        functional_count = _integer(values.get("functional")) or 0
        strict_rate = values.get("strict_percent")
        functional_rate = values.get("functional_percent")
        label = str(category).replace("_", " ")
        aria = f"{label}: strict {strict_count} of {category_total}, functional {functional_count} of {category_total}"
        category_rows.append(
            f"""
            <div class="chart-row">
              <div class="chart-label">
                <strong>{escape(label)}</strong>
                <span>{strict_count}/{category_total} strict</span>
              </div>
              <div class="paired-bars" role="img" aria-label="{escape(aria)}">
                <div class="bar bar--functional"><span style="width:{width(functional_rate)}%"></span></div>
                <div class="bar bar--strict"><span style="width:{width(strict_rate)}%"></span></div>
              </div>
              <div class="chart-value">{escape(percent(strict_rate))}</div>
            </div>
            """
        )
    category_content = (
        "".join(category_rows)
        if category_rows
        else '<p class="empty">No category results are available for this run.</p>'
    )

    attempts_executed = _integer(scores.get("attempts_executed")) or 0
    diagnostic_specs = (
        ("Hallucinated action", scores.get("hallucinated_action_attempts")),
        ("Parse recovery", scores.get("parse_recovery_attempts")),
        ("Provider retry", scores.get("provider_retry_attempts")),
        ("Crashed", scores.get("crashed_attempts")),
        ("Timed out", scores.get("timed_out_attempts")),
    )
    diagnostic_rows = []
    for label, raw_count in diagnostic_specs:
        count = _integer(raw_count) or 0
        rate = count / attempts_executed * 100.0 if attempts_executed else 0.0
        diagnostic_rows.append(
            f"""
            <div class="diagnostic-row">
              <span>{escape(label)}</span>
              <div class="diagnostic-track" role="img"
                   aria-label="{escape(label)}: {count} of {attempts_executed} attempts">
                <span style="width:{width(rate)}%"></span>
              </div>
              <strong>{count}</strong>
            </div>
            """
        )

    latency_specs = (
        ("First attempt end-to-end", mapping(timing.get("first_attempt_e2e_ms"))),
        ("Selected attempt end-to-end", mapping(timing.get("selected_attempt_e2e_ms"))),
        ("LLM per attempt", mapping(timing.get("llm_per_attempt_ms"))),
        ("Non-LLM per attempt", mapping(timing.get("non_llm_per_attempt_ms"))),
        ("Individual LLM call", mapping(mapping(timing.get("llm_calls")).get("latency_ms"))),
    )
    latency_scale = max(
        (finite(values.get("p95_ms")) or 0.0 for _, values in latency_specs),
        default=0.0,
    )
    latency_rows = []
    for label, values in latency_specs:
        count = _integer(values.get("count")) or 0
        median = finite(values.get("median_ms"))
        p95 = finite(values.get("p95_ms"))
        if count == 0:
            latency_rows.append(
                f"""
                <div class="latency-row">
                  <div><strong>{escape(label)}</strong><span>No samples</span></div>
                  <div class="latency-empty">—</div>
                </div>
                """
            )
            continue
        latency_rows.append(
            f"""
            <div class="latency-row">
              <div><strong>{escape(label)}</strong><span>{count} sample{"s" if count != 1 else ""}</span></div>
              <div class="latency-bars">
                <div class="latency-line">
                  <span>median</span>
                  <div><i style="width:{width(median, scale=latency_scale)}%"></i></div>
                  <b>{escape(duration(median))}</b>
                </div>
                <div class="latency-line latency-line--p95">
                  <span>p95</span>
                  <div><i style="width:{width(p95, scale=latency_scale)}%"></i></div>
                  <b>{escape(duration(p95))}</b>
                </div>
              </div>
            </div>
            """
        )

    case_bars = []
    case_latencies: list[float] = []
    for case in case_results:
        attempt = selected_attempt(case)
        latency = finite(attempt.get("latency_ms"))
        if latency is not None:
            case_latencies.append(latency)
    case_ceiling = max(case_latencies, default=0.0)
    for case in case_results:
        attempt = selected_attempt(case)
        latency = finite(attempt.get("latency_ms"))
        label, css_class = status_for(case)
        bar_height = max(3.0, min((latency or 0.0) / case_ceiling * 100.0, 100.0)) if case_ceiling else 3.0
        aria = f"{case.get('key') or case.get('case_id')}: {label}, latency {duration(latency)}"
        case_bars.append(
            f'<span class="case-bar case-bar--{css_class}" style="height:{bar_height:.3f}%" '
            f'aria-label="{escape(aria)}"></span>'
        )
    chart_min_width = len(case_results) + 16
    case_chart = (
        f"""
        <div class="case-chart-scroll" role="region" tabindex="0"
             aria-label="Scrollable selected-attempt latency chart">
          <div class="case-chart-canvas" style="min-width:max(100%,{chart_min_width}px)">
            <div class="case-chart-scale"><span>{escape(duration(case_ceiling))}</span><span>0</span></div>
            <div class="case-chart" role="img"
                 aria-label="Selected attempt latency for {len(case_results)} logical case results">
              {"".join(case_bars)}
            </div>
          </div>
        </div>
        <div class="legend">
          <span><i class="legend-strict"></i>Strict</span>
          <span><i class="legend-functional"></i>Functional</span>
          <span><i class="legend-failed"></i>Failed</span>
        </div>
        """
        if case_bars
        else '<p class="empty">No case latency data is available.</p>'
    )

    repetitions = items(timing.get("by_repetition"))
    repetition_rows = []
    for repetition in repetitions:
        e2e = mapping(repetition.get("first_attempt_e2e_ms"))
        llm = mapping(repetition.get("first_attempt_llm_ms"))
        repetition_rows.append(
            f"""
            <tr>
              <td>{escape(repetition.get("repetition"))}</td>
              <td>{escape(repetition.get("strict_first_attempts"), fallback="0")}</td>
              <td>{escape(duration(e2e.get("median_ms")))}</td>
              <td>{escape(duration(llm.get("median_ms")))}</td>
            </tr>
            """
        )
    repetition_content = (
        f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>Repetition</th><th>Strict first attempts</th><th>Median E2E</th><th>Median LLM</th></tr></thead>
            <tbody>{"".join(repetition_rows)}</tbody>
          </table>
        </div>
        """
        if repetition_rows
        else '<p class="empty">No repetition data is available.</p>'
    )

    cache_probe = mapping(timing.get("cache_probe"))
    eligible_pairs = _integer(cache_probe.get("eligible_strict_pairs")) or 0

    def speedup(value: Any) -> str:
        number = finite(value)
        if number is None:
            return "—"
        direction = "faster" if number > 0 else "slower" if number < 0 else "unchanged"
        return f"{number:+.1f}% {direction}"

    cache_metrics = (
        ("End-to-end", cache_probe.get("median_e2e_speedup_percent")),
        ("First LLM call", cache_probe.get("median_first_llm_speedup_percent")),
        ("First prompt eval", cache_probe.get("median_first_prompt_eval_speedup_percent")),
    )
    cache_cards = "".join(
        f"""
        <div class="mini-stat">
          <span>{escape(label)}</span>
          <strong>{escape(speedup(value))}</strong>
        </div>
        """
        for label, value in cache_metrics
    )
    cache_note = (
        f"{eligible_pairs} eligible strict adjacent pair{'s' if eligible_pairs != 1 else ''}. "
        "This is a cache-sensitive repeat signal, not proof of a cache hit."
        if eligible_pairs
        else (
            "No eligible pairs. Use at least two repetitions; both adjacent first attempts must be strict, "
            "retry-free, timing-complete, and use the same LLM call count."
        )
    )

    comparison = mapping(summary.get("baseline_comparison"))
    if comparison:
        performance = mapping(comparison.get("performance"))
        e2e = mapping(performance.get("e2e"))
        delta = _integer(comparison.get("delta")) or 0
        warning = performance.get("warning")
        transition_specs = (
            ("Fixed", len(comparison.get("fixed") or []), "good"),
            ("Regressed", len(comparison.get("regressed") or []), "bad"),
            ("Stable pass", len(comparison.get("stable_pass") or []), "neutral"),
            ("Stable fail", len(comparison.get("stable_fail") or []), "neutral"),
        )
        transitions = "".join(
            f'<div class="mini-stat mini-stat--{css_class}"><span>{escape(label)}</span><strong>{count}</strong></div>'
            for label, count, css_class in transition_specs
        )
        warning_html = f'<p class="warning">{escape(warning)}</p>' if warning else ""
        baseline_content = f"""
        <div class="baseline-head">
          <div>
            <span>Strict score delta</span>
            <strong class="delta {"positive" if delta > 0 else "negative" if delta < 0 else ""}">{delta:+d}</strong>
          </div>
          <div>
            <span>Matched timing pairs</span>
            <strong>{_integer(e2e.get("matched_pairs")) or 0}</strong>
          </div>
          <div>
            <span>Median paired E2E</span>
            <strong>{escape(speedup(e2e.get("median_paired_speedup_percent")))}</strong>
          </div>
        </div>
        <div class="mini-grid">{transitions}</div>
        {warning_html}
        """
    else:
        baseline_content = (
            '<p class="empty">No baseline was supplied for this run. '
            "Use <code>--baseline &lt;previous-summary.json&gt;</code> to add a before/after comparison.</p>"
        )

    review_cases = [
        case
        for case in case_results
        if any(not bool(attempt.get("strict_pass")) for attempt in items(case.get("attempts")))
    ]
    unresolved_count = sum(not bool(case.get("strict_pass")) for case in review_cases)
    rescued_count = len(review_cases) - unresolved_count
    review_cards = []
    for case in review_cases:
        selected = selected_attempt(case)
        non_strict_attempts = [
            attempt for attempt in items(case.get("attempts")) if not bool(attempt.get("strict_pass"))
        ]
        headline_attempt = non_strict_attempts[-1] if non_strict_attempts else selected
        if bool(case.get("strict_pass")):
            label, css_class = "Rescued", "functional"
        else:
            label, css_class = status_for(case)
        codes = headline_attempt.get("failure_codes")
        code_text = ", ".join(str(code) for code in codes) if isinstance(codes, list) and codes else "No code"
        definition = case_definitions.get(str(case.get("case_id")), {})
        expected_actions = definition.get("expected_actions") or selected.get("expected_actions")
        attempt_blocks = []
        selected_number = _integer(case.get("selected_attempt"))
        for attempt in items(case.get("attempts")):
            attempt_number = _integer(attempt.get("attempt"))
            attempt_codes = attempt.get("failure_codes")
            attempt_code_text = (
                ", ".join(str(code) for code in attempt_codes)
                if isinstance(attempt_codes, list) and attempt_codes
                else "No diagnostics"
            )
            error_type = attempt.get("error_type")
            error_message = attempt.get("error_message")
            error_text = (
                f"{error_type}: {error_message}"
                if error_type and error_message
                else str(error_message or error_type or "No runtime error")
            )
            attempt_blocks.append(
                f"""
                <article class="failure-attempt">
                  <h3>Attempt {escape(attempt_number, fallback="?")}
                    {"<span>selected</span>" if attempt_number == selected_number else ""}
                  </h3>
                  <p class="failure-diagnostics">{escape(attempt_code_text)}</p>
                  <div class="failure-grid">
                    <div>
                      <h4>Actual final output</h4>
                      <pre><code>{escape(pretty(attempt.get("final_output"), fallback="(no final output)"))}</code></pre>
                    </div>
                    <div>
                      <h4>Model decisions</h4>
                      <pre><code>{escape(pretty(attempt.get("model_actions"), fallback="(no parsed model action recorded)"))}</code></pre>
                    </div>
                    <div>
                      <h4>Successful actions</h4>
                      <pre><code>{escape(pretty(attempt.get("observed_actions"), fallback="(no successful action recorded)"))}</code></pre>
                    </div>
                    <div>
                      <h4>Runtime result</h4>
                      <pre><code>{escape(error_text)}</code></pre>
                    </div>
                  </div>
                </article>
                """
            )
        review_cards.append(
            f"""
            <details class="failure-card">
              <summary>
                <code>{escape(case.get("key") or case.get("case_id"))}</code>
                <span>{escape(str(case.get("category") or "").replace("_", " "))}</span>
                <span class="status status--{css_class}">{escape(label)}</span>
                <span>{escape(case.get("attempts_used"), fallback="0")} attempt(s)</span>
                <span>{escape(duration(headline_attempt.get("latency_ms")))}</span>
              </summary>
              <div class="failure-body">
                <p class="failure-diagnostics">{escape(code_text)}</p>
                <div class="failure-overview">
                  <div>
                    <h3>Request</h3>
                    <pre><code>{escape(pretty(definition.get("prompt"), fallback="(request unavailable in legacy summary)"))}</code></pre>
                  </div>
                  <div>
                    <h3>Expected final output</h3>
                    <pre><code>{escape(pretty(definition.get("expected_final"), fallback="(expected output unavailable in legacy summary)"))}</code></pre>
                  </div>
                  <div>
                    <h3>Expected actions</h3>
                    <pre><code>{escape(pretty(expected_actions, fallback="(no action expected)"))}</code></pre>
                  </div>
                </div>
                {"".join(attempt_blocks)}
              </div>
            </details>
            """
        )
    review_content = (
        f"""
        <div class="failure-list">{"".join(review_cards)}</div>
        """
        if review_cards
        else '<p class="success">Every executed attempt passed strictly.</p>'
    )

    provider_params = json.dumps(
        mapping(provider.get("model_params")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(", ", ": "),
    )
    git_commit = git.get("commit")
    commit_text = str(git_commit)[:12] if git_commit else "unavailable"
    details = (
        ("Run", summary.get("run_id")),
        ("Created", summary.get("created_at")),
        ("ProtoLink", summary.get("protolink_version")),
        ("Provider", provider.get("name")),
        ("Model", provider.get("model")),
        ("Action mode", provider.get("action_mode")),
        ("Model parameters", provider_params),
        ("Suite", suite.get("id")),
        ("Selected cases", suite.get("selected_count")),
        ("Repetitions", suite.get("repetitions")),
        ("Fresh attempts", suite.get("max_fresh_attempts")),
        ("Seed", suite.get("seed")),
        ("Suite hash", suite.get("hash")),
        ("Prompt hash", summary.get("prompt_hash")),
        ("Benchmark prompt hash", summary.get("benchmark_system_prompt_hash")),
        ("Git commit", commit_text),
        ("Git dirty", git.get("dirty")),
    )
    detail_rows = "".join(f"<dt>{escape(label)}</dt><dd><code>{escape(value)}</code></dd>" for label, value in details)

    strict_rate = finite(scores.get("strict_percent"))
    if total == 0:
        badge_class, badge_text = "warn", "No cases"
    elif strict_rate == 100:
        badge_class, badge_text = "good", "All strict"
    elif strict_rate is not None and strict_rate >= 90:
        badge_class, badge_text = "warn", "Review failures"
    else:
        badge_class, badge_text = "bad", "Review failures"
    title = f"Infer-loop benchmark · {summary.get('run_id') or 'run'}"
    template = Template(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
  <title>$title</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg:#f4f7fb; --surface:#fff; --surface-soft:#f8fafc; --ink:#172033; --muted:#617087;
      --border:#dbe3ee; --grid:#e9eef5; --blue:#1677ff; --blue-soft:#dcecff; --teal:#0f9f8f;
      --teal-soft:#d8f4ef; --purple:#7c5ce5; --amber:#d78a08; --red:#d64545; --red-soft:#fce5e5;
      --green:#16835b; --green-soft:#ddf5e9; --shadow:0 18px 52px rgba(32,51,79,.08);
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { width:min(1180px,calc(100% - 32px)); margin:32px auto 64px; }
    header { display:flex; justify-content:space-between; gap:24px; align-items:flex-start; padding:28px; border:1px solid var(--border); border-radius:18px; background:linear-gradient(135deg,rgba(22,119,255,.12),rgba(15,159,143,.07)),var(--surface); box-shadow:var(--shadow); }
    .eyebrow { color:var(--blue); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
    h1 { margin:7px 0 8px; font-size:clamp(28px,4vw,44px); line-height:1.05; letter-spacing:-.035em; }
    header p { margin:0; color:var(--muted); }
    .run-badge { flex:0 0 auto; padding:8px 12px; border-radius:999px; font-size:13px; font-weight:800; }
    .run-badge.good { color:var(--green); background:var(--green-soft); }
    .run-badge.warn { color:var(--amber); background:rgba(215,138,8,.13); }
    .run-badge.bad { color:var(--red); background:var(--red-soft); }
    section { margin-top:28px; }
    h2 { margin:0 0 14px; font-size:21px; letter-spacing:-.015em; }
    .section-intro { margin:-6px 0 16px; color:var(--muted); font-size:14px; }
    .metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:18px; }
    .metric,.panel { border:1px solid var(--border); border-radius:14px; background:var(--surface); box-shadow:0 8px 28px rgba(32,51,79,.045); }
    .metric { min-width:0; padding:18px; }
    .metric-label { color:var(--muted); font-size:13px; font-weight:700; }
    .metric-value { margin-top:7px; font-size:27px; font-weight:850; letter-spacing:-.03em; }
    .metric-rate { margin-top:2px; color:var(--muted); font-size:13px; }
    .metric p { min-height:38px; margin:10px 0 0; color:var(--muted); font-size:12px; line-height:1.5; }
    .meter,.metric-rule { height:7px; margin-top:13px; overflow:hidden; border-radius:999px; background:var(--grid); }
    .meter span { display:block; height:100%; border-radius:inherit; background:var(--blue); }
    .metric--functional .meter span { background:var(--teal); }
    .metric--first .meter span { background:var(--purple); }
    .metric-rule { background:linear-gradient(90deg,var(--blue),var(--teal)); }
    .two-col { display:grid; grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr); gap:14px; }
    .panel { min-width:0; padding:20px; }
    .legend { display:flex; flex-wrap:wrap; gap:16px; margin-top:12px; color:var(--muted); font-size:12px; }
    .legend span { display:inline-flex; align-items:center; gap:6px; }
    .legend i { width:10px; height:10px; border-radius:3px; background:var(--blue); }
    .legend .legend-functional { background:var(--teal); }
    .legend .legend-failed { background:var(--red); }
    .chart-row { display:grid; grid-template-columns:minmax(130px,.42fr) minmax(160px,1fr) 56px; gap:12px; align-items:center; padding:9px 0; border-bottom:1px solid var(--grid); }
    .chart-row:last-child { border-bottom:0; }
    .chart-label { display:flex; flex-direction:column; min-width:0; }
    .chart-label strong { overflow:hidden; text-overflow:ellipsis; text-transform:capitalize; }
    .chart-label span,.latency-row span { color:var(--muted); font-size:11px; }
    .paired-bars { display:grid; gap:4px; }
    .bar,.diagnostic-track,.latency-line div { height:8px; overflow:hidden; border-radius:999px; background:var(--grid); }
    .bar span,.diagnostic-track span,.latency-line i { display:block; height:100%; border-radius:inherit; }
    .bar--functional span { background:var(--teal); }
    .bar--strict span { background:var(--blue); }
    .chart-value { text-align:right; font-variant-numeric:tabular-nums; font-weight:750; }
    .diagnostic-row { display:grid; grid-template-columns:minmax(110px,1fr) minmax(90px,1.4fr) 28px; gap:10px; align-items:center; padding:10px 0; border-bottom:1px solid var(--grid); font-size:13px; }
    .diagnostic-row:last-child { border-bottom:0; }
    .diagnostic-track span { background:var(--red); }
    .diagnostic-row strong { text-align:right; }
    .latency-row { display:grid; grid-template-columns:minmax(150px,.45fr) minmax(260px,1fr); gap:18px; align-items:center; padding:12px 0; border-bottom:1px solid var(--grid); }
    .latency-row:last-child { border-bottom:0; }
    .latency-row > div:first-child { display:flex; flex-direction:column; }
    .latency-bars { display:grid; gap:5px; }
    .latency-line { display:grid; grid-template-columns:48px 1fr 68px; gap:8px; align-items:center; }
    .latency-line i { background:var(--blue); }
    .latency-line--p95 i { background:var(--purple); }
    .latency-line b { text-align:right; font-size:12px; font-variant-numeric:tabular-nums; }
    .latency-empty,.empty { color:var(--muted); }
    .case-chart-scroll { width:100%; max-width:100%; overflow-x:auto; overscroll-behavior-inline:contain; }
    .case-chart-canvas { width:100%; }
    .case-chart-scale { display:flex; justify-content:space-between; margin:0 0 6px; color:var(--muted); font-size:11px; }
    .case-chart { display:flex; align-items:flex-end; gap:0; height:190px; padding:10px 8px 0; border-bottom:1px solid var(--border); background:linear-gradient(to top,var(--grid) 1px,transparent 1px) 0 50%/100% 50%; }
    .case-bar { flex:1 1 1px; min-width:1px; max-width:34px; border-radius:3px 3px 0 0; background:var(--blue); }
    .case-bar--functional { background:var(--teal); }
    .case-bar--failed { background:var(--red); }
    .mini-grid,.baseline-head { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; }
    .mini-stat { padding:13px; border-radius:10px; background:var(--surface-soft); }
    .mini-stat span,.baseline-head span { display:block; color:var(--muted); font-size:11px; }
    .mini-stat strong,.baseline-head strong { display:block; margin-top:4px; font-size:16px; overflow-wrap:anywhere; }
    .baseline-head { margin-bottom:12px; }
    .baseline-head > div { padding:13px; border:1px solid var(--border); border-radius:10px; }
    .delta.positive { color:var(--green); }
    .delta.negative { color:var(--red); }
    .warning,.success,.empty { margin:12px 0 0; padding:12px 14px; border-radius:10px; background:var(--surface-soft); line-height:1.55; }
    .warning { color:var(--amber); background:rgba(215,138,8,.12); }
    .success { color:var(--green); background:var(--green-soft); }
    .table-wrap { width:100%; overflow-x:auto; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { padding:10px 11px; border-bottom:1px solid var(--grid); text-align:left; vertical-align:top; }
    th { color:var(--muted); font-size:11px; letter-spacing:.04em; text-transform:uppercase; }
    td { overflow-wrap:anywhere; }
    code { color:inherit; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:.92em; }
    .status { display:inline-flex; padding:4px 5px; border-radius:999px; font-size:11px; font-weight:800; }
    .status--strict { color:var(--blue); background:var(--blue-soft); }
    .status--functional { color:var(--teal); background:var(--teal-soft); }
    .status--failed { color:var(--red); background:var(--red-soft); }
    .failure-list { display:grid; gap:10px; }
    .failure-card { overflow:hidden; border:1px solid var(--border); border-radius:11px; background:var(--surface-soft); }
    .failure-card > summary { position:relative; display:grid; grid-template-columns:minmax(190px,1.2fr) minmax(100px,.65fr) auto auto auto; gap:12px; align-items:center; padding:12px 38px 12px 14px; cursor:pointer; list-style:none; }
    .failure-card > summary::after { content:">"; position:absolute; top:50%; right:14px; color:var(--muted); font-size:20px; transform:translateY(-50%); transition:transform .15s ease; }
    .failure-card[open] > summary::after { transform:translateY(-50%) rotate(90deg); }
    .failure-card > summary > code { min-width:0; overflow-wrap:anywhere; font-weight:800; }
    .failure-card > summary > span:not(.status) { color:var(--muted); font-size:12px; }
    .failure-body { padding:0 14px 14px; border-top:1px solid var(--border); }
    .failure-overview,.failure-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .failure-overview { margin-top:12px; }
    .failure-overview > div:first-child { grid-column:1/-1; }
    .failure-overview > div,.failure-grid > div { min-width:0; }
    .failure-attempt { margin-top:14px; padding:12px; border:1px solid var(--border); border-radius:10px; background:var(--surface); }
    .failure-attempt h3 { display:flex; gap:8px; align-items:center; margin:0 0 4px; font-size:15px; }
    .failure-attempt h3 span { padding:2px 6px; border-radius:999px; color:var(--blue); background:var(--blue-soft); font-size:10px; text-transform:uppercase; }
    .failure-body h3,.failure-body h4 { margin:0 0 6px; font-size:12px; color:var(--muted); letter-spacing:.03em; text-transform:uppercase; }
    .failure-diagnostics { margin:8px 0; color:var(--red); font-size:12px; overflow-wrap:anywhere; }
    pre { max-height:260px; margin:0; padding:10px; overflow:auto; border:1px solid var(--grid); border-radius:8px; background:var(--surface-soft); white-space:pre-wrap; overflow-wrap:anywhere; }
    details.panel summary { cursor:pointer; font-weight:800; }
    dl { display:grid; grid-template-columns:minmax(130px,.28fr) minmax(0,1fr); gap:0; margin:16px 0 0; }
    dt,dd { min-width:0; margin:0; padding:9px 0; border-bottom:1px solid var(--grid); }
    dt { color:var(--muted); }
    dd { overflow-wrap:anywhere; }
    footer { margin-top:26px; color:var(--muted); font-size:12px; text-align:center; }
    @media (prefers-color-scheme:dark) {
      :root { --bg:#0b1220; --surface:#111b2d; --surface-soft:#162238; --ink:#edf4ff; --muted:#a3b2c8; --border:#2b3a52; --grid:#24334a; --blue:#58a6ff; --blue-soft:#173c65; --teal:#42d7c5; --teal-soft:#164c48; --purple:#aa91ff; --amber:#ffbd52; --red:#ff7272; --red-soft:#542a34; --green:#55d49b; --green-soft:#153f35; --shadow:0 18px 52px rgba(0,0,0,.25); }
    }
    @media (max-width:800px) {
      main { width:min(100% - 20px,1180px); margin-top:10px; }
      header { padding:20px; border-radius:14px; }
      .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .two-col { grid-template-columns:1fr; }
    }
    @media (max-width:520px) {
      header { flex-direction:column; }
      .metrics { grid-template-columns:1fr; }
      .chart-row { grid-template-columns:110px 1fr 48px; gap:8px; }
      .latency-row { grid-template-columns:1fr; gap:8px; }
      .failure-card > summary { grid-template-columns:1fr auto; }
      .failure-card > summary > span:not(.status) { display:none; }
      .failure-overview,.failure-grid { grid-template-columns:1fr; }
      .failure-overview > div:first-child { grid-column:auto; }
      dl { grid-template-columns:1fr; }
      dd { padding-top:0; }
    }
    @media print {
      :root { --bg:#fff; --surface:#fff; --surface-soft:#f6f7f8; --ink:#111; --muted:#555; --border:#ccc; --grid:#ddd; }
      body { background:#fff; }
      main { width:100%; margin:0; }
      .metric,.panel,header { box-shadow:none; break-inside:avoid; }
      details { display:block; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <div class="eyebrow">ProtoLink · infer-loop benchmark</div>
      <h1>$run_id</h1>
      <p>$provider_model · $suite_label · generated $created_at</p>
    </div>
    <span class="run-badge $badge_class">$badge_text</span>
  </header>

  <div class="metrics">$score_cards</div>

  <section class="two-col">
    <div class="panel">
      <h2>Correctness by category</h2>
      <p class="section-intro">Functional success is shown above strict, clean success.</p>
      $category_content
      <div class="legend"><span><i class="legend-functional"></i>Functional</span><span><i></i>Strict</span></div>
    </div>
    <div class="panel">
      <h2>Attempt diagnostics</h2>
      <p class="section-intro">$attempts_executed executed fresh attempts.</p>
      $diagnostic_content
    </div>
  </section>

  <section class="panel">
    <h2>Latency distributions</h2>
    <p class="section-intro">Bars share one p95 scale; medians and tails stay separate from correctness.</p>
    $latency_content
  </section>

  <section class="panel">
    <h2>Case latency and outcome</h2>
    <p class="section-intro">Each bar is the selected attempt for one logical case repetition.</p>
    $case_chart
  </section>

  <section class="two-col">
    <div class="panel">
      <h2>Repetitions</h2>
      $repetition_content
    </div>
    <div class="panel">
      <h2>Cache-sensitive repeat probe</h2>
      <div class="mini-grid">$cache_cards</div>
      <p class="section-intro cache-note">$cache_note</p>
    </div>
  </section>

  <section class="panel">
    <h2>Baseline comparison</h2>
    $baseline_content
  </section>

  <section class="panel">
    <h2>Attempt review</h2>
    <p class="section-intro">$review_count logical case result(s) had a non-strict attempt:
      $unresolved_count unresolved, $rescued_count rescued by a later fresh attempt.</p>
    $review_content
  </section>

  <section>
    <details class="panel">
      <summary>Run configuration and identity</summary>
      <dl>$detail_rows</dl>
    </details>
  </section>

  <footer>Generated locally by the ProtoLink infer-loop benchmark. No external assets or requests.</footer>
</main>
</body>
</html>
"""
    )
    document = template.substitute(
        title=escape(title),
        run_id=escape(summary.get("run_id"), fallback="Benchmark run"),
        provider_model=escape(f"{provider.get('name') or 'provider'} / {provider.get('model') or 'default'}"),
        suite_label=escape(
            f"{suite.get('id') or 'suite'} · {suite.get('selected_count') or total} cases · "
            f"{suite.get('repetitions') or 1} repetition(s)"
        ),
        created_at=escape(summary.get("created_at"), fallback="unknown time"),
        badge_class=badge_class,
        badge_text=escape(badge_text),
        score_cards="".join(score_cards),
        category_content=category_content,
        attempts_executed=attempts_executed,
        diagnostic_content="".join(diagnostic_rows),
        latency_content="".join(latency_rows),
        case_chart=case_chart,
        repetition_content=repetition_content,
        cache_cards=cache_cards,
        cache_note=escape(cache_note),
        baseline_content=baseline_content,
        review_count=len(review_cases),
        unresolved_count=unresolved_count,
        rescued_count=rescued_count,
        review_content=review_content,
        detail_rows=detail_rows,
    )
    path.write_text(document, encoding="utf-8")
