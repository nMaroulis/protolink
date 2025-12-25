import json
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.security.auth import Authenticator
from protolink.transport.agent.base import AgentTransport
from protolink.types import TransportType


class WebSocketAgentTransport(AgentTransport):
    """Transport implementation that communicates over WebSockets."""

    WS_PATH = "/ws"

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        timeout: float = 30.0,
        authenticator: Authenticator | None = None,
    ):
        self.transport_type: ClassVar[TransportType] = "websocket"
        self.host = host
        self.port = port
        self.timeout = timeout
        self.authenticator = authenticator
        self.security_context = None
        self._task_handler: Callable[[Task], Awaitable[Task]] | None = None
        # websockets.server.serve() returns a Serve object that exposes close()/wait_closed()
        self._server: Any | None = None
        self._http_client: httpx.AsyncClient | None = None

    async def authenticate(self, credentials: str) -> None:
        if not self.authenticator:
            raise RuntimeError("No authenticator configured")
        self.security_context = await self.authenticator.authenticate(credentials)

    async def send_task(self, agent_url: str, task: Task) -> Task:
        ws_url = self._build_ws_url(agent_url)
        headers = self._build_headers()

        async with connect(ws_url, extra_headers=headers, open_timeout=self.timeout, close_timeout=self.timeout) as ws:
            payload = {"type": "task", "task": task.to_dict()}
            await ws.send(json.dumps(payload))

            async for raw in ws:
                response = json.loads(raw)
                if response.get("type") == "task_result":
                    return Task.from_dict(response["task"])
                if response.get("type") == "error":
                    raise RuntimeError(response.get("message", "WebSocket task failed"))
        raise RuntimeError("WebSocket connection closed without response")

    async def send_message(self, agent_url: str, message: Message) -> Message:
        task = Task.create(message)
        response_task = await self.send_task(agent_url, task)
        if not response_task.messages:
            raise RuntimeError("No response messages returned by agent")
        return response_task.messages[-1]

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        http_url = self._convert_ws_to_http(agent_url)
        client = await self._ensure_http_client()
        url = f"{http_url.rstrip('/')}/.well-known/agent.json"
        response = await client.get(url, timeout=self.timeout)
        response.raise_for_status()
        return AgentCard.from_json(response.json())

    async def subscribe_task(self, agent_url: str, task: Task):
        raise NotImplementedError("WebSocket streaming is not implemented yet")

    async def start(self) -> None:
        if self._server:
            return

        async def handler(websocket: ServerConnection) -> None:
            if websocket.path != self.WS_PATH:
                await websocket.close(code=1008, reason="Unsupported path")
                return
            await self._handle_connection(websocket)

        self._server = await serve(handler, self.host, self.port, ping_interval=None, ping_timeout=None)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def validate_agent_url(self, agent_url: str) -> bool:
        parsed = urlparse(agent_url)
        if parsed.scheme not in {"ws", "wss"}:
            return False
        return parsed.hostname in {self.host, "127.0.0.1", "localhost"} and parsed.port == self.port

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        if not self._task_handler:
            await websocket.close(code=1011, reason="No task handler registered")
            return

        try:
            async for raw in websocket:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_error(websocket, "Invalid JSON payload")
                    continue

                msg_type = message.get("type")
                if msg_type == "task":
                    await self._process_task_message(websocket, message)
                else:
                    await self._send_error(websocket, f"Unsupported message type: {msg_type}")
        except ConnectionClosed:
            return

    async def _process_task_message(self, websocket: ServerConnection, payload: dict[str, Any]) -> None:
        if "task" not in payload:
            await self._send_error(websocket, "Missing task payload")
            return

        try:
            await self._verify_request_auth(websocket)
        except PermissionError as exc:
            await self._send_error(websocket, str(exc))
            return

        task = Task.from_dict(payload["task"])
        result = await self._task_handler(task)
        await websocket.send(json.dumps({"type": "task_result", "task": result.to_dict()}))

    async def _verify_request_auth(self, websocket: ServerConnection) -> None:
        if not self.authenticator:
            return

        auth_header = websocket.request_headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise PermissionError("Authentication required")

        token = auth_header[7:]
        self.security_context = await self.authenticator.authenticate(token)

    def _build_ws_url(self, agent_url: str) -> str:
        url = agent_url
        if url.startswith("http://"):
            url = "ws://" + url[len("http://") :]
        elif url.startswith("https://"):
            url = "wss://" + url[len("https://") :]

        if not url.startswith("ws://") and not url.startswith("wss://"):
            url = f"ws://{url.lstrip('/')}"

        if url.endswith(self.WS_PATH):
            return url

        if url.endswith("/"):
            return f"{url.rstrip('/')}{self.WS_PATH}"

        parsed = urlparse(url)
        if parsed.path and parsed.path != "/":
            return url

        return f"{url}{self.WS_PATH}"

    def _convert_ws_to_http(self, agent_url: str) -> str:
        if agent_url.startswith("wss://"):
            return "https://" + agent_url[6:]
        if agent_url.startswith("ws://"):
            return "http://" + agent_url[5:]
        return agent_url

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"
        return headers

    async def _ensure_http_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._http_client

    @staticmethod
    async def _send_error(websocket, message: str) -> None:
        await websocket.send(json.dumps({"type": "error", "message": message}))
