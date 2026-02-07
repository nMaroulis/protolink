"""Agent Client - High-level interface for agent-to-agent communication.

This module provides the `AgentClient` class, which abstracts transport details and
offers convenient methods for sending tasks, messages, and retrieving agent cards.

The client uses `ClientRequestSpec` objects to define API contracts in a transport-agnostic
way. This allows the same client code to work over HTTP, WebSocket, or any other transport.

Example:
    >>> from protolink.client import AgentClient
    >>> from protolink.models import Task
    >>>
    >>> client = AgentClient(transport="http", url="http://localhost:8000")
    >>> task = Task.create_infer(prompt="What's the weather?")
    >>> result = await client.send_task("http://localhost:8010", task)
"""

from collections.abc import AsyncIterator
from typing import Any

from protolink.models import AgentCard, ClientRequestSpec, Message, Task
from protolink.transport import Transport, get_transport
from protolink.types import TransportType


class AgentClient:
    """Client for interacting with Protolink agents.

    The AgentClient provides a high-level interface for agent-to-agent communication.
    It wraps a transport implementation and exposes typed methods for common operations:

    - `send_task()`: Send a Task to a remote agent and get the result
    - `send_task_streaming()`: Send a Task and receive streamed events
    - `send_message()`: Convenience wrapper for simple message exchange
    - `get_agent_card()`: Retrieve an agent's public metadata

    The client uses `ClientRequestSpec` class attributes to define the API contract
    for each endpoint. This allows transports to handle routing without hardcoding paths.

    Args:
        transport: Either a Transport instance or a transport type string (e.g., "http").
        url: Base URL for the transport (required if transport is a string type).

    Example:
        >>> # Using transport type string
        >>> client = AgentClient(transport="http", url="http://localhost:8000")
        >>>
        >>> # Using existing transport instance
        >>> from protolink.transport import HTTPTransport
        >>> client = AgentClient(transport=HTTPTransport(url="http://localhost:8000"))
    """

    TASK_REQUEST = ClientRequestSpec(
        name="send_task",
        path="/tasks/",
        method="POST",
        response_parser=Task.from_dict,
        request_source="body",
    )

    AGENT_CARD_REQUEST = ClientRequestSpec(
        name="get_agent_card",
        path="/.well-known/agent.json",
        method="GET",
        response_parser=AgentCard.from_dict,
        request_source="none",
    )

    TASK_STREAM_REQUEST = ClientRequestSpec(
        name="send_task_stream",
        path="/tasks/stream",
        method="POST",
        request_source="body",
    )

    def __init__(self, transport: Transport | TransportType, url: str | None = None) -> None:
        if isinstance(transport, Transport):
            self._transport = transport
        else:
            self._transport = get_transport(transport=transport, url=url)

    # ----------------------------------------------------------------------
    # Agent-to-Agent Communication
    # ----------------------------------------------------------------------

    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send a task to a remote agent."""
        return await self._transport.send(self.TASK_REQUEST, agent_url, data=task)

    async def send_task_streaming(self, agent_url: str, task: Task) -> AsyncIterator[Any]:
        """Send a task and yield streamed task events.

        This requires a transport that implements a streaming subscription API.

        Raises
        ------
        NotImplementedError
            If the configured transport does not support streaming.
        """
        subscribe = getattr(self._transport, "subscribe", None)
        if subscribe is None:
            raise NotImplementedError("Transport does not support streaming")
        async for event in subscribe(agent_url, task):
            yield event

    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send a message to a remote agent (convenience wrapper)."""
        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)
        if result_task.messages:
            return result_task.messages[-1]
        raise RuntimeError("No response messages returned by agent")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Get the public agent card."""
        return await self._transport.send(self.AGENT_CARD_REQUEST, agent_url)
