"""Starlette-based HTTP backend used by :class:`HTTPAgentTransport`.

This module provides a concrete implementation of :class:`BackendInterface`
backed by a Starlette application. It is responsible for wiring HTTP
endpoints to the transport's internal task handler and for managing the
underlying ASGI server lifecycle.
"""

import asyncio
from typing import Any

from protolink.core.task import Task
from protolink.models import EndpointSpec
from protolink.transport._deps import _require_starlette
from protolink.transport.agent.backends.base import BackendInterface


class StarletteBackend(BackendInterface):
    """Starlette implementation of :class:`BackendInterface`.

    A lightweight alternative to the FastAPI backend that exposes the same
    `/tasks/` endpoint but without Pydantic-based request validation.
    """

    def __init__(self) -> None:
        Starlette, _, _, _ = _require_starlette()  # noqa: N806

        self.app = Starlette()
        self._server_task: asyncio.Task[None] | None = None
        self._server_instance: Any = None

    # ----------------------------------------------------------------------
    # Setup Routes - Define Agent Server URIs
    # ----------------------------------------------------------------------

    def _register_endpoint(self, ep: EndpointSpec) -> None:
        _, Request, JSONResponse, HTMLResponse = _require_starlette()  # noqa: N806

        async def route(request: Request):
            if ep.method == "POST":
                payload = await request.json() if ep.is_async else request.json()
                result = (
                    await ep.handler(Task.from_dict(payload)) if ep.is_async else ep.handler(Task.from_dict(payload))
                )
            else:
                result = await ep.handler() if ep.is_async else ep.handler()

            if ep.content_type == "html":
                return HTMLResponse(result)
            return JSONResponse(result.to_json())

        self.app.add_route(ep.path, route, methods=[ep.method])

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Register all HTTP routes on the Starlette application.

        This method wires the public HTTP API to the internal agent handlers.
        Each route is registered via a dedicated helper for clarity and separation of concerns.
        """
        for ep in endpoints:
            self._register_endpoint(ep)

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

    async def start(self, host: str, port: int) -> None:
        """Start the Starlette-backed HTTP server.

        Parameters
        ----------
        host:
            Host interface for the underlying ASGI server to bind to.
        port:
            Port for the underlying ASGI server to listen on.
        """

        import uvicorn

        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        self._server_instance = server
        self._server_task = asyncio.create_task(server.serve())

        while not server.started:
            if self._server_task.done():
                break
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        """Stop the Starlette-backed HTTP server and clean up resources."""

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
