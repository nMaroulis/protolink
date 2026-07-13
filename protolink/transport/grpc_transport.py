"""gRPC transport for Protolink agent communication.

This module implements :class:`GRPCTransport`, a physical network transport
that exposes Protolink's transport-neutral ``EndpointSpec`` objects through a
single generic gRPC service. It deliberately avoids generated protobuf files:
requests and responses are compact JSON envelopes carried as gRPC byte
messages. That keeps the public ``AgentClient`` and ``AgentServer`` contracts
identical to HTTP, SSE, WebSocket, and Runtime transports while still using
gRPC's binary framing, deadlines, metadata, connection pooling, and unary-stream
support.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar, NoReturn
from urllib.parse import urlparse

from protolink.client.request_spec import ClientRequestSpec
from protolink.security.auth import Authenticator, extract_credentials
from protolink.security.tls import TLSConfig
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport._deps import _require_grpc
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


class GRPCTransport(Transport):
    """Transport implementation backed by ``grpc.aio``.

    ``GRPCTransport`` maps every Protolink endpoint onto one of two methods on
    the generic ``protolink.transport.v1.ProtolinkTransport`` service:
    ``Invoke`` for unary request/response calls and ``Stream`` for task event
    streams. The request envelope contains ``id``, ``method``, ``path``,
    optional ``data``, and optional ``params`` fields. Responses mirror the
    WebSocket/SSE envelope shape with ``ok``, ``result``, optional ``error``,
    and ``final`` for streams.

    Parameters
    ----------
    url:
        Server URL using ``grpc://`` or secure ``grpcs://``, for example
        ``"grpcs://127.0.0.1:9001"``.
    timeout:
        Deadline in seconds for outbound gRPC calls.
    authenticator:
        Optional authenticator used to validate inbound metadata and build
        outbound authentication metadata.
    credentials:
        Optional raw credentials. When provided with an authenticator, the
        transport lazily authenticates before the first outbound request.
    channel_options:
        Optional low-level ``grpc.aio.insecure_channel`` options.
    server_options:
        Optional low-level ``grpc.aio.server`` options.
    compression:
        Optional gRPC compression value accepted by grpcio.
    maximum_concurrent_rpcs:
        Optional concurrency limit for the gRPC server.
    graceful_shutdown_timeout:
        Seconds to allow in-flight RPCs to finish during ``stop()``.
    tls:
        Optional certificate and trust configuration used by ``grpcs://``
        servers and channels.
    config:
        Shared limits, retry, keepalive, shutdown, idempotency, and metrics settings.
    enable_health:
        Register the standard gRPC health service when its optional package is installed.
    enable_reflection:
        Register gRPC server reflection when its optional package is installed.
    """

    transport_type: ClassVar[TransportType] = "grpc"
    supports_streaming: ClassVar[bool] = True
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(
        streaming=True,
        tls=True,
        persistent_connections=True,
    )

    _SERVICE_NAME: ClassVar[str] = "protolink.transport.v1.ProtolinkTransport"
    _INVOKE_METHOD: ClassVar[str] = f"/{_SERVICE_NAME}/Invoke"
    _STREAM_METHOD: ClassVar[str] = f"/{_SERVICE_NAME}/Stream"

    def __init__(
        self,
        url: str,
        timeout: float = 360.0,
        authenticator: Authenticator | None = None,
        credentials: str | None = None,
        *,
        channel_options: list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None = None,
        server_options: list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None = None,
        compression: Any | None = None,
        maximum_concurrent_rpcs: int | None = None,
        graceful_shutdown_timeout: float = 3.0,
        tls: TLSConfig | None = None,
        config: TransportConfig | None = None,
        enable_health: bool = True,
        enable_reflection: bool = True,
    ) -> None:
        """Initialize a loop-safe generic gRPC client/server transport."""
        super().__init__(config=config)
        self._grpc = _require_grpc()
        self._url = url
        self._timeout = timeout
        self.authenticator = authenticator
        self.credentials = credentials
        self.tls = tls
        self.security_context: Any | None = None

        self._endpoints: dict[tuple[str, str], EndpointSpec] = {}
        self._server: Any | None = None
        self._is_running = False
        self._channels: dict[tuple[str, bool, int], Any] = {}
        self._channel_options = self._merge_options(
            (
                ("grpc.keepalive_time_ms", int((self.config.keepalive_interval or 0) * 1000)),
                ("grpc.keepalive_timeout_ms", int(self.config.keepalive_timeout * 1000)),
                ("grpc.max_send_message_length", self.config.limits.max_request_bytes),
                ("grpc.max_receive_message_length", self.config.limits.max_response_bytes),
            ),
            channel_options,
        )
        self._server_options = self._merge_options(
            (
                ("grpc.max_receive_message_length", self.config.limits.max_request_bytes),
                (
                    "grpc.max_send_message_length",
                    max(self.config.limits.max_response_bytes, self.config.limits.max_event_bytes),
                ),
            ),
            server_options,
        )
        self._compression = compression
        self._maximum_concurrent_rpcs = maximum_concurrent_rpcs or self.config.limits.max_concurrent_requests
        self._graceful_shutdown_timeout = graceful_shutdown_timeout
        self._enable_health = enable_health
        self._enable_reflection = enable_reflection
        self._health_servicer: Any | None = None

    # ------------------------------------------------------------------
    # Server routing and lifecycle
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Cache endpoint declarations for the gRPC request multiplexer.

        gRPC exposes a compact service surface, so transport-neutral
        ``EndpointSpec`` objects are stored in memory and selected from the
        incoming request envelope's ``method`` and ``path`` fields.
        """
        for endpoint in endpoints:
            self._endpoints[(endpoint.method.upper(), endpoint.path)] = endpoint

    async def start(self) -> None:
        """Start the ``grpc.aio`` server and register generic RPC handlers."""
        if self._is_running:
            return
        host, port = self._get_host_port(self._url)
        if not host or port is None:
            raise ValueError(f"Invalid URL: {self._url}. Expected grpc://host:port or grpcs://host:port.")

        self._server = self._grpc.aio.server(
            options=self._server_options,
            compression=self._compression,
            maximum_concurrent_rpcs=self._maximum_concurrent_rpcs,
        )
        generic_handler = self._grpc.method_handlers_generic_handler(
            self._SERVICE_NAME,
            {
                "Invoke": self._grpc.unary_unary_rpc_method_handler(
                    self._handle_unary,
                    request_deserializer=self._decode_message,
                    response_serializer=self._encode_message,
                ),
                "Stream": self._grpc.unary_stream_rpc_method_handler(
                    self._handle_stream,
                    request_deserializer=self._decode_message,
                    response_serializer=self._encode_message,
                ),
            },
        )
        self._server.add_generic_rpc_handlers((generic_handler,))
        await self._setup_operational_services()

        if self._is_secure_url(self._url):
            if self.tls is None:
                raise ValueError(f"gRPC TLS server at {self._url} requires TLSConfig with certfile and keyfile")
            self.tls.require_server_identity(self._url)
            private_key = self.tls.private_key_bytes()
            certificate_chain = self.tls.certificate_chain_bytes()
            credentials = self._grpc.ssl_server_credentials(
                private_key_certificate_chain_pairs=((private_key, certificate_chain),),
                root_certificates=self.tls.ca_bytes() if self.tls.require_client_cert else None,
                require_client_auth=self.tls.require_client_cert,
            )
            bound_port = self._server.add_secure_port(f"{host}:{port}", credentials)
        else:
            bound_port = self._server.add_insecure_port(f"{host}:{port}")
        if bound_port == 0:
            raise RuntimeError(f"Failed to bind gRPC transport at {self._url}")

        await self._server.start()
        self._is_running = True
        self._transport_running = True

    async def stop(self) -> None:
        """Stop the gRPC server and close caller-loop client channels."""
        await self._set_health_status(serving=False)
        if self._server is not None:
            await self._server.stop(self._graceful_shutdown_timeout)
            self._server = None
            self._is_running = False

        await self.close_loop_resources()
        loop_id = id(asyncio.get_running_loop())
        for key, channel in list(self._channels.items()):
            if key[2] == loop_id:
                await channel.close(grace=1.0)
                self._channels.pop(key, None)
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
        """Dispatch a unary gRPC request to a remote Protolink endpoint.

        The high-level ``ClientRequestSpec`` is encoded into the generic gRPC
        request envelope, sent to ``Invoke``, and parsed back through the
        request spec's response parser. Authentication metadata is injected when
        the transport has an active security context.
        """
        if self.authenticator and self.credentials and not self.security_context:
            await self.authenticate(self.credentials)

        context = self.new_request_context(request_spec, data)

        async def operation(attempt: TransportRequestContext) -> Any:
            payload = self._build_request_payload(
                request_id=attempt.request_id,
                idempotency_key=attempt.idempotency_key,
                method=request_spec.method,
                path=request_spec.path,
                request_source=request_spec.request_source,
                data=data,
                params=params,
            )
            request_size = self.check_payload_limit(payload, kind="request", url=base_url)
            channel = await self._ensure_channel(base_url)
            invoke = channel.unary_unary(
                self._INVOKE_METHOD,
                request_serializer=self._encode_message,
                response_deserializer=self._decode_message,
            )
            try:
                self._metrics.add(bytes_sent=request_size)
                response = await invoke(
                    payload,
                    timeout=self._timeout,
                    metadata=self._build_metadata(attempt),
                )
            except self._grpc.aio.AioRpcError as exc:
                self._raise_rpc_error(exc, base_url, operation="request", request_id=attempt.request_id)
            result = self._unwrap_response(
                response,
                request_id=attempt.request_id,
                base_url=base_url,
                operation="request",
            )
            response_size = self.check_payload_limit(result, kind="response", url=base_url)
            self._metrics.add(bytes_received=response_size)
            return request_spec.response_parser(result) if request_spec.response_parser else result

        async with self.request_slot():
            return await self.run_with_retries(request_spec, context, operation)

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        """Stream task events from a remote agent over gRPC unary-stream RPCs.

        The task is serialized into a ``POST /tasks/stream`` envelope and sent
        to the generic ``Stream`` method. Each response envelope yields its
        ``result`` payload until the server marks the transport stream
        ``final``.
        """
        if self.authenticator and self.credentials and not self.security_context:
            await self.authenticate(self.credentials)

        request_spec = ClientRequestSpec(
            name="task_stream",
            path="/tasks/stream",
            method="POST",
            request_source="body",
        )
        request_context = self.new_request_context(request_spec, task)
        request_id = request_context.request_id
        payload = self._build_request_payload(
            request_id=request_id,
            idempotency_key=None,
            method="POST",
            path="/tasks/stream",
            request_source="body",
            data=task,
            params=None,
        )

        request_size = self.check_payload_limit(payload, kind="request", url=agent_url)
        async with self.stream_slot():
            channel = await self._ensure_channel(agent_url)
            stream = channel.unary_stream(
                self._STREAM_METHOD,
                request_serializer=self._encode_message,
                response_deserializer=self._decode_message,
            )
            try:
                self._metrics.add(bytes_sent=request_size)
                call = stream(payload, timeout=self._timeout, metadata=self._build_metadata(request_context))
                async for response in call:
                    result = self._unwrap_response(
                        response,
                        request_id=request_id,
                        base_url=agent_url,
                        operation="stream",
                    )
                    if result is not None:
                        event_size = self.check_payload_limit(result, kind="event", url=agent_url)
                        self._metrics.add(bytes_received=event_size)
                        yield result
                    if response.get("final", False):
                        break
            except self._grpc.aio.AioRpcError as exc:
                self._raise_rpc_error(exc, agent_url, operation="stream", request_id=request_id)

    async def authenticate(self, credentials: str) -> None:
        """Authenticate outbound credentials and store the resulting context."""
        if not self.authenticator:
            raise RuntimeError("No Authenticator configured")
        self.security_context = await self.authenticator.authenticate(credentials)

    # ------------------------------------------------------------------
    # gRPC handlers
    # ------------------------------------------------------------------

    async def _handle_unary(self, request: dict[str, Any], context: Any) -> dict[str, Any]:
        """Handle one ``Invoke`` RPC by routing the request envelope."""
        await self._authenticate_context(context)
        request_id = request.get("id") if isinstance(request, dict) else None
        idempotency_key: str | None = None

        try:
            endpoint, payload = await self._prepare_endpoint_request(request)
            if endpoint.mode == "stream" or endpoint.streaming:
                raise ValueError(f"Endpoint {endpoint.method} {endpoint.path} requires the gRPC Stream method")

            raw_idempotency_key = request.get("idempotency_key")
            idempotency_key = (
                f"{endpoint.method}:{endpoint.path}:{raw_idempotency_key}" if raw_idempotency_key else None
            )
            owns_operation, cached = await self.acquire_idempotent_response(idempotency_key)
            if not owns_operation:
                if not isinstance(cached, dict):
                    raise TypeError("Cached gRPC response must be a mapping")
                cached_response = cached.copy()
                cached_response["id"] = request_id
                return cached_response
            async with self.inbound_request_slot():
                result = await self._call_endpoint(endpoint, payload)
            response = {
                "id": request_id,
                "ok": True,
                "result": self._serialize_result(result),
            }
            self.check_payload_limit(response, kind="response", url=self._url)
            self.complete_idempotent_response(idempotency_key, response)
            return response
        except asyncio.CancelledError as exc:
            self.abort_idempotent_response(idempotency_key, exc)
            raise
        except Exception as exc:
            response = self._error_response(request_id, exc)
            self.abort_idempotent_response(idempotency_key, exc)
            return response

    async def _handle_stream(self, request: dict[str, Any], context: Any) -> AsyncIterator[dict[str, Any]]:
        """Handle one ``Stream`` RPC by yielding response envelopes."""
        await self._authenticate_context(context)
        request_id = request.get("id") if isinstance(request, dict) else None

        try:
            endpoint, payload = await self._prepare_endpoint_request(request)
            if endpoint.mode != "stream" and not endpoint.streaming:
                raise ValueError(f"Endpoint {endpoint.method} {endpoint.path} is not a streaming endpoint")

            async with self.stream_slot():
                sent_final = False
                async for event_payload in self._iterate_endpoint_stream(endpoint, payload):
                    event_final = bool(event_payload.get("final", False)) if isinstance(event_payload, dict) else False
                    stream_final = is_stream_terminal_event(event_payload, event_final=event_final)
                    yield {
                        "id": request_id,
                        "ok": True,
                        "result": event_payload,
                        "final": stream_final,
                        "stream": True,
                    }
                    if stream_final:
                        sent_final = True
                        break

                if not sent_final:
                    yield {"id": request_id, "ok": True, "result": None, "final": True, "stream": True}
        except Exception as exc:
            yield self._error_response(request_id, exc, final=True, stream=True)

    # ------------------------------------------------------------------
    # Endpoint execution helpers
    # ------------------------------------------------------------------

    async def _prepare_endpoint_request(self, request: dict[str, Any]) -> tuple[EndpointSpec, Any]:
        """Validate a request envelope and resolve its endpoint and payload."""
        if not isinstance(request, dict):
            raise ValueError("gRPC request envelope must be a JSON object")

        method = str(request.get("method") or "").upper()
        path = request.get("path")
        if not request.get("id") or not method or not path:
            raise ValueError("Missing required fields: id/method/path")

        endpoint = self._resolve_endpoint(method, str(path))
        if endpoint is None:
            raise ValueError(f"No endpoint registered for {method} {path}")

        if endpoint.request_source == "body":
            payload = request.get("data")
        elif endpoint.request_source == "query_params":
            payload = request.get("params") or {}
        else:
            payload = None

        return endpoint, payload

    def _resolve_endpoint(self, method: str, path: str) -> EndpointSpec | None:
        """Resolve an endpoint, tolerating the trailing slash used by tasks."""
        endpoint = self._endpoints.get((method, path))
        if endpoint is not None:
            return endpoint

        alt_path = path.rstrip("/") if path.endswith("/") else path + "/"
        return self._endpoints.get((method, alt_path))

    async def _parse_payload(self, endpoint: EndpointSpec, payload: Any) -> Any:
        """Apply an endpoint request parser, whether sync or async."""
        if not endpoint.request_parser:
            return payload
        if is_async_callable(endpoint.request_parser):
            return await endpoint.request_parser(payload)
        parsed = endpoint.request_parser(payload)
        if inspect.isawaitable(parsed):
            return await parsed
        return parsed

    async def _call_endpoint(self, endpoint: EndpointSpec, payload: Any) -> Any:
        """Parse a unary payload and invoke the endpoint handler."""
        handler_input = await self._parse_payload(endpoint, payload)
        handler_is_async = is_async_callable(endpoint.handler)
        if endpoint.request_source != "none" and payload is not None:
            return await endpoint.handler(handler_input) if handler_is_async else endpoint.handler(handler_input)
        return await endpoint.handler() if handler_is_async else endpoint.handler()

    async def _iterate_endpoint_stream(self, endpoint: EndpointSpec, payload: Any) -> AsyncIterator[Any]:
        """Parse and iterate one bounded server-side streaming handler."""
        handler_input = await self._parse_payload(endpoint, payload)
        if endpoint.request_source != "none" and payload is not None:
            stream_obj = endpoint.handler(handler_input)
        else:
            stream_obj = endpoint.handler()
        if inspect.isawaitable(stream_obj):
            stream_obj = await stream_obj
        if not hasattr(stream_obj, "__aiter__"):
            raise TypeError("Streaming endpoint handler must return an async iterator")
        async for event in stream_obj:
            event_payload = self._serialize_result(event)
            self.check_payload_limit(event_payload, kind="event", url=self._url)
            yield event_payload

    # ------------------------------------------------------------------
    # Serialization and envelope helpers
    # ------------------------------------------------------------------

    def _build_request_payload(
        self,
        *,
        request_id: str,
        idempotency_key: str | None,
        method: str,
        path: str,
        request_source: str,
        data: Any,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Create the JSON-compatible gRPC request envelope."""
        payload: dict[str, Any] = {
            "id": request_id,
            "method": method,
            "path": path,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        if request_source == "body" and data is not None:
            payload["data"] = self._serialize_result(data)
        elif request_source == "query_params" and data is not None:
            payload["params"] = data if isinstance(data, dict) else {"data": str(data)}

        if params:
            payload.setdefault("params", {})
            payload["params"].update(params)

        return payload

    @staticmethod
    def _encode_message(message: dict[str, Any]) -> bytes:
        """Serialize a gRPC envelope into UTF-8 JSON bytes."""
        normalized = Serializer.serialize_to_dict(message)
        return json.dumps(normalized, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _decode_message(raw: bytes) -> dict[str, Any]:
        """Deserialize UTF-8 JSON bytes into a gRPC envelope."""
        message = json.loads(raw.decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("gRPC envelope must decode to a JSON object")
        return message

    def _serialize_result(self, result: Any) -> Any:
        """Recursively normalize endpoint results into JSON-compatible values."""
        return Serializer.serialize_to_dict(result)

    def _unwrap_response(
        self,
        response: dict[str, Any],
        *,
        request_id: str,
        base_url: str,
        operation: str,
    ) -> Any:
        """Validate and unwrap a response envelope from a remote peer."""
        message_id = response.get("id")
        if message_id not in {None, request_id}:
            raise TransportProtocolError(
                f"Mismatched gRPC {operation} id from {base_url}: {message_id}",
                url=base_url,
                request_id=request_id,
            )

        if not response.get("ok", False):
            error = response.get("error") or {}
            raise TransportRemoteError(
                f"gRPC {operation} failed at {base_url}: {error}",
                url=base_url,
                request_id=request_id,
            )

        return response.get("result")

    def _error_response(
        self,
        request_id: str | None,
        exc: Exception,
        *,
        final: bool = False,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build a protocol-level error envelope for handler exceptions."""
        response: dict[str, Any] = {
            "id": request_id,
            "ok": False,
            "error": {"message": str(exc), "type": exc.__class__.__name__},
        }
        if final:
            response["final"] = True
        if stream:
            response["stream"] = True
        return response

    async def _setup_operational_services(self) -> None:
        """Register standard gRPC health and reflection services when installed."""
        if self._server is None or (not self._enable_health and not self._enable_reflection):
            return
        try:
            from grpc_health.v1 import health, health_pb2_grpc
            from grpc_reflection.v1alpha import reflection
        except ImportError:
            return

        service_names = [self._SERVICE_NAME]
        if self._enable_health:
            health_api = getattr(health, "aio", health)
            self._health_servicer = health_api.HealthServicer()
            health_pb2_grpc.add_HealthServicer_to_server(self._health_servicer, self._server)
            service_names.append("grpc.health.v1.Health")
            await self._set_health_status(serving=True)
        if self._enable_reflection:
            service_names.append(reflection.SERVICE_NAME)
            reflection.enable_server_reflection(tuple(service_names), self._server)

    async def _set_health_status(self, *, serving: bool) -> None:
        """Update standard gRPC health status for all exposed service names."""
        if self._health_servicer is None:
            return
        try:
            from grpc_health.v1 import health_pb2
        except ImportError:
            return
        status = health_pb2.HealthCheckResponse.SERVING if serving else health_pb2.HealthCheckResponse.NOT_SERVING
        for service_name in ("", self._SERVICE_NAME):
            result = self._health_servicer.set(service_name, status)
            if inspect.isawaitable(result):
                await result

    @staticmethod
    def _merge_options(
        defaults: tuple[tuple[str, Any], ...],
        overrides: list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None,
    ) -> tuple[tuple[str, Any], ...]:
        """Merge gRPC options while giving explicit caller values precedence."""
        merged = dict(defaults)
        merged.update(dict(overrides or ()))
        return tuple(merged.items())

    # ------------------------------------------------------------------
    # Authentication and channels
    # ------------------------------------------------------------------

    async def _authenticate_context(self, context: Any) -> None:
        """Validate inbound metadata with the configured authenticator."""
        if not self.authenticator:
            return

        metadata = self._metadata_as_pairs(context.invocation_metadata())
        credentials = extract_credentials(metadata)
        if not credentials:
            await context.abort(self._grpc.StatusCode.UNAUTHENTICATED, "Missing credentials")
            return

        try:
            await self.authenticator.authenticate(credentials)
        except Exception as exc:
            await context.abort(self._grpc.StatusCode.UNAUTHENTICATED, f"Authentication failed: {exc}")

    def _build_metadata(self, context: TransportRequestContext) -> tuple[tuple[str, str], ...]:
        """Build lowercase gRPC metadata from the active security context."""
        metadata = [(key.lower(), value) for key, value in self._build_headers().items()]
        metadata.append(("x-protolink-request-id", context.request_id))
        if context.idempotency_key:
            metadata.append(("idempotency-key", context.idempotency_key))
        return tuple(metadata)

    def _build_headers(self) -> dict[str, str]:
        """Construct authentication headers shared with other network transports."""
        headers: dict[str, str] = {}
        if self.authenticator and self.security_context:
            token = getattr(self.security_context, "token", None)
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

    async def _ensure_channel(self, base_url: str) -> Any:
        """Return a loop-local gRPC channel for the target URL."""
        target = self._target_from_url(base_url)
        secure = self._is_secure_url(base_url)
        key = (target, secure, id(asyncio.get_running_loop()))
        channel = self._channels.get(key)
        if channel is None:
            if secure:
                root_certificates = self.tls.ca_bytes() if self.tls is not None else None
                private_key = self.tls.private_key_bytes() if self.tls is not None else None
                certificate_chain = self.tls.certificate_chain_bytes() if self.tls is not None else None
                credentials = self._grpc.ssl_channel_credentials(
                    root_certificates=root_certificates,
                    private_key=private_key,
                    certificate_chain=certificate_chain,
                )
                channel = self._grpc.aio.secure_channel(
                    target,
                    credentials,
                    options=self._channel_options,
                    compression=self._compression,
                )
            else:
                channel = self._grpc.aio.insecure_channel(
                    target,
                    options=self._channel_options,
                    compression=self._compression,
                )
            self._channels[key] = channel

            async def close_channel() -> None:
                await channel.close(grace=1.0)
                self._channels.pop(key, None)

            self.register_loop_resource(("grpc", key), close_channel)
        return channel

    @staticmethod
    def _metadata_as_pairs(metadata: Any) -> list[tuple[str, str]]:
        """Normalize grpcio metadata objects into header-like pairs."""
        pairs: list[tuple[str, str]] = []
        for item in metadata or ():
            key = getattr(item, "key", None)
            value = getattr(item, "value", None)
            if key is None:
                try:
                    key, value = item
                except (TypeError, ValueError):
                    continue
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            pairs.append((str(key), str(value)))
        return pairs

    def _raise_rpc_error(self, exc: Any, base_url: str, *, operation: str, request_id: str) -> NoReturn:
        """Translate grpcio exceptions into Protolink-style client errors."""
        code = exc.code()
        details = exc.details()
        if code == self._grpc.StatusCode.UNAVAILABLE:
            raise TransportConnectionError(
                f"Failed to connect to agent at {base_url}. Make sure the gRPC agent is running and accessible.",
                url=base_url,
                request_id=request_id,
                retryable=True,
            ) from exc
        if code == self._grpc.StatusCode.DEADLINE_EXCEEDED:
            raise TransportTimeoutError(
                f"gRPC {operation} to {base_url} exceeded {self._timeout} seconds",
                url=base_url,
                request_id=request_id,
                retryable=True,
            ) from exc
        raise TransportRemoteError(
            f"gRPC {operation} failed at {base_url}: {code.name}: {details}",
            url=base_url,
            request_id=request_id,
            retryable=code in {self._grpc.StatusCode.RESOURCE_EXHAUSTED, self._grpc.StatusCode.INTERNAL},
            status_code=code.name,
        ) from exc

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def validate_url(self) -> bool:
        """Return whether the URL uses ``grpc://`` or secure ``grpcs://``."""
        return self._url.startswith("grpc://") or self._url.startswith("grpcs://")

    @property
    def url(self) -> str:
        """The configured gRPC endpoint URL."""
        return self._url

    @property
    def timeout(self) -> float:
        """The outbound gRPC deadline in seconds."""
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        """Update the outbound gRPC deadline for future calls."""
        self._timeout = value

    @property
    def is_running(self) -> bool:
        """Whether the transport currently owns a running gRPC server."""
        return self._is_running

    @staticmethod
    def _get_host_port(url: str) -> tuple[str | None, int | None]:
        """Parse a ``grpc://`` or ``grpcs://`` URL into ``(host, port)``."""
        parsed = urlparse(url.rstrip("/"))
        return parsed.hostname, parsed.port

    @staticmethod
    def _target_from_url(url: str) -> str:
        """Convert a ProtoLink gRPC URL into the grpcio ``host:port`` target."""
        parsed = urlparse(url.rstrip("/"))
        if parsed.scheme:
            if parsed.scheme not in {"grpc", "grpcs"}:
                raise ValueError(f"Unsupported gRPC URL scheme: {parsed.scheme}")
            if not parsed.hostname or parsed.port is None:
                raise ValueError(f"Invalid gRPC URL: {url}. Expected grpc://host:port or grpcs://host:port.")
            return f"{parsed.hostname}:{parsed.port}"
        return url

    @staticmethod
    def _is_secure_url(url: str) -> bool:
        """Return whether a gRPC URL requests TLS."""
        return urlparse(url.rstrip("/")).scheme.lower() == "grpcs"
