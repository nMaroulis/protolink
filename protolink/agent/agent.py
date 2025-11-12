"""
ProtoLink - Agent Base Class

Simple agent implementation following Google's A2A protocol.
"""

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task


class Agent:
    """Base class for creating A2A-compatible agents.

    Users should subclass this and implement the handle_task method.

    Example:
        class MyAgent(Agent):
            def __init__(self):
                card = AgentCard(
                    name="my-agent",
                    description="A helpful agent",
                    url="http://localhost:8000"
                )
                super().__init__(card)

            def handle_task(self, task: Task) -> Task:
                # Get the user's message
                user_message = task.messages[0]
                user_text = user_message.parts[0].content

                # Process and respond
                response = f"You said: {user_text}"
                return task.complete(response)
    """

    def __init__(self, card: AgentCard):
        """Initialize agent with its identity card.

        Args:
            card: AgentCard describing this agent
        """
        self.card = card
        self._transport = None

    def get_agent_card(self) -> AgentCard:
        """Return the agent's identity card.

        Returns:
            AgentCard with agent metadata
        """
        return self.card

    def handle_task(self, task: Task) -> Task:
        """Process a task and return the result.

        This is the core method that users must implement.

        Args:
            task: Task to process

        Returns:
            Task with updated state and response messages

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement handle_task()")

    def process(self, message_text: str) -> str:
        """Simple synchronous processing (convenience method).

        Args:
            message_text: User input text

        Returns:
            Agent response text
        """
        # Create a task with the user message
        task = Task.create(Message.user(message_text))

        # Process the task
        result_task = self.handle_task(task)

        # Extract response
        if result_task.messages:
            last_message = result_task.messages[-1]
            if last_message.role == "agent" and last_message.parts:
                return last_message.parts[0].content

        return "No response generated"

    def set_transport(self, transport):
        """Set the transport layer for this agent.

        Args:
            transport: Transport instance for communication
        """
        self._transport = transport

    async def send_task_to(self, agent_url: str, task: Task) -> Task:
        """Send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send

        Returns:
            Task with response from target agent

        Raises:
            RuntimeError: If no transport is configured
        """
        if not self._transport:
            raise RuntimeError("No transport configured. Call set_transport() first.")

        return await self._transport.send_task(agent_url, task)

    def __repr__(self) -> str:
        return f"Agent(name='{self.card.name}', url='{self.card.url}')"
