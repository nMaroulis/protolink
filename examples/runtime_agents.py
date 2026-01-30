"""Runtime Transport Example - Multi-Agent Collaboration.

Demonstrates how agents communicate via the in-memory RuntimeTransport.
Unlike HTTP transport, RuntimeTransport allows multiple agents to share
a single transport instance for efficient local message passing.
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

    # Create shared transport
    transport = RuntimeTransport()

    # Create agents - pass transport to constructor
    assistant = Agent(
        card=AgentCard(
            name="assistant",
            description="A helpful assistant",
            url="runtime://assistant",
        ),
        transport=transport,
    )
    transport.register_agent(assistant)

    translator = TranslatorAgent(
        card=AgentCard(
            name="translator",
            description="Translates to pig latin",
            url="runtime://translator",
        ),
        transport=transport,
    )
    transport.register_agent(translator)

    print(f"\n📋 Registered agents: {[a for a in transport.list_agents() if '://' in a]}")

    # Agent-to-agent communication
    print("\n--- Assistant → Translator ---")
    task = Task.create(Message.user("Hello world"))
    response = await assistant.send_task_to("translator", task)
    print(f"Result: {response.get_last_part_content()}")

    print("\n--- Direct agent card lookup ---")
    card = await assistant.client.get_agent_card("translator")
    print(f"Found: {card.name} - {card.description}")

    print("\n✅ Demo complete!")


if __name__ == "__main__":
    asyncio.run(main())
