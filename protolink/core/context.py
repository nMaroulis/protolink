"""
ProtoLink - Context Management

Manages conversation contexts and sessions for long-running interactions.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from protolink.utils import utc_now


@dataclass
class Context:
    """Represents a conversation context (session).

    Contexts group messages across multiple turns, enabling
    long-running conversations and session persistence.

    Attributes:
        context_id: Unique identifier for this context
        messages: All messages in this context
        metadata: Custom context data
        created_at: When context was created
        last_accessed: Last activity timestamp
    """

    context_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    messages: list = field(default_factory=list)  # List[Message]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())
    last_accessed: str = field(default_factory=lambda: utc_now())

    def add_message(self, message) -> "Context":
        """Add a message to this context.

        Args:
            message: Message object to add

        Returns:
            Self for method chaining
        """
        self.messages.append(message)
        self.last_accessed = str(utc_now())
        return self

    def to_dict(self) -> dict:
        """Convert context to dictionary."""
        return {
            "context_id": self.context_id,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Context":
        """Create context from dictionary."""
        from .message import Message

        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            context_id=data.get("context_id", str(uuid.uuid4())),
            messages=messages,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", utc_now()),
            last_accessed=data.get("last_accessed", utc_now()),
        )
