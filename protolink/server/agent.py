"""
Agent server implementation responsible for exposing an agent over a transport.

The AgentServer acts as a thin coordination layer between:
- an Agent (business logic)
- a Transport (HTTP, WS, etc.)

It does **not** implement networking itself. Instead, it:
- declares the agent-facing endpoints
- binds agent handlers to transport routes
- manages the server lifecycle
"""

from __future__ import annotations

from typing import Any, Protocol

from protolink.models import AgentCard, EndpointSpec, Task
from protolink.transport import AgentTransport


class AgentInterface(Protocol):
    """Public interface an Agent must implement to be served.

    This protocol defines the minimal surface required by an AgentServer.
    Agents are not required to inherit from this protocol explicitly;
    structural typing (duck typing) is sufficient.
    """

    async def handle_task(self, task: Task) -> Task:
        """Handle an incoming task and return the updated task."""

    async def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]:
        """Return the agent's public metadata and capabilities."""

    async def get_agent_status_html(self) -> str:
        """Return a human-readable HTML status page."""


class AgentServer:
    """Binds an agent implementation to a transport.

    The AgentServer is responsible for:
    - defining the HTTP (or transport-specific) endpoints
    - wiring agent handlers to those endpoints
    - starting and stopping the underlying transport

    It intentionally contains no transport-specific or agent-specific logic.
    """

    def __init__(self, transport: AgentTransport, agent: AgentInterface) -> None:
        if transport is None:
            raise ValueError("AgentServer requires a transport instance")

        self._transport = transport
        self._agent = agent
        self._is_running = False

    # ------------------------------------------------------------------
    # Request Parsers
    # ------------------------------------------------------------------

    async def task_parser(self, request: Any) -> Task:
        return Task.from_dict(request)

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def _build_endpoints(self) -> None:
        """Register agent endpoints with the transport.

        This method declares the public API surface of the agent and
        binds each endpoint to the corresponding agent handler.
        """

        self._transport.setup_routes(
            [
                EndpointSpec(
                    name="task",
                    path="/tasks/",
                    method="POST",
                    handler=self._agent.handle_task,
                    request_source="body",
                    request_parser=self.task_parser,
                ),
                EndpointSpec(
                    name="agent_card",
                    path="/.well-known/agent.json",
                    method="GET",
                    handler=self._agent.get_agent_card,
                    request_source="none",
                ),
                EndpointSpec(
                    name="status",
                    path="/status",
                    method="GET",
                    handler=self._agent.get_agent_status_html,
                    request_source="none",
                    content_type="html",
                ),
            ]
        )

    async def start(self) -> None:
        """Start the agent server.

        This will:
        1. Register all agent endpoints with the transport
        2. Start the underlying transport server

        Calling this method multiple times is safe.
        """

        if self._is_running:
            return

        self._build_endpoints()
        await self._transport.start()
        self._is_running = True

    async def stop(self) -> None:
        """Stop the agent server.

        Shuts down the underlying transport and marks the server as inactive.
        Calling this method when the server is not running is a no-op.
        """

        if not self._is_running:
            return

        await self._transport.stop()
        self._is_running = False

    def validate_agent_url(self, agent_url: str) -> None:
        """Validate that a given agent URL matches the server transport.

        Parameters
        ----------
        agent_url:
            URL to validate against the transport configuration.

        Raises
        ------
        ValueError
            If the URL does not match the transport's allowed endpoints.
        """

        if not self._transport.validate_agent_url(agent_url):
            raise ValueError("Agent and transport URL mismatch")
