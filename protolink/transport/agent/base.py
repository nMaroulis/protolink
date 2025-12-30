"""
ProtoLink - Agent to Agent (A2A) Transport Layer

Agent-to-Agent (A2A) transport implementations for agent communication.
Supports in-memory and JSON-RPC over HTTP/WebSocket.
"""

from abc import abstractmethod
from typing import Any

from protolink.models import ClientRequestSpec
from protolink.transport.base import Transport


class AgentTransport(Transport):
    """Abstract base class for agent transport implementations."""

    @abstractmethod
    async def send(
        self, request_spec: ClientRequestSpec, base_url: str, data: Any = None, params: dict | None = None
    ) -> Any:
        """Send a generic request to an agent endpoint.

        Args:
            request_spec: The request specification (method, path, parser).
            base_url: The base URL of the agent (e.g. "http://localhost:8080").
            data: The payload to send (for body).
            params: Query parameters (for GET requests etc).

        Returns:
            The parsed response.
        """
        pass

    @abstractmethod
    def validate_agent_url(self, agent_url: str) -> bool:
        """Validate an agent URL.

        Args:
            agent_url: Agent URL to validate

        Returns:
            True if the URL is valid, False otherwise
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
