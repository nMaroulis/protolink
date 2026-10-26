"""Native worker execution preserves admission, cancellation and tool controls."""

from __future__ import annotations

import asyncio
import inspect
import threading
from contextvars import ContextVar

import pytest

from protolink import ActionDeniedError, Agent, CapabilityPolicy, RunBudget, RunContext, Task, TaskState, Tool
from protolink.core.budget import BudgetExceededError
from protolink.core.workers import SyncWorkerPool
from protolink.llms import MockLLM


async def wait_thread_event(event: threading.Event) -> None:
    async def wait() -> None:
        while not event.is_set():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), 2)


@pytest.mark.asyncio
async def test_worker_preserves_signature_arguments_context_and_exceptions():
    request_value: ContextVar[str] = ContextVar("test_worker_request")
    original = ValueError("original exception")
    loop_thread = threading.get_ident()

    def lookup(count: int) -> tuple[int, str, int]:
        """Read a request-local selection."""
        if count < 0:
            raise original
        return count, request_value.get(), threading.get_ident()

    tool = Tool.from_callable(lookup, sync_execution="thread")
    agent = Agent(name="lookup", tools=[tool], verbosity=0)
    assert tool._signature == inspect.signature(lookup)
    assert tool.description == "Read a request-local selection."
    assert set(tool.input_schema["properties"]) == {"count"}

    async def request(value: str) -> tuple[int, str, int]:
        token = request_value.set(value)
        try:
            return await agent.call_tool("lookup", count="3")
        finally:
            request_value.reset(token)

    first, second = await asyncio.gather(request("first"), request("second"))
    assert first[:2] == (3, "first")
    assert second[:2] == (3, "second")
    assert first[2] != loop_thread and second[2] != loop_thread
    with pytest.raises(ValueError) as raised:
        await agent.call_tool("lookup", count=-1)
    assert raised.value is original
    agent._sync_workers.close()


@pytest.mark.asyncio
async def test_agent_default_and_per_tool_override_keep_async_tools_on_event_loop():
    loop_thread = threading.get_ident()
    agent = Agent(name="defaults", sync_execution="thread", verbosity=0)

    @agent.tool
    def default_worker() -> int:
        return threading.get_ident()

    @agent.tool(sync_execution="inline")
    def inline_override() -> int:
        return threading.get_ident()

    @agent.tool(sync_execution="thread")
    async def async_tool() -> int:
        await asyncio.sleep(0)
        return threading.get_ident()

    class AsyncCallable:
        async def __call__(self) -> int:
            return threading.get_ident()

    agent.add_tool(Tool.from_callable(AsyncCallable(), name="async_object"))
    assert await agent.call_tool("default_worker") != loop_thread
    assert await agent.call_tool("inline_override") == loop_thread
    assert await agent.call_tool("async_tool") == loop_thread
    assert await agent.call_tool("async_object") == loop_thread
    assert inline_override() == loop_thread
    agent._sync_workers.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["direct", "inference", "delegation"])
async def test_worker_mode_applies_to_every_native_tool_path(path):
    loop_thread = threading.get_ident()
    calls = []

    def lookup(value: int) -> int:
        calls.append((value, threading.get_ident()))
        return value

    agent = Agent(name="specialist", tools=[lookup], sync_execution="thread", verbosity=0)
    if path == "direct":
        task = await agent.run_task(Task.create_tool_call("lookup", {"value": "2"}))
    elif path == "inference":
        agent.llm = MockLLM(sequential_responses=[{"type": "tool_call", "tool": "lookup", "args": {"value": 2}}, "ok"])
        task = await agent.run_task(Task.create_infer("look up"))
    else:
        parent = Agent(
            name="coordinator",
            subagents=[agent],
            llm=MockLLM(
                sequential_responses=[
                    {
                        "type": "agent_call",
                        "agent": "specialist",
                        "action": "tool_call",
                        "tool": "lookup",
                        "args": {"value": 2},
                    },
                    "ok",
                ]
            ),
            verbosity=0,
        )
        task = await parent.run_task(Task.create_infer("consult"))
        parent._sync_workers.close()
    assert task.state is TaskState.COMPLETED, task.metadata
    assert len(calls) == 1 and calls[0][0] == 2 and calls[0][1] != loop_thread
    agent._sync_workers.close()


@pytest.mark.asyncio
async def test_slow_tool_does_not_block_another_request():
    started, release = threading.Event(), threading.Event()

    def slow() -> str:
        started.set()
        assert release.wait(3)
        return "slow"

    def fast() -> str:
        return "fast"

    agent = Agent(name="concurrent", tools=[slow, fast], sync_execution="thread", max_sync_workers=2, verbosity=0)
    running = asyncio.create_task(agent.call_tool("slow"))
    try:
        await wait_thread_event(started)
        assert await asyncio.wait_for(agent.call_tool("fast"), 1) == "fast"
        assert not running.done()
    finally:
        release.set()
        await running
        agent._sync_workers.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["direct", "inference"])
