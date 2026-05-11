from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urlparse

from pydantic import BaseModel

from protolink.client.request_spec import ClientRequestSpec
from protolink.security.auth import Authenticator
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport.base import Transport
from protolink.types import TransportType
from protolink.utils.inspect import is_async_callable

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
    """

    transport_type: ClassVar[TransportType] = "websocket"
    supports_streaming: ClassVar[bool] = True

    def __init__(
        self,
        url: str,
        timeout: float = 60.0,
        authenticator: Authenticator | None = None,
    ) -> None:
        self._url: str = url
        self._timeout: float = timeout
        self.authenticator: Authenticator | None = authenticator
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
        self._endpoints = {(ep.method, ep.path): ep for ep in endpoints}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spin up the native `websockets` daemon on the specified interface.

        This instantiates an ``asyncio`` background task running the ``websockets.serve``
        lifecycle. Once bound to the designated port, all inbound TCP connections are immediately
        funneled directly into the ``_handle_connection`` multiplexer.
        """
        host, port = self._get_host_port(self._url)
        if not host or not port:
            raise ValueError(f"Invalid URL: {self._url}. Missing host or port.")

        self._server = await websockets.serve(self._handle_connection, host=host, port=port)

    async def stop(self) -> None:
        """Stop the WebSocket server and close any cached client connections."""
        for conn in list(self._client_conns.values()):
            try:
                await conn.close()
            except Exception:
                pass
        self._client_conns.clear()
        self._client_locks.clear()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

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
        message_id = uuid.uuid4().hex

        payload: dict[str, Any] = {
            "id": message_id,
            "method": request_spec.method,
            "path": request_spec.path,
        }

        if request_spec.request_source == "body" and data is not None:
            payload["data"] = self._serialize_result(data)
        elif request_spec.request_source == "query_params" and data is not None:
            if isinstance(data, dict):
                payload["params"] = data
            else:
                payload["params"] = {"data": str(data)}

        if params:
            payload.setdefault("params", {})
            payload["params"].update(params)

        loop_key = f"{base_url}_{id(asyncio.get_running_loop())}"
        lock = self._client_locks.setdefault(loop_key, asyncio.Lock())
        async with lock:
            conn = await self._ensure_client_connection(base_url, loop_key)
            try:
                await conn.send(json.dumps(payload))
                raw = await asyncio.wait_for(conn.recv(), timeout=self._timeout)
            except ConnectionClosed as e:
                self._client_conns.pop(loop_key, None)
                raise ConnectionError(f"WebSocket connection closed while talking to {base_url}") from e

        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")

        try:
            response = json.loads(raw)
        except Exception as e:
            raise RuntimeError(f"Invalid JSON response from {base_url}: {raw!r}") from e

        if response.get("id") != message_id:
            raise RuntimeError(f"Mismatched response id from {base_url}: {response.get('id')}")

        if not response.get("ok", False):
            err = response.get("error") or {}
            raise RuntimeError(f"WebSocket request failed at {base_url}: {err}")

        result = response.get("result")
        if request_spec.response_parser:
            return request_spec.response_parser(result)
        return result

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        """Establish an asynchronous streaming pipeline over a persistent WebSocket connection.

        Designed for heavy workloads (like streaming agent thought processes or task progression),
        this pushes a ``/tasks/stream`` payload with a unique ``message_id``. It then continuously
        polls the loop-isolated socket, yielding deserialized chunks back to the caller as an
        ``AsyncIterator``. The pipeline automatically terminates when the remote server sends a
        frame tagged with ``final=True``.
        """
        message_id = uuid.uuid4().hex

        payload: dict[str, Any] = {
            "id": message_id,
            "method": "POST",
            "path": "/tasks/stream",
            "data": self._serialize_result(task),
        }

        loop_key = f"{agent_url}_{id(asyncio.get_running_loop())}"
        lock = self._client_locks.setdefault(loop_key, asyncio.Lock())
        async with lock:
            conn = await self._ensure_client_connection(agent_url, loop_key)
            try:
                await conn.send(json.dumps(payload))
                while True:
                    raw = await asyncio.wait_for(conn.recv(), timeout=self._timeout)
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="replace")

                    try:
                        msg = json.loads(raw)
                    except Exception as e:
                        raise RuntimeError(f"Invalid JSON stream message from {agent_url}: {raw!r}") from e

                    if msg.get("id") != message_id:
                        raise RuntimeError(f"Mismatched stream id from {agent_url}: {msg.get('id')}")

                    if not msg.get("ok", False):
                        err = msg.get("error") or {}
                        raise RuntimeError(f"WebSocket stream failed at {agent_url}: {err}")

                    result = msg.get("result")
                    if result is not None:
                        yield result

                    if msg.get("final", False):
                        break
            except ConnectionClosed as e:
                self._client_conns.pop(loop_key, None)
                raise ConnectionError(f"WebSocket connection closed while streaming from {agent_url}") from e

    async def _ensure_client_connection(self, base_url: str, loop_key: str) -> Any:
        """Get or create a cached client WebSocket connection for ``base_url``.

        This method utilizes a ``loop_key`` (incorporating the current ``asyncio`` event
        loop ID) to lazily instantiate and cache persistent websocket connections per event
        loop. This strict isolation ensures that concurrent requests made from the main
        thread and the background server thread do not share underlying websocket primitives,
        thereby completely eliminating `Future attached to a different loop` exceptions.
        """
        existing = self._client_conns.get(loop_key)
        if existing is not None and not getattr(existing, "closed", False):
            return existing

        headers = self._build_headers()
        try:
            conn = await websockets.connect(base_url, additional_headers=headers)
        except TypeError:
            conn = await websockets.connect(base_url, extra_headers=headers)
        self._client_conns[loop_key] = conn
        return conn

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
        """Compile the HTTP upgrade headers required for the WebSocket handshake.

        If authentication is configured, this securely injects the ``Authorization: Bearer <token>``
        header into the initial HTTP GET request that is used to upgrade the connection to the
        WebSocket protocol.
        """
        headers: dict[str, str] = {}
        if self.authenticator and self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"
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
        async for raw in websocket:
            response: dict[str, Any]
            req: Any = None
            try:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="replace")
                req = json.loads(raw)
                request_id = req.get("id")
                method = req.get("method")
                path = req.get("path")

                if not request_id or not method or not path:
                    raise ValueError("Missing required fields: id/method/path")

                ep = self._endpoints.get((method, path))
                if ep is None:
                    raise ValueError(f"No endpoint registered for {method} {path}")

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
                    if ep.request_source != "none" and payload is not None:
                        stream_obj = ep.handler(handler_input)
                    else:
                        stream_obj = ep.handler()

                    if inspect.isawaitable(stream_obj):
                        stream_obj = await stream_obj

                    if not hasattr(stream_obj, "__aiter__"):
                        raise TypeError("Streaming handler must return an async iterator")

                    sent_final = False
                    async for event in stream_obj:
                        event_payload = self._serialize_result(event)
                        final = False
                        if isinstance(event_payload, dict):
                            final = bool(event_payload.get("final", False))
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": request_id,
                                    "ok": True,
                                    "result": event_payload,
                                    "final": final,
                                    "stream": True,
                                }
                            )
                        )
                        if final:
                            sent_final = True
                            break

                    if not sent_final:
                        await websocket.send(
                            json.dumps({"id": request_id, "ok": True, "result": None, "final": True, "stream": True})
                        )
                    continue

                if ep.request_source != "none" and payload is not None:
                    result = await ep.handler(handler_input) if handler_is_async else ep.handler(handler_input)
                else:
                    result = await ep.handler() if handler_is_async else ep.handler()

                response = {"id": request_id, "ok": True, "result": self._serialize_result(result)}
            except Exception as e:
                response = {
                    "id": req.get("id") if isinstance(req, dict) else None,
                    "ok": False,
                    "error": {"message": str(e), "type": e.__class__.__name__},
                }

                if isinstance(req, dict) and req.get("path") == "/tasks/stream":
                    response["final"] = True

            await websocket.send(json.dumps(response))

    def _serialize_result(self, result: Any) -> Any:
        """Recursively normalize complex data models into JSON-safe structures.

        Since websockets mandate purely text-based (or binary) JSON payloads, this utility ensures
        that rich domain models (like Pydantic ``BaseModel``, custom DataClasses, or nested lists)
        are aggressively flattened into basic Python dictionaries prior to `json.dumps()` serialization.
        """
        if hasattr(result, "to_json"):
            return result.to_json()
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, BaseModel):
            return result.model_dump()
        if isinstance(result, list):
            return [self._serialize_result(item) for item in result]
        return result

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
