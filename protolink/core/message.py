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
        role: Sender role (user, agent, system)
        parts: list[Part] = field(default_factory=list)
        timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
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
        """Create from dictionary."""
        parts = [Part.from_dict(p) for p in data.get("parts", [])]
        return cls(
            id=data.get("id", IDGenerator.generate_message_id()),
            role=data.get("role", "user"),
            parts=parts,
            timestamp=data.get("timestamp", utc_now()),
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
