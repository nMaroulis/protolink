"""Tests for the Agent class."""

from unittest.mock import AsyncMock

import pytest

from protolink.agents import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.transport import AgentTransport


class DummyTransport(AgentTransport):
    """Minimal transport implementation for testing purposes."""

    def __init__(self):
        self.handler = None

    async def send_task(self, agent_url: str, task: Task) -> Task:
        return task

    async def send_message(self, agent_url: str, message: Message) -> Message:
        return Message.agent("dummy")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        return AgentCard(name="dummy", description="dummy", url="local://dummy")

    async def subscribe_task(self, agent_url: str, task: Task):
        if False:  # pragma: no cover
            yield {}

    async def start(self) -> None:  # pragma: no cover
        pass

    async def stop(self) -> None:  # pragma: no cover
        pass

    def on_task_received(self, handler):
        self.handler = handler

    def validate_agent_url(self, agent_url: str) -> bool:
        return True


class TestAgent:
    """Test cases for the Agent class."""

    @pytest.fixture
    def agent_card(self):
        """Create a test agent card."""
        return AgentCard(name="test-agent", description="A test agent", url="http://test-agent.local")

    @pytest.fixture
    def agent(self, agent_card):
        """Create a test agent instance."""
        return Agent(agent_card)

    def test_initialization(self, agent, agent_card):
        """Test agent initialization with agent card."""
        assert agent.card == agent_card
        assert agent.client is None
        assert agent.server is None

    def test_get_agent_card(self, agent, agent_card):
        """Test get_agent_card returns the correct card."""
        assert agent.get_agent_card() == agent_card

    @pytest.mark.asyncio
    async def test_handle_task_not_implemented(self, agent):
        """Test handle_task raises NotImplementedError by default."""
        task = Task.create(Message.user("test"))
        with pytest.raises(NotImplementedError):
            await agent.handle_task(task)

    def test_process_method(self, agent):
        """Test the process method with a simple echo response."""

        # Create a test agent that implements handle_task
        class TestAgent(Agent):
            def handle_task(self, task):
                return task.complete("Test response")

        test_agent = TestAgent(agent.card)
        response = test_agent.process("Hello")
        assert response == "Test response"

    def test_set_transport(self, agent):
        """Test setting the transport."""
        transport = DummyTransport()
        agent.set_transport(transport)
        assert agent.client is not None
        assert agent.server is not None
        assert transport.handler == agent.handle_task

    @pytest.mark.asyncio
    async def test_send_task_to(self, agent):
        """Test sending a task to another agent."""
        # Create an AsyncMock for the transport
        transport = DummyTransport()
        transport.send_task = AsyncMock(return_value=Task.create(Message.agent("Response")))
        agent.set_transport(transport)

        # Create a test task
        task = Task.create(Message.user("Test"))

        # Test sending the task
        response = await agent.send_task_to("http://other-agent.local", task)

        # Verify the response and that transport was called correctly
        assert isinstance(response, Task)
        transport.send_task.assert_awaited_once_with(
            "http://other-agent.local",
            task,
        )
