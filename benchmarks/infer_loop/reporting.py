"""Scoring, timing, metadata, and artifact helpers for the infer-loop benchmark."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
import subprocess
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
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
