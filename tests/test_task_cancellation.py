"""Live task cancellation tests across direct and transported execution."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from protolink import (
    Agent,
    AgentCard,
    CancellationToken,
    RunContext,
    Task,
    TaskCancellationRequest,
    TaskNotFoundError,
    TaskState,
    create_llm,
)
from protolink.client import AgentClient
from protolink.transport import RuntimeTransport, WebSocketTransport


def _agent_card(name: str) -> AgentCard:
    """Create a quiet runtime card for cancellation tests."""
    return AgentCard(name=name, description="Cancellation test agent", url=f"runtime://{name}")


def test_cancellation_request_and_token_are_idempotent():
    """Cancellation control data should round-trip and preserve the first signal."""
    request = TaskCancellationRequest(
        id="task_cancel_round_trip",
        reason="user stopped the run",
        metadata={"actor": "test"},
    )
    assert TaskCancellationRequest.from_dict(request.to_dict()) == request

    token = CancellationToken()
    assert token.cancel("first reason") is True
    assert token.cancel("second reason") is False
    assert token.is_cancelled is True
    assert token.reason == "first reason"
    with pytest.raises(asyncio.CancelledError, match="first reason"):
        token.raise_if_cancelled()


@pytest.mark.asyncio
async def test_inference_rejects_precanceled_token_before_history_mutation():
    """The LLM loop should stop before changing conversation state."""
    token = CancellationToken()
    token.cancel("Canceled before inference")
    llm = create_llm("mock", default_response="unexpected")
    history_before = list(llm.history.messages)

    with pytest.raises(asyncio.CancelledError, match="Canceled before inference"):
        await llm.infer(
            query="do not process",
            tools={},
            cancellation_token=token,
        )

    assert llm.history.messages == history_before


@pytest.mark.asyncio
async def test_direct_async_tool_is_interrupted_before_side_effect():
    """Agent.cancel_task should stop an awaited tool before it commits work."""
    started = asyncio.Event()
    committed: list[str] = []
    agent = Agent(_agent_card("direct-cancel"), verbosity=0)

    @agent.tool(name="slow_update", description="Apply a delayed update")
    async def slow_update(value: str) -> str:
        started.set()
        await asyncio.sleep(60)
        committed.append(value)
        return value

    task = Task.create_tool_call(tool_name="slow_update", args={"value": "should-not-commit"})
    RunContext(run_id="run_direct_cancel").attach_to_task(task)
    running = asyncio.create_task(agent.execute_task(task))

    await asyncio.wait_for(started.wait(), timeout=1)
    assert task.id in agent.active_task_ids

    canceled = await agent.cancel_task(task.id, reason="Stopped by test")
    result = await asyncio.wait_for(running, timeout=1)

    assert canceled is task
    assert result is task
    assert task.state is TaskState.CANCELED
    assert task.metadata["cancel_reason"] == "Stopped by test"
    assert RunContext.from_task(task).canceled is True
    assert RunContext.from_task(task).cancel_reason == "Stopped by test"
    assert committed == []
    assert agent.active_task_ids == ()


@pytest.mark.asyncio
async def test_streaming_cancellation_emits_one_final_canceled_status():
    """Streaming consumers should receive a final canceled lifecycle event."""
    started = asyncio.Event()
    agent = Agent(_agent_card("stream-cancel"), verbosity=0)

    @agent.tool(name="wait_for_cancel", description="Wait until canceled")
    async def wait_for_cancel() -> str:
        started.set()
        await asyncio.sleep(60)
        return "unexpected"

    task = Task.create_tool_call(tool_name="wait_for_cancel")
    events: list[Any] = []

    async def consume() -> None:
        async for event in agent.handle_task_streaming(task):
            events.append(event)

    running = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)
    await agent.cancel_task(task.id, reason="User canceled stream")
    await asyncio.wait_for(running, timeout=1)

    serialized = [event.to_dict() for event in events]
    final_events = [event for event in serialized if event.get("final")]
    assert len(final_events) == 1
    assert final_events[0]["type"] == "task_status_update"
    assert final_events[0]["new_state"] == "canceled"
    assert final_events[0]["metadata"]["cancel_reason"] == "User canceled stream"
    assert not any(event["type"] == "task_error" for event in serialized)


@pytest.mark.asyncio
async def test_runtime_client_can_cancel_custom_remote_handler():
    """The protocol endpoint should control overridden server task handlers."""
    started = asyncio.Event()
    committed: list[bool] = []

    class SlowAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            started.set()
            await asyncio.sleep(60)
            committed.append(True)
            return task.complete("unexpected")

    server_transport = RuntimeTransport(url="runtime://remote-cancel")
    agent = SlowAgent(
        AgentCard(
            name="remote-cancel",
            description="Remote cancellation test",
            url="runtime://remote-cancel",
        ),
        transport=server_transport,
        verbosity=0,
    )
    client = AgentClient(RuntimeTransport(url="runtime://cancel-client"))
    assert agent.server is not None
    await agent.server.start()

    try:
        task = Task.create_infer(prompt="wait")
        running = asyncio.create_task(client.send_task("runtime://remote-cancel", task))
        await asyncio.wait_for(started.wait(), timeout=1)

        canceled = await client.cancel_task(
            "runtime://remote-cancel",
            task.id,
            reason="Remote user request",
            metadata={"actor": "test-client"},
        )
        result = await asyncio.wait_for(running, timeout=1)

        assert canceled.state is TaskState.CANCELED
        assert result.state is TaskState.CANCELED
        assert result.metadata["cancel_reason"] == "Remote user request"
        assert committed == []
    finally:
        await agent.server.stop()


@pytest.mark.asyncio
async def test_websocket_control_channel_can_cancel_blocking_request(unused_tcp_port: int):
    """WebSocket cancellation must not queue behind the active data channel."""
    started = asyncio.Event()

    class SlowAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            started.set()
            await asyncio.sleep(60)
            return task.complete("unexpected")

    url = f"ws://127.0.0.1:{unused_tcp_port}"
    server_transport = WebSocketTransport(url=url)
    agent = SlowAgent(
        AgentCard(name="ws-cancel", description="WebSocket cancellation test", url=url),
        transport=server_transport,
        verbosity=0,
    )
    client = AgentClient(WebSocketTransport(url="ws://127.0.0.1:1"))
    assert agent.server is not None
    await agent.server.start()

    try:
        task = Task.create_infer(prompt="wait")
        running = asyncio.create_task(client.send_task(url, task))
        await asyncio.wait_for(started.wait(), timeout=1)

        canceled = await asyncio.wait_for(
            client.cancel_task(url, task.id, reason="WebSocket control request"),
            timeout=1,
        )
        result = await asyncio.wait_for(running, timeout=1)

        assert canceled.state is TaskState.CANCELED
        assert result.state is TaskState.CANCELED
    finally:
        await agent.server.stop()


@pytest.mark.asyncio
async def test_cancel_unknown_task_fails_without_creating_state():
    """Cancellation must not fabricate task state for an unknown identifier."""
    agent = Agent(_agent_card("missing-cancel"), verbosity=0)

    with pytest.raises(TaskNotFoundError, match="missing-task"):
        await agent.cancel_task("missing-task")
