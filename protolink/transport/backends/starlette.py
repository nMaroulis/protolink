"""Starlette transport backend for Protolink agents.

This module provides the :class:`StarletteBackend`, utilizing the lightweight Starlette framework
to construct fast, minimalistic ASGI-compliant web servers. It is the default backend due to its
zero-overhead footprint and robust async routing capabilities.
"""

import asyncio
import json
from typing import Any

from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport._deps import _require_starlette
from protolink.transport.backends.base import BackendInterface
from protolink.utils.inspect import is_async_callable


class StarletteBackend(BackendInterface):
    def __init__(self) -> None:
        Starlette, _, _, _ = _require_starlette()  # noqa: N806

        self.app = Starlette()
        self._server_task: asyncio.Task | None = None
        self._server_instance: Any = None

    # ----------------------------------------------------------------------
    # Setup Routes - Define Server URIs
    # ----------------------------------------------------------------------

    def _register_endpoint(self, ep: EndpointSpec, authenticator: Any = None) -> None:
        _, Request, JSONResponse, HTMLResponse = _require_starlette()  # noqa: N806

        async def route(request: Request):
            # -------------------------
            # Authenticate request
            # -------------------------
            if authenticator:
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

            # -------------------------
            # Call handler
            # -------------------------
            handler_is_async = is_async_callable(ep.handler)

            if ep.request_source != "none" and payload is not None:
                result = await ep.handler(handler_input) if handler_is_async else ep.handler(handler_input)
            else:
                result = await ep.handler() if handler_is_async else ep.handler()

            # -------------------------
            # Response
            # -------------------------
            if ep.content_type == "html":
                return HTMLResponse(result)

            serialized_result = self._serialize_result(result)
            return JSONResponse(serialized_result)

        self.app.add_route(ep.path, route, methods=[ep.method])

    def setup_routes(self, endpoints: list[EndpointSpec], authenticator: Any = None) -> None:
        """Mount abstract Protolink endpoints as physical Starlette routes.

        This method serves as the architectural bridge between Protolink's `EndpointSpec` definitions
        and the Starlette routing engine. It dynamically constructs asynchronous endpoint handlers
        capable of extracting raw JSON body payloads, invoking domain logic, and transmitting
        `JSONResponse` objects back over the wire.
        """
        for ep in endpoints:
            self._register_endpoint(ep, authenticator=authenticator)

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

    async def start(self, url: str) -> None:
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
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
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

    # ----------------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------------

    def _serialize_result(self, result):
        """Recursively normalize rich domain models into strictly JSON-compatible structures.

        Starlette's native `JSONResponse` requires purely dict/list primitives. This utility ensures
        that Protolink `BaseModel`s, DataClasses, or arbitrary nested lists are aggressively flattened
        prior to final response dispatch.
        """
        if hasattr(result, "to_json"):
            return result.to_json()
        elif hasattr(result, "to_dict"):
            return result.to_dict()
        elif hasattr(result, "model_dump"):
            return result.model_dump()
        elif isinstance(result, list):
            return [self._serialize_result(item) for item in result]
        else:
            return result
