"""Run a provider-free three-agent mesh over the in-process transport.

This example opens no ports and needs no registry, model provider, or API key.
RuntimeTransport still applies Protolink's normal task serialization boundary, so
the same Agent and Task contracts can move to a network transport later.

Run it with:

    python examples/provider_free_mesh.py
"""

from __future__ import annotations

import asyncio

from protolink import Agent, AgentCard, Message, Task
from protolink.client import AgentClient


class Specialist(Agent):
    """Return one deterministic contribution to a plan."""

    def __init__(self, name: str, answer: str) -> None:
        super().__init__(
            card=AgentCard(
                name=name,
                description=f"{name.title()} specialist",
                url=f"runtime://{name}",
            ),
            transport="runtime",
            verbosity=0,
        )
        self.answer = answer

    async def handle_task(self, task: Task) -> Task:
        """Complete the task with this specialist's deterministic advice."""
        return task.complete(f"{self.card.name}: {self.answer}")


class Planner(Agent):
    """Fan a request out to two specialists and combine their answers."""

    async def handle_task(self, task: Task) -> Task:
        """Delegate in parallel through normal Agent-to-Agent calls."""
        request = str(task.get_last_part_content())
        replies = await asyncio.gather(
            self.call_agent(
                "runtime://researcher",
                Task.create(Message.user(request)),
            ),
            self.call_agent(
                "runtime://reviewer",
                Task.create(Message.user(request)),
            ),
        )
        summary = "\n".join(str(reply.get_last_part_content()) for reply in replies)
        return task.complete(f"Plan for {request}:\n{summary}")


async def main() -> None:
    """Start the mesh, send one task through it, and stop cleanly."""
    agents: list[Agent] = [
        Specialist("researcher", "collect the evidence"),
        Specialist("reviewer", "check the risky assumptions"),
        Planner(
            card=AgentCard(
                name="planner",
                description="Coordinates specialist agents",
                url="runtime://planner",
            ),
            transport="runtime",
            verbosity=0,
        ),
    ]

    for agent in agents:
        agent.start(background=True)

    try:
        client = AgentClient("runtime", url="runtime://client")
        result = await client.send_task(
            "runtime://planner",
            Task.create(Message.user("ship v1")),
        )
        print(result.get_last_part_content())
    finally:
        for agent in reversed(agents):
            agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
