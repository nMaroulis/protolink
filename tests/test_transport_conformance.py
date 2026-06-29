"""Shared transport contract coverage for core agent operations."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from protolink import Agent, AgentCard, Task, create_llm
from protolink.client import AgentClient
from protolink.core.agent_card import AgentCapabilities
from protolink.transport import HTTPTransport, RuntimeTransport, WebSocketTransport


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
