from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, final

from protolink import __version__ as protolink_version
from protolink.types import AgentRoleType, MimeType, SecuritySchemeType, TransportType
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AgentCapabilities:
    """Defines the capabilities and limitations of an agent.

    Attributes:
        streaming: Whether the agent supports Server-Sent Events (SSE) streaming
        push_notifications: Whether the agent supports push notifications (webhooks) for task updates
        state_transition_history: Whether the agent can provide a detailed history of task state transitions
        delegation: Whether the agent can delegate tasks to other agents
        has_llm: Whether the agent has an LLM as a core component (brain)
        max_concurrency: Maximum number of concurrent tasks the agent can handle
        message_batching: Whether the agent can process multiple messages in a single request
        tool_calling: Whether the agent can call external tools/APIs
        multi_step_reasoning: Whether the agent can perform multi-step reasoning
        timeout_support: Whether the agent respects timeouts for operations
        rag: Whether the agent supports Retrieval-Augmented Generation
        code_execution: Whether the agent has access to a safe execution sandbox
    """

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False
    # ProtoLink-native discovery and runtime fields
    delegation: bool = True
    has_llm: bool = False
    max_concurrency: int = 1
    message_batching: bool = False
    tool_calling: bool = False
    multi_step_reasoning: bool = False
    timeout_support: bool = False
    rag: bool = False
    code_execution: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return all capabilities as a dict."""
        return asdict(self)

    def enabled(self) -> list[str]:
        """Return a list of enabled capabilities (truthy ones)."""
        result = []
        for k, v in asdict(self).items():
            if isinstance(v, bool) and v:
                result.append(k)
            elif isinstance(v, int) and v > 0:
                result.append(f"{k}: {v}")
        return result


@dataclass
class AgentSkill:
    """Represents a task that an agent can perform.

    Attributes:
        id: Unique Human-readable identifier for the task
        description: Detailed description of what the task does [Optional]
        input_schema: Schema for the input data (JSON schema) [Optional]
        output_schema: Schema for the output data (JSON schema) [Optional]
        tags: List of tags for categorization [Optional]
        examples: Example inputs, outputs, or usage scenarios [Optional]
    """

    id: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    examples: list[Any] = field(default_factory=list)

    def __post_init__(self):
        """Validate fields after initialization."""
        if self.tags is None:
            self.tags = []
        if self.examples is None:
            self.examples = []
        if self.input_schema is None:
            self.input_schema = {}
        if self.output_schema is None:
            self.output_schema = {}


@dataclass(frozen=True, slots=True)
class AgentInterface:
    """Describe an additional endpoint exposed by an agent.

    ``AgentCard.url`` and ``AgentCard.transport`` remain the primary interface. Use this type only when the same agent
    is reachable through more than one transport, such as HTTP for broad compatibility and gRPC for internal calls.

    Args:
        url: Absolute endpoint URL.
        transport: Registered ProtoLink transport name.
        protocol_version: Protocol version served by this endpoint.
    """

    url: str
    transport: TransportType
    protocol_version: str = protolink_version

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentInterface:
        """Create an interface from serialized card data."""
        return cls(
            url=str(data["url"]),
            transport=data.get("transport", "http"),
            protocol_version=str(data.get("protocolVersion", protolink_version)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the interface in AgentCard wire format."""
        return {
            "url": self.url,
            "transport": self.transport,
            "protocolVersion": self.protocol_version,
        }


