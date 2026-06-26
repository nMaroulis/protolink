import pytest

from protolink import (
    Agent,
    AgentCard,
    InMemoryEventSink,
    RunBudget,
    RunContext,
    RunEvent,
    Task,
    create_llm,
)


def test_run_context_round_trips_through_task_metadata():
    """RunContext should be the typed source of truth for task runtime metadata."""
    task = Task.create_infer(prompt="summarize the attached material")
    context = RunContext(
        run_id="run_test_context",
        session_id="session_alpha",
        trace_id="trace_alpha",
        workspace_uri="file:///workspace",
        parent_run_id="run_parent",
        agent_chain=["gateway"],
        permissions={"fs.read": {"paths": ["file:///workspace"]}},
        budget=RunBudget(max_steps=4, max_llm_calls=2, max_runtime_seconds=30.0),
        metadata={"customer": "generic-app"},
        created_at="2026-01-01T00:00:00+00:00",
    )

    context.attach_to_task(task)
    restored = RunContext.from_task(task)

    assert restored.to_dict() == context.to_dict()
    assert task.metadata["run_id"] == "run_test_context"
    assert task.metadata["session_id"] == "session_alpha"
    assert task.metadata["trace_id"] == "trace_alpha"
    assert task.metadata["workspace_uri"] == "file:///workspace"


def test_run_context_can_upgrade_legacy_task_metadata():
    """Legacy metadata keys should hydrate into the typed runtime context."""
    task = Task.create_infer(prompt="hello")
    task.metadata.update(
        {
            "session_id": "legacy_session",
            "trace_id": "legacy_trace",
            "workspace": "memory://workspace",
            "permissions": {"network": False},
            "budgets": {"max_steps": 3},
        }
    )

    context = RunContext.ensure_task_context(task, agent_name="legacy_agent")

    assert context.run_id == task.id
    assert context.session_id == "legacy_session"
    assert context.trace_id == "legacy_trace"
    assert context.workspace_uri == "memory://workspace"
    assert context.permissions == {"network": False}
    assert context.budget.max_steps == 3
    assert context.agent_chain == ["legacy_agent"]
    assert task.metadata["run_context"]["run_id"] == task.id


@pytest.mark.asyncio
async def test_golden_run_event_stream_snapshot_from_mock_agent():
    """A generic mock-agent run should produce a stable normalized event stream."""
    llm = create_llm("mock", default_response="golden response")
    agent = Agent(
        AgentCard(
            name="golden_agent",
            description="Generic golden-run test agent",
            url="runtime://golden-agent",
            capabilities={"streaming": True},
        ),
        llm=llm,
        verbosity=0,
    )
    task = Task.create_infer(prompt="produce a short response")
    RunContext(
        run_id="run_golden",
        session_id="session_golden",
        workspace_uri="memory://workspace",
        agent_chain=["client"],
        budget=RunBudget(max_steps=5),
        created_at="2026-01-01T00:00:00+00:00",
    ).attach_to_task(task)

    sink = InMemoryEventSink()
    legacy_events = []
    async for event in agent.handle_task_streaming(task):
        legacy_events.append(event)
        await sink.emit_task_event(event, context=RunContext.from_task(task))

    snapshot = []
    for event in sink.to_list():
        summary = event["summary"]
        if event["type"] == "task.artifact":
            summary = "Artifact produced"
        elif event["type"] == "context.prepared":
            summary = "Context prepared"
        elif event["type"] == "llm.call.completed":
            summary = "LLM call completed"
        snapshot.append(
            {
                "sequence": event["sequence"],
                "type": event["type"],
                "run_id": event["run_id"],
                "agent_name": event["agent_name"],
                "severity": event["severity"],
                "summary": summary,
                "final": event["final"],
                "payload_type": event["payload"].get("type"),
                "llm_event_type": event["payload"].get("llm_event_type"),
            }
        )

    assert snapshot == [
        {
            "sequence": 1,
            "type": "task.status",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "Task state changed to working",
            "final": False,
            "payload_type": "task_status_update",
            "llm_event_type": None,
        },
        {
            "sequence": 2,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_step",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_step",
        },
        {
            "sequence": 3,
            "type": "context.prepared",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "Context prepared",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "context_prepared",
        },
        {
            "sequence": 4,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_context",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_context",
        },
        {
            "sequence": 5,
            "type": "llm.call.started",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "LLM call started: mock-gpt",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_call_started",
        },
        {
            "sequence": 6,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_chunk",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_chunk",
        },
        {
            "sequence": 7,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_call_metrics",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_call_metrics",
        },
        {
            "sequence": 8,
            "type": "llm.call.completed",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "LLM call completed",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_call_completed",
        },
        {
            "sequence": 9,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_response",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_response",
        },
        {
            "sequence": 10,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_action",
            "final": False,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_action",
        },
        {
            "sequence": 11,
            "type": "llm.stream",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "llm_final: golden response",
            "final": True,
            "payload_type": "task_llm_stream",
            "llm_event_type": "llm_final",
        },
        {
            "sequence": 12,
            "type": "task.artifact",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "Artifact produced",
            "final": False,
            "payload_type": "task_artifact_update",
            "llm_event_type": None,
        },
        {
            "sequence": 13,
            "type": "task.status",
            "run_id": "run_golden",
            "agent_name": "golden_agent",
            "severity": "info",
            "summary": "Task finished with state completed",
            "final": True,
            "payload_type": "task_status_update",
            "llm_event_type": None,
        },
    ]

    recovered_final = RunEvent.from_task_event(legacy_events[-1])
    assert recovered_final.run_id == "run_golden"
    assert recovered_final.agent_name == "golden_agent"
