"""Local dataset evaluations over actual Agent runs and reusable Python checks."""

from __future__ import annotations

import inspect
import json
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from protolink.core.run_context import RunBudget
from protolink.core.task import Task

if TYPE_CHECKING:
    from protolink.agents.base import Agent
    from protolink.core.report import RunReport


@dataclass(frozen=True)
class EvaluationCase:
    """One uniquely named input with optional reference output and metadata."""

    name: str
    prompt: str
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or not isinstance(self.prompt, str):
            raise ValueError("Evaluation cases require a nonblank name and a string prompt")


@dataclass(frozen=True)
class EvaluationScore:
    """A named score from zero to one, with optional evaluator explanation."""

    name: str
    value: float
    comment: str = ""

    def __post_init__(self) -> None:
        if not self.name or not math.isfinite(self.value) or not 0 <= self.value <= 1:
            raise ValueError("Evaluation scores require a name and a finite value between zero and one")


@dataclass
class EvaluationSample:
    """One actual run, its reference case, diagnostic evidence and evaluator scores.

    Checks receive this object. They may inspect task/report without invoking more
    tools. A model-based judge can be supplied as an async custom check; the caller
    owns its credentials, cost and calibration. Interrupted/failed runs remain
    samples with errors instead of being mistaken for successful final responses.
    """

    case: EvaluationCase
    repetition: int
    task: Task | None = None
    report: RunReport | None = None
    output: Any = None
    error: str | None = None
    duration_seconds: float = 0
    scores: list[EvaluationScore] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_report: bool = False) -> dict[str, Any]:
        """Export sample evidence; traces are optional and may contain private inputs."""
        from dataclasses import asdict

        result = {
            "case": asdict(self.case),
            "repetition": self.repetition,
            "output": self.output,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "scores": [asdict(score) for score in self.scores],
            "usage": self.usage,
        }
        if self.report is not None and include_report:
            result["report"] = self.report.to_dict()
        return result


