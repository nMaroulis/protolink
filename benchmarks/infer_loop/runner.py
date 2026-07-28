"""Command-line and orchestration facade for the infer-loop benchmark.

Implementation details live in focused sibling modules. Imports remain here so
existing callers can continue using benchmarks.infer_loop.runner.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protolink import Task, TaskState, __version__, create_llm
from protolink.llms.base import LLM
from protolink.telemetry import LocalTraceRecorder

from .catalog import generate_cases as generate_cases
from .evaluation import (
    _find_infer_output,
    _find_trace,
    _task_state,
)
from .evaluation import (
    _trace_metrics as _trace_metrics,
)
from .evaluation import (
    _validate_attempt as _validate_attempt,
)
from .evaluation import (
    run_attempt as run_attempt,
)
from .mesh import BenchmarkMesh as BenchmarkMesh
from .models import (
    CATEGORIES,
    DEFAULT_SYSTEM_PROMPT,
    SUITE_SIZES,
    SUITE_VERSION,
)
from .models import (
    ActionLedger as ActionLedger,
)
from .models import (
    AttemptResult as AttemptResult,
)
from .models import (
    BenchmarkCase as BenchmarkCase,
)
from .models import (
    BenchmarkConfig as BenchmarkConfig,
)
from .models import (
    BenchmarkRun as BenchmarkRun,
)
from .models import (
    CaseResult as CaseResult,
)
from .models import (
    ExpectedAction as ExpectedAction,
)
from .models import (
    LedgerEntry as LedgerEntry,
)
from .models import (
    LLMCallResult as LLMCallResult,
)
from .reporting import (
    _aggregate_scores,
    _attempt_row,
    _create_output_dir,
    _git_metadata,
    _llm_call_rows,
    _redact_config,
    _timing_summary,
)
from .reporting import (
    _cache_probe as _cache_probe,
)
from .reporting import (
    _distribution as _distribution,
)
from .reporting import (
    _llm_call_fieldnames as _llm_call_fieldnames,
)
from .reporting import (
    _prompt_source_hash as _prompt_source_hash,
)
from .reporting import (
    _suite_hash as _suite_hash,
)
from .reporting import (
    _write_csv as _write_csv,
)
from .reporting import (
    compare_with_baseline as compare_with_baseline,
)


def _select_cases(config: BenchmarkConfig) -> list[BenchmarkCase]:
    generated_count = config.count if config.count is not None else SUITE_SIZES[config.suite]
    selected = generate_cases(generated_count, seed=config.seed)
    if config.categories:
        selected = [case for case in selected if case.category in config.categories]
    if config.case_patterns:
        selected = [
            case for case in selected if any(fnmatch.fnmatchcase(case.id, pattern) for pattern in config.case_patterns)
        ]
    if config.shuffle:
        random.Random(config.seed).shuffle(selected)
    if config.limit is not None:
        selected = selected[: config.limit]
    if not selected:
        raise ValueError("Case selection is empty")
    return selected


def _create_llm(config: BenchmarkConfig) -> LLM:
    options = dict(config.provider_options)
    if config.model is not None:
        options["model"] = config.model
    if config.base_url is not None:
        options["base_url"] = config.base_url
    if config.model_params:
        options["model_params"] = dict(config.model_params)
    options["max_parse_failures"] = config.max_parse_failures
    if config.provider in {"ollama", "llama.cpp-server", "lmstudio", "openai-compatible", "vllm"}:
        options["supports_tool_calling"] = config.supports_tool_calling
    return create_llm(config.provider, **options)


async def _warm_up(
    mesh: BenchmarkMesh,
    recorder: LocalTraceRecorder,
    count: int,
    timeout: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index in range(count):
        token = f"BENCH-WARMUP-{index + 1}"
        task = Task.create_infer(prompt=f"Do not call tools or agents. Return exactly {token}")
        task.metadata["benchmark_warmup"] = True
        trace_cursor = len(recorder.traces)
        started = time.perf_counter()
        result_task: Task | None = None
        error: Exception | None = None
        try:
            result_task = await asyncio.wait_for(
                mesh.client.send_task(mesh.coordinator.card.url, task),
                timeout=timeout,
            )
        except Exception as exc:
            error = exc
            # A warm-up is excluded from scores; the scored suite will expose a
            # persistent provider or prompt problem with full diagnostics.
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        trace = _find_trace(recorder, task_id=task.id, cursor=trace_cursor)
        metrics, call_timings = _trace_metrics(trace)
        final_output = _find_infer_output(result_task or task)
        results.append(
            {
                "index": index + 1,
                "task_id": task.id,
                "completed": (
                    error is None
                    and _task_state(result_task or task) == TaskState.COMPLETED.value
                    and final_output == token
                ),
                "latency_ms": latency_ms,
                "llm_latency_ms": metrics["llm_latency_ms"],
                "provider_load_ms": metrics["provider_load_ms"],
                "provider_prompt_eval_ms": metrics["provider_prompt_eval_ms"],
                "provider_generation_ms": metrics["provider_generation_ms"],
                "llm_call_timings": [call.to_dict() for call in call_timings],
                "error_type": type(error).__name__ if error is not None else None,
                "error_message": str(error) if error is not None else None,
            }
        )
    return results


def _progress_line(
    *,
    logical_index: int,
    logical_total: int,
    result: AttemptResult,
) -> str:
    if result.strict_pass:
        status = "STRICT PASS"
    elif result.functional_pass:
        status = "FUNCTIONAL/RECOVERED"
    else:
        status = "FAIL"
    return (
        f"[{logical_index:>3}/{logical_total}] {result.case_id} "
        f"attempt {result.attempt}: {status} "
        f"({result.llm_steps} step(s), e2e={result.latency_ms / 1000:.2f}s, "
        f"llm={result.llm_latency_ms / 1000:.2f}s)"
    )


async def run_benchmark(config: BenchmarkConfig, *, llm: LLM | None = None) -> BenchmarkRun:
    """Execute a configured benchmark and write its artifacts."""
    benchmark_started = time.perf_counter()
    cases = _select_cases(config)
    suite_hash = _suite_hash(cases)
    git = _git_metadata()
    prompt_hash = _prompt_source_hash()
    output_dir = _create_output_dir(config)
    run_id = output_dir.name
    recorder = LocalTraceRecorder(path=output_dir / "traces.jsonl", max_traces=0)
    active_llm = llm or _create_llm(config)
    preflight_started = time.perf_counter()
    if config.preflight:
        if not active_llm.validate_connection():
            raise RuntimeError(
                f"Provider preflight failed for {config.provider}/{getattr(active_llm, 'model', config.model)}"
            )
    preflight_ms = (time.perf_counter() - preflight_started) * 1000 if config.preflight else 0.0
    resolved_model = str(getattr(active_llm, "model", None) or config.model or "default")
    mesh = BenchmarkMesh(
        llm=active_llm,
        recorder=recorder,
        system_prompt=config.system_prompt,
        verbosity=config.verbosity,
    )
    case_results: list[CaseResult] = []
    attempt_results: list[AttemptResult] = []
    logical_total = len(cases) * config.repetitions
    logical_index = 0
    startup_ms = 0.0
    warmup_results: list[dict[str, Any]] = []
    warmup_wall_ms = 0.0
    scored_wall_ms = 0.0
    progress_output_ms = 0.0
    teardown_ms = 0.0
    try:
        startup_started = time.perf_counter()
        await mesh.start()
        startup_ms = (time.perf_counter() - startup_started) * 1000
        warmup_started = time.perf_counter()
        warmup_results = await _warm_up(mesh, recorder, config.warmup, config.timeout)
        warmup_wall_ms = (time.perf_counter() - warmup_started) * 1000
        scored_started = time.perf_counter()
        # Case-major repetitions keep identical prompts adjacent, which makes
        # the paired repeat signal more useful for prompt-cache comparisons.
        for case in cases:
            for repetition in range(1, config.repetitions + 1):
                logical_index += 1
                current_attempts: list[AttemptResult] = []
                for attempt_number in range(1, config.attempts + 1):
                    result = await run_attempt(
                        mesh=mesh,
                        recorder=recorder,
                        case=case,
                        repetition=repetition,
                        attempt=attempt_number,
                        timeout=config.timeout,
                    )
                    current_attempts.append(result)
                    attempt_results.append(result)
                    if not config.quiet:
                        progress_started = time.perf_counter()
                        print(
                            _progress_line(
                                logical_index=logical_index,
                                logical_total=logical_total,
                                result=result,
                            ),
                            flush=True,
                        )
                        progress_output_ms += (time.perf_counter() - progress_started) * 1000
                    if result.strict_pass:
                        break
                case_results.append(
                    CaseResult(
                        case_id=case.id,
                        category=case.category,
                        repetition=repetition,
                        attempts=current_attempts,
                    )
                )
        scored_wall_ms = max((time.perf_counter() - scored_started) * 1000 - progress_output_ms, 0.0)
    finally:
        teardown_started = time.perf_counter()
        mesh.stop()
        teardown_ms = (time.perf_counter() - teardown_started) * 1000

    scores = _aggregate_scores(case_results, attempt_results)
    timing = _timing_summary(
        case_results=case_results,
        attempts=attempt_results,
        warmups=warmup_results,
        lifecycle={
            "preflight_ms": preflight_ms,
            "startup_ms": startup_ms,
            "warmup_wall_ms": warmup_wall_ms,
            "scored_wall_ms": scored_wall_ms,
            "progress_output_ms": progress_output_ms,
            "teardown_ms": teardown_ms,
            "benchmark_wall_ms": (time.perf_counter() - benchmark_started) * 1000,
        },
    )
    provider_summary = {
        "name": config.provider,
        "model": resolved_model,
        "base_url": config.base_url,
        "model_params": _redact_config(config.model_params),
        "provider_options": _redact_config(config.provider_options),
        "supports_tool_calling": config.supports_tool_calling,
        "action_mode": "native" if active_llm.uses_native_action_prompt else "json_prompt",
        "max_parse_failures": config.max_parse_failures,
    }
    performance_fingerprint = {
        "provider": provider_summary,
        "warmup": config.warmup,
        "warmup_completed": sum(item["completed"] for item in warmup_results),
        "warmup_failed": sum(not item["completed"] for item in warmup_results),
        "repetition_order": "case_major",
        "repetitions": config.repetitions,
        "max_fresh_attempts": config.attempts,
        "timeout": config.timeout,
        "verbosity": config.verbosity,
    }
    summary: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protolink_version": __version__,
        "provider": provider_summary,
        "suite": {
            "id": config.suite,
            "version": SUITE_VERSION,
            "hash": suite_hash,
            "seed": config.seed,
            "generated_count": config.count if config.count is not None else SUITE_SIZES[config.suite],
            "selected_count": len(cases),
            "repetitions": config.repetitions,
            "max_fresh_attempts": config.attempts,
            "categories": list(config.categories),
            "case_patterns": list(config.case_patterns),
            "shuffle": config.shuffle,
            "repetition_order": "case_major",
        },
        "prompt_hash": prompt_hash,
        "benchmark_system_prompt_hash": hashlib.sha256(config.system_prompt.encode()).hexdigest(),
        "git": git,
        "scores": scores,
        "timing": timing,
        "performance_fingerprint": performance_fingerprint,
        "case_results": [result.to_dict() for result in case_results],
    }
    if config.baseline is not None:
        summary["baseline_comparison"] = compare_with_baseline(
            current_cases=case_results,
            current_suite_hash=suite_hash,
            baseline_path=config.baseline,
            current_timing=timing,
            current_performance_fingerprint=performance_fingerprint,
        )

    rows = [
        _attempt_row(
            run_id=run_id,
            suite_hash=suite_hash,
            provider=config.provider,
            model=resolved_model,
            result=result,
        )
        for result in attempt_results
    ]
    _write_csv(output_dir / "results.csv", rows)
    llm_call_rows = _llm_call_rows(
        run_id=run_id,
        suite_hash=suite_hash,
        provider=config.provider,
        model=resolved_model,
        attempts=attempt_results,
    )
    _write_csv(
        output_dir / "llm_calls.csv",
        llm_call_rows,
        fieldnames=_llm_call_fieldnames(),
    )
    failure_keys = {result.key for result in case_results if not result.strict_pass}
    failure_rows = [
        row
        for row, result in zip(rows, attempt_results, strict=True)
        if f"{result.case_id}#r{result.repetition}" in failure_keys
    ]
    _write_csv(
        output_dir / "failures.csv",
        failure_rows,
        fieldnames=list(rows[0]) if rows else None,
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return BenchmarkRun(
        output_dir=output_dir,
        summary=summary,
        cases=case_results,
        attempts=attempt_results,
    )


def _parse_key_value(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("expected KEY=JSON_VALUE")
    key, raw_value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("configuration key must not be empty")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return key, value


def _pairs_to_dict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        values[key] = value
    return values


def build_parser() -> argparse.ArgumentParser:
    """Create the benchmark command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark ProtoLink's infer loop with deterministic final, tool, delegation, multi-step, "
            "and grounding tasks."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    provider_group = parser.add_argument_group("provider")
    provider_group.add_argument("--provider", default="ollama", help="Provider passed to create_llm().")
    provider_group.add_argument("--model", help="Exact model id; provider default when omitted.")
    provider_group.add_argument(
        "--base-url",
        help="Provider server URL. Ollama defaults to OLLAMA_URL or http://localhost:11434.",
    )
    provider_group.add_argument("--temperature", type=float, default=0.0)
    provider_group.add_argument("--model-seed", type=int, default=1337, help="Ollama sampling seed.")
    provider_group.add_argument("--num-ctx", type=int, default=8192, help="Ollama context window.")
    provider_group.add_argument("--num-predict", type=int, default=2048, help="Ollama generation limit.")
    provider_group.add_argument(
        "--model-param",
        action="append",
        default=[],
        type=_parse_key_value,
        metavar="KEY=JSON_VALUE",
        help="Repeatable provider model parameter; overrides convenience defaults.",
    )
    provider_group.add_argument(
        "--provider-option",
        action="append",
        default=[],
        type=_parse_key_value,
        metavar="KEY=JSON_VALUE",
        help="Repeatable create_llm constructor option outside model_params.",
    )
    provider_group.add_argument(
        "--api-key-env",
        help="Read an API key from this environment variable and pass it as api_key.",
    )
    provider_group.add_argument(
        "--supports-tool-calling",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use a server model's native tool interface instead of the JSON prompt fallback.",
    )
    provider_group.add_argument(
        "--max-parse-failures",
        type=int,
        default=3,
        help="Consecutive action-envelope parse attempts allowed by the infer loop (1..10).",
    )
    provider_group.add_argument(
        "--preflight",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate the provider connection before scoring.",
    )
    provider_group.add_argument(
        "--warmup",
        type=int,
        help="Unscored warm-up tasks. Defaults to 1 for Ollama and 0 for other providers.",
    )

    suite_group = parser.add_argument_group("suite")
    suite_group.add_argument("--suite", choices=sorted(SUITE_SIZES), default="smoke")
    suite_group.add_argument("--count", type=int, help="Override the suite's generated case count.")
    suite_group.add_argument("--seed", type=int, default=1337, help="Deterministic task-generation seed.")
    suite_group.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Fresh attempts per logical case, stopping after the first strict pass.",
    )
    suite_group.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Repeat each selected case adjacently for reliability and cache-sensitive timing.",
    )
    suite_group.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Best-effort timeout in seconds per task.",
    )
    suite_group.add_argument(
        "--category",
        action="append",
        choices=CATEGORIES,
        default=[],
        help="Run only this category; repeat the option to select more.",
    )
    suite_group.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run case ids matching this shell-style pattern; repeatable.",
    )
    suite_group.add_argument("--limit", type=int, help="Run only the first N filtered cases.")
    suite_group.add_argument("--shuffle", action="store_true", help="Shuffle selected cases with --seed.")
    suite_group.add_argument(
        "--list-cases",
        action="store_true",
        help="Print selected case ids and prompts without contacting a provider.",
    )

    output_group = parser.add_argument_group("output and comparison")
    output_group.add_argument(
        "--output-dir", default="benchmark_results", help="Parent directory for timestamped runs."
    )
    output_group.add_argument("--run-name", help="Optional output subdirectory name.")
    output_group.add_argument(
        "--baseline",
        type=Path,
        help="Previous summary.json to compare correctness transitions and paired timing.",
    )
    output_group.add_argument(
        "--fail-under",
        type=float,
        help="Exit 2 when the strict percentage is lower than this threshold.",
    )
    output_group.add_argument(
        "--system-prompt-file",
        type=Path,
        help="Replace the benchmark's complementary coordinator instructions from a UTF-8 file.",
    )
    output_group.add_argument("--quiet", action="store_true", help="Hide per-attempt progress.")
    output_group.add_argument("--verbosity", type=int, choices=(0, 1, 2), default=0)
    return parser


