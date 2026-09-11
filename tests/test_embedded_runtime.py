"""Composition remains a convenience around existing local/network lifecycle."""

import asyncio

import pytest

from protolink import Agent, AgentCard, AgentGroup, RunHandle, Task
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.storage import SQLiteRunStore
from protolink.transport.runtime_transport import RuntimeTransport


def make_agent(name, **kwargs):
    a = Agent(AgentCard(name=name, description="test", url=f"runtime://{name}"), verbosity=0, **kwargs)

    @a.tool
    def echo(value: str) -> str:
        return value

    return a


@pytest.mark.asyncio
async def test_direct_group_handle_report_and_store(tmp_path):
    a = make_agent("direct", run_store=SQLiteRunStore(str(tmp_path / "runs.db")))
    async with AgentGroup([a]) as group:
        task = Task.create_tool_call(tool_name="echo", args={"value": "hello"})
        handle = group.run("direct", task)
        result = await asyncio.wait_for(handle.result(), 2)
        events = [event async for event in handle.events()]
        assert result.task.id == task.id and result.status == "completed"
        assert events and handle.report == result.report
        assert a.run_store.get_report(result.report.context.run_id) is not None
        assert a._transport is None


@pytest.mark.asyncio
async def test_runtime_transport_group_and_external_ownership():
    registry = Registry(transport=RuntimeTransport("runtime://managed-registry"))
    external = make_agent("external", transport="runtime")
    await external._serve(register=False)
    owned = make_agent("owned", transport="runtime")
    async with AgentGroup([owned], external_agents=[external], registry=registry, own_registry=True):
        names = {card.name for card in await registry.discover()}
        assert names == {"owned"}
        client = AgentClient(RuntimeTransport("runtime://handle-client"))
        task = Task.create_tool_call(tool_name="echo", args={"value": "wire"})
        result = await RunHandle.start(owned.card.url, task, client=client).result()
        assert result.status == "completed" and result.task.id == task.id
    assert RuntimeTransport.get_transport(owned.card.url) is None
    assert RuntimeTransport.get_transport(external.card.url) is external._transport
    await external._stop()


@pytest.mark.asyncio
async def test_partial_startup_failure_cleans_started_and_failing_resources(monkeypatch):
    first = make_agent("first", transport="runtime")
    second = make_agent("second", transport="runtime")
    external = make_agent("untouched")
    await external._serve(register=False)
    original = second._transport.start

    async def fail_start():
        await original()
        raise RuntimeError("partial startup")

    monkeypatch.setattr(second._transport, "start", fail_start)
    with pytest.raises(RuntimeError, match="partial startup"):
        await AgentGroup([first, second], external_agents=[external]).start()
    assert RuntimeTransport.get_transport(first.card.url) is None
    assert RuntimeTransport.get_transport(second.card.url) is None
    assert not getattr(external, "_stopped", False)


@pytest.mark.asyncio
async def test_group_cancels_owned_runs_on_exit():
    entered = asyncio.Event()
    cleaned = asyncio.Event()
    a = make_agent("waiting")

    @a.tool
    async def wait() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async with AgentGroup([a]) as group:
        handle = group.run(a, Task.create_tool_call(tool_name="wait", args={}))
        await entered.wait()
    assert cleaned.is_set()
    assert (await handle.result()).status == "canceled"


