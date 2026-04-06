"""In-memory transport for local agent communication.

This module provides :class:`RuntimeTransport`, an in-memory transport that enables agents to communicate directly
without network overhead. Perfect for testing, local multi-agent setups, and rapid prototyping.

Unlike network transports (HTTP, WebSocket), RuntimeTransport:
- Routes messages directly in-memory, avoiding TCP overhead.
- Supports isolated agents communicating across a fast local message bus by declaring unique 'runtime://' URLs.
- Mimics HTTP boundaries by enforcing payload serialization semantics using Pydantic.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from protolink.client.request_spec import ClientRequestSpec
from protolink.models import Task
from protolink.transport.base import Transport
from protolink.types import TransportType

if TYPE_CHECKING:
    from protolink.server.endpoint_handler import EndpointSpec


class RuntimeTransport(Transport):
    """In-memory transport for process-local agent communication.

    Enables agents to communicate without network overhead by routing
    messages directly in-memory via a class-level global registry.
    This transport enforces payload serialization similarly to HTTP
    transports to guarantee interchangeable behavior and safety boundaries.

    Parameters
    ----------
    url : str
        URL identifying this transport endpoint (e.g., ``"runtime://alice"``).
    """

    transport_type: ClassVar[TransportType] = "runtime"
    """Identifier for the transport type used by the registry."""

    supports_streaming: ClassVar[bool] = True
    """Indicates whether this transport supports asynchronous streaming."""

    # Global registry for cross-transport routing
    _registry: ClassVar[dict[str, RuntimeTransport]] = {}

    def __init__(self, url: str) -> None:
        """Initialize the in-memory transport.

        Args:
            url: The unique runtime URL for this agent transport endpoint.
        """
        self._url: str = url
        self._endpoints: dict[tuple[str, str], EndpointSpec] = {}
        self._is_running: bool = False

    @classmethod
    def get_transport(cls, base_url: str) -> RuntimeTransport | None:
        """Retrieve a registered transport instance by its URL.

        Args:
            base_url: The unique URL of the target transport.

        Returns:
            The associated `RuntimeTransport` instance, or None if not found.
        """
        return cls._registry.get(base_url)

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
        """Send a request to a registered peer agent.

        Routes requests directly to agent handlers based on the target base URL
        and the requested HTTP method and path encoded in the request specification.

        Args:
            request_spec: Specifications of the request including HTTP method, path, and parsers.
            base_url: The URL of the target agent to deliver the request to.
            data: The request payload (typically a Task object or compatible primitive).
            params: Optional query parameters (unused natively but supported for API alignment).

        Returns:
            The raw or parsed response produced by the target endpoint's handler.

        Raises:
            ConnectionError: If the target agent transport is not actively registered.
            RuntimeError: If the requested endpoint path or method does not exist on the target.
        """
        target: RuntimeTransport | None = self.get_transport(base_url)
        if not target:
            raise ConnectionError(f"Failed to connect to agent at {base_url}. Agent transport not found in registry.")

        # Resolve the applicable endpoint configuration on the target node
        endpoint_key: tuple[str, str] = (request_spec.method.upper(), request_spec.path)
        endpoint: EndpointSpec | None = target._endpoints.get(endpoint_key)

        if not endpoint:
            # Reattempt resolution by normalizing the trailing slash
            alt_path = request_spec.path.rstrip("/") if request_spec.path.endswith("/") else request_spec.path + "/"
            endpoint = target._endpoints.get((request_spec.method.upper(), alt_path))

        if not endpoint:
            raise RuntimeError(
                f"Agent at {base_url} returned HTTP 404: Endpoint {request_spec.method} {request_spec.path} not found"
            )

        # Simulate robust network serialization/deserialization mimicking HTTP transport boundaries
        payload: Any = data
        if payload is not None:
            if hasattr(payload, "to_dict"):
                dict_payload: dict[str, Any] = payload.to_dict()
                if endpoint.request_parser:
                    payload = endpoint.request_parser(dict_payload)
                else:
                    payload = dict_payload
            elif isinstance(payload, BaseModel):
                dict_payload = payload.model_dump()
                if endpoint.request_parser:
                    payload = endpoint.request_parser(dict_payload)
                else:
                    payload = dict_payload

        # Process the request payload inside the endpoint handler
        result: Any
        if endpoint.request_source in ("body", "query_params") and payload is not None:
            result = endpoint.handler(payload)
        else:
            result = endpoint.handler()

        # Await resolving for asynchronous endpoint implementations
        if inspect.isawaitable(result):
            result = await result

        # Emulate outgoing response serialization using specified JSON parsers
        if request_spec.response_parser:
            if hasattr(result, "to_dict"):
                return request_spec.response_parser(result.to_dict())
            elif isinstance(result, BaseModel):
                return request_spec.response_parser(result.model_dump())
            elif isinstance(result, dict):
                return request_spec.response_parser(result)

        return result

    # ------------------------------------------------------------------
    # Streaming Support
    # ------------------------------------------------------------------

    async def subscribe(self, base_url: str, task: Task) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to a streaming stream of task updates.

        Args:
            base_url: The URL of the target agent to connect to for streaming.
            task: The Task triggering the streaming sequence.

        Yields:
            Event dictionaries corresponding to streamed updates from the handler.

        Raises:
            ConnectionError: If the target agent transport is not actively registered.
            RuntimeError: If the resolved endpoint does not natively support asynchronous iteration.
        """
        target: RuntimeTransport | None = self.get_transport(base_url)
        if not target:
            raise ConnectionError(f"Failed to connect to agent at {base_url}. Agent transport not found in registry.")

        # Resolve an endpoint explicitly designed for streaming
        stream_endpoints: list[EndpointSpec] = [ep for ep in target._endpoints.values() if ep.streaming]
        if not stream_endpoints:
            # Fallback wrapper enabling non-streaming endpoints to mock a final stream response
            fallback_spec = ClientRequestSpec(
                name="task",
                path="/tasks/",
                method="POST",
                request_source="body",
            )
            result: Any = await self.send(fallback_spec, base_url, data=task)
            from protolink.core.events import TaskStatusUpdateEvent

            yield TaskStatusUpdateEvent(task_id=result.id, new_state="completed", final=True).to_dict()
            return

        endpoint: EndpointSpec = stream_endpoints[0]

        # Emulate boundary validation across streaming task delivery
        payload: Any = task
        if endpoint.request_parser:
            payload = endpoint.request_parser(task.to_dict())

        # Begin generator sequence
        result = endpoint.handler(payload)

        if inspect.isawaitable(result):
            result = await result

        if hasattr(result, "__aiter__"):
            async for event in result:
                yield event.to_dict() if hasattr(event, "to_dict") else event
        else:
            raise RuntimeError("Streaming endpoint handler must return an AsyncIterator")

    # ------------------------------------------------------------------
    # Transport Lifecycle
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register designated endpoint specifications for handler routing.

        Args:
            endpoints: A comprehensive collection of `EndpointSpec` routing instructions.
        """
        for endpoint in endpoints:
            self._endpoints[(endpoint.method.upper(), endpoint.path)] = endpoint

    async def start(self) -> None:
        """Mount the local transport to the global class registry marking it entirely reachable."""
        RuntimeTransport._registry[self._url] = self
        self._is_running = True

    async def stop(self) -> None:
        """Unmount the connected transport removing it gracefully from active registry loops."""
        RuntimeTransport._registry.pop(self._url, None)
        self._endpoints.clear()
        self._is_running = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def validate_url(self) -> bool:
        """Validate whether the configuration abides by runtime requirements.

        Returns:
            bool: True if the configured URL strictly begins with 'runtime://'.
        """
        return self._url.startswith("runtime://")

    @property
    def url(self) -> str:
        """str: The unified transport URL allocated explicitly upon initialization."""
        return self._url

    @property
    def is_running(self) -> bool:
        """bool: The initialization status detailing active connection capability."""
        return self._is_running

    def __repr__(self) -> str:
        """Formulate explicit class identification string mapping status conditions.

        Returns:
            str: Representative diagnostic output indicating current registry conditions.
        """
        return f"RuntimeTransport(url={self._url}, running={self._is_running})"
