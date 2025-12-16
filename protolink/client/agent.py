from protolink.models import Message, Task
from protolink.transport import AgentTransport


class AgentClient:
    def __init__(self, transport: AgentTransport):
        self.transport = transport

    # ----------------------------------------------------------------------
    # Agent-to-Agent Communication
    # ----------------------------------------------------------------------
    async def send_task(self, agent_url: str, task: Task) -> Task:
        return await self.transport.send_task(agent_url, task)

    async def send_message(self, agent_url: str, message: Message) -> Message:
        return await self.transport.send_message(agent_url, message)
