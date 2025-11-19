import asyncio
from collections.abc import Awaitable, Callable

import httpx
import uvicorn
from fastapi import FastAPI, Request

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.security.auth import AuthProvider
from protolink.transport.transport import Transport


class HTTPTransport(Transport):
    def __init__(
        self, host: str = "0.0.0.0", port: int = 8000, timeout: float = 30.0, auth_provider: AuthProvider | None = None
    ):
        """Initialize HTTP REST transport.

        Args:
            host: Host to bind the server to
            port: Port to listen on
            timeout: Request timeout in seconds
            auth_provider: Optional authentication provider
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._server: asyncio.Task[None] | None = None
        self._request_id = 0
        self.auth_provider = auth_provider
        self.auth_context = None
        self._task_handler: Callable[[Task], Awaitable[Task]] | None = None
        self.app = FastAPI()
        self._setup_routes()

    async def authenticate(self, credentials: str) -> None:
        pass

    async def send_task(self, agent_url: str, task: Task, skill: str | None = None) -> Task:
        pass

    async def send_message(self, agent_url: str, message: Message) -> Message:
        pass

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        pass

    async def subscribe_task(self, agent_url: str, task: Task):
        pass

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.post("/tasks/")
        async def handle_task(request: Request) -> dict:
            if not self._task_handler:
                raise RuntimeError("No task handler registered")

            task_data = await request.json()
            task = Task.model_validate(task_data)
            result = await self._task_handler(task)
            return result.model_dump()

    async def start(self) -> None:
        """Start the HTTP server."""
        if self._server and not self._server.done():
            return

        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        self._server = asyncio.create_task(server.serve())

        # Initialize HTTP client
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server and not self._server.done():
            self._server.cancel()
            try:
                await self._server
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()
            self._client = None

    def on_task_received(self, handler: Callable[[Task], Awaitable[Task]]) -> None:
        """Register task handler."""
        self._task_handler = handler
