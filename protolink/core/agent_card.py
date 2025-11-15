from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentCapabilities:
    """Defines the capabilities and limitations of an agent.

    Attributes:
        streaming: Whether the agent supports Server-Sent Events (SSE) streaming
        push_notifications: Whether the agent supports push notifications (webhooks) for task updates
        state_transition_history: Whether the agent can provide a detailed history of task state transitions
        max_concurrency: Maximum number of concurrent tasks the agent can handle
        message_batching: Whether the agent can process multiple messages in a single request
        tool_calling: Whether the agent can call external tools/APIs
        multi_step_reasoning: Whether the agent can perform multi-step reasoning
        timeout_support: Whether the agent respects timeouts for operations
        delegation: Whether the agent can delegate tasks to other agents
        rag_support: Whether the agent supports Retrieval-Augmented Generation
        code_execution: Whether the agent has access to a safe execution sandbox
    """

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False
    # Extensions to A2A spec
    max_concurrency: int = 1
    message_batching: bool = False
    tool_calling: bool = False
    multi_step_reasoning: bool = False
    timeout_support: bool = False
    delegation: bool = False
    rag_support: bool = False
    code_execution: bool = False


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
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    security_schemes: dict[str, dict[str, Any]] | None = field(default_factory=dict)
    required_scopes: list[str] | None = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON format (A2A agent card spec)."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": asdict(self.capabilities) if self.capabilities else {},
            "securitySchemes": self.security_schemes,
            "requiredScopes": self.required_scopes,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AgentCard":
        """Create from JSON format."""
        capabilities_data = data.get("capabilities", {})
        capabilities = AgentCapabilities(**capabilities_data) if capabilities_data else AgentCapabilities()

        return cls(
            name=data["name"],
            description=data["description"],
            url=data["url"],
            version=data.get("version", "1.0.0"),
            capabilities=capabilities,
            security_schemes=data.get("securitySchemes", {}),
            required_scopes=data.get("requiredScopes", []),
        )
