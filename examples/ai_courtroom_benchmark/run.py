#!/usr/bin/env python3
"""Run the modular paired AI courtroom advocacy benchmark."""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from .courtroom.benchmark import BenchmarkSettings, ModelSpec, run_benchmark
    from .courtroom.config import CaseConfig, load_case_config
    from .courtroom.providers import SUPPORTED_PROVIDERS, SUPPORTED_REFERENCE_MODELS
except ImportError:
    from courtroom.benchmark import BenchmarkSettings, ModelSpec, run_benchmark
    from courtroom.config import CaseConfig, load_case_config
    from courtroom.providers import SUPPORTED_PROVIDERS, SUPPORTED_REFERENCE_MODELS


class ConsoleProgress:
    """Elapsed-time progress reporter for potentially long live comparisons."""

    def __init__(self, *, verbosity: int) -> None:
        self.verbosity = verbosity
        self.started = time.monotonic()

    def __call__(self, level: int, message: str) -> None:
        if self.verbosity < level:
            return
        elapsed = time.monotonic() - self.started
        print(f"  [{elapsed:7.1f}s] {message}", flush=True)


async def async_main(args: argparse.Namespace) -> int:
    """Validate controls, run the benchmark, and print the report location."""
    try:
        case = load_case_config(args.case)
    except ValueError as exc:
        raise SystemExit(f"Invalid case configuration: {exc}") from None

    if args.model_a_side is None:
        args.model_a_side = case.decision.positive_side_id
    _validate_args(args, case=case)

    model_a_value = args.model_a or ("reference-evidence" if args.model_a_provider == "reference" else None)
    model_b_value = args.model_b or ("reference-narrative" if args.model_b_provider == "reference" else None)
    control_model_value = args.control_model or ("reference-evidence" if args.control_provider == "reference" else None)
    candidate_a = ModelSpec(
        id="model_a",
        label=args.model_a_label or model_a_value or "Model A",
        provider=args.model_a_provider,
        model=model_a_value,
        base_url=args.model_a_base_url,
    )
    candidate_b = ModelSpec(
        id="model_b",
        label=args.model_b_label or model_b_value or "Model B",
        provider=args.model_b_provider,
        model=model_b_value,
        base_url=args.model_b_base_url,
    )
    control = ModelSpec(
        id="control",
        label="Fixed judge and jury control",
        provider=args.control_provider,
        model=control_model_value,
        base_url=args.control_base_url,
    )

    uses_live_provider = any(
        provider != "reference"
        for provider in (
            candidate_a.provider,
            candidate_b.provider,
            control.provider,
        )
    )
    trial_count = args.replicates * (2 if args.mode == "paired" else 1)
    argument_count = sum(len(stage.speakers) for stage in case.procedure.stages)
    calls_per_trial = len(case.jurors) + argument_count + argument_count * len(case.jurors) + len(case.jurors) + 1

    if args.plan:
        _validate_model_selections(args)
        print("AI Courtroom Advocacy Benchmark")
        print(f"Case valid: {case.title}")
        print(f"Candidates: {candidate_a.label} vs {candidate_b.label}")
        print(f"Evidence: {len(case.evidence)}")
        print(f"Jurors: {len(case.jurors)}")
        print(f"Stages: {len(case.procedure.stages)}")
        print(f"Arguments per trial: {argument_count}")
        print(f"Trials: {trial_count}")
        print(f"Scheduled A2A exchanges: {trial_count * calls_per_trial}")
        print("Plan only: no agents started and no model calls made.")
        return 0

    if uses_live_provider and not args.allow_live:
        raise SystemExit(
            "This benchmark will make many live model calls. Review the providers, start with one replicate, "
            "then pass `--allow-live` to acknowledge API usage."
        )
    _validate_model_selections(args)

    verbosity = _progress_verbosity(args, uses_live_provider=uses_live_provider)
    progress = ConsoleProgress(verbosity=verbosity)
    destination = Path(args.output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    print("AI Courtroom Advocacy Benchmark")
    print(f"Case: {case.title}")
    print(f"Candidates: {candidate_a.label} vs {candidate_b.label}")
    print(f"Mode: {args.mode} · trials={trial_count} · scheduled A2A exchanges≈{trial_count * calls_per_trial}")
    print(f"Output: {destination}")

    benchmark = await run_benchmark(
        case=case,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        control=control,
        settings=BenchmarkSettings(
            benchmark_id=args.run_id or _default_run_id(case),
            mode=args.mode,
            model_a_side=args.model_a_side,
            seed=args.seed,
            replicates=args.replicates,
            temperature=args.temperature,
            max_attempts=args.max_attempts,
            action_parse_attempts=args.action_parse_attempts,
            agent_verbosity=args.agent_verbosity,
        ),
        output_root=destination,
        progress=progress,
    )

    print("\nResults:")
    side_labels = {side.id: side.label for side in case.sides}
    for trial in benchmark["trials"]:
        result = trial["result"]
        verdict = result.get("verdict")
        if isinstance(verdict, dict):
            winner = side_labels[str(verdict["winning_side_id"])]
            print(f"  {trial['trial_id']}: {winner} ({verdict['positive_votes']}-{verdict['negative_votes']})")
        else:
            error = result.get("error") or {}
            print(f"  {trial['trial_id']}: FAILED ({error.get('type', 'unknown error')})")
    fairness = benchmark["fairness"]
    print(f"Fairness audit: {'passed' if fairness['all_passed'] else 'needs attention'}")
    print(f"Open {destination / 'report.html'}")
    has_failed_trial = any(trial.get("result", {}).get("status") != "completed" for trial in benchmark["trials"])
    return 1 if has_failed_trial else 0


def build_parser() -> argparse.ArgumentParser:
    """Build the portable benchmark CLI documented by the example README."""
    root = Path(__file__).resolve().parent
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(
        description=("Compare two advocate LLMs on the same configured case, with a paired role swap and fixed jury."),
    )
    parser.add_argument("--case", default=str(root / "cases" / "c91_incident.json"))

    parser.add_argument("--model-a-provider", choices=SUPPORTED_PROVIDERS, default="reference")
    parser.add_argument("--model-a", help="Exact model ID; reference-evidence for the offline default.")
    parser.add_argument("--model-a-label", help="Human-readable report label for candidate A.")
    parser.add_argument("--model-a-base-url", help="Optional endpoint used only by candidate A.")

    parser.add_argument("--model-b-provider", choices=SUPPORTED_PROVIDERS, default="reference")
    parser.add_argument("--model-b", help="Exact model ID; reference-narrative for the offline default.")
    parser.add_argument("--model-b-label", help="Human-readable report label for candidate B.")
    parser.add_argument("--model-b-base-url", help="Optional endpoint used only by candidate B.")

    parser.add_argument("--control-provider", choices=SUPPORTED_PROVIDERS, default="reference")
    parser.add_argument("--control-model", help="Exact fixed model ID for the judge and every juror.")
    parser.add_argument("--control-base-url", help="Optional endpoint used only by fixed control agents.")

    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Shared temperature from 0 to 1.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Reference-fixture seed and live-run label; later replicates increment it.",
    )
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--mode", choices=("paired", "single"), default="paired")
    parser.add_argument(
        "--model-a-side",
        default=None,
        help="Configured side assigned to Model A in single mode; defaults to the case's positive side.",
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--action-parse-attempts", type=int, default=3)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Validate the case and print the execution plan without starting agents or making model calls.",
    )

    progress_group = parser.add_mutually_exclusive_group()
    progress_group.add_argument("-q", "--quiet", dest="verbosity", action="store_const", const=0)
    progress_group.add_argument("-v", "--verbose", dest="verbosity", action="store_const", const=2)
    parser.set_defaults(verbosity=None)
    parser.add_argument("--agent-verbosity", choices=(0, 1, 2), type=int, default=0)
    parser.add_argument("--output-dir", default=str(root / "output" / timestamp))
    parser.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


