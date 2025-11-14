"""Tests for the Agent class."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from protolink.agent.agent import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task


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
        assert agent._transport is None

    def test_get_agent_card(self, agent, agent_card):
        """Test get_agent_card returns the correct card."""
        assert agent.get_agent_card() == agent_card

    def test_handle_task_not_implemented(self, agent):
        """Test handle_task raises NotImplementedError by default."""
        task = Task.create(Message.user("test"))
        with pytest.raises(NotImplementedError):
            agent.handle_task(task)

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
        mock_transport = MagicMock()
        agent.set_transport(mock_transport)
        assert agent._transport == mock_transport

    @pytest.mark.asyncio
    async def test_send_task_to(self, agent):
        """Test sending a task to another agent."""
        # Create an AsyncMock for the transport
        mock_transport = AsyncMock()
        # Configure the async method to return a Task
        mock_transport.send_task.return_value = Task.create(Message.agent("Response"))
        agent.set_transport(mock_transport)

        # Create a test task
        task = Task.create(Message.user("Test"))

        # Test sending the task
        response = await agent.send_task_to("http://other-agent.local", task)

        # Verify the response and that transport was called correctly
        assert isinstance(response, Task)
        mock_transport.send_task.assert_called_once_with(
            "http://other-agent.local",
            task,
        )
