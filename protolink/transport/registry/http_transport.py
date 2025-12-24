from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx

from protolink.models import AgentCard
from protolink.transport.registry.backends.starlette import StarletteRegistryBackend
from protolink.transport.registry.base import RegistryTransport
from protolink.types import TransportType


class HTTPRegistryTransport(RegistryTransport):
    """HTTP-based Agent-to-Registry transport."""

    transport_type: ClassVar[TransportType] = "http"

    def __init__(
        self,
        *,
        url: str,
        timeout: float = 10.0,
    ) -> None:
        self.url = url
        self._set_from_url(url)
        self.timeout = timeout

        self.backend = StarletteRegistryBackend()
        self.app = self.backend.app

        self._client: httpx.AsyncClient | None = None

        # Handlers that are called for different Server Requests
        # POST /agents/
        self._register_handler: Callable[[AgentCard], Awaitable[None]] | None = None
        # DELETE /agents/
        self._unregister_handler: Callable[[str], Awaitable[None]] | None = None
        # GET /agents/
        self._discover_handler: Callable[[dict[str, Any]], Awaitable[list[AgentCard]]] | None = None
        # GET /status/
        self._status_handler: Callable[[], Awaitable[str]] | None = None

        # TTL for registry entries (server-side)
        self.ttl_seconds = 30

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.backend.setup_routes(self)
        await self.backend.start(self.host, self.port)
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def stop(self) -> None:
        await self.backend.stop()
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    # ------------------------------------------------------------------
    # Client-side API (Agent → Registry)
    # ------------------------------------------------------------------

    async def register(self, card: AgentCard) -> None:
        """Register an agent to the registry.

        Args:
            card: AgentCard to register

        Raises:
            ConnectionError: If registry is not reachable
            RuntimeError: If registration fails for other reasons
        """
        try:
            client = await self._ensure_client()
            response = await client.post(
                f"{self.url}/agents/",
                json=card.to_json(),
            )
            response.raise_for_status()
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Failed to connect to registry at {self.url}. Make sure the registry server is running and accessible."
            ) from e
        except httpx.RemoteProtocolError as e:
            raise ConnectionError(
                f"Protocol error when communicating with registry at {self.url}. "
                f"The target may not be a proper HTTP server or may be misconfigured."
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Registry at {self.url} returned HTTP {e.response.status_code}: {e.response.text}"
            ) from e

    async def unregister(self, agent_url: str) -> None:
        """Unregister an agent from the registry.

        Args:
            agent_url: URL of the agent to unregister

        Raises:
            ConnectionError: If registry is not reachable
            RuntimeError: If unregistration fails for other reasons
        """
        try:
            client = await self._ensure_client()
            response = await client.delete(
                f"{self.url}/agents/",
                params={"agent_url": agent_url},
            )
            response.raise_for_status()
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Failed to connect to registry at {self.url}. Make sure the registry server is running and accessible."
            ) from e
        except httpx.RemoteProtocolError as e:
            raise ConnectionError(
                f"Protocol error when communicating with registry at {self.url}. "
                f"The target may not be a proper HTTP server or may be misconfigured."
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Registry at {self.url} returned HTTP {e.response.status_code}: {e.response.text}"
            ) from e

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover agents in the registry.

        Args:
            filter_by: Optional filter criteria

        Returns:
            List of AgentCard objects

        Raises:
            ConnectionError: If registry is not reachable
            RuntimeError: If discovery fails for other reasons
        """
        try:
            client = await self._ensure_client()
            response = await client.get(
                f"{self.url}/agents/",
                params=filter_by or {},
            )
            response.raise_for_status()
            return [AgentCard.from_json(c) for c in response.json()]
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Failed to connect to registry at {self.url}. Make sure the registry server is running and accessible."
            ) from e
        except httpx.RemoteProtocolError as e:
            raise ConnectionError(
                f"Protocol error when communicating with registry at {self.url}. "
                f"The target may not be a proper HTTP server or may be misconfigured."
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Registry at {self.url} returned HTTP {e.response.status_code}: {e.response.text}"
            ) from e

    # ------------------------------------------------------------------
    # Server-side handlers (Registry logic)
    # ------------------------------------------------------------------

    def on_register_received(self, handler: Callable[[AgentCard], Awaitable[None]]) -> None:
        self._register_handler = handler

    def on_unregister_received(self, handler: Callable[[str], Awaitable[None]]) -> None:
        self._unregister_handler = handler

    def on_discover_received(self, handler: Callable[[dict[str, Any]], Awaitable[list[AgentCard]]]) -> None:
        self._discover_handler = handler

    def on_status_received(self, handler: Callable[[], Awaitable[str]]) -> None:
        self._status_handler = handler

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    # TODO(): Do this in the backend
    def _set_from_url(self, url: str) -> None:
        """Populate host, port, and canonical url from a full URL."""
        parsed = urlparse(url.rstrip("/"))
        self.host = parsed.hostname
        self.port = parsed.port