def _validate_args(args: argparse.Namespace, *, case: CaseConfig) -> None:
    if args.replicates < 1:
        raise SystemExit("--replicates must be at least 1")
    if args.replicates > 100:
        raise SystemExit("--replicates cannot exceed 100")
    if not 1 <= args.max_attempts <= 5:
        raise SystemExit("--max-attempts must be between 1 and 5")
    if not 1 <= args.action_parse_attempts <= 5:
        raise SystemExit("--action-parse-attempts must be between 1 and 5")
    if not math.isfinite(args.temperature) or not 0.0 <= args.temperature <= 1.0:
        raise SystemExit("--temperature must be a finite value between 0 and 1")
    if args.mode == "single" and args.model_a_side not in case.sides_by_id:
        allowed = ", ".join(case.sides_by_id)
        raise SystemExit(f"--model-a-side must be one of: {allowed}")


def _validate_model_selections(args: argparse.Namespace) -> None:
    """Reject ambiguous live backends and unknown offline fixtures early."""
    selections = (
        ("Model A", "--model-a", args.model_a_provider, args.model_a, "reference-evidence"),
        ("Model B", "--model-b", args.model_b_provider, args.model_b, "reference-narrative"),
        ("Control", "--control-model", args.control_provider, args.control_model, "reference-evidence"),
    )
    for label, flag, provider, configured_model, reference_default in selections:
        if provider == "reference":
            reference_model = configured_model or reference_default
            if reference_model not in SUPPORTED_REFERENCE_MODELS:
                allowed = ", ".join(SUPPORTED_REFERENCE_MODELS)
                raise SystemExit(f"{flag} for {label} must be one of: {allowed}")
        elif not configured_model or not configured_model.strip():
            raise SystemExit(f"{flag} is required when {label} uses live provider `{provider}`")


def _default_run_id(case: CaseConfig) -> str:
    """Build a case-specific benchmark ID when the hidden override is absent."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{case.id}-advocacy-{timestamp}"


def _progress_verbosity(args: argparse.Namespace, *, uses_live_provider: bool) -> int:
    configured = getattr(args, "verbosity", None)
    if configured is not None:
        return int(configured)
    return 2 if uses_live_provider else 1


if __name__ == "__main__":
    main()
