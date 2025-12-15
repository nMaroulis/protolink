"""FastAPI-based HTTP backend used by :class:`HTTPAgentTransport`.

This module provides a concrete implementation of :class:`BackendInterface`
backed by a FastAPI application. It is responsible only for:

* defining the HTTP schema (Pydantic models when ``validate_schema`` is True)
* wiring HTTP routes to the transport's internal task handler
* starting and stopping the underlying ASGI server

Business logic stays in the transport and the agents.
"""

import asyncio
from typing import Any

from pydantic import Field

from protolink.core.task import Task
from protolink.transport._deps import _require_fastapi
from protolink.transport.agent.backends.base import BackendInterface


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
        FastAPI, _, _, _ = _require_fastapi(validate_schema=validate_schema)  # noqa: N806

        self.validate_schema: bool = validate_schema
        self.app = FastAPI()
        self._server_task: asyncio.Task[None] | None = None
        self._server_instance: Any = None

    # ----------------------------------------------------------------------
    # Setup Routes - Define Agent Server URIs
    # ----------------------------------------------------------------------

    def setup_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register all HTTP routes on the FastAPI application."""
        self._setup_task_routes(transport)
        self._setup_agent_card_routes(transport)

    def _setup_task_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register `/tasks/` POST endpoint."""

        _, Request, JSONResponse, BaseModel = _require_fastapi(validate_schema=self.validate_schema)  # noqa: N806

        if self.validate_schema:

            class PartSchema(BaseModel):
                type: str
                content: Any

            class MessageSchema(BaseModel):
                id: str
                role: str
                parts: list[PartSchema]
                timestamp: str

            class ArtifactSchema(BaseModel):
                artifact_id: str
                parts: list[PartSchema]
                metadata: dict[str, Any] = Field(default_factory=dict)
                created_at: str

            class TaskSchema(BaseModel):
                id: str
                state: str
                messages: list[MessageSchema]
                artifacts: list[ArtifactSchema] = Field(default_factory=list)
                metadata: dict[str, Any] = Field(default_factory=dict)
                created_at: str

            @self.app.post("/tasks/")
            async def handle_task(task: TaskSchema) -> JSONResponse:
                if not transport._task_handler:
                    raise RuntimeError("No task handler registered")

                internal_task = Task.from_dict(task.model_dump())
                result = await transport._task_handler(internal_task)

                return JSONResponse(result.to_dict())

        else:

            @self.app.post("/tasks/")
            async def handle_task(request: Request) -> JSONResponse:
                if not transport._task_handler:
                    raise RuntimeError("No task handler registered")

                data = await request.json()
                task = Task.from_dict(data)
                result = await transport._task_handler(task)

                return JSONResponse(result.to_dict())

    def _setup_agent_card_routes(self, transport: "HTTPAgentTransport") -> None:  # noqa: F821
        """Register agent card discovery endpoints.

        Both `/` and `/.well-known/agent.json` return the agent card.
        """

        _, Request, JSONResponse, _ = _require_fastapi()  # noqa: N806

        @self.app.get("/")
        @self.app.get("/.well-known/agent.json")
        async def get_agent_card(request: Request) -> JSONResponse:
            if not transport._agent_card_handler:
                raise RuntimeError("No agent card handler registered")

            result = transport._agent_card_handler()
            return JSONResponse(result.to_json())

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

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
