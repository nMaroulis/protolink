"""Tests for the Agent class."""

import asyncio
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from protolink.agents import Agent
from protolink.client import RegistryClient
from protolink.core.agent_card import AgentCard, AgentSkill
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.tools import BaseTool
from protolink.transport import Transport


class DummyTransport(Transport):
    """Minimal transport implementation for testing purposes."""

    def __init__(self, url="http://test-transport.local"):
        self.handler = None
        self._url = url
        self._agent_card_handler = None

    @property
    def url(self):
        return self._url

    async def send(self, request_spec: Any, base_url: str, data: Any = None, params: dict | None = None) -> Any:
        # For testing, we might want to return different things based on request_spec
        if request_spec.name == "send_task":
            # Return the task assuming it was echo'd or similar
            if data:
                return data
            return Task.create(Message.agent("dummy"))
        elif request_spec.name == "send_message":
            return Message.agent("dummy")
        elif request_spec.name == "get_agent_card":
            return AgentCard(name="dummy", description="dummy", url="local://dummy")
        return None

    async def start(self) -> None:  # pragma: no cover
        pass

    async def stop(self) -> None:  # pragma: no cover
        pass

    def validate_url(self) -> bool:
        return True


class DummyLLM(LLM):
    """Mock LLM for testing."""

    model_type = "dummy"
    provider = "dummy_provider"
    model = "dummy_model"
    model_params: ClassVar[dict] = {}
    system_prompt = ""

    def __init__(self):
        # Use class-level defaults
        super().__init__(model=self.model, model_params=self.model_params.copy())

    def call(self, history: ConversationHistory) -> str:
        """Generate a response from the LLM."""
        return "Mock response"

    async def call_stream(self, history: ConversationHistory):
        """Generate a streaming response from the LLM."""
        yield "Mock stream response"

    def validate_connection(self) -> bool:
        return True

    def infer(self, query: str, tools: dict[str, BaseTool]) -> Part:
        return Part("infer_response", "Mock infer response")


class DummyTool(BaseTool):
    """Mock tool for testing."""

    def __init__(self, name="test_tool", description="Test tool"):
        self.name = name
        self.description = description
        self.input_schema = {}
        self.output_schema = {}
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
        assert agent.get_agent_card(as_json=False) == agent_card

    # @pytest.mark.asyncio
    # async def test_handle_task_not_implemented(self, agent):
    #     """Test handle_task raises NotImplementedError by default."""
    #     task = Task.create(Message.user("test"))
    #     with pytest.raises(NotImplementedError):
    #         await agent.handle_task(task)

    @pytest.mark.asyncio
    async def test_process_method(self, agent):
        """Test the process method with a simple echo response."""

        # Create a test agent that implements handle_task
        class TestAgent(Agent):
            async def handle_task(self, task):
                return task.complete("Test response")

        test_agent = TestAgent(agent.card)
        response = await test_agent.process("Hello")
        assert response == "Test response"

    def test_set_transport(self, agent):
        """Test setting the transport."""
        transport = DummyTransport(url=agent.card.url)
        agent.set_transport(transport)
        assert agent.client is not None
        assert agent.server is not None

    @pytest.mark.asyncio
    async def test_send_task_to(self, agent):
        """Test sending a task to another agent."""
        # Create an AsyncMock for the transport
        transport = DummyTransport(url=agent.card.url)
        transport.send = AsyncMock(return_value=Task.create(Message.agent("Response")))
        agent.set_transport(transport)

        # Create a test task
        task = Task.create(Message.user("Test"))

        # Test sending the task
        response = await agent.send_task_to("http://other-agent.local", task)

        # Verify the response and that transport was called correctly
        assert isinstance(response, Task)
        # Check that send was called. We can check arguments strictly or loosely.
        # endpoint, base_url, data=...
        transport.send.assert_awaited_once()
        args, kwargs = transport.send.await_args
        assert args[1] == "http://other-agent.local"  # base_url
        assert kwargs["data"] == task

    @pytest.mark.asyncio
    async def test_send_message_to(self, agent):
        """Test sending a message to another agent."""
        transport = DummyTransport(url=agent.card.url)
        # The transport should return a Task when send_task is called (which send_message uses)
        transport.send = AsyncMock(return_value=Task.create(Message.agent("Response message")))
        agent.set_transport(transport)

        message = Message.user("Test message")
        response = await agent.send_message_to("http://other-agent.local", message)

        assert isinstance(response, Message)
        assert response.role == "agent"
        transport.send.assert_awaited_once()
        args, kwargs = transport.send.await_args
        assert args[1] == "http://other-agent.local"
        assert kwargs["data"].messages[0].parts[0].content == message.parts[0].content

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
            patch("protolink.agents.base.get_transport") as mock_get_transport,
        ):
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_transport_instance = MagicMock()
            mock_get_transport.return_value = mock_transport_instance

            # Pass both registry (transport type) and registry_url
            agent = Agent(agent_card, registry="http", registry_url="http://registry.local")

            assert agent.registry_client is not None
            mock_client_class.assert_called_once_with(transport=mock_transport_instance)
            mock_get_transport.assert_called_once_with("http", url="http://registry.local")

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
        # Invalid registry type logs an error but doesn't raise an exception
        agent = Agent(agent_card, registry=123)
        # registry_client should be None when invalid type is provided
        assert agent.registry_client is None

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
            async def handle_task(self, task):
                return task.complete("Test response")

        test_agent = TestAgent(agent.card)
        task = Task.create(Message.user("test"))

        events = []
        async for event in test_agent.handle_task_streaming(task):
            events.append(event)

        # Should have status update, artifact update (if any), and completion
        assert len(events) >= 2

        # First event should be working status
        assert events[0].new_state == "working"

        # Last event should be completion (not error)
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

        with pytest.raises(ValueError, match="Unknown transport name: invalid"):
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

    @pytest.mark.asyncio
    async def test_register_and_unregister(self, agent_card):
        """Test manual registration and unregistration."""
        mock_registry_client = MagicMock(spec=RegistryClient)
        mock_registry_client.register = AsyncMock()
        mock_registry_client.unregister = AsyncMock()

        agent = Agent(agent_card, registry=mock_registry_client)

        await agent.register()
        mock_registry_client.register.assert_called_once_with(agent_card)

        await agent.unregister()
        mock_registry_client.unregister.assert_called_once_with(agent_card.url)

    def test_transport_url_mismatch(self, agent_card):
        """Test error when transport URL doesn't match agent card URL."""
        transport = DummyTransport("http://different-url.local")

        with pytest.raises(
            ValueError,
            match=r"Transport URL http://different-url\.local does not match AgentCard URL http://test-agent\.local",
        ):
            Agent(agent_card, transport=transport)
