from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urlparse

from protolink.client.request_spec import ClientRequestSpec
from protolink.security.auth import Authenticator
from protolink.security.tls import TLSConfig
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport._streaming import is_stream_terminal_event
from protolink.transport.base import Transport, TransportRequestContext
from protolink.transport.config import TransportCapabilities, TransportConfig
from protolink.transport.errors import (
    TransportConnectionError,
    TransportProtocolError,
    TransportRemoteError,
    TransportTimeoutError,
)
from protolink.types import TransportType
from protolink.utils.inspect import is_async_callable
from protolink.utils.serialization import Serializer

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "WebSocketTransport requires the 'websockets' package. Install it with: pip install protolink[http]"
    ) from exc


class WebSocketTransport(Transport):
    """WebSocket transport.

    It supports the existing `Transport.send(ClientRequestSpec, base_url, ...)` API by
    encoding the request as a JSON message over WebSocket and waiting for a correlated
    JSON response.

    This means **no changes** are required to `ClientRequestSpec` or `EndpointSpec` for
    basic request/response functionality.

    **Concurrency and Event Loop Isolation**
    Because Protolink executes agents using isolated background threads when ``background=True``,
    a single ``WebSocketTransport`` instance may be accessed by multiple ``asyncio`` event loops
    concurrently (e.g., the server running in a background thread and client requests dispatched
    from the main thread).

    To prevent `asyncio` cross-loop contamination, this transport implements loop-aware connection
    management. Persistent WebSocket connections and their synchronization primitives (like
    ``asyncio.Lock``) are dynamically cached using composite keys incorporating the caller's
    event loop ID. This guarantees strict isolation of connections per thread.

    Args:
        url: Server URL using ``ws://`` or secure ``wss://``.
        timeout: Timeout in seconds for outbound operations.
        authenticator: Optional application-level request authenticator.
        credentials: Optional credentials for outbound authentication.
        tls: Optional certificate and trust configuration used by ``wss://``
            servers and clients.
        config: Shared limits, retry, keepalive, shutdown, idempotency, and metrics settings.
    """

    transport_type: ClassVar[TransportType] = "websocket"
    supports_streaming: ClassVar[bool] = True
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(
        streaming=True,
        tls=True,
        bidirectional=True,
        persistent_connections=True,
    )

    def __init__(
        self,
        url: str,
        timeout: float = 360.0,
        authenticator: Authenticator | None = None,
        credentials: str | None = None,
        *,
        tls: TLSConfig | None = None,
        config: TransportConfig | None = None,
    ) -> None:
        """Initialize a loop-safe WebSocket transport.

        Client connections are created lazily per event loop and closed on
        their owning loops during shutdown.
        """
        super().__init__(config=config)
        self._url: str = url
        self._timeout: float = timeout
        self.authenticator: Authenticator | None = authenticator
        self.credentials: str | None = credentials
        self.tls = tls
        self.security_context: Any | None = None

        self._endpoints: dict[tuple[str, str], EndpointSpec] = {}
        self._server: Any | None = None

        # Loop-aware connection states to prevent cross-loop boundary exceptions.
        # Keys are structured as: f"{base_url}_{id(asyncio.get_running_loop())}"
        self._client_conns: dict[str, Any] = {}
        self._client_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Server routing
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register the supported protocol handlers into memory.

        Unlike HTTP servers that utilize complex routing engines, WebSocket multiplexes all logic
        over a single persistent endpoint. This method caches the abstract ``EndpointSpec`` objects
        into an internal dictionary keyed by ``(method, path)``, enabling the central
        ``_handle_connection`` router to rapidly dispatch incoming JSON-RPC style frames to their
        appropriate domain handlers.

        Parameters
        ----------
        endpoints:
            Endpoint specifications to expose over this transport.
        """
        for ep in endpoints:
            self._endpoints[(ep.method.upper(), ep.path)] = ep

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spin up the native `websockets` daemon on the specified interface.

        This instantiates an ``asyncio`` background task running the ``websockets.serve``
        lifecycle. Once bound to the designated port, all inbound TCP connections are immediately
        funneled directly into the ``_handle_connection`` multiplexer.
        """
        if self._transport_running:
            return
        host, port = self._get_host_port(self._url)
        if not host or not port:
            raise ValueError(f"Invalid URL: {self._url}. Missing host or port.")

        kwargs: dict[str, Any] = {
            "close_timeout": self.config.shutdown_timeout,
            "max_size": self.config.limits.max_request_bytes,
            "max_queue": self.config.limits.max_concurrent_requests,
            "ping_interval": self.config.keepalive_interval,
            "ping_timeout": self.config.keepalive_timeout,
        }
        if self.authenticator:
            kwargs["process_request"] = self._process_request
        if urlparse(self._url).scheme.lower() == "wss":
            if self.tls is None:
                raise ValueError(f"WSS server at {self._url} requires TLSConfig with certfile and keyfile")
            self.tls.require_server_identity(self._url)
            kwargs["ssl"] = self.tls.create_server_context()

        self._server = await websockets.serve(
            self._handle_connection,
            host=host,
            port=port,
            **kwargs,
        )
        self._transport_running = True

    async def _process_request(self, path: str, request_headers: Any) -> Any:
        """Authenticate incoming websocket handshake requests."""
        if not self.authenticator:
            return None

        # websockets v14+ passes a Request object (which has a .headers attribute)
        # instead of a raw headers object.
        headers = request_headers
        if hasattr(request_headers, "headers"):
            headers = request_headers.headers

        from protolink.security.auth import extract_credentials

        credentials = extract_credentials(headers)
        if not credentials:
            try:
                from websockets.datastructures import Headers
                from websockets.http11 import Response

                return Response(
                    status_code=401,
                    reason_phrase="Unauthorized",
                    headers=Headers([("Content-Type", "text/plain")]),
                    body=b"Unauthorized: Missing credentials",
                )
            except ImportError:
                return 401, [("Content-Type", "text/plain")], b"Unauthorized: Missing credentials"

        try:
            await self.authenticator.authenticate(credentials)
            return None  # Let connection proceed
        except Exception as e:
            try:
                from websockets.datastructures import Headers
                from websockets.http11 import Response

                return Response(
                    status_code=401,
                    reason_phrase="Unauthorized",
                    headers=Headers([("Content-Type", "text/plain")]),
                    body=f"Unauthorized: {e}".encode(),
                )
            except ImportError:
                return 401, [("Content-Type", "text/plain")], f"Unauthorized: {e}".encode()

    async def stop(self) -> None:
        """Stop the WebSocket server and close any cached client connections."""
        await self.close_loop_resources()
        self._client_conns.clear()
        self._client_locks.clear()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._transport_running = False

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    async def send(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Multiplex a single synchronous-style request over a persistent WebSocket connection.

        This client orchestrator translates a RESTful ``ClientRequestSpec`` into a JSON-RPC
        flavored payload by injecting a unique ``message_id``. It secures an exclusive lease
        on the loop-isolated connection via ``asyncio.Lock()``, pushes the payload, and blocks
        until a frame with the exact matching ``id`` is yielded by the remote server.

        This design facilitates transparent, bi-directional communication while appearing identical
        to standard HTTP request/response lifecycles to the developer.
        """
        context = self.new_request_context(request_spec, data)

        async def operation(attempt: TransportRequestContext) -> Any:
            if self.authenticator and self.credentials and not self.security_context:
                await self.authenticate(self.credentials)
            payload = self._build_request_payload(request_spec, data, params, attempt)
            request_size = self.check_payload_limit(payload, kind="request", url=base_url)
            loop_key = f"{base_url}_{id(asyncio.get_running_loop())}_{request_spec.channel}"
            lock = self._client_locks.setdefault(loop_key, asyncio.Lock())
            async with lock:
                conn = await self._ensure_client_connection(
                    base_url,
                    loop_key,
                    request_id=attempt.request_id,
                )
                try:
                    self._metrics.add(bytes_sent=request_size)
                    await conn.send(json.dumps(payload))
                    raw = await asyncio.wait_for(conn.recv(), timeout=self._timeout)
                except TimeoutError as exc:
                    raise TransportTimeoutError(
                        f"WebSocket request to {base_url} timed out",
                        url=base_url,
                        request_id=attempt.request_id,
                        retryable=True,
                    ) from exc
                except ConnectionClosed as exc:
                    self._client_conns.pop(loop_key, None)
                    self.discard_loop_resource(("websocket", loop_key))
                    raise TransportConnectionError(
                        f"WebSocket connection closed while talking to {base_url}",
                        url=base_url,
                        request_id=attempt.request_id,
                        retryable=True,
                    ) from exc

            response = self._decode_response(raw, base_url, attempt.request_id)
            result = self._unwrap_response(response, base_url, attempt.request_id)
            response_size = self.check_payload_limit(result, kind="response", url=base_url)
            self._metrics.add(bytes_received=response_size)
            return request_spec.response_parser(result) if request_spec.response_parser else result

        async with self.request_slot():
            return await self.run_with_retries(request_spec, context, operation)

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        """Establish an asynchronous streaming pipeline over a persistent WebSocket connection.

        Designed for heavy workloads (like streaming agent thought processes or task progression),
        this pushes a ``/tasks/stream`` payload with a unique ``message_id``. It then continuously
        polls the loop-isolated socket, yielding deserialized chunks back to the caller as an
        ``AsyncIterator``. The pipeline automatically terminates when the remote server sends a
        frame tagged with ``final=True``.
        """
        if self.authenticator and self.credentials and not self.security_context:
            await self.authenticate(self.credentials)

        request_spec = ClientRequestSpec(
            name="task_stream",
            path="/tasks/stream",
            method="POST",
            request_source="body",
        )
        context = self.new_request_context(request_spec, task)
        message_id = context.request_id

        payload: dict[str, Any] = {
            "id": message_id,
            "method": "POST",
            "path": "/tasks/stream",
            "data": self._serialize_result(task),
        }

        request_size = self.check_payload_limit(payload, kind="request", url=agent_url)
        async with self.stream_slot():
            loop_key = f"{agent_url}_{id(asyncio.get_running_loop())}_default"
            lock = self._client_locks.setdefault(loop_key, asyncio.Lock())
            async with lock:
                conn = await self._ensure_client_connection(
                    agent_url,
                    loop_key,
                    request_id=message_id,
                )
                try:
                    self._metrics.add(bytes_sent=request_size)
                    await conn.send(json.dumps(payload))
                    while True:
                        raw = await asyncio.wait_for(conn.recv(), timeout=self._timeout)
                        msg = self._decode_response(raw, agent_url, message_id)
                        result = self._unwrap_response(msg, agent_url, message_id, operation="stream")
                        if result is not None:
                            event_size = self.check_payload_limit(result, kind="event", url=agent_url)
                            self._metrics.add(bytes_received=event_size)
                            yield result
                        if msg.get("final", False):
                            break
                except TimeoutError as exc:
                    raise TransportTimeoutError(
                        f"WebSocket stream from {agent_url} timed out",
                        url=agent_url,
                        request_id=message_id,
                        retryable=True,
                    ) from exc
                except ConnectionClosed as exc:
                    self._client_conns.pop(loop_key, None)
                    self.discard_loop_resource(("websocket", loop_key))
                    raise TransportConnectionError(
                        f"WebSocket connection closed while streaming from {agent_url}",
                        url=agent_url,
                        request_id=message_id,
                        retryable=True,
                    ) from exc

    async def _ensure_client_connection(
        self,
        base_url: str,
        loop_key: str,
        *,
        request_id: str | None = None,
    ) -> Any:
        """Get or create a cached client WebSocket connection for ``base_url``.

        This method utilizes a ``loop_key`` (incorporating the current ``asyncio`` event
        loop ID) to lazily instantiate and cache persistent websocket connections per event
        loop. This strict isolation ensures that concurrent requests made from the main
        thread and the background server thread do not share underlying websocket primitives,
        thereby completely eliminating `Future attached to a different loop` exceptions.
        """
        existing = self._client_conns.get(loop_key)
        if existing is not None and self._connection_is_open(existing):
            return existing

        headers = self._build_headers()
        connect_kwargs: dict[str, Any] = {
            "close_timeout": self.config.shutdown_timeout,
            "max_size": max(self.config.limits.max_response_bytes, self.config.limits.max_event_bytes),
            "max_queue": self.config.limits.max_concurrent_requests,
            "ping_interval": self.config.keepalive_interval,
            "ping_timeout": self.config.keepalive_timeout,
        }
        if urlparse(base_url).scheme.lower() == "wss" and self.tls is not None:
            connect_kwargs["ssl"] = self.tls.create_client_context()
        try:
            try:
                conn = await websockets.connect(base_url, additional_headers=headers, **connect_kwargs)
            except TypeError:
                conn = await websockets.connect(base_url, extra_headers=headers, **connect_kwargs)
        except (OSError, TimeoutError, ConnectionClosed) as exc:
            raise TransportConnectionError(
                f"Failed to connect to WebSocket agent at {base_url}",
                url=base_url,
                request_id=request_id,
                retryable=True,
            ) from exc
        self._client_conns[loop_key] = conn
        self.register_loop_resource(("websocket", loop_key), conn.close)
        return conn

    def _build_request_payload(
        self,
        request_spec: ClientRequestSpec,
        data: Any,
        params: dict[str, Any] | None,
        context: TransportRequestContext,
    ) -> dict[str, Any]:
        """Build a correlated JSON request envelope."""
        payload: dict[str, Any] = {
            "id": context.request_id,
            "method": request_spec.method,
            "path": request_spec.path,
        }
        if context.idempotency_key:
            payload["idempotency_key"] = context.idempotency_key
        if request_spec.request_source == "body" and data is not None:
            payload["data"] = self._serialize_result(data)
        elif request_spec.request_source == "query_params" and data is not None:
            payload["params"] = data if isinstance(data, dict) else {"data": str(data)}
        if params:
            payload.setdefault("params", {})
            payload["params"].update(params)
        return payload

    def _decode_response(self, raw: Any, base_url: str, request_id: str) -> dict[str, Any]:
        """Decode and validate one WebSocket response frame."""
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        try:
            response = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise TransportProtocolError(
                f"Invalid JSON response from {base_url}: {raw!r}",
                url=base_url,
                request_id=request_id,
            ) from exc
        if not isinstance(response, dict):
            raise TransportProtocolError(
                f"WebSocket response from {base_url} must be a JSON object",
                url=base_url,
                request_id=request_id,
            )
        return response

    def _unwrap_response(
        self,
        response: dict[str, Any],
        base_url: str,
        request_id: str,
        *,
        operation: str = "request",
    ) -> Any:
        """Validate correlation and unwrap a WebSocket response envelope."""
        if response.get("id") != request_id:
            raise TransportProtocolError(
                f"Mismatched WebSocket {operation} id from {base_url}: {response.get('id')}",
                url=base_url,
                request_id=request_id,
            )
        if not response.get("ok", False):
            error = response.get("error") or {}
            raise TransportRemoteError(
                f"WebSocket {operation} failed at {base_url}: {error}",
                url=base_url,
                request_id=request_id,
            )
        return response.get("result")

    @staticmethod
    def _connection_is_open(conn: Any) -> bool:
        """Return whether a cached WebSocket client connection is reusable."""
        closed = getattr(conn, "closed", None)
        if isinstance(closed, bool):
            return not closed

        open_attr = getattr(conn, "open", None)
        if isinstance(open_attr, bool):
            return open_attr

        state = getattr(conn, "state", None)
        protocol = getattr(conn, "protocol", None)
        protocol_state = getattr(protocol, "state", None)
        active_state = state if state is not None else protocol_state
        state_name = getattr(active_state, "name", None)
        if state_name is not None:
            return state_name == "OPEN"

        return True

    # ------------------------------------------------------------------
    # Authentication & Security
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: str) -> None:
        """Validate credentials and establish a WebSocket security context.

        Delegates validation to the injected ``Authenticator``. The resulting token or security
        state is permanently bound to the transport instance and seamlessly injected into the
        handshake headers when initializing new physical ``websockets.connect()`` streams.
        """
        if not self.authenticator:
            raise RuntimeError("No Authenticator configured")
        self.security_context = await self.authenticator.authenticate(credentials)

    def _build_headers(self) -> dict[str, str]:
        """Compile the HTTP upgrade headers required for the WebSocket handshake."""
        headers: dict[str, str] = {}
        if self.authenticator and self.security_context:
            context = self.security_context
            token = getattr(context, "token", None)
            if token:
                scheme = getattr(self.authenticator, "security_scheme", None)
                if scheme:
                    if scheme.auth_type == "http":
                        if scheme.auth_scheme == "basic":
                            headers["Authorization"] = f"Basic {token}"
                        elif scheme.auth_scheme == "bearer":
                            headers["Authorization"] = f"Bearer {token}"
                        else:
                            headers["Authorization"] = f"{scheme.auth_scheme.capitalize()} {token}"
                    elif scheme.auth_type == "apiKey":
                        headers["X-API-Key"] = token
                        headers["Authorization"] = f"ApiKey {token}"
                    else:
                        headers["Authorization"] = f"Bearer {token}"
                else:
                    headers["Authorization"] = f"Bearer {token}"
        return headers

    # ------------------------------------------------------------------
    # Server internals
    # ------------------------------------------------------------------

    async def _handle_connection(self, websocket: Any) -> None:
        """The central multiplexer for all inbound WebSocket traffic.

        This loop continuously consumes raw JSON frames from the underlying socket. It deserializes
        the request to identify its correlation ``id``, intended ``method``, and ``path``. It then:
        1. Resolves the appropriate ``EndpointSpec`` registered via ``setup_routes``.
        2. Normalizes input data into the expected format (body vs. query parameters).
        3. Executes the underlying domain handler. If the handler is a streaming generator, it loops
           and emits chunked frames incrementally. Otherwise, it executes a standard request/response pattern.
        4. Serializes the final result and transmits it back with the matching correlation ``id``.
        """
        try:
            async for raw in websocket:
                response: dict[str, Any]
                req: Any = None
                idempotency_key: str | None = None
                try:
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="replace")
                    req = json.loads(raw)
                    self.check_payload_limit(req, kind="request", url=self._url)
                    request_id = req.get("id")
                    method = str(req.get("method")).upper()
                    path = req.get("path")

                    if not request_id or not method or not path:
                        raise ValueError("Missing required fields: id/method/path")

                    ep = self._endpoints.get((method, path))
                    if ep is None:
                        raise ValueError(f"No endpoint registered for {method} {path}")

                    raw_idempotency_key = req.get("idempotency_key")
                    idempotency_key = f"{method}:{path}:{raw_idempotency_key}" if raw_idempotency_key else None
                    if ep.mode != "stream" and not ep.streaming:
                        owns_operation, cached = await self.acquire_idempotent_response(idempotency_key)
                        if not owns_operation:
                            if not isinstance(cached, dict):
                                raise TypeError("Cached WebSocket response must be a mapping")
                            cached_response = cached.copy()
                            cached_response["id"] = request_id
                            await websocket.send(json.dumps(cached_response))
                            continue

                    if ep.request_source == "body":
                        payload = req.get("data")
                    elif ep.request_source == "query_params":
                        payload = req.get("params") or {}
                    else:
                        payload = None

                    if ep.request_parser:
                        handler_input = (
                            await ep.request_parser(payload)
                            if is_async_callable(ep.request_parser)
                            else ep.request_parser(payload)
                        )
                    else:
                        handler_input = payload

                    handler_is_async = is_async_callable(ep.handler)

                    if ep.mode == "stream" or ep.streaming:
                        await self._send_stream_response(
                            websocket,
                            ep,
                            payload,
                            handler_input,
                            request_id,
                        )
                        continue

                    async with self.inbound_request_slot():
                        if ep.request_source != "none" and payload is not None:
                            result = await ep.handler(handler_input) if handler_is_async else ep.handler(handler_input)
                        else:
                            result = await ep.handler() if handler_is_async else ep.handler()

                    response = {"id": request_id, "ok": True, "result": self._serialize_result(result)}
                    self.check_payload_limit(response, kind="response", url=self._url)
                    self.complete_idempotent_response(idempotency_key, response)
                except Exception as e:
                    response = {
                        "id": req.get("id") if isinstance(req, dict) else None,
                        "ok": False,
                        "error": {"message": str(e), "type": e.__class__.__name__},
                    }

                    if isinstance(req, dict) and req.get("path") == "/tasks/stream":
                        response["final"] = True
                    self.complete_idempotent_response(idempotency_key, response)

                await websocket.send(json.dumps(response))
        except ConnectionClosed:
            pass

    async def _send_stream_response(
        self,
        websocket: Any,
        endpoint: EndpointSpec,
        payload: Any,
        handler_input: Any,
        request_id: str,
    ) -> None:
        """Run one bounded server stream and emit correlated envelopes."""
        async with self.stream_slot():
            if endpoint.request_source != "none" and payload is not None:
                stream_obj = endpoint.handler(handler_input)
            else:
                stream_obj = endpoint.handler()

            if inspect.isawaitable(stream_obj):
                stream_obj = await stream_obj
            if not hasattr(stream_obj, "__aiter__"):
                raise TypeError("Streaming handler must return an async iterator")

            sent_final = False
            async for event in stream_obj:
                event_payload = self._serialize_result(event)
                self.check_payload_limit(event_payload, kind="event", url=self._url)
                event_final = bool(event_payload.get("final", False)) if isinstance(event_payload, dict) else False
                stream_final = is_stream_terminal_event(event_payload, event_final=event_final)
                await websocket.send(
                    json.dumps(
                        {
                            "id": request_id,
                            "ok": True,
                            "result": event_payload,
                            "final": stream_final,
                            "stream": True,
                        }
                    )
                )
                if stream_final:
                    sent_final = True
                    break

            if not sent_final:
                await websocket.send(
                    json.dumps({"id": request_id, "ok": True, "result": None, "final": True, "stream": True})
                )

    def _serialize_result(self, result: Any) -> Any:
        """Recursively normalize complex data models into JSON-safe structures.

        Since websockets mandate purely text-based (or binary) JSON payloads, this utility ensures
        that rich domain models (like Pydantic ``BaseModel``, custom DataClasses, or nested lists)
        are aggressively flattened into basic Python dictionaries prior to `json.dumps()` serialization.
        """
        return Serializer.serialize_to_dict(result)

    def _get_host_port(self, url: str) -> tuple[str | None, int | None]:
        """Parse a ``ws://`` or ``wss://`` URL and return (host, port)."""
        parsed = urlparse(url.rstrip("/"))
        return parsed.hostname, parsed.port

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def validate_url(self) -> bool:
        """Return True if the transport URL uses ``ws://`` or ``wss://``."""
        return self._url.startswith("ws://") or self._url.startswith("wss://")

    @property
    def url(self) -> str:
        """Base URL for this transport (server bind address)."""
        return self._url

    @property
    def timeout(self) -> float:
        """Get the timeout for WebSocket operations."""
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        """Set the timeout for WebSocket operations."""
        self._timeout = value