@pytest.mark.asyncio
async def test_immediate_cancellation_and_interrupted_transport_do_not_replay():
    a = make_agent("never-start")
    handle = RunHandle.start(a, Task.create_tool_call(tool_name="echo", args={"value": "no"}))
    await handle.cancel()
    assert (await handle.result()).status == "canceled"
    calls = []

    class BrokenClient:
        async def send_task_streaming(self, url, task):
            calls.append(task.id)
            yield {"type": "task_progress", "task_id": task.id}
            raise ConnectionError("connection lost after possible effect")

    result = await RunHandle.start(
        "runtime://unavailable", Task.create_infer(prompt="test"), client=BrokenClient()
    ).result()
    assert result.status == "uncertain" and result.task is None
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_kind", ["http", "sse", "websocket", "grpc"])
async def test_process_events_and_cancellation_across_transports(tmp_path, unused_tcp_port, transport_kind):
    import sys

    from protolink import CapabilityPolicy
    from protolink.tools.builtins import process_tool
    from protolink.transport import GRPCTransport, HTTPTransport, SSEJSONRPCTransport, WebSocketTransport

    factory = {
        "http": HTTPTransport,
        "sse": SSEJSONRPCTransport,
        "websocket": WebSocketTransport,
        "grpc": GRPCTransport,
    }[transport_kind]
    scheme = {"websocket": "ws", "grpc": "grpc"}.get(transport_kind, "http")
    url = f"{scheme}://127.0.0.1:{unused_tcp_port}"
    options = {"log_level": "critical", "access_log": False} if scheme == "http" else {}
    a = Agent(
        AgentCard(name="wire-process", description="test", url=url, capabilities={"streaming": True}),
        transport=factory(url=url, **options),
        verbosity=0,
    )
    a.add_tool(process_tool())
    client = AgentClient(factory(url=f"{scheme}://127.0.0.1:0", **options))
    args = {
        "argv": [sys.executable, "-c", "import time; print('ready',flush=True); time.sleep(30)"],
        "cwd": str(tmp_path),
        "env": {},
    }
    try:
        async with AgentGroup([a]):
            handle = RunHandle.start(url, Task.create_tool_call(tool_name="execute_command", args=args), client=client)
            if transport_kind == "http":
                async with asyncio.timeout(5):
                    while a.get_cancellation_token(handle.task.id) is None:
                        await asyncio.sleep(0)
                await handle.cancel()
            async with asyncio.timeout(5):
                async for event in handle.events():
                    if event.type == "process.output":
                        await handle.cancel()
                result = await handle.result()
            assert result.status == "canceled"
            assert result.report.final_task is not None
            a.action_authorizer.policy = CapabilityPolicy({"process.execute": "deny"})
            denied = await RunHandle.start(
                url, Task.create_tool_call(tool_name="execute_command", args=args), client=client
            ).result()
            assert denied.status == "failed"
            assert not any(event.type == "action.started" for event in denied.report.events)
    finally:
        await client.transport.stop()


@pytest.mark.asyncio
async def test_delegated_tool_counts_against_parent_budget():
    from protolink import RunBudget, RunContext
    from protolink.core.budget import BudgetExceededError

    registry = Registry(transport=RuntimeTransport("runtime://budget-registry"))
    parent = make_agent("budget-parent", transport="runtime", registry=registry)
    child = make_agent("budget-child", transport="runtime", registry=registry)
    context = RunContext(agent_chain=[parent.card.name], budget=RunBudget(max_tool_calls=1))
    async with AgentGroup([parent, child], registry=registry, own_registry=True):
        result = await parent._handle_agent_call(
            child.card.name, "tool_call", {"tool": "echo", "args": {"value": "ok"}}, parent_context=context
        )
        assert result.result == "ok"
        with pytest.raises(BudgetExceededError):
            await parent._handle_agent_call(
                child.card.name, "tool_call", {"tool": "echo", "args": {"value": "again"}}, parent_context=context
            )


@pytest.mark.asyncio
async def test_task_submission_is_not_retried_after_possible_effect():
    from protolink import RetryPolicy, TransportConfig, TransportConnectionError

    transport = RuntimeTransport(
        "runtime://no-replay",
        config=TransportConfig(
            retry=RetryPolicy(
                max_attempts=3,
                retryable_methods=frozenset({"POST"}),
                initial_backoff=0,
            )
        ),
    )
    calls = []

    async def possible_effect(context):
        calls.append(context.request_id)
        raise TransportConnectionError("response lost after effect", retryable=True)

    spec = AgentClient.TASK_REQUEST
    with pytest.raises(TransportConnectionError):
        await transport.run_with_retries(spec, transport.new_request_context(spec), possible_effect)
    assert len(calls) == 1
    assert spec.idempotent  # Keep server-side response deduplication.
