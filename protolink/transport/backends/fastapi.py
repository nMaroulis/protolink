"""FastAPI-based HTTP backend used by :class:`HTTPTransport`.

This module provides a concrete implementation of :class:`BackendInterface`
backed by a FastAPI application. It is responsible only for:

* defining the HTTP schema (Pydantic models when ``validate_schema`` is True)
* wiring HTTP routes to the transport's internal task handler
* starting and stopping the underlying ASGI server

Business logic stays in the transport and the agents.
"""

import asyncio
from typing import Any

from protolink.core.task import Task
from protolink.transport.backends.base import BackendInterface


class FastAPIBackend(BackendInterface):
    """FastAPI implementation of :class:`BackendInterface`.

    Parameters
    ----------
    validate_schema:
        When ``True`` (default), requests are validated using Pydantic models.
        When ``False``, the raw JSON payload is passed through and validated
        only by the core ``Task`` model.
    """

    def __init__(self, *, validate_schema: bool = False) -> None:
        from fastapi import FastAPI

        self.validate_schema: bool = validate_schema
        self.app = FastAPI()
        self._server_task: asyncio.Task[None] | None = None
        self._server_instance: Any = None

    def setup_routes(self, transport: "HTTPTransport") -> None:  # noqa: F821
        """Register HTTP routes on the FastAPI application.

        The handler delegates incoming HTTP requests to the private
        ``_task_handler`` callback on the associated transport instance.
        """

        from fastapi import Request
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel

        if self.validate_schema:

            class PartSchema(BaseModel):
                """HTTP representation of a content part within a message or artifact."""

                type: str
                content: Any

            class MessageSchema(BaseModel):
                """HTTP representation of a single chat message.

                Mirrors :class:`protolink.core.message.Message.to_dict`.
                """

                id: str
                role: str
                parts: list[PartSchema]
                timestamp: str

            class ArtifactSchema(BaseModel):
                """HTTP representation of a :class:`Artifact`."""

                artifact_id: str
                parts: list[PartSchema]
                metadata: dict[str, Any] = {}
                created_at: str

            class TaskSchema(BaseModel):
                """HTTP representation of a :class:`Task`.

                Mirrors :meth:`Task.to_dict`, including nested messages
                and artifacts.
                """

                id: str
                state: str
                messages: list[MessageSchema]
                artifacts: list[ArtifactSchema] = []
                metadata: dict[str, Any] = {}
                created_at: str

            @self.app.post("/tasks/")
            async def handle_task(task: TaskSchema):
                """Handle a task request validated by Pydantic models."""

                if not transport._task_handler:
                    raise RuntimeError("No task handler registered")

                internal_task = Task.from_dict(task.model_dump())
                result = await transport._task_handler(internal_task)
                return JSONResponse(result.to_dict())
        else:

            @self.app.post("/tasks/")
            async def handle_task(request: Request):
                """Handle a task request using the raw JSON payload."""

                if not transport._task_handler:
                    raise RuntimeError("No task handler registered")

                data = await request.json()
                task = Task.from_dict(data)
                result = await transport._task_handler(task)
                return JSONResponse(result.to_dict())

    async def start(self, host: str, port: int) -> None:
        """Start the FastAPI-backed HTTP server.

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
        """Stop the FastAPI-backed HTTP server and clean up resources."""

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
