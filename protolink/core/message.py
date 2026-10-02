from dataclasses import dataclass, field
from typing import Any

from protolink.core.part import Part
from protolink.types import MessageRoleType
from protolink.utils.datetime import utc_now
from protolink.utils.id_generator import IDGenerator


@dataclass
class Message:
    """Single unit of communication between agents.

    Attributes:
        id: Unique message identifier
        role: Sender role, such as user, agent, assistant, or system.
        parts: Ordered content parts carried by the message.
        timestamp: ISO timestamp recording message creation.
    """

    id: str = field(default_factory=lambda: IDGenerator.generate_message_id())
    role: MessageRoleType = "user"
    parts: list[Part] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: utc_now())

    def add_text(self, text: str) -> "Message":
        """Add a text part to the message."""
        self.parts.append(Part.text(text))
        return self

    def add_part(self, part: Part) -> "Message":
        """Add a part to the message."""
        self.parts.append(part)
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Restore parts and retain supplied identity and timestamp fields.

        Missing IDs and timestamps are generated for newly constructed messages.
        """
        parts = [Part.from_dict(p) for p in data.get("parts", [])]
        return cls(
            id=data["id"] if "id" in data else IDGenerator.generate_message_id(),
            role=data.get("role", "user"),
            parts=parts,
            timestamp=data["timestamp"] if "timestamp" in data else utc_now(),
        )

    @classmethod
    def user(cls, text: str) -> "Message":
        """Create a user message with text (convenience method)."""
        return cls(role="user").add_text(text)

    @classmethod
    def agent(cls, text: str) -> "Message":
        """Create an agent message with text (convenience method)."""
        return cls(role="agent").add_text(text)

    @classmethod
    def assistant(cls, text: str) -> "Message":
        """Create an assistant message with text (convenience method)."""
        return cls(role="assistant").add_text(text)

    @classmethod
    def route(
        cls,
        route_key: str,
        *,
        reason: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Message":
        """Create an agent message with a structured route decision."""
        return cls(
            role="agent",
            parts=[
                Part.route(
                    route_key,
                    reason=reason,
                    confidence=confidence,
                    metadata=metadata,
                )
            ],
        )

    @classmethod
    def infer(
        cls,
        *,
        prompt: str | None = None,
        user: str | None = None,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Message":
        """Create a user message with an infer part (convenience method)."""
        part = Part.infer(
            prompt=prompt,
            user=user,
            output_schema=output_schema,
            metadata=metadata,
        )
        return cls(role="user", parts=[part])

    @classmethod
    def tool_call(
        cls,
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> "Message":
        """Create a user message with a tool_call part (convenience method)."""
        part = Part.tool_call(
            tool_name=tool_name,
            args=args or {},
            call_id=call_id,
        )
        return cls(role="user", parts=[part])
