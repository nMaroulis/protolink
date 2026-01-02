"""Tests for the Registry class."""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from protolink.discovery.registry import Registry
from protolink.models import AgentCard
from protolink.transport import HTTPTransport, Transport


class DummyTransport(Transport):
    """Minimal registry transport implementation for testing purposes."""

    def __init__(self, url="http://test-registry.local"):
        self._url = url
        self._register_handler = None
        self._unregister_handler = None
        self._discover_handler = None
        self._status_handler = None
        self._started = False

    @property
    def url(self):
        return self._url

    async def send(self, request_spec: Any, base_url: str, data: Any = None, params: dict | None = None) -> Any:
        # Mock generic response for registry operations
        if request_spec.name == "discover":
            return []
        return None

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    def on_register_received(self, handler):
        self._register_handler = handler

    def on_unregister_received(self, handler):
        self._unregister_handler = handler

    def on_discover_received(self, handler):
        self._discover_handler = handler

    def on_status_received(self, handler):
        self._status_handler = handler

    def setup_routes(self, endpoints: list) -> None:
        """Setup routes - dummy implementation for testing."""
        pass

    def validate_url(self) -> bool:
        return True


class TestRegistry:
    """Test cases for the Registry class."""

    @pytest.fixture
    def dummy_transport(self):
        """Create a dummy transport for testing."""
        return DummyTransport()

    @pytest.fixture
    def http_transport(self):
        """Create an HTTP transport for testing."""
        import socket

        # Find a random available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]
        return HTTPTransport(url=f"http://localhost:{port}")

    @pytest.fixture
    def agent_card(self):
        """Create a test agent card."""
        return AgentCard(name="test-agent", description="A test agent", url="http://test-agent.local", version="1.0.0")

    @pytest.fixture
    def agent_card2(self):
        """Create a second test agent card."""
        return AgentCard(
            name="test-agent-2", description="Another test agent", url="http://test-agent2.local", version="1.0.0"
        )

    def test_initialization_with_transport(self, dummy_transport):
        """Test registry initialization with transport."""
        registry = Registry(transport=dummy_transport)
        assert registry._client is not None
        assert registry._server is not None
        assert registry.count() == 0
        assert registry.start_time is None

    def test_initialization_with_url(self):
        """Test registry initialization with URL."""
        registry = Registry(url="http://localhost:9000")
        assert registry._client is not None
        assert registry._server is not None
        assert isinstance(registry._server._transport, HTTPTransport)

    def test_initialization_without_transport_or_url(self):
        """Test registry initialization fails without URL when using default transport."""
        with pytest.raises(ValueError, match="url must be provided if transport is a TransportType"):
            Registry()

    def test_initialization_with_verbose(self):
        """Test registry initialization with verbose level."""
        registry = Registry(url="http://localhost:9000", verbose=3)
        assert registry.logger is not None

    @pytest.mark.asyncio
    async def test_start_stop(self, dummy_transport):
        """Test registry start and stop lifecycle."""
        registry = Registry(transport=dummy_transport)
        assert registry.start_time is None

        await registry.start()
        assert registry.start_time is not None
        assert dummy_transport._started is True

        await registry.stop()
        assert dummy_transport._started is False

    @pytest.mark.asyncio
    async def test_start_with_exception(self, dummy_transport):
        """Test registry start with exception."""
        dummy_transport.start = AsyncMock(side_effect=Exception("Test error"))
        registry = Registry(transport=dummy_transport)

        with pytest.raises(Exception, match="Test error"):
            await registry.start()

    @pytest.mark.asyncio
    async def test_register_agent(self, dummy_transport, agent_card):
        """Test registering an agent."""
        registry = Registry(transport=dummy_transport)

        # Mock the client register method
        registry._client.register = AsyncMock()

        await registry.register(agent_card)
        registry._client.register.assert_called_once_with(agent_card)

    @pytest.mark.asyncio
    async def test_unregister_agent(self, dummy_transport):
        """Test unregistering an agent."""
        registry = Registry(transport=dummy_transport)

        # Mock the client unregister method
        registry._client.unregister = AsyncMock()

        await registry.unregister("http://test-agent.local")
        registry._client.unregister.assert_called_once_with("http://test-agent.local")

    @pytest.mark.asyncio
    async def test_discover_agents(self, dummy_transport):
        """Test discovering agents."""
        registry = Registry(transport=dummy_transport)

        # Mock the client discover method
        expected_agents = [AgentCard(name="test", description="test", url="http://test.local")]
        registry._client.discover = AsyncMock(return_value=expected_agents)

        result = await registry.discover()
        assert result == expected_agents
        registry._client.discover.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_discover_agents_with_filter(self, dummy_transport):
        """Test discovering agents with filter."""
        registry = Registry(transport=dummy_transport)

        # Mock the client discover method
        expected_agents = [AgentCard(name="test", description="test", url="http://test.local")]
        registry._client.discover = AsyncMock(return_value=expected_agents)

        filter_by = {"name": "test"}
        result = await registry.discover(filter_by)
        assert result == expected_agents
        registry._client.discover.assert_called_once_with(filter_by)

    @pytest.mark.asyncio
    async def test_handle_register(self, dummy_transport, agent_card):
        """Test server-side register handler."""
        registry = Registry(transport=dummy_transport)

        await registry.handle_register(agent_card)

        assert registry.count() == 1
        assert agent_card.url in registry._agents
        assert registry._agents[agent_card.url] == agent_card

    @pytest.mark.asyncio
    async def test_handle_unregister(self, dummy_transport, agent_card):
        """Test server-side unregister handler."""
        registry = Registry(transport=dummy_transport)

        # First register an agent
        await registry.handle_register(agent_card)
        assert registry.count() == 1

        # Then unregister it
        await registry.handle_unregister(agent_card.url)
        assert registry.count() == 0
        assert agent_card.url not in registry._agents

    @pytest.mark.asyncio
    async def test_handle_unregister_nonexistent(self, dummy_transport):
        """Test unregistering a non-existent agent."""
        registry = Registry(transport=dummy_transport)

        # Should not raise an exception
        await registry.handle_unregister("http://nonexistent.local")
        assert registry.count() == 0

    @pytest.mark.asyncio
    async def test_handle_discover_no_filter(self, dummy_transport, agent_card, agent_card2):
        """Test server-side discover handler without filter."""
        registry = Registry(transport=dummy_transport)

        # Register some agents
        await registry.handle_register(agent_card)
        await registry.handle_register(agent_card2)

        result = await registry.handle_discover()
        assert len(result) == 2
        assert agent_card in result
        assert agent_card2 in result

    @pytest.mark.asyncio
    async def test_handle_discover_with_filter(self, dummy_transport, agent_card, agent_card2):
        """Test server-side discover handler with filter."""
        registry = Registry(transport=dummy_transport)

        # Register some agents
        await registry.handle_register(agent_card)
        await registry.handle_register(agent_card2)

        # Filter by name
        filter_by = {"name": "test-agent"}
        result = await registry.handle_discover(filter_by, as_json=False)
        assert len(result) == 1
        assert result[0] == agent_card

    @pytest.mark.asyncio
    async def test_handle_discover_filter_no_match(self, dummy_transport, agent_card):
        """Test server-side discover handler with filter that matches nothing."""
        registry = Registry(transport=dummy_transport)

        # Register an agent
        await registry.handle_register(agent_card)

        # Filter by non-existent name
        filter_by = {"name": "nonexistent"}
        result = await registry.handle_discover(filter_by)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_handle_discover_filter_by_nonexistent_field(self, dummy_transport, agent_card):
        """Test server-side discover handler filtering by non-existent field."""
        registry = Registry(transport=dummy_transport)

        # Register an agent
        await registry.handle_register(agent_card)

        # Filter by non-existent field
        filter_by = {"nonexistent": "value"}
        result = await registry.handle_discover(filter_by)
        assert len(result) == 0

    def test_handle_status_html(self, dummy_transport, agent_card):
        """Test server-side status HTML handler."""
        registry = Registry(transport=dummy_transport)
        registry.start_time = time.time()

        # Register an agent
        registry._agents[agent_card.url] = agent_card

        result = registry.handle_status_html()

        assert isinstance(result, str)
        assert "Registry" in result
        assert "HTTP" in result
        assert agent_card.name in result

    def test_handle_status_html_no_start_time(self, dummy_transport):
        """Test server-side status HTML handler without start time."""
        registry = Registry(transport=dummy_transport)
        registry.start_time = None

        result = registry.handle_status_html()

        assert isinstance(result, str)
        assert "Registry" in result
        assert "HTTP" in result

    def test_list_urls(self, dummy_transport, agent_card, agent_card2):
        """Test listing agent URLs."""
        registry = Registry(transport=dummy_transport)

        # Initially empty
        assert registry.list_urls() == []

        # Add agents
        registry._agents[agent_card.url] = agent_card
        registry._agents[agent_card2.url] = agent_card2

        urls = registry.list_urls()
        assert len(urls) == 2
        assert agent_card.url in urls
        assert agent_card2.url in urls

    def test_count(self, dummy_transport, agent_card):
        """Test counting agents."""
        registry = Registry(transport=dummy_transport)

        # Initially empty
        assert registry.count() == 0

        # Add an agent
        registry._agents[agent_card.url] = agent_card
        assert registry.count() == 1

    def test_clear(self, dummy_transport, agent_card, agent_card2):
        """Test clearing all agents."""
        registry = Registry(transport=dummy_transport)

        # Add agents
        registry._agents[agent_card.url] = agent_card
        registry._agents[agent_card2.url] = agent_card2
        assert registry.count() == 2

        # Clear
        registry.clear()
        assert registry.count() == 0
        assert registry.list_urls() == []

    def test_repr(self, dummy_transport):
        """Test registry string representation."""
        registry = Registry(transport=dummy_transport)
        assert repr(registry) == "Registry(agents=0)"

        # Add an agent
        registry._agents["http://test.local"] = AgentCard(name="test", description="test", url="http://test.local")
        assert repr(registry) == "Registry(agents=1)"

    @pytest.mark.asyncio
    async def test_integration_full_lifecycle(self, http_transport, agent_card):
        """Test full registry lifecycle with HTTP transport."""
        registry = Registry(transport=http_transport)

        # Start registry
        await registry.start()
        assert registry.start_time is not None

        # Register agent (directly call handler to avoid network)
        await registry.handle_register(agent_card)
        assert registry.count() == 1

        # Discover agents
        agents = await registry.handle_discover()
        assert len(agents) == 1
        assert agents[0] == agent_card

        # Get status HTML
        status_html = registry.handle_status_html()
        assert agent_card.name in status_html

        # Unregister agent
        await registry.handle_unregister(agent_card.url)
        assert registry.count() == 0

        # Stop registry
        await registry.stop()

    def test_filter_by_multiple_attributes(self, dummy_transport):
        """Test filtering agents by multiple attributes."""
        registry = Registry(transport=dummy_transport)

        # Create agents with different attributes
        agent1 = AgentCard(
            name="agent1", description="desc1", url="http://agent1.local", version="1.0.0", tags=["tag1"]
        )
        agent2 = AgentCard(
            name="agent2", description="desc2", url="http://agent2.local", version="2.0.0", tags=["tag2"]
        )

        registry._agents[agent1.url] = agent1
        registry._agents[agent2.url] = agent2

        # Filter by name and version
        filter_by = {"name": "agent1", "version": "1.0.0"}
        result = asyncio.run(registry.handle_discover(filter_by, as_json=False))
        assert len(result) == 1
        assert result[0] == agent1

        # Filter by non-matching combination
        filter_by = {"name": "agent1", "version": "2.0.0"}
        result = asyncio.run(registry.handle_discover(filter_by, as_json=False))
        assert len(result) == 0
