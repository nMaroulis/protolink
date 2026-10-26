"""Applications consume terminal tool evidence without wrapping their tools."""

import asyncio

import pytest

from protolink import (
    Agent,
    AgentHooks,
    ContextPolicy,
    RunEvent,
    RunHandle,
    RunReport,
    Task,
    ToolRejectedError,
    create_llm,
)
from protolink.core.evidence import collect_tool_evidence


def scripted(name, responses, **kwargs):
    return Agent(name=name, llm=create_llm("mock", sequential_responses=responses), verbosity=0, **kwargs)


def tool_call(name="lookup", **args):
    return {"type": "tool_call", "tool": name, "args": args}


def test_evidence_correlates_native_events_without_duplicate_terminal_observations():
    action = {"kind": "tool.call", "name": "lookup", "action_id": "action-1", "payload": {"arguments": {"key": 7}}}
    started = RunEvent(
        type="action.started",
        run_id="worker-run",
        action_id="action-1",
        payload={"action": action},
        timestamp="2026-01-01T00:00:01+00:00",
    )
    completed = RunEvent(
        type="action.completed",
        run_id="worker-run",
        task_id="worker-task",
        agent_name="worker",
        action_id="action-1",
        parent_action_id="consultation",
        delegation_id="consultation",
        payload={"action": action, "result": None},
        timestamp="2026-01-01T00:00:03+00:00",
    )
    # A replayed snapshot and the enclosing consultation are not additional tool executions.
    delegation = RunEvent(
        type="action.completed",
        action_id="consultation",
        payload={"action": {"kind": "agent.call", "name": "worker"}, "result": "answer"},
    )
    report = RunReport.from_events([started, completed, completed.to_dict(), delegation])
    (evidence,) = report.tool_evidence
    assert evidence.tool_name == "lookup"
    assert evidence.arguments == {"key": 7}
    assert evidence.result is None and not evidence.result_omitted
    assert evidence.duration_seconds == 2
    assert evidence.run_id == "worker-run" and evidence.task_id == "worker-task"
    assert evidence.agent_name == "worker"
    assert evidence.parent_action_id == evidence.delegation_id == "consultation"
    assert RunReport.from_dict(report.to_dict()).tool_evidence == (evidence,)
    detached = evidence.to_dict()
    detached["arguments"]["key"] = "changed"
    assert evidence.arguments == {"key": 7}


def test_evidence_distinguishes_policy_and_validation_rejections_from_executed_effects():
    action = {"kind": "tool.call", "name": "remove", "action_id": "denied", "payload": {"arguments": {"key": 7}}}
    events = [
        RunEvent(type="action.requested", action_id="denied", payload={"action": action}),
        RunEvent(
            type="action.denied", action_id="denied", payload={"decision": {"effect": "deny", "reason": "private"}}
        ),
        RunEvent(
            type="action.rejected",
            payload={
                "metadata": {
                    "tool": "lookup",
                    "args": {"key": "bad"},
                    "phase": "validation",
                    "rejection": {"code": "invalid_arguments"},
                }
            },
        ),
    ]
    denied, invalid = collect_tool_evidence(events)
    assert denied.outcome == invalid.outcome == "rejected"
    assert denied.arguments == {"key": 7} and invalid.arguments is None
    assert denied.started_at is denied.duration_seconds is None
    assert denied.error["effect"] == "deny"
    assert invalid.error["code"] == "invalid_arguments"


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("exposed", [False, True])
async def test_inference_evidence_respects_explicit_result_visibility(streaming, exposed):
    agent = scripted("evidence-visibility", [tool_call(key=7), "done"], expose_tool_results=exposed)

    @agent.tool
    def lookup(key: int) -> dict:
        return {"key": key, "value": "private-marker"}

    task = Task.create_infer(prompt="lookup key seven")
    if streaming:
        result = await RunHandle.start(agent, task).result()
        report = result.report
        assert result.tool_evidence == report.tool_evidence
    else:
        report = RunReport.from_task(await agent.handle_task(task))
    (evidence,) = report.tool_evidence
    assert evidence.tool_name == "lookup" and evidence.arguments == {"key": 7}
    assert evidence.outcome == "completed"
    assert evidence.result_omitted is not exposed
    assert evidence.started_at and evidence.finished_at and evidence.duration_seconds is not None
    if exposed:
        assert evidence.result == {"key": 7, "value": "private-marker"}
    else:
        assert evidence.result is None
        assert "private-marker" not in str(report.to_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "rejected", "failed", "canceled"])
