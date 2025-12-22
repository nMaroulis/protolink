"""Tests for the Agent class."""

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from protolink.agents import Agent
from protolink.client import RegistryClient
from protolink.core.agent_card import AgentCard, AgentSkill
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.llms.base import LLM
from protolink.tools import BaseTool
from protolink.transport import AgentTransport


class DummyTransport(AgentTransport):
    """Minimal transport implementation for testing purposes."""

    def __init__(self, url="http://test-transport.local"):
        self.handler = None
        self._url = url
        self._agent_card_handler = None

    @property
    def url(self):
        return self._url

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

    def on_get_agent_card_received(self, handler):
        self._agent_card_handler = handler

    def on_get_agent_status_received(self, handler):
        pass


class DummyLLM(LLM):
    """Mock LLM for testing."""

    model_type = "dummy"
    provider = "dummy_provider"
    model = "dummy_model"
    model_params: ClassVar[dict] = {}
    system_prompt = ""

    def validate_connection(self) -> bool:
        return True

    async def generate_response(self, messages: list, **kwargs) -> str:
        return "Mock response"

    async def generate_stream_response(self, messages: list, **kwargs):
        yield "Mock stream response"

    def set_model_params(self, **params):
        pass

    def set_system_prompt(self, prompt: str):
        pass


