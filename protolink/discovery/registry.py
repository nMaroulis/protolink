# protolink/registry/registry.py
from typing import Any

from protolink.client import RegistryClient
from protolink.models import AgentCard
from protolink.transport import HTTPRegistryTransport, RegistryTransport
from protolink.utils.logging import get_logger


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
            transport = HTTPRegistryTransport(url=url)

        self.transport = transport
        self.client = RegistryClient(self.transport)

        # Local store for agent cards
        self._agents: dict[str, AgentCard] = {}

        # Wire server-side handlers
        self.transport._register_local = self._register_local
        self.transport._unregister_local = self._unregister_local
        self.transport._discover_local = self._discover_local

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the registry server via the transport."""
        await self.transport.start()

    async def stop(self) -> None:
        """Stop the registry server via the transport."""
        await self.transport.stop()

    # ------------------------------------------------------------------
    # Client API (agents call these)
    # ------------------------------------------------------------------

    async def register(self, card: AgentCard) -> None:
        await self.client.register(card)

    async def unregister(self, agent_url: str) -> None:
        await self.client.unregister(agent_url)

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        return await self.client.discover(filter_by)

    # ------------------------------------------------------------------
    # Server-side handlers
    # ------------------------------------------------------------------

    async def _register_local(self, card: AgentCard) -> None:
        self._agents[card.url] = card

        self.logger.info(
            "Agent Card Registered:",
            extra={
                "agent_url": card.url,
                "card": card.to_json(),
            },
        )

    async def _unregister_local(self, agent_url: str) -> None:
        self._agents.pop(agent_url, None)

    async def _discover_local(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        if not filter_by:
            return list(self._agents.values())

        def match(card: AgentCard) -> bool:
            return all(getattr(card, k, None) == v for k, v in filter_by.items())

        return [c for c in self._agents.values() if match(c)]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def list_urls(self) -> list[str]:
        return list(self._agents.keys())

    def count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        self._agents.clear()

    def __repr__(self) -> str:
        return f"Registry(agents={self.count()})"
