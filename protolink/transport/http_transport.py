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
        self._server_task: asyncio.Task[None] | None = None
        self._server_instance: uvicorn.Server | None = None
        self._request_id = 0
        self.auth_provider = auth_provider
        self.auth_context = None
        self._task_handler: Callable[[Task], Awaitable[Task]] | None = None
        self.app = FastAPI()
        self._setup_routes()

    async def authenticate(self, credentials: str) -> None:
        if not self.auth_provider:
            raise RuntimeError("No auth provider configured")

        self.auth_context = await self.auth_provider.authenticate(credentials)

    async def send_task(self, agent_url: str, task: Task, skill: str | None = None) -> Task:
        client = await self._ensure_client()
        headers = self._build_headers(skill)

        url = f"{agent_url.rstrip('/')}/tasks/"
        response = await client.post(url, json=task.to_dict(), headers=headers)
        response.raise_for_status()
        return Task.from_dict(response.json())

    async def send_message(self, agent_url: str, message: Message) -> Message:
        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)
        if result_task.messages:
            return result_task.messages[-1]
        raise RuntimeError("No response messages returned by agent")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        client = await self._ensure_client()
        url = f"{agent_url.rstrip('/')}/.well-known/agent.json"
        response = await client.get(url)
        response.raise_for_status()
        return AgentCard.from_json(response.json())

    async def subscribe_task(self, agent_url: str, task: Task):
        raise NotImplementedError("HTTP streaming is not implemented yet")

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.post("/tasks/")
        async def handle_task(request: Request) -> dict:
            if not self._task_handler:
                raise RuntimeError("No task handler registered")

            task_data = await request.json()
            task = Task.from_dict(task_data)
            result = await self._task_handler(task)
            return result.to_dict()

    async def start(self) -> None:
        """Start the HTTP server."""
        if self._server_task and not self._server_task.done():
            return

        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        self._server_instance = server
        self._server_task = asyncio.create_task(server.serve())

        while not server.started:
            if self._server_task.done():
                break
            await asyncio.sleep(0.05)

        # Initialize HTTP client
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def stop(self) -> None:
        """Stop the HTTP server."""
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

        if self._client:
            await self._client.aclose()
            self._client = None

    def on_task_received(self, handler: Callable[[Task], Awaitable[Task]]) -> None:
        """Register task handler."""
        self._task_handler = handler

    async def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _build_headers(self, skill: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}

        if self.auth_context:
            headers["Authorization"] = f"Bearer {self.auth_context.token}"

        return headers
