# protolink/registry/registry.py
import time
from typing import Any

from protolink.client import RegistryClient
from protolink.models import AgentCard
from protolink.server import RegistryServer
from protolink.transport import Transport, get_transport
from protolink.types import TransportType
from protolink.utils.logging import get_logger
from protolink.utils.renderers import to_registry_status_html


class Registry:
    """Centralized Registry with server and client components.

    Usage:
        registry = Registry(url="http://localhost:9000")
        await registry.start()
        # Registry server is now running
    """

    def __init__(self, transport: TransportType | Transport = "http", url: str | None = None, verbose: int = 1):
        """Initialize the registry.

        Args:
            transport: Transport instance
            url: Registry URL
            verbose: Verbosity level [0: Warning, 2: Info, 3: Debug]
        """
        self.logger = get_logger(__name__, verbose)

        # Create default HTTP transport if none provided
        if isinstance(transport, str):
            if url is None:
                raise ValueError("url must be provided if transport is a TransportType")
            transport = get_transport(transport, url=url)
        elif not isinstance(transport, Transport):
            raise ValueError("transport must be a TransportType or Transport instance")

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

    async def register(self, card: AgentCard) -> dict[str, str]:
        try:
            response = await self._client.register(card)
        except Exception as e:
            self.logger.exception(f"Failed to register agent {card.url}: {e}")
            response = {"status": str(e)}
        return response

    async def unregister(self, agent_url: str) -> dict[str, str]:
        try:
            response = await self._client.unregister(agent_url)
        except Exception as e:
            self.logger.exception(f"Failed to unregister agent {agent_url}: {e}")
            response = {"status": str(e)}
        return response

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        return await self._client.discover(filter_by)

    # ------------------------------------------------------------------
    # Server-side handlers
    # ------------------------------------------------------------------

    async def handle_register(self, card: AgentCard) -> dict[str, str]:
        self._agents[card.url] = card

        self.logger.info(
            f"Agent {card.name} registered on address {card.url}.",
            extra={
                "card": card.to_dict(),
            },
        )
        return {"status": "agent registered successfully"}

    async def handle_unregister(self, agent_url: str) -> dict[str, str]:
        self._agents.pop(agent_url, None)
        return {"status": "agent unregistered successfully"}

    async def handle_discover(
        self, filter_by: dict[str, Any] | None = None, *, as_json: bool = False
    ) -> list[dict[str, Any]] | list[AgentCard]:
        """Handle an incoming discover request by an Agent. It returns the AgentCard objects as a Dict."""
        if not filter_by:
            if as_json:
                return [c.to_dict() for c in self._agents.values()]
            else:
                return list(self._agents.values())

        filtered_agents = [c for c in self._agents.values() if self._match(filter_by, c)]
        if as_json:
            return [c.to_dict() for c in filtered_agents]
        else:
            return filtered_agents

    def handle_status_html(self) -> str:
        """Return the registry's status as HTML.

        Returns:
            HTML string with registry status information
        """
        return to_registry_status_html("Registry", "HTTP", self._agents, self.start_time)

    # ------------------------------------------------------------------
    # Getters & Setters
    # ------------------------------------------------------------------

    @property
    def client(self) -> RegistryClient:
        return self._client

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
