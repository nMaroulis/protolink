import json
from typing import Any, ClassVar

import httpx

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.security.auth import Authenticator
from protolink.transport.agent.base import AgentTransport
from protolink.types import TransportType


class JSONRPCTransport(AgentTransport):
    """JSON-RPC 2.0 transport over HTTP/WebSocket.

    Implements A2A protocol communication using:
        - HTTP for synchronous requests
        - SSE (Server-Sent Events) for streaming/async (v0.2.0)

    Uses JSON-RPC 2.0 for method calls:
        - tasks/send - Send a task
        - tasks/sendSubscribe - Send task with streaming updates (NEW v0.2.0)
        - message/send - Send a message
        - /.well-known/agent.json - Get agent card
    """

    def __init__(self, timeout: float = 30.0, authenticator: Authenticator | None = None):
        """Initialize JSON-RPC transport.

        Args:
            timeout: Request timeout in seconds
            authenticator: Authenticator for request authentication (NEW v0.3.0)
        """
        self.transport_type: ClassVar[TransportType] = "json-rpc"
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        self.authenticator = authenticator
        self.security_context = None

    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id

    async def authenticate(self, credentials: str) -> None:
        """Set authentication credentials.

        Args:
            credentials: Token or API key for authentication
        """
        if not self.authenticator:
            raise RuntimeError("No auth provider configured")

        self.security_context = await self.authenticator.authenticate(credentials)

    async def _json_rpc_call(self, url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make a JSON-RPC 2.0 call.

        Args:
            url: Target URL
            method: RPC method name
            params: Method parameters

        Returns:
            Result from RPC call

        Raises:
            Exception: If RPC call fails
        """

        client = self._get_client()

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._next_request_id(),
        }

        headers = {}
        if self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"

        response = await client.post(url, json=request, headers=headers)
        response.raise_for_status()

        result = response.json()

        if "error" in result:
            raise Exception(f"RPC Error: {result['error']}")

        return result.get("result", {})

    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send task via JSON-RPC.

        Args:
            agent_url: Target agent URL
            task: Task to send

        Returns:
            Processed task
        """
        result = await self._json_rpc_call(agent_url, "tasks/send", {"task": task.to_dict()})

        return Task.from_dict(result.get("task", {}))

    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send message via JSON-RPC.

        Args:
            agent_url: Target agent URL
            message: Message to send

        Returns:
            Response message
        """
        result = await self._json_rpc_call(agent_url, "message/send", {"message": message.to_dict()})

        return Message.from_dict(result.get("message", {}))

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Fetch agent card via well-known URI.

        Args:
            agent_url: Agent base URL

        Returns:
            AgentCard
        """
        client = self._get_client()

        # Try standard A2A well-known path
        well_known_url = f"{agent_url.rstrip('/')}/.well-known/agent.json"

        try:
            response = await client.get(well_known_url)
            response.raise_for_status()
            data = response.json()
            return AgentCard.from_json(data)
        except Exception as e:
            raise Exception(f"Failed to fetch agent card: {e}")  # noqa: B904

    async def subscribe_task(self, agent_url: str, task: Task):
        """Subscribe to task updates via SSE (NEW in v0.2.0).

        Streams task events using Server-Sent Events format.

        Args:
            agent_url: Target agent URL
            task: Task to send

        Yields:
            Event dictionaries
        """
        client = self._get_client()

        request = {
            "jsonrpc": "2.0",
            "method": "tasks/sendSubscribe",
            "params": {"task": task.to_dict()},
            "id": self._next_request_id(),
        }

        headers = {}
        if self.security_context:
            headers["Authorization"] = f"Bearer {self.security_context.token}"

        try:
            async with client.stream("POST", agent_url, json=request, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    # Parse SSE format: data: {...}
                    if line.startswith("data:"):
                        try:
                            event_data = json.loads(line[5:].strip())
                            yield event_data
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            raise Exception(f"Streaming failed: {e}")  # noqa: B904

    async def close(self):
        """Close the transport and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