async def test_canceled_thread_retains_capacity_and_cannot_publish_late_success(path):
    started, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def blocking(value: int) -> int:
        if value == 1:
            started.set()
            assert release.wait(3)
        else:
            second_started.set()
        return value

    agent = Agent(name="cancel", tools=[blocking], sync_execution="thread", max_sync_workers=1, verbosity=0)
    if path == "inference":
        agent.llm = MockLLM(
            sequential_responses=[{"type": "tool_call", "tool": "blocking", "args": {"value": 1}}, "unexpected"]
        )
        first = Task.create_infer("block")
    else:
        first = Task.create_tool_call("blocking", {"value": 1})
    first_run = asyncio.create_task(agent.run_task(first))
    second_run = None
    try:
        await wait_thread_event(started)
        await agent.cancel_task(first.id, reason="user stopped")
        assert (await asyncio.wait_for(first_run, 1)).state is TaskState.CANCELED
        second = Task.create_tool_call("blocking", {"value": 2})
        second_run = asyncio.create_task(agent.run_task(second))
        await asyncio.sleep(0.03)
        assert not second_started.is_set()
        assert not second_run.done()
        release.set()
        assert (await asyncio.wait_for(second_run, 1)).state is TaskState.COMPLETED
        await asyncio.sleep(0)
        terminal = [event["type"] for event in first.metadata["run_events"] if event["type"].startswith("action.")]
        assert terminal.count("action.canceled") == 1
        assert "action.completed" not in terminal
        assert first.state is TaskState.CANCELED
        assert not any(part.type == "tool_output" for artifact in first.artifacts for part in artifact.parts)
    finally:
        release.set()
        await first_run
        if second_run is not None:
            await second_run
        agent._sync_workers.close()


@pytest.mark.asyncio
async def test_canceling_queued_call_never_invokes_it_or_loses_a_slot():
    pool = SyncWorkerPool(1)
    started, release = threading.Event(), threading.Event()
    calls = []

    def blocking() -> None:
        started.set()
        assert release.wait(3)

    first = asyncio.create_task(pool.run(blocking))
    try:
        await wait_thread_event(started)
        queued = asyncio.create_task(pool.run(calls.append, "canceled"))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        release.set()
        await first
        await asyncio.wait_for(pool.run(calls.append, "next"), 1)
        assert calls == ["next"]
    finally:
        release.set()
        await first
        pool.close()


@pytest.mark.asyncio
async def test_shutdown_is_lazy_and_closes_pool_even_when_server_stop_fails():
    agent = Agent(name="lifecycle", sync_execution="thread", verbosity=0)
    assert agent._sync_workers._executor is None

    class BrokenServer:
        async def stop(self) -> None:
            raise ValueError("server stop failed")

    agent._server = BrokenServer()
    with pytest.raises(ValueError, match="server stop failed"):
        await agent._stop()
    assert agent._sync_workers._executor is None
    assert agent._sync_workers._closed
    await agent._stop()  # Idempotent cleanup.


@pytest.mark.asyncio
async def test_shutdown_does_not_wait_for_canceled_thread_and_rejects_queued_work():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocking() -> str:
        started.set()
        try:
            assert release.wait(3)
            return "late"
        finally:
            finished.set()

    agent = Agent(name="shutdown", tools=[blocking], sync_execution="thread", max_sync_workers=1, verbosity=0)
    running = asyncio.create_task(agent.call_tool("blocking"))
    queued = None
    try:
        await wait_thread_event(started)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        queued = asyncio.create_task(agent.call_tool("blocking"))
        await asyncio.sleep(0)
        await asyncio.wait_for(agent._stop(), 1)
        assert not finished.is_set()
        with pytest.raises(RuntimeError, match="closed"):
            await queued
        with pytest.raises(RuntimeError, match="closed"):
            await agent.call_tool("blocking")
    finally:
        release.set()
        await wait_thread_event(finished)
        if queued is not None and not queued.done():
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
        agent._sync_workers.close()


@pytest.mark.asyncio
async def test_authorization_and_budget_reject_before_worker_submission():
    calls = []

    def write() -> str:
        calls.append(True)
        return "written"

    agent = Agent(
        name="guarded",
        tools=[Tool.from_callable(write, capabilities=["test.write"])],
        sync_execution="thread",
        policy=CapabilityPolicy({"test.write": "deny"}),
        verbosity=0,
    )
    denied = Task.create_tool_call("write", {})
    with pytest.raises(ActionDeniedError):
        await agent.run_task(denied)
    assert denied.state is TaskState.FAILED
    agent.action_authorizer.policy = CapabilityPolicy()
    context = RunContext(budget=RunBudget(max_tool_calls=0))
    exhausted = Task.create_tool_call("write", {}, context=context)
    with pytest.raises(BudgetExceededError):
        await agent.run_task(exhausted)
    assert exhausted.state is TaskState.FAILED
    assert calls == []
    assert agent._sync_workers._executor is None
    agent._sync_workers.close()


def test_worker_configuration_roundtrip_and_validation():
    agent = Agent(name="configured", sync_execution="thread", max_sync_workers=2, verbosity=0)
    restored = Agent.from_dict(agent.to_dict())
    assert restored.sync_execution == "thread"
    assert restored._sync_workers.max_workers == 2
    for value in (0, -1, True, "2"):
        with pytest.raises(ValueError, match="max_sync_workers"):
            Agent(name="invalid", max_sync_workers=value, verbosity=0)
    with pytest.raises(ValueError, match="sync_execution"):
        Agent(name="invalid", sync_execution="invalid", verbosity=0)
    with pytest.raises(ValueError, match="sync_execution"):
        Tool.from_callable(lambda: None, sync_execution="invalid")
