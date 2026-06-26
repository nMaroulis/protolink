import pytest

from protolink import (
    Agent,
    AgentCard,
    ApprovalRequest,
    ContextManifest,
    PolicyDecision,
    PolicyEffect,
    RedactionPolicy,
    RunAction,
    RunContext,
    RunEvent,
    RunRecorder,
    RunReplay,
    Task,
    assert_budget_under,
    assert_no_denied_actions,
    assert_run_events,
    create_llm,
)


@pytest.mark.asyncio
async def test_run_recorder_builds_report_and_replay_from_stream():
    """RunRecorder should turn a streamed agent run into a durable report."""
    llm = create_llm("mock", default_response="report response")
    agent = Agent(
        AgentCard(
            name="report_agent",
            description="Run report test agent",
            url="runtime://report-agent",
            capabilities={"streaming": True},
        ),
        llm=llm,
        verbosity=0,
    )
    task = Task.create_infer(prompt="produce a concise response")
    context = RunContext(run_id="run_report", session_id="session_report", agent_chain=["client"])
    context.attach_to_task(task)

    recorder = RunRecorder(context=context)
    async for task_event in agent.handle_task_streaming(task):
        await recorder.record_task_event(task_event)

    report = recorder.to_report(metadata={"api_key": "secret-value"})
    replay = RunReplay(report.to_dict())

    assert report.context is not None
    assert report.context.run_id == "run_report"
    assert report.context_manifests
    assert report.final_task is not None
    assert replay.find_events("context.prepared")
    assert_run_events(
        replay,
        ["task.status", "context.prepared", "llm.call.started", "llm.call.completed", "task.status"],
    )
    assert_no_denied_actions(report)
    usage = assert_budget_under(report, max_total_tokens=2000)
    assert usage["input_tokens"] > 0

    redacted = report.redacted(RedactionPolicy())
    assert redacted.metadata["api_key"] == "[REDACTED]"


def test_run_event_promotes_causal_action_ids():
    """RunEvent should expose action/span IDs without consumers parsing metadata."""
    event = RunEvent.from_task_event(
        {
            "type": "task_llm_stream",
            "task_id": "task_1",
            "agent_name": "agent",
            "llm_event_type": "tool_start",
            "step": 2,
            "metadata": {
                "tool": "lookup",
                "action_id": "action_child",
                "parent_action_id": "action_parent",
            },
        }
    )

    assert event.type == "action.started"
    assert event.action_id == "action_child"
    assert event.parent_action_id == "action_parent"
    assert event.span_id == "action_child"
    assert event.parent_span_id == "action_parent"
    assert event.payload["action_id"] == "action_child"
    assert RunEvent.from_dict(event.to_dict()).action_id == "action_child"


def test_run_report_assertions_catch_denials_and_budget_overages():
    """Golden-run helpers should fail loudly on denied actions and budgets."""
    report = RunReplay(
        [
            RunEvent(type="task.status"),
            RunEvent(type="action.policy", action_id="action_denied", payload={"decision": {"effect": "deny"}}),
            RunEvent(
                type="llm.call.completed",
                payload={
                    "metrics": {
                        "usage": {
                            "input_tokens": 12,
                            "output_tokens": 4,
                            "total_tokens": 16,
                        }
                    }
                },
            ),
        ]
    ).report

    assert_run_events(report, ["task.status", "llm.call.completed"], ordered=True, allow_extra=True)
    with pytest.raises(AssertionError, match="Denied action"):
        assert_no_denied_actions(report)
    with pytest.raises(AssertionError, match="Budget assertion exceeded"):
        assert_budget_under(report, max_total_tokens=10)


def test_redaction_policy_applies_to_runtime_surfaces():
    """Shared redaction should work across events, manifests, and approvals."""
    policy = RedactionPolicy()

    event = RunEvent(type="task.status", payload={"api_key": "secret"})
    assert event.to_dict(redaction_policy=policy)["payload"]["api_key"] == "[REDACTED]"

    manifest = ContextManifest(metadata={"authorization": "Bearer secret"})
    assert manifest.to_dict(redaction_policy=policy)["metadata"]["authorization"] == "[REDACTED]"

    request = ApprovalRequest(
        action=RunAction(kind="tool.call", name="publish", payload={"password": "secret"}),
        policy_decision=PolicyDecision(
            effect=PolicyEffect.REQUIRE_APPROVAL,
            reason="approval required",
            policy_name="test",
        ),
        run_id="run_redaction",
    )
    assert request.to_dict(redaction_policy=policy)["action"]["payload"]["password"] == "[REDACTED]"
