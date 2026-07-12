"""Shared transport contract coverage for core agent operations."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from protolink import Agent, AgentCard, Task, create_llm
from protolink.client import AgentClient
from protolink.core.agent_card import AgentCapabilities
from protolink.transport import GRPCTransport, HTTPTransport, RuntimeTransport, SSEJSONRPCTransport, WebSocketTransport
from protolink.transport.factory import get_transport


def _card(name: str, url: str, *, streaming: bool = False) -> AgentCard:
    """Create an agent card for transport conformance tests."""
    return AgentCard(
        name=name,
        description=f"{name} transport conformance agent",
        url=url,
        capabilities=AgentCapabilities(streaming=streaming),
    )


async def _collect_stream(client: AgentClient, agent_url: str, task: Task) -> list[dict[str, Any]]:
    """Collect a task stream into serialized event dictionaries."""
    events: list[dict[str, Any]] = []
    async for event in client.send_task_streaming(agent_url, task):
        events.append(event.to_dict() if hasattr(event, "to_dict") else event)
    return events


async def _assert_request_response_contract(agent: Agent, client: AgentClient) -> None:
    """Assert task submission and agent-card retrieval through a transport."""
    assert agent.server is not None
    await agent.server.start()
    try:
        card = await client.get_agent_card(agent.card.url)
        task = await client.send_task(agent.card.url, Task.create_infer(prompt="hello"))

        assert card.name == agent.card.name
        assert task.get_last_part_content() == "transport ok"
    finally:
        await agent.server.stop()


async def _assert_streaming_contract(agent: Agent, client: AgentClient) -> None:
    """Assert streaming transports emit a final task status event."""
    assert agent.server is not None
    await agent.server.start()
    try:
        events = await _collect_stream(client, agent.card.url, Task.create_infer(prompt="stream"))
        assert events[-1]["type"] == "task_status_update"
        assert events[-1]["final"] is True
        assert events[-1]["new_state"] == "completed"
    finally:
        await agent.server.stop()


@pytest.mark.asyncio
async def test_runtime_transport_conforms_to_agent_contract() -> None:
    """Runtime transport should support request/response, metadata, and streaming."""
    url = "runtime://transport-conformance-runtime"
    server_transport = RuntimeTransport(url=url)
    agent = Agent(
        _card("runtime-conformance", url, streaming=True),
        transport=server_transport,
        llm=create_llm("mock", default_response="transport ok"),
        verbosity=0,
    )
    client = AgentClient(RuntimeTransport(url="runtime://transport-conformance-client"))

    await _assert_request_response_contract(agent, client)
    await _assert_streaming_contract(agent, client)


@pytest.mark.asyncio
async def test_http_transport_conforms_to_agent_request_response_contract(unused_tcp_port) -> None:
    """HTTP transport should honor the same task and card contracts."""
    url = f"http://127.0.0.1:{unused_tcp_port}"
    agent = Agent(
        _card("http-conformance", url),
        transport=HTTPTransport(url=url, log_level="critical", access_log=False),
        llm=create_llm("mock", default_response="transport ok"),
        verbosity=0,
    )
    client = AgentClient(HTTPTransport(url="http://127.0.0.1:0", log_level="critical", access_log=False))

    await _assert_request_response_contract(agent, client)


@pytest.mark.asyncio
async def test_sse_transport_streams_until_final_task_status(unused_tcp_port) -> None:
    """SSE should not stop when a nested LLM event marks itself final."""
    url = f"http://127.0.0.1:{unused_tcp_port}"
    server_transport = SSEJSONRPCTransport(url=url, log_level="critical", access_log=False)
    client_transport = SSEJSONRPCTransport(
        url="http://127.0.0.1:0",
        log_level="critical",
        access_log=False,
    )
    agent = Agent(
        _card("sse-conformance", url, streaming=True),
        transport=server_transport,
        llm=create_llm("mock", default_response="transport ok"),
        verbosity=0,
    )
    client = AgentClient(client_transport)

    assert agent.server is not None
    await agent.server.start()
    try:
        events = await _collect_stream(client, url, Task.create_infer(prompt="stream"))
        assert any(event["type"] == "task_llm_stream" and event["final"] is True for event in events)
        assert events[-1]["type"] == "task_status_update"
        assert events[-1]["final"] is True
        assert events[-1]["new_state"] == "completed"
    finally:
        await client_transport.stop()
        await agent.server.stop()


def test_grpc_transport_factory_registration() -> None:
    """The default factory should expose the registered gRPC transport."""
    pytest.importorskip("grpc")

    transport = get_transport("grpc", url="grpc://127.0.0.1:0")

    assert isinstance(transport, GRPCTransport)
    assert transport.transport_type == "grpc"
    assert transport.supports_streaming is True
    assert transport.validate_url() is True


@pytest.mark.asyncio
async def test_grpc_transport_conforms_to_agent_contract(unused_tcp_port) -> None:
    """gRPC transport should honor request/response and streaming contracts."""
    pytest.importorskip("grpc")

    url = f"grpc://127.0.0.1:{unused_tcp_port}"
    agent = Agent(
        _card("grpc-conformance", url, streaming=True),
        transport=GRPCTransport(url=url),
        llm=create_llm("mock", default_response="transport ok"),
        verbosity=0,
    )
    client = AgentClient(GRPCTransport(url="grpc://127.0.0.1:0"))

    await _assert_request_response_contract(agent, client)
    await asyncio.sleep(0.01)
    await _assert_streaming_contract(agent, client)


@pytest.mark.asyncio
async def test_grpc_stop_closes_channels_for_current_loop() -> None:
    """Stopping gRPC should close channels cached for the caller's event loop."""
    pytest.importorskip("grpc")
    transport = GRPCTransport(url="grpc://127.0.0.1:0")
    loop_id = id(asyncio.get_running_loop())
    current_channel = AsyncMock()
    other_channel = AsyncMock()
    current_key = ("127.0.0.1:8000", False, loop_id)
    other_key = ("127.0.0.1:8001", False, loop_id + 1)
    transport._channels[current_key] = current_channel
    transport._channels[other_key] = other_channel

    await transport.stop()

    current_channel.close.assert_awaited_once_with(grace=1.0)
    other_channel.close.assert_not_awaited()
    assert current_key not in transport._channels
    assert other_key in transport._channels


@pytest.mark.asyncio
async def test_websocket_transport_conforms_to_streaming_contract(unused_tcp_port) -> None:
    """WebSocket transport should honor request/response and streaming contracts."""
    pytest.importorskip("websockets")
    url = f"ws://127.0.0.1:{unused_tcp_port}"
    agent = Agent(
        _card("websocket-conformance", url, streaming=True),
        transport=WebSocketTransport(url=url),
        llm=create_llm("mock", default_response="transport ok"),
        verbosity=0,
    )
    client = AgentClient(WebSocketTransport(url="ws://127.0.0.1:0"))

    await _assert_request_response_contract(agent, client)
    await asyncio.sleep(0.01)
    await _assert_streaming_contract(agent, client)
