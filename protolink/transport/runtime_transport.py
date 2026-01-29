"""In-memory transport for local agent communication.

This module provides :class:`RuntimeTransport`, an in-memory transport that enables agents to communicate directly
without network overhead. Perfect for testing, local multi-agent setups, and rapid prototyping.

Unlike network transports (HTTP, WebSocket), RuntimeTransport:
- Does not have a meaningful URL (agents are addressed by name/URL directly)
- Supports multiple agents sharing a single transport instance
- Routes messages directly in-memory without serialization
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from protolink.client.request_spec import ClientRequestSpec
from protolink.models import AgentCard, Task
from protolink.transport.base import Transport
from protolink.types import TransportType

if TYPE_CHECKING:
    from protolink.server.endpoint_handler import EndpointSpec


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol for agents that can be registered with RuntimeTransport.

    Agents must implement the minimal interface required for in-memory task handling and introspection.
    """

    card: AgentCard

    async def handle_task(self, task: Task) -> Task:
        """Handle an incoming task and return the updated task."""
        ...

    def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]:
        """Return the agent's public metadata and capabilities."""
        ...

    def get_agent_status_html(self) -> str:
        """Return a human-readable HTML status page."""
        ...

    def handle_task_streaming(self, task: Task) -> AsyncIterator[Any]:
        """Stream task events for real-time updates."""
        ...


