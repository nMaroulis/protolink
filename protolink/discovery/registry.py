# protolink/registry/registry.py
import time
from typing import Any

from protolink.client import RegistryClient
from protolink.models import AgentCard
from protolink.server import RegistryServer
from protolink.transport import HTTPRegistryTransport, RegistryTransport
from protolink.utils.logging import get_logger
from protolink.utils.renderers import to_registry_status_html


class Registry:
    """Centralized Registry with server and client components.

    Usage:
        registry = Registry(url="http://localhost:9000")
        await registry.start()
        # Registry server is now running
    """

    def __init__(self, transport: RegistryTransport | None = None, url: str | None = None, verbose: int = 1):
        """Initialize the registry.

        Args:
            transport: RegistryTransport instance
            url: Registry URL
            verbose: Verbosity level [0: Warning, 2: Info, 3: Debug]
        """
        self.logger = get_logger(__name__, verbose)

        # Create default HTTP transport if none provided
        if transport is None:
            if url is None:
                raise ValueError("At least one of transport or url must be provided")
            else:
                self.logger.info(f"Creating default HTTPRegistryTransport using the provided URL: {url}")
                transport = HTTPRegistryTransport(url=url)

        # Local store for agent cards
        self._agents: dict[str, AgentCard] = {}

        self.start_time: float | None = None

        # Setup registry client
        self._client = RegistryClient(transport)

        # Setup registry server
        self._server = RegistryServer(self, transport)

    # ------------------------------------------------------------------
    # Registry Server Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the registry server via the transport."""
        if self._server:
            try:
                await self._server.start()
            except Exception as e:
                self.logger.exception(f"Unexpected error during server start: {e}")
                raise
        self.start_time = time.time()

    async def stop(self) -> None:
        """Stop the registry server via the transport."""
        if self._server:
            await self._server.stop()

    # ------------------------------------------------------------------
    # Client API (agents call these)
    # ------------------------------------------------------------------

    async def register(self, card: AgentCard) -> None:
        await self._client.register(card)

    async def unregister(self, agent_url: str) -> None:
        await self._client.unregister(agent_url)

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        return await self._client.discover(filter_by)

    # ------------------------------------------------------------------
    # Server-side handlers
    # ------------------------------------------------------------------

    async def handle_register(self, card: AgentCard) -> None:
        self._agents[card.url] = card

        self.logger.info(
            "Agent Card Registered:",
            extra={
                "agent_url": card.url,
                "card": card.to_json(),
            },
        )

    async def handle_unregister(self, agent_url: str) -> None:
        self._agents.pop(agent_url, None)

    async def handle_discover(
        self, filter_by: dict[str, Any] | None = None, *, as_json: bool = True
    ) -> list[dict[str, Any]] | list[AgentCard]:
        """Handle an incoming discover request by an Agent. It returns the AgentCard objects as a Dict."""
        if not filter_by:
            return list(self._agents.values())

        return [c.to_json() if as_json else c for c in self._agents.values() if self._match(filter_by, c)]

    def handle_status_html(self) -> str:
        """Return the registry's status as HTML.

        Returns:
            HTML string with registry status information
        """
        return to_registry_status_html("Registry", "HTTP", self._agents, self.start_time)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _match(self, filter_by: dict[str, Any], card: AgentCard) -> bool:
        return all(getattr(card, k, None) == v for k, v in filter_by.items())

    def list_urls(self) -> list[str]:
        return list(self._agents.keys())

    def count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        self._agents.clear()

    def __repr__(self) -> str:
        return f"Registry(agents={self.count()})"
