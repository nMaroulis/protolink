"""Runtime Transport Example - Multi-Agent Collaboration.

Demonstrates how agents communicate via the in-memory RuntimeTransport.
Unlike HTTP transport, RuntimeTransport allows agents to communicate without
network overhead, whilst still maintaining process isolation abstractions.
"""

from __future__ import annotations

import asyncio

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import RuntimeTransport


class AssistantAgent(Agent):
    """A helpful assistant that responds to user queries."""

    async def handle_task(self, task: Task) -> Task:
        user_message = task.get_last_part_content()
        return task.complete(f"Hello! I received: '{user_message}'")


class TranslatorAgent(Agent):
    """An agent that translates messages to pig latin."""

    async def handle_task(self, task: Task) -> Task:
        user_message = task.get_last_part_content()
        translated = self._to_pig_latin(user_message)
        return task.complete(f"Translation: {translated}")

    @staticmethod
    def _to_pig_latin(text: str) -> str:
        """Simple pig latin conversion for demonstration."""
        words = text.split()
        result = []
        for word in words:
            if word[0].lower() in "aeiou":
                result.append(word + "yay")
            else:
                result.append(word[1:] + word[0] + "ay")
        return " ".join(result)


async def main() -> None:
    """Demonstrate multi-agent collaboration via RuntimeTransport."""
    print("=" * 50)
    print("  RuntimeTransport Multi-Agent Demo")
    print("=" * 50)

    # Initialize agents completely isolated from each other via unique transport URLs
    # Their endpoints will be mutually resolvable across the runtime transport's class registry internally.
    assistant = Agent(
        card=AgentCard(
            name="assistant",
            description="A helpful assistant",
            url="runtime://assistant",
        ),
        transport=RuntimeTransport(url="runtime://assistant"),
    )

    translator = TranslatorAgent(
        card=AgentCard(
            name="translator",
            description="Translates to pig latin",
            url="runtime://translator",
        ),
        transport=RuntimeTransport(url="runtime://translator"),
    )

    # Boot the servers (which internally mounts the transports)
    await asyncio.gather(assistant.start(), translator.start())

    print(f"\n📋 Active runtime transports: {list(RuntimeTransport._registry.keys())}")

    try:
        # Agent-to-agent communication
        print("\n--- Assistant → Translator ---")
        task = Task.create(Message.user("Hello world"))
        # We can send by the target's transport URL directly
        response = await assistant.call_agent("runtime://translator", task)
        print(f"Result: {response.get_last_part_content()}")

        print("\n--- Direct agent card lookup ---")
        card = await assistant.client.get_agent_card("runtime://translator")
        print(f"Found: {card.name} - {card.description}")

        print("\n✅ Demo complete!")
    finally:
        # Shutdown
        await asyncio.gather(assistant.stop(), translator.stop())


if __name__ == "__main__":
    asyncio.run(main())
