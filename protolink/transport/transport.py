"""
ProtoLink - Transport Layer

Transport implementations for agent communication.
Supports in-memory and JSON-RPC over HTTP/WebSocket.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task


class Transport(ABC):
    """Abstract base class for transport implementations."""

    @abstractmethod
    async def send_task(self, agent_url: str, task: Task, skill: str | None = None) -> Task:
        """Send a task to an agent.

        Args:
            agent_url: Target agent URL
            task: Task to send
            skill: Skill to use for authorization

        Returns:
            Task with response
        """
        pass

    @abstractmethod
    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send a message to an agent.

        Args:
            agent_url: Target agent URL
            message: Message to send

        Returns:
            Response message
        """
        pass

    @abstractmethod
    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Fetch agent card from agent URL.

        Args:
            agent_url: Agent URL

        Returns:
            AgentCard with agent metadata
        """
        pass

    @abstractmethod
    async def subscribe_task(self, agent_url: str, task: Task) -> AsyncIterator[dict]:
        """Subscribe to task updates via streaming (NEW in v0.2.0).

        Streams task events (status updates, artifacts, progress) as they occur.
        Implements Server-Sent Events (SSE) for real-time updates.

        Args:
            agent_url: Target agent URL
            task: Task to send and subscribe to

        Yields:
            Event dictionaries with updates
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start the transport server.

        For server-side transports, this should start listening for incoming requests.
        For client-only transports, this can be a no-op.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport server.

        For server-side transports, this should stop listening and clean up resources.
        For client-only transports, this can be a no-op.
        """
        pass

    @abstractmethod
    def on_task_received(self, handler: Callable[[Task], Awaitable[Task]]) -> None:
        """Register a handler for incoming tasks.

        Args:
            handler: Async function that processes incoming tasks and returns responses
        """
        pass
