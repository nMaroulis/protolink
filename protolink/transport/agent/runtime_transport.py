import inspect
from collections.abc import Awaitable, Callable
from typing import ClassVar, Protocol, runtime_checkable

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.transport.agent.base import AgentTransport
from protolink.types import TransportType


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol for the minimal Agent interface needed by RuntimeTransport."""

    card: AgentCard


class RuntimeAgentTransport(AgentTransport):
    """In-memory transport for local agent communication.

    Agents communicate directly without network overhead.
    Perfect for testing and local multi-agent setups.
    """

    def __init__(self):
        """Initialize in-memory transport."""
        self.transport_type: ClassVar[TransportType] = "runtime"
        self.agents: dict[str, AgentProtocol] = {}
        self._task_handler: Callable[[Task], Awaitable[Task]] | None = None

    def register_agent(self, agent: AgentProtocol) -> None:
        """Register an agent for in-memory communication.

        Args:
            agent: Agent instance to register
        """
        self.agents[agent.card.url] = agent
        self.agents[agent.card.name] = agent  # Allow lookup by name too

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the transport.

        Args:
            agent_id: Agent URL or name
        """
        if agent_id in self.agents:
            del self.agents[agent_id]

    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send task to local agent.

        Args:
            agent_url: Agent URL or name
            task: Task to send

        Returns:
            Processed task

        Raises:
            ValueError: If agent not found
        """
        if agent_url not in self.agents:
            raise ValueError(f"Agent not found: {agent_url}")

        agent = self.agents[agent_url]
        result = agent.handle_task(task)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send message to local agent.

        Args:
            agent_url: Agent URL or name
            message: Message to send

        Returns:
            Response message
        """
        # Create a task with the message
        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)

        # Extract response message
        if result_task.messages:
            return result_task.messages[-1]

        return Message.agent("No response")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Get agent card from local agent.

        Args:
            agent_url: Agent URL or name

        Returns:
            AgentCard

        Raises:
            ValueError: If agent not found
        """
        if agent_url not in self.agents:
            raise ValueError(f"Agent not found: {agent_url}")

        return self.agents[agent_url].get_agent_card()

    async def start(self) -> None:
        """No-op for in-memory transport."""
        pass

    async def stop(self) -> None:
        """Clean up resources."""
        self.agents.clear()
        self._task_handler = None

    async def _handle_incoming_task(self, task: Task) -> Task:
        """Process an incoming task.

        Args:
            task: Task to process

        Returns:
            Processed task

        Raises:
            RuntimeError: If no task handler is registered
        """
        if not self._task_handler:
            raise RuntimeError("No task handler registered")
        return await self._task_handler(task)

    async def subscribe_task(self, agent_url: str, task: Task):
        """Subscribe to task updates (NEW in v0.2.0).

        For in-memory transport, yields events directly without streaming.

        Args:
            agent_url: Agent URL or name
            task: Task to send

        Yields:
            Event dictionaries
        """
        if agent_url not in self.agents:
            raise ValueError(f"Agent not found: {agent_url}")

        agent = self.agents[agent_url]

        # Use streaming handler if available
        if hasattr(agent, "handle_task_streaming"):
            async for event in agent.handle_task_streaming(task):
                if hasattr(event, "to_dict"):
                    yield event.to_dict()
                else:
                    yield event
        else:
            # Fall back to regular handler
            result_task = agent.handle_task(task)
            if inspect.isawaitable(result_task):
                result_task = await result_task
            from protolink.core.events import TaskStatusUpdateEvent

            yield TaskStatusUpdateEvent(task_id=result_task.id, new_state="completed", final=True).to_dict()

    async def _process_incoming_message(self, message: Message) -> Message | None:
        """Process incoming message and return response.

        Args:
            message: Incoming message

        Returns:
            Response message if any
        """
        if message.to not in self.agents:
            raise ValueError(f"Recipient agent not found: {message.to}")

        agent = self.agents[message.to]
        if message.type == "task":
            task = Task.model_validate_json(message.content)
            # Since we can't call process_task on AgentProtocol, we need to check if it's callable
            if hasattr(agent, "process_task") and callable(agent.process_task):
                response = await agent.process_task(task)
                return Message(
                    from_=message.to, to=message.sender, type="task_response", content=response.model_dump_json()
                )
            raise NotImplementedError("Agent does not implement process_task")
        return None

    def list_agents(self) -> list:
        """List all registered agents.

        Returns:
            List of agent URLs
        """
        return list(self.agents.keys())

    def validate_agent_url(self, agent_url: str) -> bool:
        """Validate an agent URL.

        Args:
            agent_url: Agent URL to validate

        Returns:
            True if the URL is valid, False otherwise
        """
        return True
