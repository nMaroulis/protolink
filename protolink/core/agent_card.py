from dataclasses import asdict, dataclass, field
from typing import Any

from protolink import __version__ as protolink_version
from protolink.types import MimeType, SecuritySchemeType, TransportType
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


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
        rag: Whether the agent supports Retrieval-Augmented Generation
        code_execution: Whether the agent has access to a safe execution sandbox
    """

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False
    # Extensions to A2A spec
    has_llm: bool = False
    max_concurrency: int = 1
    message_batching: bool = False
    tool_calling: bool = False
    multi_step_reasoning: bool = False
    timeout_support: bool = False
    delegation: bool = False
    rag: bool = False
    code_execution: bool = False


@dataclass
class AgentSkill:
    """Represents a task that an agent can perform.

    Attributes:
        id: Unique Human-readable identifier for the task
        description: Detailed description of what the task does [Optional]
        tags: List of tags for categorization [Optional]
        examples: Example inputs or usage scenarios [Optional]
    """

    id: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate fields after initialization."""
        if self.tags is None:
            self.tags = []
        if self.examples is None:
            self.examples = []


@dataclass
class AgentCard:
    """Agent identity and capability declaration.

    Attributes:
        name: Agent name
        description: Agent purpose/description
        url: Service endpoint URL
        version: Agent version
        protocol_version: Protolink Protocol version
        capabilities: Supported features
        skills: List of skills the agent can perform
        input_formats: List of supported input formats
        output_formats: List of supported output formats
        security_schemes: Security schemes for authentication
    """

    name: str
    description: str
    url: str
    transport: TransportType = "http"
    version: str = "1.0.0"
    protocol_version: str = protolink_version
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = field(default_factory=list)
    input_formats: list[MimeType] = field(default_factory=lambda: ["text/plain"])
    output_formats: list[MimeType] = field(default_factory=lambda: ["text/plain"])
    security_schemes: dict[SecuritySchemeType, dict[str, Any]] | None = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON format (A2A agent card spec)."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "capabilities": asdict(self.capabilities) if self.capabilities else {},
            "skills": [asdict(skill) for skill in self.skills],
            "inputFormats": self.input_formats,
            "outputFormats": self.output_formats,
            "securitySchemes": self.security_schemes,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AgentCard":
        """Create from JSON format."""

        cls._validate_fields(data)

        capabilities_data = data.get("capabilities", {})
        capabilities = AgentCapabilities(**capabilities_data) if capabilities_data else AgentCapabilities()
        skills = [AgentSkill(**skill_data) for skill_data in data.get("skills", [])]

        return cls(
            name=data["name"],
            description=data["description"],
            url=data["url"],
            version=data.get("version", "1.0.0"),
            protocol_version=data.get("protocolVersion", protolink_version),
            capabilities=capabilities,
            skills=skills,
            input_formats=data.get("inputFormats", ["text/plain"]),
            output_formats=data.get("outputFormats", ["text/plain"]),
            security_schemes=data.get("securitySchemes", {}),
        )

    @staticmethod
    def _validate_fields(data: dict[str, Any]) -> None:
        """Validate fields."""
        required_fields = ["name", "description", "url"]
        for f in required_fields:
            if f not in data:
                raise ValueError(f"AgentCard :: Missing required field: {f}")
