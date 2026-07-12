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
from protolink.transport.base import Transport, TransportRequestContext
from protolink.transport.config import TransportCapabilities, TransportConfig
from protolink.transport.errors import TransportConnectionError, TransportError, TransportRemoteError
from protolink.types import TransportType

if TYPE_CHECKING:
    from protolink.server.endpoint_handler import EndpointSpec


class RuntimeTransport(Transport):
    """In-memory transport for process-local agent communication.

    The ``RuntimeTransport`` enables agents to communicate seamlessly without the
    overhead of establishing TCP connections, allocating ports, or marshalling
    data across network sockets. Instead, it routes messages directly in-memory
    via a thread-safe, class-level global registry.

    **Architectural Simulation**
    To ensure that agents built for local runtime execution are 100% compatible
    with distributed environments (like ``HTTPTransport``), this transport strictly
    enforces payload serialization/deserialization boundaries (via Pydantic).
    This means if a payload is structurally invalid, it will fail locally just
    as it would over a real network request.

    **Concurrency and Event Loops**
    Unlike socket-based transports, the ``RuntimeTransport`` accesses shared memory
    across Python event loops. It abstracts away inter-loop communication by directly
    executing asynchronous handlers and resolving their responses in the caller's context.

    Parameters
    ----------
    url : str
        URL identifying this transport endpoint. Must use the ``runtime://`` scheme
        (e.g., ``"runtime://alice"``).
    config : TransportConfig, optional
        Shared limits, retry, shutdown, idempotency, and metrics settings.
    """

    transport_type: ClassVar[TransportType] = "runtime"
    """Identifier for the transport type used by the registry."""

    supports_streaming: ClassVar[bool] = True
    """Indicates whether this transport supports asynchronous streaming."""

    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(
        networked=False,
        streaming=True,
    )

    # Global registry for cross-transport routing
    _registry: ClassVar[dict[str, RuntimeTransport]] = {}

    def __init__(self, url: str, *, config: TransportConfig | None = None) -> None:
        """Initialize the in-memory transport.

        Args:
            url: The unique runtime URL for this agent transport endpoint.
            config: Shared production transport behavior.
        """
        super().__init__(config=config)
        self._url: str = url
        self._endpoints: dict[tuple[str, str], EndpointSpec] = {}
        self._is_running: bool = False

    @classmethod
    def get_transport(cls, base_url: str) -> RuntimeTransport | None:
        """Retrieve a registered peer transport instance from the global registry.

        This mechanism acts as an in-memory DNS resolver. When an agent requests
        communication with a `runtime://` URI, this method resolves the URI to
        the active `RuntimeTransport` instance instantiated in the current Python process.

        Args:
            base_url: The unique URI of the target transport (e.g., ``runtime://bob``).

        Returns:
            The active `RuntimeTransport` instance, or `None` if the target is offline or unregistered.
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
        """Execute a zero-overhead remote procedure call (RPC) against a peer agent.

        This client orchestrator perfectly mimics a standard network-based HTTP request,
        but resolves entirely within process memory:

        1. **Resolution**: Resolves the target `base_url` against the global registry.
        2. **Routing**: Cross-references the requested HTTP `method` and `path` against
           the target transport's internal endpoint dictionary.
        3. **Serialization Boundary**: Strictly forces the request payload through Pydantic
           parsing logic (simulating JSON wire serialization) to guarantee structural safety.
        4. **Execution**: Dispatches the payload to the underlying Python handler and `await`s
           the result regardless of which event loop the target server was initialized on.
        5. **Response Marshalling**: Translates the rich domain model returned by the handler
           back through standard serialization layers before yielding it to the caller.

        Args:
            request_spec: The high-level specification detailing HTTP verb, path, and serializers.
            base_url: The exact URI of the target agent.
            data: The request payload (typically a `Task` or `Message`).
            params: Optional query parameters (mimicked for API symmetry).

        Returns:
            The parsed response emitted by the target agent.

        Raises:
            ConnectionError: If the target URI is not registered in the global memory bus.
            RuntimeError: If the target endpoint (method/path) cannot be resolved.
        """
        context = self.new_request_context(request_spec, data)
        request_size = self.check_payload_limit({"data": data, "params": params}, kind="request", url=base_url)

        async def operation(attempt: TransportRequestContext) -> Any:
            try:
                self._metrics.add(bytes_sent=request_size)
                result = await self._send_once(
                    request_spec,
                    base_url,
                    data,
                    params,
                    idempotency_key=attempt.idempotency_key,
                )
            except TransportError:
                raise
            except Exception as exc:
                raise TransportRemoteError(
                    f"Runtime request failed at {base_url}: {exc}",
                    url=base_url,
                    request_id=attempt.request_id,
                ) from exc
            response_size = self.check_payload_limit(result, kind="response", url=base_url)
            self._metrics.add(bytes_received=response_size)
            return result

        async with self.request_slot():
            return await self.run_with_retries(request_spec, context, operation)

    async def _send_once(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        """Execute one in-process request without retry orchestration."""
        del params
        target: RuntimeTransport | None = self.get_transport(base_url)
        if not target:
            raise TransportConnectionError(
                f"Failed to connect to agent at {base_url}. Agent transport not found in registry.",
                url=base_url,
                retryable=True,
            )

        # Resolve the applicable endpoint configuration on the target node
        endpoint_key: tuple[str, str] = (request_spec.method.upper(), request_spec.path)
        endpoint: EndpointSpec | None = target._endpoints.get(endpoint_key)

        if not endpoint:
            # Reattempt resolution by normalizing the trailing slash
            alt_path = request_spec.path.rstrip("/") if request_spec.path.endswith("/") else request_spec.path + "/"
            endpoint = target._endpoints.get((request_spec.method.upper(), alt_path))

        if not endpoint:
            raise TransportRemoteError(
                f"Agent at {base_url} returned HTTP 404: Endpoint {request_spec.method} {request_spec.path} not found",
                url=base_url,
                status_code=404,
            )

        cache_key = (
            f"{request_spec.method}:{request_spec.path}:{idempotency_key}" if idempotency_key is not None else None
        )
        owns_operation, cached = await target.acquire_idempotent_response(cache_key)
        if not owns_operation:
            return cached

        try:
            async with target.inbound_request_slot():
                parsed_result = await self._invoke_endpoint(endpoint, data, request_spec)
        except BaseException as exc:
            target.abort_idempotent_response(cache_key, exc)
            raise
        target.complete_idempotent_response(cache_key, parsed_result)
        return parsed_result

    async def _invoke_endpoint(
        self,
        endpoint: EndpointSpec,
        data: Any,
        request_spec: ClientRequestSpec,
    ) -> Any:
        """Apply the runtime serialization boundary and invoke one endpoint."""
        # Simulate robust network serialization/deserialization mimicking HTTP transport boundaries
        payload: Any = data
        if payload is not None:
            if hasattr(payload, "to_dict"):
                dict_payload: dict[str, Any] = payload.to_dict()
                if endpoint.request_parser:
                    payload = endpoint.request_parser(dict_payload)
                    if inspect.isawaitable(payload):
                        payload = await payload
                else:
                    payload = dict_payload
            elif isinstance(payload, BaseModel):
                dict_payload = payload.model_dump()
                if endpoint.request_parser:
                    payload = endpoint.request_parser(dict_payload)
                    if inspect.isawaitable(payload):
                        payload = await payload
                else:
                    payload = dict_payload
            elif endpoint.request_parser:
                payload = endpoint.request_parser(payload)
                if inspect.isawaitable(payload):
                    payload = await payload

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
        parsed_result = result
        if request_spec.response_parser:
            if hasattr(result, "to_dict"):
                parsed_result = request_spec.response_parser(result.to_dict())
            elif isinstance(result, BaseModel):
                parsed_result = request_spec.response_parser(result.model_dump())
            elif isinstance(result, dict):
                parsed_result = request_spec.response_parser(result)

        return parsed_result

    # ------------------------------------------------------------------
    # Streaming Support
    # ------------------------------------------------------------------

    async def subscribe(self, agent_url: str, task: Task) -> AsyncIterator[dict[str, Any]]:
        """Establish a local asynchronous streaming pipeline to a peer agent.

        Designed for streaming workloads like real-time agent thought processing, this method
        circumvents WebSocket infrastructure and natively consumes the target agent's `AsyncIterator`.

        It resolves the `base_url`, locates an endpoint flagged for `streaming`, enforces the
        Pydantic serialization boundary, and then seamlessly yields deserialized dictionaries
        from the underlying Python generator directly into the caller's event loop context.

        Args:
            base_url: The target agent URI.
            task: The `Task` invoking the streaming logic.

        Yields:
            Incremental dictionaries representing chunked event progression.

        Raises:
            ConnectionError: If the target agent is not actively registered.
            RuntimeError: If the resolved endpoint fails to return an `AsyncIterator`.
        """
        base_url = agent_url
        request_size = self.check_payload_limit(task, kind="request", url=base_url)
        async with self.stream_slot():
            target: RuntimeTransport | None = self.get_transport(base_url)
            if not target:
                raise TransportConnectionError(
                    f"Failed to connect to agent at {base_url}. Agent transport not found in registry.",
                    url=base_url,
                    retryable=True,
                )

            # Resolve an endpoint explicitly designed for streaming
            stream_endpoints: list[EndpointSpec] = [ep for ep in target._endpoints.values() if ep.streaming]
            if not stream_endpoints:
                # Fallback wrapper enabling non-streaming endpoints to mock a final stream response
                fallback_spec = ClientRequestSpec(
                    name="task",
                    path="/tasks/",
                    method="POST",
                    request_source="body",
                    idempotent=True,
                )
                result: Any = await self.send(fallback_spec, base_url, data=task)
                from protolink.core.events import TaskStatusUpdateEvent

                event = TaskStatusUpdateEvent(task_id=result.id, new_state="completed", final=True).to_dict()
                event_size = self.check_payload_limit(event, kind="event", url=base_url)
                self._metrics.add(bytes_sent=request_size, bytes_received=event_size)
                yield event
                return

            endpoint: EndpointSpec = stream_endpoints[0]

            # Emulate boundary validation across streaming task delivery
            payload: Any = task
            if endpoint.request_parser:
                payload = endpoint.request_parser(task.to_dict())
                if inspect.isawaitable(payload):
                    payload = await payload

            # Begin generator sequence
            result = endpoint.handler(payload)

            if inspect.isawaitable(result):
                result = await result

            if hasattr(result, "__aiter__"):
                self._metrics.add(bytes_sent=request_size)
                async for event in result:
                    serialized = event.to_dict() if hasattr(event, "to_dict") else event
                    event_size = self.check_payload_limit(serialized, kind="event", url=base_url)
                    self._metrics.add(bytes_received=event_size)
                    yield serialized
            else:
                raise TransportRemoteError(
                    "Streaming endpoint handler must return an AsyncIterator",
                    url=base_url,
                )

    # ------------------------------------------------------------------
    # Transport Lifecycle
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Cache abstract endpoint models into the local routing table.

        Instead of delegating to heavy ASGI frameworks like Starlette or FastAPI,
        the `RuntimeTransport` maintains a highly optimized dictionary mapping
        `(HTTP_METHOD, PATH)` tuples to their corresponding `EndpointSpec` instances.

        Args:
            endpoints: A list of `EndpointSpec` configurations defining the server API.
        """
        for endpoint in endpoints:
            self._endpoints[(endpoint.method.upper(), endpoint.path)] = endpoint

    async def start(self) -> None:
        """Activate the transport and broadcast its availability to the local process.

        This method injects the transport instance into the `RuntimeTransport._registry`
        singleton dictionary. Once registered, any other agent running in the same Python
        process can instantly route messages to this transport using its `runtime://` URI.
        """
        if self._is_running:
            return
        RuntimeTransport._registry[self._url] = self
        self._is_running = True
        self._transport_running = True

    async def stop(self) -> None:
        """Gracefully terminate transport operations and drop from the global registry.

        This method removes the transport's URI from the `_registry`, severing incoming
        connections. It subsequently clears all loaded endpoints, ensuring garbage collection
        can aggressively prune the isolated server state.
        """
        RuntimeTransport._registry.pop(self._url, None)
        self._endpoints.clear()
        self._is_running = False
        self._transport_running = False

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