async def test_direct_tool_evidence_is_live_and_terminal_once(outcome):
    agent = Agent(name=f"direct-{outcome}", verbosity=0)
    entered, release = asyncio.Event(), asyncio.Event()

    @agent.tool
    async def lookup(key: int) -> dict:
        entered.set()
        await release.wait()
        if outcome == "rejected":
            raise ToolRejectedError("Choose another key", code="invalid_selection")
        if outcome == "failed":
            raise ValueError("Service unavailable")
        return {"key": key}

    handle = RunHandle.start(agent, Task.create_tool_call(tool_name="lookup", args={"key": 7}))
    observations = []

    async def observe():
        async for item in handle.tool_evidence():
            observations.append(item)

    subscription = asyncio.create_task(observe())
    await asyncio.wait_for(entered.wait(), 2)
    assert not observations
    if outcome == "canceled":
        await handle.cancel("Stop this lookup")
    else:
        release.set()
    result = await asyncio.wait_for(handle.result(), 2)
    await asyncio.wait_for(subscription, 2)
    assert tuple(observations) == result.tool_evidence
    (evidence,) = observations
    assert evidence.outcome == outcome and evidence.arguments == {"key": 7}
    assert evidence.action_id and evidence.agent_name == agent.card.name
    if outcome == "completed":
        assert evidence.result == {"key": 7}
    if outcome == "rejected":
        assert evidence.error["code"] == "invalid_selection"
    if outcome == "failed":
        assert evidence.error["code"] == "ValueError"
    assert [item async for item in handle.tool_evidence()] == observations


@pytest.mark.asyncio
async def test_delegated_evidence_preserves_child_execution_identity():
    child = Agent(name="evidence-specialist", expose_tool_results=True, verbosity=0)

    @child.tool
    async def lookup(key: int) -> dict:
        return {"key": key}

    parent = scripted(
        "evidence-coordinator",
        [
            {
                "type": "agent_call",
                "agent": child.card.name,
                "action": "tool_call",
                "tool": "lookup",
                "args": {"key": 7},
            },
            "finished",
        ],
        subagents=[child],
    )
    result = await asyncio.wait_for(parent.start_run("consult specialist").result(), 2)
    assert result.status == "completed"
    (evidence,) = result.tool_evidence
    assert evidence.agent_name == child.card.name
    assert evidence.run_id != result.report.context.run_id
    assert evidence.task_id != result.task.id
    assert evidence.parent_action_id and evidence.parent_action_id == evidence.delegation_id
    assert evidence.arguments == {"key": 7} and evidence.result == {"key": 7}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["rejected", "failed", "canceled"])
async def test_inference_evidence_retains_failed_rejected_and_canceled_calls(outcome):
    agent = scripted(f"infer-{outcome}", [tool_call(key=7), "stopped"])
    entered, release = asyncio.Event(), asyncio.Event()

    @agent.tool
    async def lookup(key: int) -> str:
        entered.set()
        await release.wait()
        if outcome == "rejected":
            raise ToolRejectedError("Key was unavailable", code="unavailable")
        if outcome == "failed":
            raise ValueError("Service unavailable")
        return "late result"

    handle = agent.start_run("lookup key")
    await asyncio.wait_for(entered.wait(), 2)
    if outcome == "canceled":
        await handle.cancel("Stop lookup")
    else:
        release.set()
    result = await asyncio.wait_for(handle.result(), 2)
    (evidence,) = result.tool_evidence
    assert evidence.outcome == outcome
    assert evidence.action_id and evidence.arguments == {"key": 7}
    if outcome != "canceled":
        assert evidence.error
    assert "late result" not in str(result.report.to_dict())


def test_delegation_rejection_envelopes_are_not_tool_execution():
    event = RunEvent.from_task_event(
        {
            "type": "task_llm_stream",
            "llm_event_type": "agent_call_rejected",
            "metadata": {
                "agent": "worker",
                "action": "tool_call",
                "tool": "lookup",
                "action_id": "consultation",
                "rejection": {"code": "no_such_tool"},
            },
        }
    )
    assert not collect_tool_evidence([event])


def test_evidence_preserves_execution_timestamps_when_normalizing_queued_events():
    def event(event_type, timestamp):
        return RunEvent.from_task_event(
            {
                "type": "task_llm_stream",
                "llm_event_type": event_type,
                "timestamp": timestamp,
                "metadata": {"tool": "lookup", "args": {}, "action_id": "tool-1"},
            }
        )

    started_at = "2026-01-01T00:00:01+00:00"
    finished_at = "2026-01-01T00:00:04+00:00"
    (evidence,) = collect_tool_evidence([event("tool_start", started_at), event("tool_result", finished_at)])
    assert evidence.started_at == started_at and evidence.finished_at == finished_at
    assert evidence.duration_seconds == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated_action", ["tool_call", "infer"])
