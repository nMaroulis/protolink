"""Protolink 0.6.3 run reports, replay, assertions, and redaction.

``RunRecorder`` turns a live application stream into a durable ``RunReport``.
``RunReplay`` and assertion helpers make the same report useful for CLI UIs,
debug snapshots, and golden-run integration tests.

Run it with:

    python examples/v063_run_reports.py
"""

from __future__ import annotations

import asyncio

from protolink import (
    Agent,
    AgentCard,
    RedactionPolicy,
    RunContext,
    RunRecorder,
    RunReplay,
    Task,
    assert_budget_under,
    assert_no_denied_actions,
    assert_run_events,
    create_llm,
)


async def main() -> None:
    """Record one streamed run and replay its normalized event report."""
    agent = Agent(
        AgentCard(
            name="report_agent",
            description="Produces one reportable mock response",
            url="runtime://v063-report-agent",
            capabilities={"streaming": True},
        ),
        llm=create_llm("mock", default_response="reportable response"),
        verbosity=0,
    )
    task = Task.create_infer(prompt="produce a concise response")
    context = RunContext(
        run_id="run_v063_report",
        session_id="session_v063_report",
        agent_chain=["example-client"],
    )
    context.attach_to_task(task)

    recorder = RunRecorder(context=context)
    async for event in agent.handle_task_streaming(task):
        await recorder.record_task_event(event)

    report = recorder.to_report(metadata={"api_key": "secret-demo-key"})
    replay = RunReplay(report.to_dict())

    assert_run_events(
        replay,
        ["task.status", "context.prepared", "llm.call.started", "llm.call.completed", "task.status"],
    )
    assert_no_denied_actions(report)
    usage = assert_budget_under(report, max_total_tokens=2000)
    redacted = report.redacted(RedactionPolicy())

    print("Report run id:", report.context.run_id if report.context else None)
    print("Context manifests:", len(report.context_manifests))
    print("Replay llm completions:", len(replay.find_events("llm.call.completed")))
    print("Estimated total tokens:", usage["total_tokens"])
    print("Redacted metadata:", redacted.metadata)


if __name__ == "__main__":
    asyncio.run(main())
