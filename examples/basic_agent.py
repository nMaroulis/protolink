"""
Basic Agent Example

Shows how to create a simple agent that echoes user input.
"""
from protolink.agent import Agent
from protolink.models import AgentCard, Task


class EchoAgent(Agent):
    """A simple agent that echoes back user messages."""

    def __init__(self):
        card = AgentCard(
            name="echo-agent",
            description="An agent that echoes back your messages",
            url="local://echo-agent"
        )
        super().__init__(card)

    def handle_task(self, task: Task) -> Task:
        """Process the task by echoing back the user's message."""
        # Get the user's message
        if task.messages:
            user_message = task.messages[0]
            if user_message.parts:
                user_text = user_message.parts[0].content

                # Create a response
                response = f"Echo: {user_text}"
                return task.complete(response)

        return task.fail("No message to echo")


def main():
    # Create the agent
    agent = EchoAgent()

    print(f"Agent: {agent.card.name}")
    print(f"Description: {agent.card.description}")
    print()

    # Test the agent with direct processing
    test_messages = [
        "Hello, agent!",
        "How are you?",
        "This is a test message"
    ]

    for msg in test_messages:
        print(f"User: {msg}")
        response = agent.process(msg)
        print(f"Agent: {response}")
        print()


if __name__ == "__main__":
    main()