async def test_parent_cancellation_retains_one_child_tool_terminal(delegated_action):
    child = scripted("canceled-specialist", [tool_call(key=7), "finished"], expose_tool_results=True)
    entered = asyncio.Event()

    @child.tool
    async def lookup(key: int) -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    call = {"type": "agent_call", "agent": child.card.name, "action": delegated_action}
    call.update({"tool": "lookup", "args": {"key": 7}} if delegated_action == "tool_call" else {"prompt": "lookup key"})
    parent = scripted("canceling-coordinator", [call, "finished"], subagents=[child])
    handle = parent.start_run("consult specialist")
    await asyncio.wait_for(entered.wait(), 2)
    await handle.cancel("stop parent")
    result = await asyncio.wait_for(handle.result(), 2)
    (evidence,) = result.tool_evidence
    assert result.status == "canceled"
    assert evidence.agent_name == child.card.name and evidence.outcome == "canceled"
    assert evidence.parent_action_id and evidence.parent_action_id == evidence.delegation_id
    assert evidence.result_omitted and evidence.result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("exposed", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_exposed_evidence_retains_actual_return_before_history_hooks_and_offloading(exposed, streaming):
    returned = {"private": "returned-credential-marker", "body": "x" * 200, "nested": {"value": "original"}}

    def source() -> dict:
        return returned

    def transform(observation):
        observation.result.pop("private")
        observation.result["nested"]["value"] = "transformed"

    model = create_llm("mock", sequential_responses=[tool_call("source"), "finished"])
    agent = Agent(
        name="actual-return",
        llm=model,
        tools=[source],
        hooks=[AgentHooks(after_tool=transform)],
        context_policy=ContextPolicy(tool_result_max_chars=40),
        expose_tool_results=exposed,
        verbosity=0,
    )
    task = Task.create_infer(prompt="read source")
    if streaming:
        report = (await RunHandle.start(agent, task).result()).report
    else:
        report = RunReport.from_task(await agent.handle_task(task))
    (evidence,) = report.tool_evidence
    assert evidence.result_omitted is not exposed
    if exposed:
        assert evidence.result == returned
        assert evidence.result["nested"]["value"] == "original"
        assert "context_artifact" not in evidence.result
    else:
        assert evidence.result is None
        assert "returned-credential-marker" not in str(report.to_dict())
    assert "returned-credential-marker" not in str(model.history.to_list())
    assert "context_artifact" in str(model.history.to_list())
    artifacts = next(iter(agent.context_artifacts.sessions.values()))
    assert '"value": "transformed"' in next(iter(artifacts.values()))
    assert "returned-credential-marker" not in str(artifacts)


@pytest.mark.asyncio
@pytest.mark.parametrize("exposed", [False, True])
@pytest.mark.parametrize("hook_outcome", ["failed", "canceled"])
async def test_hook_failure_or_cancellation_preserves_completed_tool_evidence(exposed, hook_outcome):
    calls = 0
    hook_entered = asyncio.Event()

    def source() -> dict:
        nonlocal calls
        calls += 1
        return {"value": "actual", "credential": "returned-private-marker"}

    async def transform(observation):
        observation.result["value"] = "transformed"
        hook_entered.set()
        if hook_outcome == "canceled":
            await asyncio.Event().wait()
        raise ValueError("Observation could not be prepared")

    agent = Agent(
        name="post-tool-failure",
        llm=create_llm("mock", sequential_responses=[tool_call("source"), "finished"]),
        tools=[source],
        hooks=[AgentHooks(after_tool=transform)],
        expose_tool_results=exposed,
        verbosity=0,
    )
    handle = agent.start_run("read source")
    await asyncio.wait_for(hook_entered.wait(), 2)
    if hook_outcome == "canceled":
        await handle.cancel("Cancel after the tool returned")
    result = await asyncio.wait_for(handle.result(), 2)
    assert result.status == hook_outcome and calls == 1
    (evidence,) = result.tool_evidence
    assert evidence.outcome == "completed"
    assert evidence.result_omitted is not exposed
    assert not any(event.type == "action.failed" for event in result.report.events)
    assert sum(event.type == "action.completed" for event in result.report.events) == 1
    if exposed:
        assert evidence.result == {"value": "actual", "credential": "returned-private-marker"}
    else:
        assert evidence.result is None
        assert "returned-private-marker" not in str(result.report.to_dict())
    assert [item async for item in handle.tool_evidence()] == [evidence]
