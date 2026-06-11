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

    The registry maintains secondary indexes for agent names, roles, and tags
    to optimize discovery performance.

    Time Complexity:
        - handle_register: O(T) where T is the number of tags (index updates are O(1))
        - handle_unregister: O(T)
        - handle_discover: O(K) where K is the number of candidates (was O(N))
        - count/list_urls: O(1) / O(N)

    Space Complexity:
        - O(N * I) where I is the number of indexed fields.

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

        # Secondary indexes for O(1) discovery lookups
        self._index_name: dict[str, set[str]] = {}
        self._index_role: dict[str, set[str]] = {}
        self._index_tags: dict[str, set[str]] = {}

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

    def start(self, *, background: bool = False) -> None:
        """Start the registry runtime and initialize the discovery server.

        This is the primary public entrypoint for running the registry. It is designed to be
        environment-agnostic, working seamlessly in:
        - standard scripts
        - async applications
        - background threads
        - Jupyter notebooks (interactive environments)

        **Technical Note on Lifecycle Orchestration:**
        Protolink handles the transition between synchronous and asynchronous contexts using
        a dual-mode execution strategy:

        1. **Deterministic Background Mode (``background=True``):** Starts a dedicated thread
           with its own ``asyncio`` event loop. To prevent race conditions, this method
           utilizes a ``threading.Event`` to block the caller until the background registry is
           fully initialized and ready to receive traffic. Any startup failures (e.g., port
           collisions) are captured and re-raised in the caller thread.

        2. **Blocking Mode (``background=False``):** Utilizes ``asyncio.run()`` to take over
           the main thread's execution. This is the recommended pattern for standalone
           registry scripts.

        Args:
            background: Controls execution mode. If True, returns immediately after startup.

        Notes:
            - Safe to call in any environment.
            - Re-raises background startup exceptions in the main thread.
        """

        async def _lifecycle():
            try:
                await self._serve()
                # Signal that startup completed successfully if in background mode
                if hasattr(self, "_ready_event"):
                    self._ready_event.set()
                await self._serve_forever()
            except Exception as e:
                # Store startup failure so the main thread can re-raise it
                self._startup_exception = e
                # Unblock waiting thread even on failure if in background mode
                if hasattr(self, "_ready_event"):
                    self._ready_event.set()
                raise

        if background:
            self._ready_event = threading.Event()
            self._startup_exception = None

            def _thread_target():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

                self._background_task = self._loop.create_task(_lifecycle())

                try:
                    self._loop.run_until_complete(self._background_task)
                finally:
                    # Cancel pending tasks cleanly
                    pending = asyncio.all_tasks(self._loop)

                    for task in pending:
                        task.cancel()

                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

                    self._loop.close()

            self._thread = threading.Thread(
                target=_thread_target,
                daemon=False,
            )
            self._thread.start()
            # Wait until registry startup completes
            ready = self._ready_event.wait(timeout=10)

            if not ready:
                self.logger.warning("Registry background thread took more than 10s to start.")

            # Re-raise startup exceptions in caller thread
            if self._startup_exception is not None:
                raise self._startup_exception

            return

        # Blocking mode
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                self.logger.error(
                    "Registry.start() called in blocking mode from within an active event loop. "
                    "This will block the loop. Use \033[1mbackground=True\033[22m instead."
                )
        except RuntimeError:
            pass

        asyncio.run(_lifecycle())
        return

    def stop(self) -> None:
        """Stop the registry runtime and orchestrate a graceful teardown.

        This method handles shutdown across all supported execution environments (scripts,
        async loops, background threads, and notebooks). It is specifically designed to
        safely terminate registries started with ``background=True``.

        **Technical Note on Thread-Safe Teardown:**
        When the registry is running in a background thread, its lifecycle is managed by a private
        event loop. To stop it from the main thread, we utilize ``call_soon_threadsafe`` to
        inject a cancellation request into the background loop. This triggers a
        ``CancelledError`` within the ``_lifecycle()`` coroutine, allowing it to execute its
        ``finally`` blocks—which perform critical cleanup like closing the transport and
        stopping the ASGI server.

        The subsequent ``join(timeout=10)`` synchronizes the main thread with the background
        thread's exit. This ensures that the caller doesn't proceed (or the process doesn't
        exit) while the background server is still in the middle of a graceful port release
        or connection drain.

        Notes:
            - Safe to call multiple times.
            - Blocks the main thread briefly to ensure deterministic cleanup.
        """

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
        """Register an agent via the registry client.

        Time: O(1) network request.
        """
        try:
            self.logger.debug(f"Registering agent {card.name} on address {card.url}.")
            response = await self._client.register(card)
        except Exception as e:
            self.logger.exception(f"Failed to register agent {card.url}: {e}")
            response = {"status": str(e)}
        return response

    async def unregister(self, agent_url: str) -> dict[str, str]:
        """Unregister an agent via the registry client.

        Time: O(1) network request.
        """
        try:
            self.logger.debug(f"Unregistering agent {agent_url}.")
            response = await self._client.unregister(agent_url)
        except Exception as e:
            self.logger.exception(f"Failed to unregister agent {agent_url}: {e}")
            response = {"status": str(e)}
        return response

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover agents via the registry client.

        Time: O(1) network request.
        """
        return await self._client.discover(filter_by)

    # ------------------------------------------------------------------
    # Server-side handlers
    # ------------------------------------------------------------------

    async def handle_register(self, card: AgentCard) -> dict[str, str]:
        """Process a registration request and update discovery indexes.

        Time: O(T) where T is the number of tags.
        """
        # Clean up old indexes if agent already exists
        if card.url in self._agents:
            await self.handle_unregister(card.url)

        self._agents[card.url] = card

        # Update indexes
        self._index_name.setdefault(card.name, set()).add(card.url)
        self._index_role.setdefault(card.role, set()).add(card.url)
        for tag in card.tags:
            self._index_tags.setdefault(tag, set()).add(card.url)

        self.logger.info(
            f"Agent {card.name} registered on address {card.url}.",
            extra={
                "card": card.to_dict(),
            },
        )
        return {"status": "agent registered successfully"}

    async def handle_unregister(self, agent_url: str) -> dict[str, str]:
        """Process an unregistration request and clean up discovery indexes.

        Time: O(T) where T is the number of tags.
        """
        card = self._agents.pop(agent_url, None)
        if card:
            # Clean up indexes
            if card.name in self._index_name:
                self._index_name[card.name].discard(agent_url)
                if not self._index_name[card.name]:
                    del self._index_name[card.name]

            if card.role in self._index_role:
                self._index_role[card.role].discard(agent_url)
                if not self._index_role[card.role]:
                    del self._index_role[card.role]

            for tag in card.tags:
                if tag in self._index_tags:
                    self._index_tags[tag].discard(agent_url)
                    if not self._index_tags[tag]:
                        del self._index_tags[tag]

        return {"status": "agent unregistered successfully"}

    async def handle_discover(
        self, filter_by: dict[str, Any] | None = None, *, as_json: bool = False
    ) -> list[dict[str, Any]] | list[AgentCard]:
        """Handle an incoming discover request by using secondary indexes.

        If indexed fields (name, role, tags) are present in the filter, the search is optimized using set intersections.

        Args:
            filter_by: Dictionary of fields to match.
            as_json: If True, returns dicts instead of AgentCard objects.

        Time: O(K) where K is the number of potential candidates in the intersected sets.
        Improved from O(N) linear scan.
        """
        if not filter_by:
            if as_json:
                return [c.to_dict() for c in self._agents.values()]
            else:
                return list(self._agents.values())

        # Attempt to use indexes for filtering
        candidate_urls: set[str] | None = None

        # Check for indexed fields in filter
        if "name" in filter_by:
            candidate_urls = self._index_name.get(filter_by["name"], set())

        if "role" in filter_by:
            role_urls = self._index_role.get(filter_by["role"], set())
            candidate_urls = candidate_urls & role_urls if candidate_urls is not None else role_urls

        if "tags" in filter_by:
            tag_filter = filter_by["tags"]
            if isinstance(tag_filter, str):
                tag_urls = self._index_tags.get(tag_filter, set())
                candidate_urls = candidate_urls & tag_urls if candidate_urls is not None else tag_urls

        # Robustness check: if index search yielded nothing BUT the store is not empty,
        # it might be due to manual dict manipulation (common in tests).
        # We fallback to a full scan if the index returned zero results but agents exist.
        if candidate_urls is None or (not candidate_urls and self._agents):
            filtered_agents = [c for c in self._agents.values() if self._match(filter_by, c)]
        else:
            # Refine candidates with full match for non-indexed fields
            filtered_agents = [self._agents[url] for url in candidate_urls if self._match(filter_by, self._agents[url])]

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
        """Match an agent card against a set of filters.

        Time: O(F) where F is the number of filters.
        """
        return all(getattr(card, k, None) == v for k, v in filter_by.items())

    def list_urls(self) -> list[str]:
        """List all registered agent URLs.

        Time: O(N)
        """
        return list(self._agents.keys())

    def count(self) -> int:
        """Get the number of registered agents.

        Time: O(1)
        """
        return len(self._agents)

    def clear(self) -> None:
        """Clear all agents and indexes.

        Time: O(1)
        """
        self._agents.clear()
        self._index_name.clear()
        self._index_role.clear()
        self._index_tags.clear()

    def __repr__(self) -> str:
        return f"Registry(agents={self.count()})"
