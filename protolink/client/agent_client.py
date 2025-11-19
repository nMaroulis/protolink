from protolink.models import Message, Task
from protolink.transport import Transport


class AgentClient:
    def __init__(self, transport: Transport):
        self.transport = transport

    def send_task(self, task: Task):
        self.transport.send_task(task)

    def send_message(self, agent_url: str, message: Message):
        self.transport.send_message(agent_url, message)

    def get_agent_card(self, agent_url: str):
        self.transport.get_agent_card(agent_url)