@final
@dataclass
class AgentCard:
    """Agent identity and capability declaration.

    Attributes:
        name: Agent name
        description: Agent purpose/description
        url: Service endpoint URL
        version: Agent version
        protocol_version: Legacy ProtoLink native discovery-card version. A2A adapters advertise their protocol version
            per interface instead.
        capabilities: Supported features
        skills: List of skills the agent can perform
        input_formats: List of supported input formats
        output_formats: List of supported output formats
        security_schemes: Security schemes for authentication
        role: ProtoLink-native role describing the agent's responsibility in the runtime topology
        tags: Optional List of tags for categorization. These tags can be used for filtering during ProtoLink discovery.
            E.g. "finance", "travel", "math" etc.
        interfaces: Optional additional endpoints for this same agent identity.
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
    role: AgentRoleType = "worker"
    tags: list[str] = field(default_factory=list)
    interfaces: list[AgentInterface] = field(default_factory=list)

    def __post_init__(self):
        """Normalize fields after initialization."""
        # If capabilities is passed as a dict, convert it to AgentCapabilities and fill missing fields with defaults
        capabilities: Any = self.capabilities
        if isinstance(capabilities, Mapping):
            self.capabilities = AgentCapabilities(**dict(capabilities))
        elif not isinstance(capabilities, AgentCapabilities):
            raise TypeError(f"capabilities must be AgentCapabilities or mapping, got {type(capabilities).__name__}")
        raw_interfaces: list[Any] = list(self.interfaces)
        self.interfaces = [
            AgentInterface.from_dict(interface) if isinstance(interface, Mapping) else interface
            for interface in raw_interfaces
        ]
        if not all(isinstance(interface, AgentInterface) for interface in self.interfaces):
            raise TypeError("interfaces must contain AgentInterface instances or mappings")

    def to_dict(self) -> dict[str, Any]:
        """Convert to ProtoLink's native discovery-card JSON format.

        Standard A2A bindings use their own versioned serializers at the wire boundary; see :mod:`protolink.a2a.v1`.
        """
        data = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "transport": self.transport,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "capabilities": asdict(self.capabilities) if self.capabilities else {},
            "skills": [asdict(skill) for skill in self.skills],
            "inputFormats": self.input_formats,
            "outputFormats": self.output_formats,
            "securitySchemes": self.security_schemes,
            "tags": self.tags,
        }
        if self.interfaces:
            data["additionalInterfaces"] = [interface.to_dict() for interface in self.interfaces]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        """Create from Python dict/JSON data."""

        cls._validate_fields(data)

        capabilities_data = data.get("capabilities", {})
        capabilities = AgentCapabilities(**capabilities_data) if capabilities_data else AgentCapabilities()
        skills = [AgentSkill(**skill_data) for skill_data in data.get("skills", [])]

        return cls(
            name=data["name"],
            description=data["description"],
            url=data["url"],
            transport=data.get("transport", "http"),
            version=data.get("version", "1.0.0"),
            protocol_version=data.get("protocolVersion", protolink_version),
            capabilities=capabilities,
            skills=skills,
            input_formats=data.get("inputFormats", ["text/plain"]),
            output_formats=data.get("outputFormats", ["text/plain"]),
            security_schemes=data.get("securitySchemes", {}),
            tags=data.get("tags", []),
            interfaces=data.get("interfaces", data.get("additionalInterfaces", [])),
        )

    @staticmethod
    def _validate_fields(data: dict[str, Any]) -> None:
        """Perform strict validation of mandatory AgentCard fields."""

        # 1. Name is mandatory for identity
        if not data.get("name"):
            raise ValueError(
                "\033[1mAgentCard\033[22m :: Missing required field \033[1mname\033[22m. "
                "The agent must have a unique name for identification."
            )

        # 2. Description is mandatory - helps other agents discover capabilities
        if not data.get("description"):
            raise ValueError(
                "\033[1mAgentCard\033[22m :: Missing required field \033[1mdescription\033[22m. "
                "A description is required so other agents can identify what this agent does and how to interact with it."  # noqa: E501
            )

        # 3. URL is mandatory - required for transport and registration
        if not data.get("url"):
            raise ValueError(
                "\033[1mAgentCard\033[22m :: Missing required field \033[1murl\033[22m. "
                "An agent cannot register to a registry or use the underlying transport layer without a valid URL endpoint."  # noqa: E501
            )

    def get_prompt_format(self) -> str:
        """Generate deterministic JSON metadata for delegation prompts.

        The result is a complete JSON object rather than a Python-style repr, so quotes, newlines, booleans, and nested
        schemas cannot corrupt the surrounding prompt. Capabilities are emitted as an explicit data object, and skills
        are sorted by identifier for stable prompt caching.

        The format includes:
        - Agent name and description
        - Capability metadata
        - List of tools with their schemas (if any skills are registered)

        Example:
            {
              "capabilities": {"delegation": true},
              "description": "Weather forecasts",
              "name": "weather_agent",
              "tools": [
                {
                  "description": "Return a forecast",
                  "examples": [{"location": "Athens"}],
                  "input_schema": {"type": "object"},
                  "name": "get_weather",
                  "output_schema": {"type": "object"}
                }
              ]
            }

        Returns:
            A valid JSON object describing the agent and its capabilities.
        """
        tools = [
            {
                "name": skill.id,
                "description": skill.description,
                "input_schema": skill.input_schema,
                "output_schema": skill.output_schema,
                "examples": skill.examples,
            }
            for skill in sorted(self.skills, key=lambda item: item.id)
        ]
        metadata = {
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities.as_dict(),
            "tools": tools,
        }
        return json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, default=str)
