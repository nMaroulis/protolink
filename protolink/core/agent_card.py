from dataclasses import dataclass, field
from typing import Any

@dataclass
class AgentCard:
    """Agent identity and capability declaration.
    
    Attributes:
        name: Agent name
        description: Agent purpose/description
        url: Service endpoint URL
        version: Agent version
        capabilities: Supported features
    """
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: dict[str, Any] = field(default_factory=lambda: {
        "streaming": False,
        "tasks": True
    })
    
    def to_json(self) -> dict[str, Any]:
        """Convert to JSON format (A2A agent card spec)."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": self.capabilities
        }
    
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'AgentCard':
        """Create from JSON format."""
        return cls(
            name=data["name"],
            description=data["description"],
            url=data["url"],
            version=data.get("version", "1.0.0"),
            capabilities=data.get("capabilities", {"streaming": False, "tasks": True})
        )
