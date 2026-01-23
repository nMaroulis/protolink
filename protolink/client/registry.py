from typing import Any

from protolink.client.request_spec import ClientRequestSpec
from protolink.models import AgentCard
from protolink.transport import Transport

# ----------------------------------------------------------------------
# Agent-to-Registry Communication
# ----------------------------------------------------------------------


class RegistryClient:
    REGISTER_REQUEST = ClientRequestSpec(
        name="register",
        path="/agents/",
        method="POST",
        request_source="body",
    )

    UNREGISTER_REQUEST = ClientRequestSpec(
        name="unregister",
        path="/agents/",
        method="DELETE",
        request_source="body",
    )

    DISCOVER_REQUEST = ClientRequestSpec(
        name="discover",
        path="/agents/",
        method="GET",
        request_source="none",
    )

    def __init__(self, transport: Transport):
        self.transport = transport

    async def register(self, card: AgentCard) -> dict[str, str]:
        """Register an agent to the registry.

        Args:
            card: AgentCard to register

        Raises:
            ConnectionError: If registry is not reachable
            RuntimeError: If registration fails for other reasons
        """
        response = await self.transport.send(
            request_spec=self.REGISTER_REQUEST, base_url=self.transport.url, data=card.to_dict()
        )
        return response

    async def unregister(self, agent_url: str) -> dict[str, str]:
        response = await self.transport.send(
            request_spec=self.UNREGISTER_REQUEST, base_url=self.transport.url, data={"agent_url": agent_url}
        )
        return response

    async def discover(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        response = await self.transport.send(
            request_spec=self.DISCOVER_REQUEST, base_url=self.transport.url, data=filter_by
        )
        return [AgentCard.from_dict(c) for c in response]

    @property
    def url(self) -> str:
        return self.transport.url
