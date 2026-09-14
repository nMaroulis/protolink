"""Parent evidence retains worker identities, live progress, and partial effects."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from protolink import (
    Agent,
    AgentCard,
    AgentGroup,
    Artifact,
    CompletionCheck,
    CompletionValidator,
    Part,
    RunContext,
    RunEvent,
    RunHandle,
    RunReport,
    SQLiteRunStore,
    Task,
    create_llm,
)
from protolink.core.execution import execution_scope


def agent(name, responses=None, **kwargs):
    return Agent(
        AgentCard(name=name, description="Delegation test", url=f"runtime://{name}", capabilities={"streaming": True}),
        llm=create_llm("mock", sequential_responses=responses) if responses else None,
        transport="runtime",
        verbosity=0,
        **kwargs,
    )


def delegate(child, *, action="tool_call", tool="work"):
    payload = {"tool": tool, "args": {}} if action == "tool_call" else {"prompt": "work"}
    return {"type": "agent_call", "agent": child.card.name, "action": action, **payload}


def discover(parent, child):
    parent.discover_agents = AsyncMock(return_value=[child.card])
    parent._resolve_agent_url = AsyncMock(return_value=child.card.url)


@pytest.mark.asyncio
async def test_worker_progress_arrives_live_and_receipts_are_saved_once(tmp_path):
    child = agent("live-child")
    release = asyncio.Event()

    @child.tool
    async def work() -> dict:
        await release.wait()
        return {"changed": True}

    store = SQLiteRunStore(tmp_path / "parent.db")
    parent = agent("live-parent", [delegate(child), "parent done"], run_store=store)
    discover(parent, child)
    task = Task.create_infer(prompt="delegate work")
    async with AgentGroup([parent, child]):
        handle = RunHandle.start(parent, task)

        async def observe_start():
            async for event in handle.events():
                if event.type == "action.started" and event.agent_name == child.card.name:
                    return event

        try:
            started = await asyncio.wait_for(observe_start(), 2)
            assert not release.is_set()
            assert started.task_id != task.id
            assert started.run_id != handle.context.run_id
        finally:
            release.set()
        result = await asyncio.wait_for(handle.result(), 2)

    assert result.status == "completed" and result.output == "parent done"
    events = result.report.events
    worker = [event for event in events if event.agent_name == child.card.name]
    completed = [event for event in worker if event.type == "action.completed"]
    assert len(completed) == 1
    assert completed[0].action_id == started.action_id
    assert completed[0].parent_action_id == completed[0].delegation_id
    assert completed[0].parent_action_id
    assert all(not event.final for event in worker)
    assert any(event.metadata.get("source_final") for event in worker)
    assert [event.task_id for event in events if event.final and event.type == "task.status"] == [task.id]
    assert len({event.event_id for event in events}) == len(events)
    assert len({artifact["id"] for artifact in result.report.artifacts}) == len(result.report.artifacts)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    saved = store.get_report(handle.context.run_id)
    assert completed[0].event_id in {event.event_id for event in saved.events}
    saved_task = store.get_task(task.id)
    validator = CompletionValidator(
        [
            CompletionCheck(
                "worker executed", lambda evidence: any(o.result == {"changed": True} for o in evidence.outcomes)
            )
        ]
    )
    (accepted,) = await validator.validate(saved_task)
    assert accepted.passed


@pytest.mark.asyncio
async def test_nested_delegation_keeps_worker_identity_in_nonstreamed_parent():
    worker = agent("nested-worker")

    @worker.tool
    def work() -> str:
        return "edited"

    middle = agent("nested-middle", [delegate(worker), "middle done"])
    parent = agent("nested-root", [delegate(middle, action="infer"), "root done"])
    discover(middle, worker)
    discover(parent, middle)
    async with AgentGroup([parent, middle, worker]):
        task = await parent.run_task(Task.create_infer(prompt="nested"))
    report = RunReport.from_task(task)
    receipts = [
        event for event in report.events if event.type == "action.completed" and event.agent_name == worker.card.name
    ]
    assert len(receipts) == 1
    assert receipts[0].payload["result"] == "edited"
    assert receipts[0].parent_action_id
    assert receipts[0].metadata["parent_run_id"] != report.context.run_id
    assert len({event.event_id for event in report.events}) == len(report.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnect", "missing_final", "cancel"])
async def test_interrupted_delegation_keeps_executed_receipts_without_resubmitting(failure):
    child = agent("interrupted-child")
    parent = agent("interrupted-parent", [delegate(child), "must not execute"])
    discover(parent, child)
    emitted = asyncio.Event()
    calls = 0

    async def subscribe(_url, task):
        nonlocal calls
        calls += 1
        context = RunContext.from_task(task)
        yield RunEvent(
            type="action.completed",
            event_id="partial-effect",
            action_id="edit",
            run_id=context.run_id,
            task_id=task.id,
            agent_name=child.card.name,
            payload={"action": {"kind": "tool.call", "name": "work"}, "result": "changed"},
        )
        emitted.set()
        if failure == "disconnect":
            raise ConnectionError("connection lost after effect")
        if failure == "cancel":
            await asyncio.Event().wait()

    parent.client.send_task_streaming = subscribe
    parent.client.get_agent_card = AsyncMock(return_value=child.card)
    parent.client.send_task = AsyncMock(side_effect=AssertionError("must not replay"))
    parent.client.cancel_task = AsyncMock()
    task = Task.create_infer(prompt="delegate")
    handle = RunHandle.start(parent, task)
    await asyncio.wait_for(emitted.wait(), 2)
    if failure == "cancel":
        await handle.cancel("stop parent")
    result = await asyncio.wait_for(handle.result(), 2)
    assert result.status == ("canceled" if failure == "cancel" else "failed")
    assert [event.event_id for event in result.report.events].count("partial-effect") == 1
    assert any(event["event_id"] == "partial-effect" for event in task.metadata["run_events"])
    assert calls == 1
    parent.client.send_task.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_call_override_merges_failed_worker_snapshot_and_artifacts():
    child_task = Task.create_infer(prompt="work")
    child_task.begin()
    child_task.add_artifact(Artifact(parts=[Part.text("partial output")]))
    child_task.fail("later failure")
    receipt = RunEvent(
        type="action.completed",
        action_id="edit",
        run_id="worker-run",
        task_id=child_task.id,
        payload={"action": {"kind": "tool.call", "name": "work"}, "result": "changed"},
    )
    child_task.metadata["run_events"] = [receipt.to_dict()]
    parent = agent("legacy-parent")

    async def legacy_call(_url, _task):
        return child_task

    parent.call_agent = legacy_call
    parent._resolve_agent_url = AsyncMock(return_value="runtime://legacy-child")
    parent_task = Task.create_infer(prompt="parent")
    with execution_scope(parent_task), pytest.raises(RuntimeError, match="later failure"):
        await parent._handle_agent_call("legacy-child", "infer", {"prompt": "work"})
    assert parent_task.metadata["run_events"][0]["event_id"] == receipt.event_id
    assert parent_task.artifacts == child_task.artifacts


@pytest.mark.asyncio
async def test_delegation_receipt_alone_is_not_an_executed_tool():
    task = Task.create_infer(prompt="answer only")
    report = RunReport.from_events(
        [
            RunEvent(
                type="action.completed",
                action_id="delegate",
                payload={"action": {"kind": "agent.call", "name": "worker"}, "result": "done"},
            )
        ]
    )
    (result,) = await CompletionValidator([CompletionCheck("edit", lambda _: True)]).validate(task, report=report)
    assert result.code == "execution_evidence_missing"


@pytest.mark.asyncio
async def test_custom_unary_worker_keeps_its_handler_and_returns_receipts_once():
    class UnaryWorker(Agent):
        async def handle_task(self, task):
            return task.complete(await self.call_tool("work"))

    child = UnaryWorker(
        AgentCard(name="unary-worker", description="custom", url="runtime://unary-worker"),
        transport="runtime",
        verbosity=0,
    )
    assert not child.card.capabilities.streaming
    calls = 0

    @child.tool
    def work() -> str:
        nonlocal calls
        calls += 1
        return "custom output"

    parent = agent("unary-parent", [delegate(child, action="infer"), "parent done"])
    discover(parent, child)
    async with AgentGroup([parent, child]):
        result = await RunHandle.start(parent, Task.create_infer(prompt="custom worker")).result()
    assert result.status == "completed" and calls == 1
    receipts = [
        event
        for event in result.report.events
        if event.type == "action.completed" and event.agent_name == child.card.name
    ]
    assert len(receipts) == 1 and receipts[0].payload["result"] == "custom output"
    assert receipts[0].parent_action_id


@pytest.mark.asyncio
async def test_a2a_delegation_uses_mapped_task_without_native_subscription():
    child = agent("a2a-worker")
    parent = agent("a2a-parent", [delegate(child, action="infer"), "parent done"])
    discover(parent, child)
    parent.client._select_protocol = AsyncMock(return_value=("a2a", None))
    parent.client.get_agent_card = AsyncMock(side_effect=AssertionError("native discovery is not applicable"))
    parent.client.send_task_streaming = AsyncMock(side_effect=AssertionError("native streaming is not applicable"))

    async def mapped_task(_url, task, *, protocol):
        assert protocol == "a2a"
        return task.complete("mapped output")

    parent.client.send_task = AsyncMock(side_effect=mapped_task)
    result = await RunHandle.start(parent, Task.create_infer(prompt="A2A worker")).result()
    assert result.status == "completed"
    parent.client.send_task.assert_awaited_once()
    parent.client.get_agent_card.assert_not_called()
    parent.client.send_task_streaming.assert_not_called()
