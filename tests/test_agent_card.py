"""Tests for the AgentCard class."""

from protolink.core.agent_card import AgentCapabilities, AgentCard


def test_agent_card_initialization():
    """Test AgentCard initialization with required fields."""
    card = AgentCard(name="test-agent", description="A test agent", url="http://test-agent.local")

    assert card.name == "test-agent"
    assert card.description == "A test agent"
    assert card.url == "http://test-agent.local"
    assert card.version == "1.0.0"
    assert isinstance(card.capabilities, AgentCapabilities)
    assert card.capabilities.streaming is False
    assert card.security_schemes == {}


def test_agent_card_custom_values():
    """Test AgentCard initialization with custom values."""
    capabilities = AgentCapabilities(streaming=True, tool_calling=True)
    card = AgentCard(
        name="custom-agent",
        description="Custom agent with settings",
        url="http://custom.local",
        version="2.0.0",
        capabilities=capabilities,
        security_schemes={"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
    )

    assert card.version == "2.0.0"
    assert card.capabilities == capabilities
    assert card.capabilities.streaming is True
    assert card.capabilities.tool_calling is True
    assert card.security_schemes == {"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}


def test_to_dict():
    """Test conversion to JSON format."""
    capabilities = AgentCapabilities(streaming=True, tool_calling=True)
    card = AgentCard(
        name="json-agent",
        description="Agent for JSON testing",
        url="http://json-test.local",
        capabilities=capabilities,
        security_schemes={"bearer": {"type": "http", "scheme": "bearer"}},
    )

    json_data = card.to_dict()

    assert json_data["name"] == "json-agent"
    assert json_data["description"] == "Agent for JSON testing"
    assert json_data["url"] == "http://json-test.local"
    assert json_data["version"] == "1.0.0"
    assert json_data["capabilities"]["streaming"] is True
    assert json_data["capabilities"]["tool_calling"] is True
    assert json_data["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}


def test_from_dict():
    """Test creation from JSON data."""
    json_data = {
        "name": "from-json",
        "description": "Agent created from JSON",
        "url": "http://from-json.local",
        "version": "3.0.0",
        "capabilities": {"streaming": True, "tool_calling": True},
        "securitySchemes": {"oauth2": {"type": "oauth2"}},
    }

    card = AgentCard.from_dict(json_data)

    assert card.name == "from-json"
    assert card.description == "Agent created from JSON"
    assert card.url == "http://from-json.local"
    assert card.version == "3.0.0"
    assert isinstance(card.capabilities, AgentCapabilities)
    assert card.capabilities.streaming is True
    assert card.capabilities.tool_calling is True
    assert card.security_schemes == {"oauth2": {"type": "oauth2"}}


def test_from_dict_missing_fields():
    """Test from_dict with missing optional fields."""
    json_data = {"name": "minimal-agent", "description": "Minimal agent", "url": "http://minimal.local"}

    card = AgentCard.from_dict(json_data)

    assert card.name == "minimal-agent"
    assert card.version == "1.0.0"  # Default value
    assert isinstance(card.capabilities, AgentCapabilities)
    assert card.capabilities.streaming is False  # Default value
    assert card.security_schemes == {}  # Default empty dict
