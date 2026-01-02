"""Registry server implementation for handling incoming requests."""

from __future__ import annotations

from typing import Any, Protocol

from protolink.models import AgentCard
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport import Transport


class RegistryInterface(Protocol):
    """Public interface a Registry must implement to be served.

    This protocol defines the minimal surface required by an RegistryServer.
    Registries are not required to inherit from this protocol explicitly; structural typing (duck typing) is sufficient.
    """

    async def handle_register(self, card: AgentCard) -> dict[str, str]:
        """Handle an incoming register request by an Agent."""

    async def handle_unregister(self, agent_url: str) -> dict[str, str]:
        """Handle an incoming unregister request by an Agent."""

    async def handle_discover(self, filter_by: dict[str, Any] | None = None) -> list[dict[str, Any]] | list[AgentCard]:
        """Return a the Registry's list of registered Agents."""

    def handle_status_html(self) -> str:
        """Return a human-readable HTML status page."""


class RegistryServer:
    """Thin wrapper that wires a task handler into a transport."""

    def __init__(self, registry: RegistryInterface, transport: Transport) -> None:
        if transport is None:
            raise ValueError("RegistryServer requires a transport instance")

        self._transport = transport
        self._registry = registry
        self._is_running = False

    # ------------------------------------------------------------------
    # Request Parsers
    # ------------------------------------------------------------------

    async def register_parser(self, request: Any) -> AgentCard:
        return AgentCard.from_dict(request)

    async def unregister_parser(self, request: Any) -> str:
        return request.get("agent_url")

    async def discover_parser(self, request: Any) -> dict[str, Any] | None:
        return request.get("filter_by")

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def _build_endpoints(self) -> None:
        """Register registry endpoints with the transport.

        This method declares the public API surface of the registry and binds each endpoint to the corresponding
        registry handler.
        """

        self._transport.setup_routes(
            [
                EndpointSpec(
                    name="register",
                    path="/agents/",
                    method="POST",
                    handler=self._registry.handle_register,
                    request_source="body",
                    request_parser=self.register_parser,
                ),
                EndpointSpec(
                    name="unregister",
                    path="/agents/",
                    method="DELETE",
                    handler=self._registry.handle_unregister,
                    request_source="body",
                    request_parser=self.unregister_parser,
                ),
                EndpointSpec(
                    name="discover",
                    path="/agents/",
                    method="GET",
                    handler=self._registry.handle_discover,
                    request_source="query_params",
                    request_parser=self.discover_parser,
                ),
                EndpointSpec(
                    name="status",
                    path="/status",
                    method="GET",
                    handler=self._registry.handle_status_html,
                    request_source="none",
                    content_type="html",
                ),
            ]
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the underlying transport."""

        if self._is_running:
            return
        self._build_endpoints()
        await self._transport.start()
        self._is_running = True

    async def stop(self) -> None:
        """Stop the underlying transport and mark the server as idle."""

        if not self._is_running:
            return

        await self._transport.stop()
        self._is_running = False
