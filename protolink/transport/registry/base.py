"""
ProtoLink - Agent to Registry (A2R) Transport Layer

Agent-to-Registry (A2R) transport implementations for agent communication.
"""

from abc import abstractmethod
from typing import Any

from protolink.models import AgentCard
from protolink.transport.base import Transport


class RegistryTransport(Transport):
    """Abstract base class for registry transport implementations."""

    @abstractmethod
    async def register(self, card: AgentCard) -> None:
        """Register an agent with the registry."""
        ...

    @abstractmethod
    async def unregister(self, agent_url: str) -> None:
        """Unregister an agent from the registry."""
        ...

    @abstractmethod
    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Return all agents registered with the registry."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the HTTP server and initialize the HTTP client."""
        ...

    async def stop(self) -> None:
        """Stop the HTTP server and close the underlying HTTP client."""
        ...
