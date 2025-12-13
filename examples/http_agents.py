"""HTTP transport example with two agents chatting over REST."""

from __future__ import annotations

import asyncio

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import HTTPAgentTransport


class FriendlyAgent(Agent):
    """Simple agent that replies with a templated message."""

    def __init__(self, name: str, description: str, port: int) -> None:
        transport = HTTPAgentTransport(host="127.0.0.1", port=port, backend="starlette")
        card = AgentCard(name=name, description=description, url=f"http://127.0.0.1:{port}")
        super().__init__(card, transport=transport)

    async def handle_task(self, task: Task) -> Task:
        user_text = task.messages[-1].parts[0].content
        return task.complete(f"[{self.card.name}] heard: '{user_text}'")


async def main() -> None:
    """Spin up two HTTP agents and send them tasks."""

    alice = FriendlyAgent("alice", "Greets everyone", port=8010)
    bob = FriendlyAgent("bob", "Echoes whatever it receives", port=8011)

    await asyncio.gather(alice.start(), bob.start())

    try:
        print("=== Alice -> Bob ===")
        hello = Task.create(Message.user("Hi Bob, how are you?"))
        bob_reply = await alice.send_task_to(bob.card.url, hello)
        print(bob_reply.messages[-1].parts[0].content)

        print("\n=== Bob -> Alice ===")
        ping = Task.create(Message.user("Hey Alice, got your ping!"))
        alice_reply = await bob.send_task_to(alice.card.url, ping)
        print(alice_reply.messages[-1].parts[0].content)

    finally:
        await asyncio.gather(alice.stop(), bob.stop())


if __name__ == "__main__":
    asyncio.run(main())
