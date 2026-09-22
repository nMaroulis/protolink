"""Communicate through runtime:// endpoints without opening network ports.

AgentGroup manages readiness and cleanup. Task serialization preserves the
same boundary used by distributed transports.
"""

from __future__ import annotations

import asyncio

from protolink import Agent, AgentGroup
from protolink.models import AgentCard, Message, Task


class AssistantAgent(Agent):
    """A baseline agent implementation representing a generic Assistant.

    This class inherits from the core `Agent` and overrides the `handle_task`
    lifecycle method. In a real-world scenario, this agent would house an LLM
    backend and tools. Here, it acts as a deterministic echo chamber to validate
    transport routing.
    """

    async def handle_task(self, task: Task) -> Task:
        """Process incoming task requests from the local runtime transport.

        This method intercepts the task payload, extracts the terminal user message
        from the conversation history, and returns a fully completed task object.
        The underlying transport mechanism transparently returns this response
        back to the caller loop.
        """
        user_message = task.get_last_part_content()
        return task.complete(f"Hello! I received: '{user_message}'")


class TranslatorAgent(Agent):
    """A specialized domain agent representing a discrete microservice.

    This agent encapsulates a specific skill (translating English to Pig Latin).
    By isolating this logic into a distinct agent and communicating with it via
    the `runtime://` URI scheme, we simulate a distributed microservices architecture
    entirely within local memory.
    """

    async def handle_task(self, task: Task) -> Task:
        """Extract the message context, apply the domain logic, and respond.

        This asynchronous handler serves as the main entrypoint for task execution.
        It securely processes the input and packages the mutated state back into a
        `Task` container, fulfilling the standard Protolink agent contract.
        """
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
    """Call a local peer through the runtime transport with managed lifecycle."""
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
        transport="runtime",
    )

    translator = TranslatorAgent(
        card=AgentCard(
            name="translator",
            description="Translates to pig latin",
            url="runtime://translator",
        ),
        transport="runtime",
    )

    # Start, await readiness, and clean up as one owned group.
    async with AgentGroup([assistant, translator]):
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


if __name__ == "__main__":
    asyncio.run(main())
