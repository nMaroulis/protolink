"""Starlette-based HTTP backend used by :class:`HTTPAgentTransport`.

This module provides a concrete implementation of :class:`BackendInterface`
backed by a Starlette application. It is responsible for wiring HTTP
endpoints to the transport's internal task handler and for managing the
underlying ASGI server lifecycle.
"""

import asyncio
from typing import Any

from protolink.core.task import Task
from protolink.transport.agent.backends.base import BackendInterface


class StarletteBackend(BackendInterface):
    """Starlette implementation of :class:`BackendInterface`.

    A lightweight alternative to the FastAPI backend that exposes the same
    `/tasks/` endpoint but without Pydantic-based request validation.
    """

    def __init__(self) -> None:
        from starlette.applications import Starlette

        self.app = Starlette()
        self._server_task: asyncio.Task[None] | None = None
        self._server_instance: Any = None

    def setup_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register HTTP routes on the Starlette application.

        The handler delegates incoming HTTP requests to the private
        ``_task_handler`` callback on the associated transport instance.
        """

        from starlette.requests import Request
        from starlette.responses import JSONResponse

        @self.app.route("/tasks/", methods=["POST"])
        async def handle_task(request: Request):  # type: ignore[unused-ignore]
            """Handle a task request using the raw JSON payload."""

            if not transport._task_handler:
                raise RuntimeError("No task handler registered")

            task_data = await request.json()
            task = Task.from_dict(task_data)
            result = await transport._task_handler(task)
            return JSONResponse(result.to_dict())

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
