"""Starlette-based HTTP backend used by :class:`HTTPAgentTransport`.

This module provides a concrete implementation of :class:`BackendInterface`
backed by a Starlette application. It is responsible for wiring HTTP
endpoints to the transport's internal task handler and for managing the
underlying ASGI server lifecycle.
"""

import asyncio
from typing import Any

from protolink.core.task import Task
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

    def setup_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register all HTTP routes on the Starlette application.

        This method wires the public HTTP API to the internal transport handlers.
        Each route is registered via a dedicated helper for clarity and separation
        of concerns.
        """
        self._setup_task_routes(transport)
        self._setup_agent_card_routes(transport)
        self._setup_agent_status_routes(transport)

    def _setup_task_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register `/tasks/` POST endpoint."""

        _, Request, JSONResponse, _ = _require_starlette()  # noqa: N806

        @self.app.route("/tasks/", methods=["POST"])
        async def handle_task(request: Request) -> JSONResponse:
            if not transport._task_handler:
                raise RuntimeError("No task handler registered")

            task_data = await request.json()
            task = Task.from_dict(task_data)
            result = await transport._task_handler(task)

            return JSONResponse(result.to_dict())

    def _setup_agent_card_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register agent card discovery endpoints.

        Both `/` and `/.well-known/agent.json` return the agent card.
        """

        _, Request, JSONResponse, _ = _require_starlette()  # noqa: N806

        @self.app.route("/", methods=["GET"])
        @self.app.route("/.well-known/agent.json", methods=["GET"])
        async def get_agent_card(request: Request) -> JSONResponse:
            if not transport._agent_card_handler:
                raise RuntimeError("No agent card handler registered")

            result = transport._agent_card_handler()
            return JSONResponse(result.to_json())

    def _setup_agent_status_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register agent status endpoint.

        GET /status returns agent status.
        """

        _, Request, _, HTMLResponse = _require_starlette()  # noqa: N806

        @self.app.route("/status", methods=["GET"])
        async def get_agent_status(request: Request) -> HTMLResponse:
            if not transport._agent_status_handler:
                raise RuntimeError("No agent status handler registered")

            result = transport._agent_status_handler()
            return HTMLResponse(result)

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
