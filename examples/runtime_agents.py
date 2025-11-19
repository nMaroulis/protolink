"""Runtime transport example mirroring the HTTP chat demo."""

from __future__ import annotations

import asyncio

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import RuntimeTransport


class FriendlyAgent(Agent):
    """Simple agent that processes runtime transport tasks."""

    def __init__(self, name: str, description: str, transport: RuntimeTransport):
        card = AgentCard(name=name, description=description, url=f"local://{name}")
        super().__init__(card)
        self.set_transport(transport)
        transport.register_agent(self)

    async def handle_task(self, task: Task) -> Task:
        user_text = task.messages[-1].parts[0].content
        return task.complete(f"[{self.card.name}] heard: '{user_text}'")


async def main() -> None:
    """Demonstrate two agents talking over in-memory runtime transport."""

    transport = RuntimeTransport()
    alice = FriendlyAgent("alice", "Greets everyone", transport)
    bob = FriendlyAgent("bob", "Echoes whatever it receives", transport)

    print("=== Runtime Transport Demo ===\n")

    print("Alice -> Bob")
    hello = Task.create(Message.user("Hi Bob, how are you?"))
    bob_reply = await alice.send_task_to("bob", hello)
    print(bob_reply.messages[-1].parts[0].content)

    print("\nBob -> Alice")
    ping = Task.create(Message.user("Hey Alice, got your ping!"))
    alice_reply = await bob.send_task_to("alice", ping)
    print(alice_reply.messages[-1].parts[0].content)

    print("\nRegistered agents:", transport.list_agents())


if __name__ == "__main__":
    asyncio.run(main())
