"""
ProtoLink - Registry Class

The registry is a centralized service that allows agents to register themselves and their capabilities. Agents can
query the registry to discover other agents and their capabilities.
"""

import asyncio
import threading
import time
from typing import Any, Literal

from protolink.client import RegistryClient
from protolink.models import AgentCard
from protolink.server import RegistryServer
from protolink.transport import Transport, get_transport
from protolink.types import TransportType
from protolink.utils.logging import get_logger
from protolink.utils.renderers.status import to_registry_status_html


class Registry:
    """Centralized Registry with server and client components.

    Usage:
        registry = Registry(url="http://localhost:9000")
        registry.start()
        # Registry server is now running
    """

    def __init__(
        self, transport: TransportType | Transport = "http", url: str | None = None, verbosity: Literal[0, 1, 2] = 1
    ):
        """Initialize the registry.

        Args:
            transport: Transport instance
            url: Registry URL
            verbosity: Verbosity level [0: Warning, 1: Info, 2: Debug]
        """
        self.logger = get_logger(__name__, verbosity)

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

        # Runtime Lifecycle State
        self._background_task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Registry Server Lifecycle
    # ------------------------------------------------------------------

    async def _serve(self) -> None:
        """Initialize and start the registry runtime.

        This method starts the registry server and initializes runtime state.

        It does NOT:
        - block indefinitely
        - manage event loops
        - handle threading
        - detect execution environments

        It is the internal async startup primitive used by the public `start()` API.

        Raises:
            Exception: Propagates unexpected server startup errors.
        """

        if self._server:
            try:
                await self._server.start()
            except Exception as e:
                self.logger.exception(f"Unexpected error during server start: {e}")
                raise

        self.start_time = time.time()

    async def _serve_forever(self) -> None:
        """Keep the registry runtime alive until cancelled."""

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.logger.info("Registry shutting down...")
            await self._stop()

    async def _stop(self) -> None:
        """Internal async shutdown primitive."""

        # Guard against double stop
        if getattr(self, "_stopped", False):
            return
        self._stopped = True

        if self._server:
            await self._server.stop()

    def start(self, *, background: bool = False) -> None | asyncio.Task:
        """Start the registry runtime.

        This method automatically adapts to the current execution environment and
        works seamlessly in:
        - standard Python scripts
        - async applications
        - Jupyter notebooks

        Args:
            background:
                Controls execution mode.

                - If True, starts the registry in the background and returns immediately.
                - If False (default), blocks execution until shutdown.

        Returns:
            asyncio.Task | None:
                - Returns an asyncio Task when running inside an existing async event loop.
                - Returns None in blocking/script execution mode.

        Notes:
            - This is the recommended entrypoint for starting the registry.
            - The async runtime is automatically managed internally.
        """

        async def _lifecycle():
            await self._serve()
            await self._serve_forever()

        try:
            # Existing event loop (Jupyter / async app)
            loop = asyncio.get_running_loop()

            self._background_task = loop.create_task(_lifecycle())
            return self._background_task

        except RuntimeError:
            # Standard Python script

            if background:

                def _thread_target():
                    self._loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._loop)

                    self._background_task = self._loop.create_task(_lifecycle())

                    try:
                        self._loop.run_until_complete(self._background_task)
                    finally:
                        self._loop.close()

                self._thread = threading.Thread(
                    target=_thread_target,
                    daemon=False,
                )
                self._thread.start()

                return None

            # Blocking mode
            asyncio.run(_lifecycle())
            return None

    def stop(self) -> None:
        """Stop the registry runtime.

        This method automatically handles shutdown across:
        - scripts
        - async environments
        - background threads
        - Jupyter notebooks

        Notes:
            - Safe to call multiple times.
            - Cancels active runtime tasks before cleanup.
        """

        # Async task mode (Jupyter / async app with existing event loop)
        if self._background_task and not self._background_task.done():
            loop = self._background_task.get_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._background_task.cancel)
                return

        # Background thread mode
        if self._loop and self._loop.is_running():
            if self._background_task and not self._background_task.done():
                self._loop.call_soon_threadsafe(self._background_task.cancel)

        # Wait for the thread to fully exit before returning,
        # so the process doesn't die while uvicorn is still cleaning up
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    # ------------------------------------------------------------------
    # Client API (agents call these)
    # ------------------------------------------------------------------

    async def register(self, card: AgentCard) -> dict[str, str]:
        try:
            self.logger.debug(f"Registering agent {card.name} on address {card.url}.")
            response = await self._client.register(card)
        except Exception as e:
            self.logger.exception(f"Failed to register agent {card.url}: {e}")
            response = {"status": str(e)}
        return response

    async def unregister(self, agent_url: str) -> dict[str, str]:
        try:
            self.logger.debug(f"Unregistering agent {agent_url}.")
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
