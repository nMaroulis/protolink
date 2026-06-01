"""FastAPI transport backend for Protolink agents.

This module provides the :class:`FastAPIBackend`, utilizing the FastAPI framework to construct
highly validated, ASGI-compliant web servers. It translates abstract agent endpoints into native
FastAPI routes, optionally leveraging Pydantic schema generation.
"""

import asyncio
import json
from typing import Any

from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport._deps import _require_fastapi
from protolink.transport.backends.base import BackendInterface
from protolink.utils.inspect import is_async_callable


class FastAPIBackend(BackendInterface):
    def __init__(self, *, validate_schema: bool = False) -> None:
        FastAPI, _, _, _, _ = _require_fastapi(validate_schema=validate_schema)  # noqa: N806

        self.app = FastAPI()
        self._server_task: asyncio.Task | None = None
        self._server_instance: Any = None

    # ----------------------------------------------------------------------
    # Setup Routes - Define Server URIs
    # ----------------------------------------------------------------------

    def _register_endpoint(self, ep: EndpointSpec, authenticator: Any = None) -> None:
        _, Request, JSONResponse, HTMLResponse, _ = _require_fastapi()  # noqa: N806

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

    async def start(self, url: str) -> None:
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

        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
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

    # ----------------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------------

    def _serialize_result(self, result):
        """Recursively normalize rich domain models into strictly JSON-compatible structures.

        FastAPI's native `JSONResponse` requires purely dict/list primitives. This utility ensures
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
