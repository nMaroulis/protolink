"""Protolink 0.6.6 normalized run-report regression diffing.

This provider-free example builds completed reports directly so it can show the
comparison contract without calling a model, tool, transport, or external
service. A real application would record each run with ``RunRecorder`` and keep
the baseline report in a ``RunStore`` or test fixture.

Run it with:

    python examples/run_regression_diff.py
"""

from __future__ import annotations

from protolink import (
    Message,
    Part,
    RunContext,
    RunEvent,
    RunReport,
    RunReportDiffConfig,
    RunReportTolerance,
    Task,
    TaskState,
    assert_run_matches,
    diff_run_reports,
)

REGRESSION_CONFIG = RunReportDiffConfig(
    tolerances=(
        # Explicit rules opt these otherwise volatile timings back into a
        # bounded comparison.
        RunReportTolerance(
            "/events/*/payload/latency_ms",
            absolute_tolerance=50.0,
        ),
        RunReportTolerance(
            "/metrics/*/latency_ms",
            absolute_tolerance=50.0,
        ),
    )
)


def build_report(
    *,
    label: str,
    answer: str,
    latency_ms: float,
    sequence_start: int,
    timestamp: str,
) -> RunReport:
    """Build one completed report with deliberately volatile execution fields."""
    task = Task(
        id=f"task_{label}",
        state=TaskState.COMPLETED,
        messages=[
            Message(
                id=f"message_{label}",
                role="agent",
                parts=[Part.text(answer)],
                timestamp=timestamp,
            )
        ],
        created_at=timestamp,
    )
    context = RunContext(
        run_id=f"run_{label}",
        session_id="regression-demo",
        trace_id=f"trace_{label}",
        agent_chain=["regression-agent"],
        created_at=timestamp,
    )
    context.attach_to_task(task)
    final_task = task.to_dict()
    events = [
        RunEvent(
            event_id=f"event_llm_{label}",
            type="llm.call.completed",
            run_id=context.run_id,
            task_id=task.id,
            agent_name="regression-agent",
            sequence=sequence_start,
            summary="Model call completed",
            payload={"provider": "mock", "model": "regression-fixture", "latency_ms": latency_ms},
            metadata={"source_type": "task_llm_stream"},
            timestamp=timestamp,
        ),
        RunEvent(
            event_id=f"event_task_{label}",
            type="task.status",
            run_id=context.run_id,
            task_id=task.id,
            agent_name="regression-agent",
            sequence=sequence_start + 1,
            summary="Task completed",
            payload={"state": "completed", "metadata": {"task": final_task}},
            final=True,
            metadata={"source_type": "task_status_update"},
            timestamp=timestamp,
        ),
    ]
    return RunReport.from_events(
        events,
        context=context,
        final_task=final_task,
        metadata={"suite": "provider-free-regression-example"},
    )


def main() -> None:
    """Show volatile-field normalization and a real behavioral difference."""
    baseline = build_report(
        label="baseline",
        answer="The approved total is 42.",
        latency_ms=100.0,
        sequence_start=1,
        timestamp="2026-07-17T09:00:00Z",
    )
    equivalent_candidate = build_report(
        label="candidate_same",
        answer="The approved total is 42.",
        latency_ms=125.0,
        sequence_start=101,
        timestamp="2026-07-17T09:05:00Z",
    )

    equivalent = diff_run_reports(
        baseline,
        equivalent_candidate,
        config=REGRESSION_CONFIG,
    )
    assert equivalent.matches
    assert_run_matches(
        baseline,
        equivalent_candidate,
        config=REGRESSION_CONFIG,
    )
    print("Equivalent candidate:", "MATCH")

    changed_candidate = build_report(
        label="candidate_changed",
        answer="The approved total is 43.",
        latency_ms=125.0,
        sequence_start=201,
        timestamp="2026-07-17T09:10:00Z",
    )
    changed = diff_run_reports(
        baseline,
        changed_candidate,
        config=REGRESSION_CONFIG,
    )
    assert not changed.matches
    print("Changed candidate:", "CHANGED")
    print(changed.format(max_differences=5))

    try:
        assert_run_matches(
            baseline,
            changed_candidate,
            config=REGRESSION_CONFIG,
        )
    except AssertionError as exc:
        print("Regression assertion:", str(exc).splitlines()[0])


if __name__ == "__main__":
    main()
