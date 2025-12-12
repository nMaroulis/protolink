"""HTTP transport implementation for talking to remote Protolink agents.

This module exposes :class:`HTTPTransport`, which sends and receives
``Task`` and ``Message`` objects over plain HTTP using either a Starlette
or FastAPI backend for the server side.
"""

from collections.abc import Awaitable, Callable
from typing import Literal, TypeAlias

import httpx

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.security.auth import Authenticator
from protolink.transport.backends import BackendInterface, FastAPIBackend, StarletteBackend
from protolink.transport.transport import Transport

BackendName: TypeAlias = Literal["starlette", "fastapi"]


class HTTPTransport(Transport):
    """HTTP-based transport for Protolink agents.

    Parameters
    ----------
    host:
        Host interface for the HTTP server to bind to when running as a
        server (e.g. ``"0.0.0.0"``).
    port:
        Port the HTTP server listens on.
    timeout:
        Request timeout (in seconds) for the internal HTTP client.
    authenticator:
        Optional authentication provider used to obtain auth context.
    backend:
        Name of the HTTP backend implementation to use. Currently
        ``"starlette"`` (default) and ``"fastapi"`` are supported.
    validate_schema:
        When using the FastAPI backend, controls whether incoming
        requests are validated with Pydantic models.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        timeout: float = 30.0,
        authenticator: Authenticator | None = None,
        backend: BackendName = "starlette",
        *,
        validate_schema: bool = False,
    ) -> None:
        self.host: str = host
        self.port: int = port
        self.timeout: float = timeout
        self.authenticator: Authenticator | None = authenticator
        self.security_context: object | None = None
        self._task_handler: Callable[[Task], Awaitable[Task]] | None = None
        self._client: httpx.AsyncClient | None = None

        # Select backend implementation.
        if backend.lower() == "fastapi":
            self.backend: BackendInterface = FastAPIBackend(validate_schema=validate_schema)
        else:
            self.backend = StarletteBackend()

        self.app = self.backend.app

    async def authenticate(self, credentials: str) -> None:
        """Authenticate using the configured :class:`Authenticator`.

        Raises
        ------
        RuntimeError
            If no authentication provider has been configured.
        """

        if not self.authenticator:
            raise RuntimeError("No Authenticator configured")

        self.security_context = await self.authenticator.authenticate(credentials)

    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send a ``Task`` to a remote agent and return the resulting task."""

        client = await self._ensure_client()
        headers = self._build_headers()
        url = f"{agent_url.rstrip('/')}/tasks/"
        response = await client.post(url, json=task.to_dict(), headers=headers)
        response.raise_for_status()
        return Task.from_dict(response.json())

    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Convenience wrapper around :meth:`send_task` for a single message."""

        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)
        if result_task.messages:
            return result_task.messages[-1]
        raise RuntimeError("No response messages returned by agent")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Fetch the remote agent's :class:`AgentCard` description."""

        client = await self._ensure_client()
        url = f"{agent_url.rstrip('/')}/.well-known/agent.json"
        response = await client.get(url)
        response.raise_for_status()
        return AgentCard.from_json(response.json())

    async def subscribe_task(self, agent_url: str, task: Task) -> None:
        """Subscribe to a long-running task (not yet implemented)."""

        raise NotImplementedError("HTTP streaming is not implemented yet")

    async def start(self) -> None:
        """Start the HTTP server and initialize the HTTP client."""

        if not self._task_handler:
            raise RuntimeError("No task handler registered")

        self.backend.setup_routes(self)
        await self.backend.start(self.host, self.port)

        # Initialize HTTP client
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def stop(self) -> None:
        """Stop the HTTP server and close the underlying HTTP client."""

        await self.backend.stop()
        if self._client:
            await self._client.aclose()
            self._client = None

    def on_task_received(self, handler: Callable[[Task], Awaitable[Task]]) -> None:
        """Register a callback that will handle incoming tasks."""

        self._task_handler = handler

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return an initialized :class:`httpx.AsyncClient` instance."""

        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for an outgoing request.

        Includes authentication headers when an auth context is present.
        """

        headers: dict[str, str] = {}

        if self.authenticator and self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"

        return headers

    def validate_agent_url(self, agent_url: str) -> bool:
        """Validate an agent URL.

        Parameters
        ----------
        agent_url:
            Agent URL to validate.

        Returns
        -------
        bool
            ``True`` if the URL is allowed, ``False`` otherwise.
        """

        allowed = {
            f"http://{self.host}:{self.port}",
            f"https://{self.host}:{self.port}",
        }

        return agent_url in allowed
