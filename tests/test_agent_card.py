"""Tests for the AgentCard class."""

from protolink.core.agent_card import AgentCard


def test_agent_card_initialization():
    """Test AgentCard initialization with required fields."""
    card = AgentCard(name="test-agent", description="A test agent", url="http://test-agent.local")

    assert card.name == "test-agent"
    assert card.description == "A test agent"
    assert card.url == "http://test-agent.local"
    assert card.version == "1.0.0"
    assert card.capabilities == {"streaming": False, "tasks": True}


def test_agent_card_custom_values():
    """Test AgentCard initialization with custom values."""
    card = AgentCard(
        name="custom-agent",
        description="Custom agent with settings",
        url="http://custom.local",
        version="2.0.0",
        capabilities={"streaming": True, "custom_capability": 42},
        security_schemes={"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        required_scopes=["read:data", "write:data"],
    )

    assert card.version == "2.0.0"
    assert card.capabilities == {"streaming": True, "custom_capability": 42}
    assert card.security_schemes == {"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
    assert card.required_scopes == ["read:data", "write:data"]


def test_to_json():
    """Test conversion to JSON format."""
    card = AgentCard(
        name="json-agent",
        description="Agent for JSON testing",
        url="http://json-test.local",
        security_schemes={"bearer": {"type": "http", "scheme": "bearer"}},
        required_scopes=["read:data"],
    )

    json_data = card.to_json()

    assert json_data == {
        "name": "json-agent",
        "description": "Agent for JSON testing",
        "url": "http://json-test.local",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "tasks": True},
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "requiredScopes": ["read:data"],
    }


def test_from_json():
    """Test creation from JSON data."""
    json_data = {
        "name": "from-json",
        "description": "Agent created from JSON",
        "url": "http://from-json.local",
        "version": "3.0.0",
        "capabilities": {"streaming": True},
        "securitySchemes": {"oauth2": {"type": "oauth2"}},
        "requiredScopes": ["read:data"],
    }

    card = AgentCard.from_json(json_data)

    assert card.name == "from-json"
    assert card.description == "Agent created from JSON"
    assert card.url == "http://from-json.local"
    assert card.version == "3.0.0"
    assert card.capabilities == {"streaming": True}
    assert card.security_schemes == {"oauth2": {"type": "oauth2"}}
    assert card.required_scopes == ["read:data"]


def test_from_json_missing_fields():
    """Test from_json with missing optional fields."""
    json_data = {"name": "minimal-agent", "description": "Minimal agent", "url": "http://minimal.local"}

    card = AgentCard.from_json(json_data)

    assert card.name == "minimal-agent"
    assert card.version == "1.0.0"  # Default value
    assert card.capabilities == {"streaming": False, "tasks": True}  # Default value
    assert card.security_schemes == {}  # Default empty dict
    assert card.required_scopes == []  # Default empty list