class RuntimeTransport(Transport):
    """In-memory transport for local agent communication.

    Enables multiple agents to communicate without network overhead by
    routing messages directly in-memory. Agents register themselves with
    the transport and can then send tasks to each other using their
    names or URLs as identifiers.

    Parameters
    ----------
    None
        RuntimeTransport does not require configuration.

    Example
    -------
    >>> transport = RuntimeTransport()
    >>> transport.register_agent(alice)
    >>> transport.register_agent(bob)
    >>> # Alice can now send tasks to Bob via the transport
    >>> await alice.send_task_to("bob", task)
    """

    transport_type: ClassVar[TransportType] = "runtime"
    supports_streaming: ClassVar[bool] = True

    def __init__(self) -> None:
        """Initialize in-memory transport."""
        self._agents: dict[str, AgentProtocol] = {}
        self._endpoints: list[EndpointSpec] = []
        self._is_running: bool = False

    # ------------------------------------------------------------------
    # Agent Registry
    # ------------------------------------------------------------------

    def register_agent(self, agent: AgentProtocol) -> None:
        """Register an agent for in-memory communication.

        Agents are registered by both their URL and name for flexible lookup.

        Args:
            agent: Agent instance implementing AgentProtocol.
        """
        self._agents[agent.card.url] = agent
        self._agents[agent.card.name] = agent

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the transport.

        Args:
            agent_id: Agent URL or name to unregister.
        """
        agent = self._agents.get(agent_id)
        if agent:
            # Remove both URL and name entries
            self._agents.pop(agent.card.url, None)
            self._agents.pop(agent.card.name, None)

    def get_agent(self, agent_id: str) -> AgentProtocol | None:
        """Get a registered agent by URL or name.

        Args:
            agent_id: Agent URL or name.

        Returns:
            AgentProtocol instance or None if not found.
        """
        return self._agents.get(agent_id)

    def list_agents(self) -> list[str]:
        """List all registered agent identifiers.

        Returns:
            List of registered agent URLs and names.
        """
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Transport Interface (Client-side)
    # ------------------------------------------------------------------

    async def send(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request to a registered agent.

        Routes requests directly to agent handlers based on the request spec.

        Args:
            request_spec: Client request specification (endpoint name, path, etc.).
            base_url: Agent URL or name to send the request to.
            data: Request payload (task, etc.).
            params: Optional query parameters (not used for runtime transport).

        Returns:
            Response from the agent handler.

        Raises:
            ValueError: If the target agent is not registered.
            NotImplementedError: If the endpoint is not supported.
        """
        agent = self._agents.get(base_url)
        if not agent:
            raise ValueError(f"Agent not found: {base_url}")

        return await self._dispatch(agent, request_spec, data)

    async def _dispatch(
        self,
        agent: AgentProtocol,
        request_spec: ClientRequestSpec,
        data: Any,
    ) -> Any:
        """Dispatch a request to the appropriate agent handler.

        Args:
            agent: Target agent.
            request_spec: Request specification.
            data: Request data.

        Returns:
            Handler response, optionally parsed.
        """
        match request_spec.name:
            case "send_task":
                return await self._handle_send_task(agent, request_spec, data)
            case "get_agent_card":
                return await self._handle_get_agent_card(agent, request_spec)
            case "status":
                return self._handle_status(agent)
            case _:
                raise NotImplementedError(f"Endpoint '{request_spec.name}' not supported by RuntimeTransport")

    async def _handle_send_task(
        self,
        agent: AgentProtocol,
        request_spec: ClientRequestSpec,
        data: Any,
    ) -> Task:
        """Handle send_task request."""
        task = data if isinstance(data, Task) else Task.from_dict(data)
        result = await agent.handle_task(task)

        # Apply response parser for wire-format compatibility
        if request_spec.response_parser:
            return request_spec.response_parser(result.to_dict())
        return result

    async def _handle_get_agent_card(
        self,
        agent: AgentProtocol,
        request_spec: ClientRequestSpec,
    ) -> AgentCard | dict[str, Any]:
        """Handle get_agent_card request."""
        result = agent.get_agent_card(as_json=True)

        # Handle potential async implementations
        if inspect.isawaitable(result):
            result = await result

        # At this point, result is AgentCard | dict[str, Any]
        card: AgentCard | dict[str, Any] = result  # type: ignore[assignment]

        if request_spec.response_parser:
            if isinstance(card, dict):
                return request_spec.response_parser(card)
            return request_spec.response_parser(card.to_dict())
        return card

    def _handle_status(self, agent: AgentProtocol) -> str:
        """Handle status request."""
        return agent.get_agent_status_html()

    # ------------------------------------------------------------------
    # Streaming Support
    # ------------------------------------------------------------------

    async def subscribe(self, agent_url: str, task: Task) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to streaming task updates.

        Args:
            agent_url: Agent URL or name.
            task: Task to process.

        Yields:
            Event dictionaries from the agent's streaming handler.

        Raises:
            ValueError: If the agent is not found.
        """
        agent = self._agents.get(agent_url)
        if not agent:
            raise ValueError(f"Agent not found: {agent_url}")

        if hasattr(agent, "handle_task_streaming"):
            async for event in agent.handle_task_streaming(task):
                yield event.to_dict() if hasattr(event, "to_dict") else event
        else:
            # Fallback: execute non-streaming and emit completion event
            result = await agent.handle_task(task)
            from protolink.core.events import TaskStatusUpdateEvent

            yield TaskStatusUpdateEvent(task_id=result.id, new_state="completed", final=True).to_dict()

    # ------------------------------------------------------------------
    # Transport Lifecycle
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Store endpoint specifications for reference.

        RuntimeTransport handles routing directly in send() rather than
        through HTTP-style route handlers.

        Args:
            endpoints: List of endpoint specifications.
        """
        self._endpoints = endpoints

    async def start(self) -> None:
        """Start the transport (no-op for in-memory transport)."""
        self._is_running = True

    async def stop(self) -> None:
        """Stop the transport and clean up resources."""
        self._agents.clear()
        self._endpoints.clear()
        self._is_running = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def validate_url(self) -> bool:
        """Validate URL (always valid for runtime transport)."""
        return True

    @property
    def url(self) -> str:
        """Get the transport URL.

        RuntimeTransport doesn't have a meaningful URL since it hosts
        multiple agents. Returns a placeholder identifier.
        """
        return "runtime://local"

    @property
    def is_running(self) -> bool:
        """Check if the transport is running."""
        return self._is_running

    def __repr__(self) -> str:
        return f"RuntimeTransport(agents={len(self._agents) // 2})"
