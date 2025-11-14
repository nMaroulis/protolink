"""
Multi-Agent Communication Example

Shows how agents can communicate with each other using InMemoryTransport.
"""

import asyncio

from protolink.agent import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import RuntimeTransport


class GreeterAgent(Agent):
    """An agent that greets users."""

    def __init__(self):
        card = AgentCard(name="greeter", description="Greets users warmly", url="local://greeter")
        super().__init__(card)

    def handle_task(self, task: Task) -> Task:
        user_message = task.messages[0]
        user_text = user_message.parts[0].content

        response = f"Hello! You said: {user_text}. Have a great day!"
        return task.complete(response)


class TranslatorAgent(Agent):
    """An agent that 'translates' by uppercasing text."""

    def __init__(self):
        card = AgentCard(
            name="translator",
            description="Translates text to uppercase",
            url="local://translator",
        )
        super().__init__(card)

    def handle_task(self, task: Task) -> Task:
        user_message = task.messages[0]
        user_text = user_message.parts[0].content

        response = user_text.upper()
        return task.complete(response)


class CoordinatorAgent(Agent):
    """An agent that coordinates between other agents."""

    def __init__(self):
        card = AgentCard(
            name="coordinator",
            description="Coordinates between multiple agents",
            url="local://coordinator",
        )
        super().__init__(card)

    def handle_task(self, task: Task) -> Task:
        user_message = task.messages[0]
        user_text = user_message.parts[0].content

        # This will be set by the transport
        response = f"Coordinator received: {user_text}"
        return task.complete(response)


async def main():
    # Create agents
    greeter = GreeterAgent()
    translator = TranslatorAgent()
    coordinator = CoordinatorAgent()

    # Create in-memory transport
    transport = RuntimeTransport()

    # Register all agents
    transport.register_agent(greeter)
    transport.register_agent(translator)
    transport.register_agent(coordinator)

    # Set transport for agents (so they can communicate)
    greeter.set_transport(transport)
    translator.set_transport(transport)
    coordinator.set_transport(transport)

    print("=== Multi-Agent Communication Demo ===\n")

    # Test 1: Direct communication to greeter
    print("Test 1: Send message to Greeter")
    task1 = Task.create(Message.user("Hello from user!"))
    result1 = await transport.send_task("greeter", task1)
    print("User: Hello from user!")
    print(f"Greeter: {result1.messages[-1].parts[0].content}\n")

    # Test 2: Send to translator
    print("Test 2: Send message to Translator")
    task2 = Task.create(Message.user("translate this"))
    result2 = await transport.send_task("translator", task2)
    print("User: translate this")
    print(f"Translator: {result2.messages[-1].parts[0].content}\n")

    # Test 3: Chain communication (coordinator -> greeter)
    print("Test 3: Coordinator forwards to Greeter")
    message = Message.user("Forward this message")
    task3 = Task.create(message)

    # Coordinator sends to greeter
    greeter_task = await coordinator.send_task_to("greeter", task3)
    print("User -> Coordinator -> Greeter")
    print(f"Greeter response: {greeter_task.messages[-1].parts[0].content}\n")

    # Test 4: List all agents
    print("Test 4: List all registered agents")
    agents = transport.list_agents()
    print(f"Registered agents: {agents}\n")

    # Test 5: Get agent cards
    print("Test 5: Fetch agent cards")
    for agent_name in ["greeter", "translator", "coordinator"]:
        card = await transport.get_agent_card(agent_name)
        print(f"- {card.name}: {card.description}")


if __name__ == "__main__":
    asyncio.run(main())
