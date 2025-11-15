import httpx

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.security.auth import AuthProvider
from protolink.transport.transport import Transport


class HTTPTransport(Transport):
    def __init__(self, timeout: float = 30.0, auth_provider: AuthProvider | None = None):
        """Initialize HTTP REST transport."""
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        self.auth_provider = auth_provider
        self.auth_context = None

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

    async def close(self):
        pass
