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

    def _register_endpoint(self, ep: EndpointSpec) -> None:
        _, Request, JSONResponse, HTMLResponse, _ = _require_fastapi()  # noqa: N806

        async def route(request: Request):
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

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register all HTTP routes on the FastAPI application.

        This method wires the public HTTP API to the internal handlers.
        Each route is registered via a dedicated helper for clarity and
        parity with the Starlette backend.
        """
        for ep in endpoints:
            self._register_endpoint(ep)

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

    async def start(self, url: str) -> None:
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
        """Auto-serialize models or objects."""
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