def _validate_cli_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.count is not None and args.count < 1:
        parser.error("--count must be at least 1")
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.warmup is not None and args.warmup < 0:
        parser.error("--warmup must not be negative")
    if args.max_parse_failures < 1 or args.max_parse_failures > 10:
        parser.error("--max-parse-failures must be between 1 and 10")
    if args.fail_under is not None and not 0 <= args.fail_under <= 100:
        parser.error("--fail-under must be between 0 and 100")
    if args.num_ctx < 1 or args.num_predict < 1:
        parser.error("--num-ctx and --num-predict must be at least 1")


def config_from_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> BenchmarkConfig:
    """Resolve provider-aware defaults without hiding them from the summary."""
    _validate_cli_args(parser, args)
    provider = str(args.provider).lower()
    model_params: dict[str, Any] = {"temperature": args.temperature}
    base_url = args.base_url
    if provider == "ollama":
        base_url = base_url or os.getenv("OLLAMA_URL") or "http://localhost:11434"
        model_params.update(
            {
                "seed": args.model_seed,
                "num_ctx": args.num_ctx,
                "num_predict": args.num_predict,
            }
        )
    model_params.update(_pairs_to_dict(args.model_param))
    provider_options = _pairs_to_dict(args.provider_option)
    if args.api_key_env:
        api_key = os.getenv(args.api_key_env)
        if not api_key:
            parser.error(f"--api-key-env points to unset or empty variable {args.api_key_env!r}")
        provider_options["api_key"] = api_key
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if args.system_prompt_file:
        try:
            system_prompt = args.system_prompt_file.expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"could not read --system-prompt-file: {exc}")
    warmup = args.warmup if args.warmup is not None else (1 if provider == "ollama" else 0)
    return BenchmarkConfig(
        provider=provider,
        model=args.model,
        base_url=base_url,
        model_params=model_params,
        provider_options=provider_options,
        max_parse_failures=args.max_parse_failures,
        supports_tool_calling=args.supports_tool_calling,
        suite=args.suite,
        count=args.count,
        seed=args.seed,
        attempts=args.attempts,
        repetitions=args.repetitions,
        timeout=args.timeout,
        categories=tuple(args.category),
        case_patterns=tuple(args.case),
        limit=args.limit,
        shuffle=args.shuffle,
        warmup=warmup,
        preflight=args.preflight,
        output_root=Path(args.output_dir),
        run_name=args.run_name,
        baseline=args.baseline,
        fail_under=args.fail_under,
        system_prompt=system_prompt,
        verbosity=args.verbosity,
        quiet=args.quiet,
    )