class DummyTool(BaseTool):
    """Mock tool for testing."""

    def __init__(self, name="test_tool", description="Test tool"):
        self.name = name
        self.description = description
        self.tags = ["test"]

    async def __call__(self, **kwargs):
        return f"Tool result: {kwargs}"


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

    @pytest.mark.asyncio
    async def test_send_message_to(self, agent):
        """Test sending a message to another agent."""
        transport = DummyTransport()
        transport.send_message = AsyncMock(return_value=Message.agent("Response message"))
        agent.set_transport(transport)

        message = Message.user("Test message")
        response = await agent.send_message_to("http://other-agent.local", message)

        assert isinstance(response, Message)
        assert response.role == "agent"
        transport.send_message.assert_awaited_once_with("http://other-agent.local", message)

    def test_agent_with_llm(self, agent_card):
        """Test agent initialization with LLM."""
        llm = DummyLLM()
        agent = Agent(agent_card, llm=llm)

        assert agent.llm == llm
        assert agent.card.capabilities.has_llm is True

    def test_agent_with_registry_string(self, agent_card):
        """Test agent initialization with registry URL string."""
        with (
            patch("protolink.agents.base.RegistryClient") as mock_client_class,
            patch("protolink.agents.base.HTTPRegistryTransport") as mock_transport,
        ):
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_transport_instance = MagicMock()
            mock_transport.return_value = mock_transport_instance

            agent = Agent(agent_card, registry="http://registry.local")

            assert agent.registry_client is not None
            mock_client_class.assert_called_once_with(transport=mock_transport_instance)
            mock_transport.assert_called_once_with(url="http://registry.local")

    def test_agent_with_registry_instance(self, agent_card):
        """Test agent initialization with Registry instance."""
        from protolink.discovery.registry import Registry

        mock_registry = MagicMock()
        mock_client = MagicMock(spec=RegistryClient)
        mock_registry.client = mock_client
        mock_registry.get_client.return_value = mock_client

        # Make the mock pass isinstance check
        mock_registry.__class__ = Registry

        agent = Agent(agent_card, registry=mock_registry)

        assert agent.registry_client == mock_client

    def test_agent_with_invalid_registry(self, agent_card):
        """Test agent initialization with invalid registry type."""
        with pytest.raises(ValueError, match="Invalid registry type"):
            Agent(agent_card, registry=123)

    def test_agent_skills_auto_mode(self, agent_card):
        """Test agent with auto skills detection."""
        agent = Agent(agent_card, skills="auto")
        assert agent.skills == "auto"

    def test_agent_skills_fixed_mode(self, agent_card):
        """Test agent with fixed skills mode."""
        agent = Agent(agent_card, skills="fixed")
        assert agent.skills == "fixed"

    def test_add_tool(self, agent):
        """Test adding a tool to the agent."""
        tool = DummyTool()
        agent.add_tool(tool)

        assert "test_tool" in agent.tools
        assert agent.tools["test_tool"] == tool

        # Check that skill was added to agent card
        skill_ids = [skill.id for skill in agent.card.skills]
        assert "test_tool" in skill_ids

    def test_add_tool_decorator(self, agent):
        """Test using the tool decorator."""

        @agent.tool("decorated_tool", "A decorated tool")
        def test_function(x: int) -> str:
            return f"Result: {x}"

        assert "decorated_tool" in agent.tools
        tool = agent.tools["decorated_tool"]
        assert tool.description == "A decorated tool"

        # Check skill was added
        skill_ids = [skill.id for skill in agent.card.skills]
        assert "decorated_tool" in skill_ids

    @pytest.mark.asyncio
    async def test_call_tool(self, agent):
        """Test calling a registered tool."""
        tool = DummyTool()
        agent.add_tool(tool)

        result = await agent.call_tool("test_tool", arg1="value1")
        assert result == "Tool result: {'arg1': 'value1'}"

    def test_call_tool_not_found(self, agent):
        """Test calling a non-existent tool."""
        with pytest.raises(ValueError, match="Tool nonexistent not found"):
            asyncio.run(agent.call_tool("nonexistent"))

    def test_auto_detect_skills_from_tools(self, agent):
        """Test auto-detection of skills from tools."""
        tool1 = DummyTool("tool1", "First tool")
        tool2 = DummyTool("tool2", "Second tool")
        agent.add_tool(tool1)
        agent.add_tool(tool2)

        skills = agent._auto_detect_skills()
        skill_ids = [skill.id for skill in skills]

        assert "tool1" in skill_ids
        assert "tool2" in skill_ids

    def test_auto_detect_skills_from_methods(self, agent):
        """Test auto-detection of skills from public methods."""

        class TestAgentWithMethods(Agent):
            def custom_method(self):
                """A custom method for testing."""
                pass

            def handle_task(self, task):
                return task.complete("test")

        test_agent = TestAgentWithMethods(agent.card)
        skills = test_agent._auto_detect_skills(include_public_methods=True)
        skill_ids = [skill.id for skill in skills]

        assert "custom_method" in skill_ids

    def test_add_skill_to_agent_card_no_duplicates(self, agent):
        """Test that duplicate skills are not added."""
        skill1 = AgentSkill("test_skill", "First skill")
        skill2 = AgentSkill("test_skill", "Duplicate skill")

        agent._add_skill_to_agent_card(skill1)
        agent._add_skill_to_agent_card(skill2)

        skill_ids = [skill.id for skill in agent.card.skills]
        assert skill_ids.count("test_skill") == 1

    @pytest.mark.asyncio
    async def test_handle_task_streaming_default(self, agent):
        """Test default streaming implementation."""

        class TestAgent(Agent):
            def handle_task(self, task):
                return task.complete("Test response")

        test_agent = TestAgent(agent.card)
        task = Task.create(Message.user("test"))

        events = []
        async for event in test_agent.handle_task_streaming(task):
            events.append(event)

        # Should have status update, artifact update (if any), and completion
        assert len(events) >= 2
        assert events[0].new_state == "working"
        assert events[-1].new_state == "completed"

    def test_get_context_manager(self, agent):
        """Test getting the context manager."""
        context_manager = agent.get_context_manager()
        assert context_manager == agent.context_manager

    def test_set_llm(self, agent):
        """Test setting the LLM."""
        llm = DummyLLM()
        agent.set_llm(llm)

        assert agent.llm == llm

    def test_set_transport_invalid(self, agent):
        """Test setting invalid transport."""
        with pytest.raises(ValueError, match="transport must not be None"):
            agent.set_transport(None)

        with pytest.raises(TypeError, match="transport must be an instance of AgentTransport"):
            agent.set_transport("invalid")

    def test_agent_repr(self, agent):
        """Test agent string representation."""
        repr_str = repr(agent)
        assert "test-agent" in repr_str
        assert "http://test-agent.local" in repr_str

    @pytest.mark.asyncio
    async def test_start_with_registry(self, agent_card):
        """Test starting agent with registry registration."""
        mock_registry_client = MagicMock(spec=RegistryClient)
        mock_registry_client.register = AsyncMock()

        agent = Agent(agent_card, registry=mock_registry_client)

        with patch("protolink.server.AgentServer") as mock_server:
            mock_server_instance = MagicMock()
            mock_server_instance.start = AsyncMock()
            mock_server.return_value = mock_server_instance

            await agent.start(register=True)

            mock_registry_client.register.assert_called_once_with(agent_card)

    @pytest.mark.asyncio
    async def test_stop_with_registry(self, agent_card):
        """Test stopping agent with registry unregistration."""
        mock_registry_client = MagicMock(spec=RegistryClient)
        mock_registry_client.unregister = AsyncMock()

        agent = Agent(agent_card, registry=mock_registry_client)

        with patch("protolink.server.AgentServer") as mock_server:
            mock_server_instance = MagicMock()
            mock_server_instance.stop = AsyncMock()
            mock_server.return_value = mock_server_instance

            await agent.start(register=False)
            await agent.stop()

            mock_registry_client.unregister.assert_called_once_with(agent_card.url)

    @pytest.mark.asyncio
    async def test_discover_agents(self, agent_card):
        """Test discovering agents through registry."""
        mock_registry_client = MagicMock(spec=RegistryClient)
        mock_registry_client.discover = AsyncMock(return_value=[agent_card])

        agent = Agent(agent_card, registry=mock_registry_client)

        discovered = await agent.discover_agents()

        assert len(discovered) == 1
        assert discovered[0] == agent_card
        mock_registry_client.discover.assert_called_once_with(filter_by=None)

    def test_register_and_unregister(self, agent_card):
        """Test manual registration and unregistration."""
        mock_registry_client = MagicMock(spec=RegistryClient)
        mock_registry_client.register = MagicMock()
        mock_registry_client.unregister = MagicMock()

        agent = Agent(agent_card, registry=mock_registry_client)

        agent.register()
        mock_registry_client.register.assert_called_once_with(agent_card)

        agent.unregister()
        mock_registry_client.unregister.assert_called_once_with(agent_card.url)

    def test_transport_url_mismatch(self, agent_card):
        """Test error when transport URL doesn't match agent card URL."""
        transport = DummyTransport("http://different-url.local")

        with pytest.raises(
            ValueError,
            match=r"Transport URL http://different-url\.local does not match AgentCard URL http://test-agent\.local",
        ):
            Agent(agent_card, transport=transport)
