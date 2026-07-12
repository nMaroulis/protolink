"""FastAPI transport backend for Protolink agents.

This module provides the :class:`FastAPIBackend`, utilizing the FastAPI framework to construct
highly validated, ASGI-compliant web servers. It translates abstract agent endpoints into native
FastAPI routes, optionally leveraging Pydantic schema generation.
"""

import asyncio
import inspect
import json
from typing import Any

from protolink.security.tls import TLSConfig
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport._deps import _require_fastapi
from protolink.transport.backends.base import BackendInterface
from protolink.utils.inspect import is_async_callable


class FastAPIBackend(BackendInterface):
    def __init__(self, *, validate_schema: bool = False, log_level: str = "info", access_log: bool = True) -> None:
        FastAPI, _, _, _, _, _ = _require_fastapi(validate_schema=validate_schema)  # noqa: N806

        self.app = FastAPI()
        self._server_task: asyncio.Task | None = None
        self._server_instance: Any = None
        self._log_level = log_level
        self._access_log = access_log

    # ----------------------------------------------------------------------
    # Setup Routes - Define Server URIs
    # ----------------------------------------------------------------------

    def _register_endpoint(self, ep: EndpointSpec, authenticator: Any = None) -> None:
        _, Request, JSONResponse, HTMLResponse, StreamingResponse, _ = _require_fastapi()  # noqa: N806

        async def route(request: Request):
            # -------------------------
            # Authenticate request
            # -------------------------
            if authenticator:
                from protolink.security.auth import extract_credentials

                credentials = extract_credentials(request.headers, dict(request.query_params))
                if not credentials:
                    return JSONResponse(status_code=401, content={"error": "Missing credentials"})
                try:
                    await authenticator.authenticate(credentials)
                except Exception as e:
                    return JSONResponse(status_code=401, content={"error": f"Authentication failed: {e}"})

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
                    ),
                    media_type="text/event-stream",
                )

            # -------------------------
            # Call handler
            # -------------------------
            handler_is_async = is_async_callable(ep.handler)

            if ep.request_source != "none":
                result = await ep.handler(handler_input) if handler_is_async else ep.handler(handler_input)
            else:
                result = await ep.handler() if handler_is_async else ep.handler()

            # -------------------------
            # Response
            # -------------------------
            if ep.content_type == "html":
                return HTMLResponse(content=result)

            serialized_result = self._serialize_result(result)
            return JSONResponse(content=serialized_result)

        self.app.add_api_route(
            ep.path,
            route,
            methods=[ep.method],
        )

    async def _stream_sse(self, *, ep: EndpointSpec, handler_input: Any, payload: Any, request_id: str | None):
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
                final = bool(event_payload.get("final", False)) if isinstance(event_payload, dict) else False
                yield self._sse_frame(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "ok": True,
                        "result": event_payload,
                        "final": final,
                    }
                )
                if final:
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

    def setup_routes(self, endpoints: list[EndpointSpec], authenticator: Any = None) -> None:
        """Mount abstract Protolink endpoints as physical FastAPI routes.

        This method acts as the architectural bridge between Protolink's internal `EndpointSpec`
        definitions and the external ASGI routing engine. It dynamically constructs asynchronous
        HTTP handlers capable of extracting JSON payloads, validating them (if enabled), and
        marshaling the result back over the wire via FastAPI's `JSONResponse`.
        """
        for ep in endpoints:
            self._register_endpoint(ep, authenticator=authenticator)

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

    async def start(self, url: str, tls: TLSConfig | None = None) -> None:
        """Boot the Uvicorn ASGI server as an isolated background task.

        Extracts the host and port from the provided URL, instantiates a programmatic Uvicorn
        `Server` instance, and schedules it within the current asyncio event loop. To prevent
        race conditions, it actively polls `server.started` to ensure the TCP socket is bound
        before yielding control back to the caller.
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
            **self._uvicorn_tls_kwargs(url, tls),
        )
        server = uvicorn.Server(config)

        self._server_instance = server
        self._server_task = asyncio.create_task(server.serve())

        while not server.started:
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        """Gracefully orchestrate Uvicorn server teardown.

        Injects the `should_exit` signal directly into the Uvicorn state machine, triggering a
        graceful draining of active connections. It then safely `await`s the server's background
        task to prevent orphaned processes and suppresses any expected `CancelledError` exceptions.
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
