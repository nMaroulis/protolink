from protolink.models import AgentCard, Message, Task
from protolink.transport import Transport


class AgentClient:
    def __init__(self, transport: Transport):
        self.transport = transport

    async def send_task(self, agent_url: str, task: Task, skill: str | None = None) -> Task:
        return await self.transport.send_task(agent_url, task, skill=skill)

    async def send_message(self, agent_url: str, message: Message) -> Message:
        return await self.transport.send_message(agent_url, message)

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        return await self.transport.get_agent_card(agent_url)
