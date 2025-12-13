from protolink.models import AgentCard
from protolink.transport.registry import RegistryTransport

# ----------------------------------------------------------------------
# Agent-to-Registry Communication
# ----------------------------------------------------------------------


class RegistryClient:
    def __init__(self, transport: RegistryTransport):
        self.transport = transport

    async def register(self, card: AgentCard) -> None:
        await self.transport.register(card)

    async def unregister(self, agent_url: str) -> None:
        await self.transport.unregister(agent_url)

    async def discover(self, filters: dict | None = None) -> list[AgentCard]:
        return await self.transport.discover(filters)
