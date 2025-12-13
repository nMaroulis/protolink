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

        # In-memory registry store (server-side)
        self._agents: dict[str, AgentCard] = {}

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
        client = await self._ensure_client()
        response = await client.post(
            f"{self.url}/agents/",
            json=card.to_json(),
        )
        response.raise_for_status()

    async def unregister(self, agent_url: str) -> None:
        client = await self._ensure_client()
        response = await client.delete(
            f"{self.url}/agents/",
            params={"agent_url": agent_url},
        )
        response.raise_for_status()

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        client = await self._ensure_client()
        response = await client.get(
            f"{self.url}/agents/",
            params=filter_by or {},
        )
        response.raise_for_status()

        return [AgentCard.from_json(c) for c in response.json()]

    # ------------------------------------------------------------------
    # Server-side handlers (Registry logic)
    # ------------------------------------------------------------------

    async def _register_local(self, card: AgentCard) -> None:
        self._agents[card.url] = card

    async def _unregister_local(self, agent_url: str) -> None:
        self._agents.pop(agent_url, None)

    async def _discover_local(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        if not filter_by:
            return list(self._agents.values())

        def match(card: AgentCard) -> bool:
            return all(getattr(card, k, None) == v for k, v in filter_by.items())

        return [c for c in self._agents.values() if match(c)]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    # TODO(): Do this in the backend
    def _set_from_url(self, url: str) -> None:
        """Populate host, port, and canonical url from a full URL."""
        parsed = urlparse(url.rstrip("/"))
        self.host = parsed.hostname
        self.port = parsed.port