def _print_summary(run: BenchmarkRun) -> None:
    scores = run.summary["scores"]
    timing = run.summary["timing"]
    print()
    print(f"STRICT     {scores['strict']}/{scores['total']} ({scores['strict_percent']:.1f}%)")
    print(f"FUNCTIONAL {scores['functional']}/{scores['total']} ({scores['functional_percent']:.1f}%)")
    print(
        f"FIRST TRY  {scores['first_attempt_strict']}/{scores['total']} ({scores['first_attempt_strict_percent']:.1f}%)"
    )
    print(f"RESCUED ON LATER ATTEMPT {scores['rescued_on_later_attempt']}")
    print(
        "ATTEMPT DIAGNOSTICS "
        f"parse-recovery={scores['parse_recovery_attempts']} "
        f"hallucinated-action={scores['hallucinated_action_attempts']} "
        f"crashed={scores['crashed_attempts']} timed-out={scores['timed_out_attempts']}"
    )
    strict_timing = timing["strict_first_attempt_e2e_ms"]
    print(
        f"LLM STEPS avg={scores['average_llm_steps']:.2f} p95={scores['p95_llm_steps']:.0f}; "
        f"STRICT FIRST-TRY LATENCY median={strict_timing['median_ms'] / 1000:.2f}s "
        f"p95={strict_timing['p95_ms'] / 1000:.2f}s"
    )
    print(
        f"WALL TIME  scored={timing['scored_wall_ms'] / 1000:.2f}s "
        f"warmup={timing['warmup_wall_ms'] / 1000:.2f}s; "
        f"LLM CALLS median={timing['llm_calls']['latency_ms']['median_ms'] / 1000:.2f}s"
    )
    cache_probe = timing["cache_probe"]
    if cache_probe["eligible_strict_pairs"]:
        e2e_speedup = cache_probe["median_e2e_speedup_percent"]
        first_llm_speedup = cache_probe["median_first_llm_speedup_percent"]
        first_prompt_speedup = cache_probe["median_first_prompt_eval_speedup_percent"]
        print(
            "REPEAT PROBE "
            f"pairs={cache_probe['eligible_strict_pairs']} "
            f"e2e-speedup={f'{e2e_speedup:+.1f}%' if e2e_speedup is not None else 'n/a'} "
            f"first-llm={f'{first_llm_speedup:+.1f}%' if first_llm_speedup is not None else 'n/a'} "
            f"first-prompt-eval={f'{first_prompt_speedup:+.1f}%' if first_prompt_speedup is not None else 'n/a'}"
        )
    comparison = run.summary.get("baseline_comparison")
    if comparison:
        delta = int(comparison["delta"])
        print(f"BASELINE   delta={delta:+d} fixed={len(comparison['fixed'])} regressed={len(comparison['regressed'])}")
        performance = comparison["performance"]
        paired = performance["e2e"]
        if paired["matched_pairs"]:
            paired_speedup = paired["median_paired_speedup_percent"]
            print(
                "PERFORMANCE "
                f"strict-pairs={paired['matched_pairs']} "
                f"median-delta={paired['median_paired_delta_ms']:+.1f}ms "
                f"speedup={f'{paired_speedup:+.1f}%' if paired_speedup is not None else 'n/a'}"
            )
        if performance["warning"]:
            print(f"WARNING    {performance['warning']}")
    print(f"RESULTS    {run.output_dir}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(parser, args)
    try:
        cases = _select_cases(config)
    except ValueError as exc:
        parser.error(str(exc))
    if args.list_cases:
        for case in cases:
            print(f"{case.id}\t{case.category}\t{case.prompt}")
        print(f"\n{len(cases)} selected case(s); suite hash {_suite_hash(cases)}")
        return 0

    try:
        run = asyncio.run(run_benchmark(config))
    except KeyboardInterrupt:
        print("Benchmark interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Benchmark infrastructure failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    _print_summary(run)
    if config.fail_under is not None and run.strict_percent < config.fail_under:
        print(
            f"Strict score {run.strict_percent:.3f}% is below --fail-under {config.fail_under:.3f}%.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
