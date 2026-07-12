"""Starlette transport backend for Protolink agents.

This module provides the :class:`StarletteBackend`, utilizing the lightweight Starlette framework
to construct fast, minimalistic ASGI-compliant web servers. It is the default backend due to its
zero-overhead footprint and robust async routing capabilities.
"""

import asyncio
import inspect
import json
from typing import TYPE_CHECKING, Any

from protolink.security.tls import TLSConfig
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport._deps import _require_starlette
from protolink.transport._streaming import is_stream_terminal_event
from protolink.transport.backends.base import BackendInterface
from protolink.utils.inspect import is_async_callable

if TYPE_CHECKING:
    from protolink.transport.base import Transport


class StarletteBackend(BackendInterface):
    def __init__(
        self,
        *,
        log_level: str = "info",
        access_log: bool = True,
        keepalive_timeout: float = 20.0,
        limit_concurrency: int = 100,
    ) -> None:
        Starlette, _, _, _, _ = _require_starlette()  # noqa: N806

        self.app = Starlette()
        self._server_task: asyncio.Task | None = None
        self._server_instance: Any = None
        self._log_level = log_level
        self._access_log = access_log
        self._keepalive_timeout = keepalive_timeout
        self._limit_concurrency = limit_concurrency

    # ----------------------------------------------------------------------
    # Setup Routes - Define Server URIs
    # ----------------------------------------------------------------------

    def _register_endpoint(
        self,
        ep: EndpointSpec,
        authenticator: Any = None,
        transport: "Transport | None" = None,
    ) -> None:
        _, Request, JSONResponse, HTMLResponse, StreamingResponse = _require_starlette()  # noqa: N806

        async def route(request: Request):
            # -------------------------
            # Authenticate request
            # -------------------------
            if authenticator and ep.path not in {"/healthz", "/readyz"}:
                from protolink.security.auth import extract_credentials

                credentials = extract_credentials(request.headers, dict(request.query_params))
                if not credentials:
                    return JSONResponse({"error": "Missing credentials"}, status_code=401)
                try:
                    await authenticator.authenticate(credentials)
                except Exception as e:
                    return JSONResponse({"error": f"Authentication failed: {e}"}, status_code=401)

            # -------------------------
            # Extract raw payload
            # -------------------------
            if ep.request_source == "body":
                try:
                    payload = await request.json()
                except json.JSONDecodeError:
                    payload = None
            elif ep.request_source == "query_params":
                payload = dict(request.query_params)
            else:
                payload = None

            if transport is not None:
                transport.check_payload_limit(payload, kind="request", url=str(request.url))

            # -------------------------
            # Parse payload
            # -------------------------
            if ep.request_parser:
                handler_input = (
                    await ep.request_parser(payload)
                    if is_async_callable(ep.request_parser)
                    else ep.request_parser(payload)
                )
            else:
                handler_input = payload

            if ep.mode == "stream" or ep.streaming:
                request_id = request.headers.get("x-protolink-request-id")
                return StreamingResponse(
                    self._stream_sse(
                        ep=ep,
                        handler_input=handler_input,
                        payload=payload,
                        request_id=request_id,
                        transport=transport,
                    ),
                    media_type="text/event-stream",
                    headers={"X-Protolink-Request-ID": request_id or ""},
                )

            raw_idempotency_key = request.headers.get("idempotency-key")
            idempotency_key = f"{ep.method}:{ep.path}:{raw_idempotency_key}" if raw_idempotency_key else None
            if transport is not None:
                owns_operation, cached = await transport.acquire_idempotent_response(idempotency_key)
                if not owns_operation:
                    return JSONResponse(
                        cached,
                        headers={"X-Protolink-Request-ID": request.headers.get("x-protolink-request-id", "")},
                    )

            # -------------------------
            # Call handler
            # -------------------------
            handler_is_async = is_async_callable(ep.handler)

            try:
                if ep.request_source != "none" and payload is not None:
                    result = await ep.handler(handler_input) if handler_is_async else ep.handler(handler_input)
                else:
                    result = await ep.handler() if handler_is_async else ep.handler()
            except BaseException as exc:
                if transport is not None:
                    transport.abort_idempotent_response(idempotency_key, exc)
                raise

            # -------------------------
            # Response
            # -------------------------
            if ep.content_type == "html":
                return HTMLResponse(result)

            serialized_result = self._serialize_result(result)
            if transport is not None:
                transport.check_payload_limit(serialized_result, kind="response", url=str(request.url))
                transport.complete_idempotent_response(idempotency_key, serialized_result)
            return JSONResponse(
                serialized_result,
                headers={"X-Protolink-Request-ID": request.headers.get("x-protolink-request-id", "")},
            )

        self.app.add_route(ep.path, route, methods=[ep.method])

    async def _stream_sse(
        self,
        *,
        ep: EndpointSpec,
        handler_input: Any,
        payload: Any,
        request_id: str | None,
        transport: "Transport | None" = None,
    ):
        """Yield JSON-RPC envelopes as Server-Sent Events.

        Streaming endpoint handlers return async iterators of Protolink events.
        The backend serializes each event into a JSON-RPC-style SSE envelope so
        HTTP clients can consume the same task stream shape as WebSocket clients.
        """
        try:
            if ep.request_source != "none" and payload is not None:
                stream_obj = ep.handler(handler_input)
            else:
                stream_obj = ep.handler()

            if inspect.isawaitable(stream_obj):
                stream_obj = await stream_obj

            if not hasattr(stream_obj, "__aiter__"):
                raise TypeError("Streaming endpoint handler must return an async iterator")

            sent_final = False
            async for event in stream_obj:
                event_payload = self._serialize_result(event)
                if transport is not None:
                    transport.check_payload_limit(event_payload, kind="event")
                event_final = bool(event_payload.get("final", False)) if isinstance(event_payload, dict) else False
                stream_final = is_stream_terminal_event(event_payload, event_final=event_final)
                yield self._sse_frame(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "ok": True,
                        "result": event_payload,
                        "final": stream_final,
                    }
                )
                if stream_final:
                    sent_final = True
                    break

            if not sent_final:
                yield self._sse_frame({"jsonrpc": "2.0", "id": request_id, "ok": True, "result": None, "final": True})
        except Exception as exc:
            yield self._sse_frame(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "ok": False,
                    "error": {"message": str(exc), "type": exc.__class__.__name__},
                    "final": True,
                }
            )

    def _sse_frame(self, payload: dict[str, Any]) -> str:
        """Serialize a JSON payload as a single Server-Sent Event frame."""
        return f"data: {json.dumps(payload)}\n\n"

    def setup_routes(
        self,
        endpoints: list[EndpointSpec],
        authenticator: Any = None,
        transport: "Transport | None" = None,
    ) -> None:
        """Mount abstract Protolink endpoints as physical Starlette routes.

        This method serves as the architectural bridge between Protolink's `EndpointSpec` definitions
        and the Starlette routing engine. It dynamically constructs asynchronous endpoint handlers
        capable of extracting raw JSON body payloads, invoking domain logic, and transmitting
        `JSONResponse` objects back over the wire.
        """
        for ep in endpoints:
            self._register_endpoint(ep, authenticator=authenticator, transport=transport)

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

    async def start(self, url: str, tls: TLSConfig | None = None) -> None:
        """Boot the Uvicorn ASGI server as an isolated background task.

        Extracts the host and port from the provided URL, instantiates a programmatic Uvicorn
        `Server` instance, and schedules it within the current asyncio event loop. To prevent
        race conditions during agent startup, it actively polls `server.started` to ensure the
        TCP socket is bound before yielding control.
        """
        import uvicorn

        host, port = self._get_host_port(url)
        if not host or not port:
            raise ValueError(f"Invalid URL: {url}. Missing host or port.")
        config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level=self._log_level,
            access_log=self._access_log,
            limit_concurrency=self._limit_concurrency,
            timeout_keep_alive=int(self._keepalive_timeout),
            **self._uvicorn_tls_kwargs(url, tls),
        )
        server = uvicorn.Server(config)

        self._server_instance = server
        self._server_task = asyncio.create_task(server.serve())

        while not server.started:
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        """Gracefully orchestrate Uvicorn server teardown.

        Injects the `should_exit` signal directly into the Uvicorn state machine to initiate a
        graceful draining of active connections. It then synchronously `await`s the server's
        background task, suppressing `CancelledError` exceptions to ensure a clean exit.
        """
        if self._server_instance:
            self._server_instance.should_exit = True

        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            finally:
                self._server_task = None
                self._server_instance = None
