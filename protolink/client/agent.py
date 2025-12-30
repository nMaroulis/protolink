from protolink.models import AgentCard, ClientRequestSpec, Message, Task
from protolink.transport import Transport


class AgentClient:
    """Client for interacting with Protolink agents."""

    TASK_REQUEST = ClientRequestSpec(
        name="send_task",
        path="/tasks/",
        method="POST",
        response_parser=Task.from_dict,
        request_source="body",
    )

    AGENT_CARD_REQUEST = ClientRequestSpec(
        name="get_agent_card",
        path="/.well-known/agent.json",
        method="GET",
        response_parser=AgentCard.from_dict,
        request_source="none",
    )

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    # ----------------------------------------------------------------------
    # Agent-to-Agent Communication
    # ----------------------------------------------------------------------

    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send a task to a remote agent."""
        return await self.transport.send(self.TASK_REQUEST, agent_url, data=task)

    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send a message to a remote agent (convenience wrapper)."""
        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)
        if result_task.messages:
            return result_task.messages[-1]
        raise RuntimeError("No response messages returned by agent")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Get the public agent card."""
        return await self.transport.send(self.AGENT_CARD_REQUEST, agent_url)
