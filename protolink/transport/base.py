"""
ProtoLink - Agent to Agent (A2A) Transport Layer

Agent-to-Agent (A2A) transport implementations for agent communication.
Supports in-memory and JSON-RPC over HTTP/WebSocket.
"""

from abc import ABC, abstractmethod
from typing import Any

from protolink.client.request_spec import ClientRequestSpec


class Transport(ABC):
    """Abstract base class for transport implementations."""

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
    def validate_url(self) -> bool:
        """Validate provided URL"""
        pass

    @property
    @abstractmethod
    def url(self) -> str:
        """Get the URL of the transport."""
        pass
