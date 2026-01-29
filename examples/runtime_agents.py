"""Runtime Transport Example - Multi-Agent Collaboration.

This example demonstrates how agents communicate via the in-memory
RuntimeTransport. Unlike HTTP transport, RuntimeTransport allows
multiple agents to share a single transport instance for efficient
local message passing without network overhead.

Features demonstrated:
- Agent registration with RuntimeTransport
- Agent-to-agent task communication
- Bidirectional messaging
- Agent listing and introspection
"""

from __future__ import annotations

import asyncio

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import RuntimeTransport


class AssistantAgent(Agent):
    """A helpful assistant that responds to user queries."""

    def __init__(self, transport: RuntimeTransport) -> None:
        card = AgentCard(
            name="assistant",
            description="A helpful assistant that answers questions",
            url="runtime://assistant",
        )
        super().__init__(card)
        self.transport = transport
        transport.register_agent(self)

    async def handle_task(self, task: Task) -> Task:
        """Process incoming tasks and provide helpful responses."""
        user_message = task.messages[-1].parts[0].content
        response = f"Hello! I received your message: '{user_message}'. How can I help you today?"
        return task.complete(response)


class TranslatorAgent(Agent):
    """An agent that translates messages to pig latin (for demo purposes)."""

    def __init__(self, transport: RuntimeTransport) -> None:
        card = AgentCard(
            name="translator",
            description="Translates messages to pig latin",
            url="runtime://translator",
        )
        super().__init__(card)
        self.transport = transport
        transport.register_agent(self)

    async def handle_task(self, task: Task) -> Task:
        """Translate the incoming message."""
        user_message = task.messages[-1].parts[0].content
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

    # Create a shared transport for all agents
    transport = RuntimeTransport()

    # Create and register agents
    assistant = AssistantAgent(transport)
    translator = TranslatorAgent(transport)  # noqa: F841

    print(f"\n📋 Registered agents: {transport.list_agents()}")

    # Demonstrate agent-to-agent communication
    print("\n--- Example 1: User → Assistant ---")
    user_task = Task.create(Message.user("What's the weather like?"))
    response = await assistant.send_task_to("translator", user_task)
    print(f"Translator says: {response.get_last_part_content()}")

    print("\n--- Example 2: Assistant → Translator ---")
    greeting_task = Task.create(Message.user("Hello world"))
    translation = await assistant.send_task_to("translator", greeting_task)
    print(f"Translator says: {translation.get_last_part_content()}")

    print("\n--- Example 3: Direct agent card lookup ---")
    card = await assistant.client.get_agent_card("translator")
    print(f"Found agent: {card.name} - {card.description}")

    print("\n✅ Demo complete!")


if __name__ == "__main__":
    asyncio.run(main())
