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
    """

    transport_type: ClassVar[TransportType] = "websocket"
    supports_streaming: ClassVar[bool] = True

    def __init__(
        self,
        url: str,
        timeout: float = 30.0,
        authenticator: Authenticator | None = None,
    ) -> None:
        self._url = url
        self.timeout = timeout
        self.authenticator = authenticator
        self.security_context: Any | None = None

        self._endpoints: dict[tuple[str, str], EndpointSpec] = {}
        self._server: Any | None = None

        self._client_conns: dict[str, Any] = {}
        self._client_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Server routing
    # ------------------------------------------------------------------

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register server endpoints.

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
        """Start a WebSocket server at ``self.url``."""
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
        """Send a request to a remote endpoint and return the parsed response."""
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

        lock = self._client_locks.setdefault(base_url, asyncio.Lock())
        async with lock:
            conn = await self._ensure_client_connection(base_url)
            try:
                await conn.send(json.dumps(payload))
                raw = await asyncio.wait_for(conn.recv(), timeout=self.timeout)
            except ConnectionClosed as e:
                self._client_conns.pop(base_url, None)
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
        """Subscribe to task events from a remote agent.

        This sends a POST request to ``/tasks/stream`` and yields each streamed
        event frame until the server marks the stream as final.
        """
        message_id = uuid.uuid4().hex

        payload: dict[str, Any] = {
            "id": message_id,
            "method": "POST",
            "path": "/tasks/stream",
            "data": self._serialize_result(task),
        }

        lock = self._client_locks.setdefault(agent_url, asyncio.Lock())
        async with lock:
            conn = await self._ensure_client_connection(agent_url)
            try:
                await conn.send(json.dumps(payload))
                while True:
                    raw = await asyncio.wait_for(conn.recv(), timeout=self.timeout)
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
                self._client_conns.pop(agent_url, None)
                raise ConnectionError(f"WebSocket connection closed while streaming from {agent_url}") from e

    async def _ensure_client_connection(self, base_url: str) -> Any:
        """Get or create a cached client WebSocket connection for ``base_url``."""
        existing = self._client_conns.get(base_url)
        if existing is not None and not getattr(existing, "closed", False):
            return existing

        headers = self._build_headers()
        try:
            conn = await websockets.connect(base_url, additional_headers=headers)
        except TypeError:
            conn = await websockets.connect(base_url, extra_headers=headers)
        self._client_conns[base_url] = conn
        return conn

    # ------------------------------------------------------------------
    # Authentication & Security
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: str) -> None:
        """Authenticate using the configured authenticator and store a security context."""
        if not self.authenticator:
            raise RuntimeError("No Authenticator configured")
        self.security_context = await self.authenticator.authenticate(credentials)

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP-style headers used during the WebSocket handshake."""
        headers: dict[str, str] = {}
        if self.authenticator and self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"
        return headers

    # ------------------------------------------------------------------
    # Server internals
    # ------------------------------------------------------------------

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a single inbound WebSocket connection."""
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
        """Serialize common model types into JSON-compatible structures."""
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