@dataclass(frozen=True)
class EvaluationReport:
    """Comparable experiment results with per-case scores and execution failures."""

    samples: tuple[EvaluationSample, ...]

    @property
    def passed(self) -> bool:
        """All executions completed and every check awarded its full score."""
        return all(sample.error is None and all(score.value == 1 for score in sample.scores) for sample in self.samples)

    def to_dict(self, *, include_reports: bool = False) -> dict[str, Any]:
        """Return portable experiment data with aggregate quality and latency."""
        scores: dict[str, list[float]] = {}
        for sample in self.samples:
            for score in sample.scores:
                scores.setdefault(score.name, []).append(score.value)
        return {
            "passed": self.passed,
            "samples": [sample.to_dict(include_report=include_reports) for sample in self.samples],
            "scores": {name: sum(values) / len(values) for name, values in scores.items()},
            "mean_duration_seconds": sum(sample.duration_seconds for sample in self.samples)
            / max(1, len(self.samples)),
            "total_usage": {
                key: sum(sample.usage.get(key, 0) for sample in self.samples)
                for key in ("steps", "llm_calls", "tool_calls", "input_tokens", "output_tokens")
            },
        }

    def save(self, path: str | Path, *, include_reports: bool = False) -> None:
        """Save a UTF-8 JSON experiment; output and references are application data."""
        Path(path).write_text(
            json.dumps(self.to_dict(include_reports=include_reports), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def exact_match(sample: EvaluationSample) -> EvaluationScore:
    """Compare final output to the case's reference using Python equality."""
    return EvaluationScore("exact_match", float(sample.error is None and sample.output == sample.case.expected))


def tool_used(name: str) -> Callable[[EvaluationSample], EvaluationScore]:
    """Require a successful receipt for a named tool in the actual run report."""

    def check(sample: EvaluationSample) -> EvaluationScore:
        events = sample.report.events if sample.report is not None else ()
        found = any(
            event.type == "action.completed"
            and (
                event.payload.get("action", {}).get("name") == name
                or event.payload.get("metadata", {}).get("tool") == name
            )
            for event in events
        )
        return EvaluationScore(f"tool_used:{name}", float(found))

    return check


def load_evaluation_cases(path: str | Path) -> list[EvaluationCase]:
    """Read JSONL {name, prompt, expected?, metadata?} records without executing code."""
    cases = []
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            if len(line) > 1_000_000 or len(cases) >= 10_000:
                raise ValueError("Evaluation datasets are limited to 10000 records and 1 million characters per record")
            if line.strip():
                cases.append(EvaluationCase(**json.loads(line)))
    return cases


async def evaluate(
    agent: Agent | Callable[[], Agent],
    cases: Sequence[EvaluationCase] | str | Path,
    *,
    checks: Sequence[Callable[[EvaluationSample], Any]] = (exact_match,),
    repetitions: int = 1,
    concurrency: int = 1,
    budget: RunBudget | None = None,
) -> EvaluationReport:
    """Run cases through normal Agent execution and score final outputs/evidence.

    Supply an Agent for sequential evaluations or a zero-argument factory for
    fresh models/state per run and parallel work. Each repetition uses a unique
    conversation session. Tools execute for real under ordinary policies; use
    fixtures or isolated resources for test effects. Exceptions become failed
    samples, while cancellation still propagates. Checks return EvaluationScore,
    bool or a float in [0, 1]; async checks are supported. No hosted evaluator or
    optional provider dependency is required.
    """
    import asyncio

    from protolink.agents.base import Agent

    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (repetitions, concurrency)):
        raise ValueError("repetitions and concurrency must be positive integers")
    values = load_evaluation_cases(cases) if isinstance(cases, (str, Path)) else list(cases)
    if not values or len({case.name for case in values}) != len(values) or len(values) * repetitions > 100_000:
        raise ValueError("Provide unique, nonempty cases with at most 100000 total runs")
    if isinstance(agent, Agent) and concurrency != 1:
        raise ValueError("Parallel evaluations require an Agent factory for isolated models and state")
    semaphore = asyncio.Semaphore(min(concurrency, 128))

    async def run(case, repetition):
        async with semaphore:
            sample = EvaluationSample(case, repetition)
            started = time.monotonic()
            handle = None
            try:
                instance = agent() if not isinstance(agent, Agent) else agent
                if not isinstance(instance, Agent):
                    raise TypeError("The evaluation factory must return an Agent")
                handle = instance.start_run(Task.create_infer(case.prompt, session_id=uuid4().hex, budget=budget))
                result = await handle.result()
                sample.task, sample.report = result.task, result.report
                if result.report is not None:
                    for event in result.report.events:
                        if event.type == "llm.call.completed":
                            sample.usage.update(event.payload.get("metadata", event.payload).get("budget", {}))
                sample.output = result.output
                if result.status != "completed":
                    detail = (result.error or {}).get("message")
                    sample.error = f"Run ended with status {result.status}" + (f": {detail}" if detail else "")
            except asyncio.CancelledError:
                if handle is not None:
                    await handle.cancel("Evaluation canceled")
                    await handle.result()
                raise
            except Exception as exc:
                sample.error = f"{type(exc).__name__}: {exc}"[:2000]
            sample.duration_seconds = time.monotonic() - started
            sample.scores.append(EvaluationScore("execution_completed", float(sample.error is None)))
            for check in checks:
                try:
                    score = check(sample)
                    if inspect.isawaitable(score):
                        score = await score
                    if not isinstance(score, EvaluationScore):
                        score = EvaluationScore(getattr(check, "__name__", type(check).__name__), float(score))
                    if any(existing.name == score.name for existing in sample.scores):
                        raise ValueError(f"Duplicate evaluation metric {score.name}")
                    sample.scores.append(score)
                except Exception as exc:
                    sample.error = f"Evaluator failed: {type(exc).__name__}: {exc}"[:2000]
            return sample

    tasks = [asyncio.create_task(run(case, repetition)) for case in values for repetition in range(repetitions)]
    try:
        return EvaluationReport(tuple(await asyncio.gather(*tasks)))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def compare_evaluations(
    baseline: EvaluationReport, candidate: EvaluationReport, *, tolerance: float = 0
) -> dict[str, Any]:
    """Detect mean-score regressions for corresponding cases and named metrics.

    Every baseline case/metric must occur in the candidate. Scores are averaged
    across repetitions; timing is reported separately, never treated as quality.
    This compares executed experiments and does not replay tools or model calls.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and nonnegative")

    def metrics(report):
        result: dict[tuple[str, str], list[float]] = {}
        for sample in report.samples:
            for score in sample.scores:
                result.setdefault((sample.case.name, score.name), []).append(score.value)
        return {key: sum(values) / len(values) for key, values in result.items()}

    before, after = metrics(baseline), metrics(candidate)
    regressions = [
        {"case": key[0], "metric": key[1], "baseline": value, "candidate": after.get(key)}
        for key, value in before.items()
        if key not in after or after[key] + tolerance < value
    ]
    return {
        "passed": not regressions and all(sample.error is None for sample in candidate.samples),
        "regressions": regressions,
    }
