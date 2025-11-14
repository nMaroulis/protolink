"""
ProtoLink - Context Management

Manages conversation contexts and sessions for long-running interactions.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    created_at: str = field(default_factory=lambda: datetime.now(datetime.timezone.utc).isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now(datetime.timezone.utc).isoformat())

    def add_message(self, message) -> "Context":
        """Add a message to this context.

        Args:
            message: Message object to add

        Returns:
            Self for method chaining
        """
        self.messages.append(message)
        self.last_accessed = datetime.now(datetime.timezone.utc).isoformat()
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
            created_at=data.get("created_at", datetime.now(datetime.timezone.utc).isoformat()),
            last_accessed=data.get("last_accessed", datetime.now(datetime.timezone.utc).isoformat()),
        )


class ContextManager:
    """Manages conversation contexts and their lifecycles.

    The ContextManager maintains active contexts, allowing agents to:
    - Track multi-turn conversations
    - Persist messages across requests
    - Share context across multiple agents
    - Clean up expired contexts

    Example:
        manager = ContextManager()
        context = manager.create_context()
        manager.add_message_to_context(context.context_id, message)
        context = manager.get_context(context.context_id)
    """

    def __init__(self):
        """Initialize the context manager."""
        self.contexts: dict[str, Context] = {}

    def create_context(self, context_id: str | None = None) -> Context:
        """Create a new context.

        Args:
            context_id: Optional specific ID (auto-generated if not provided)

        Returns:
            Newly created Context
        """
        if not context_id:
            context_id = str(uuid.uuid4())

        context = Context(context_id=context_id)
        self.contexts[context_id] = context
        return context

    def get_context(self, context_id: str) -> Context | None:
        """Retrieve an existing context.

        Args:
            context_id: ID of context to retrieve

        Returns:
            Context if found, None otherwise
        """
        context = self.contexts.get(context_id)
        if context:
            context.last_accessed = datetime.now(datetime.timezone.utc).isoformat()
        return context

    def add_message_to_context(self, context_id: str, message) -> bool:
        """Add a message to an existing context.

        Args:
            context_id: ID of target context
            message: Message to add

        Returns:
            True if added, False if context not found
        """
        if context := self.get_context(context_id):
            context.add_message(message)
            return True
        return False

    def delete_context(self, context_id: str) -> bool:
        """Remove a context.

        Args:
            context_id: ID of context to delete

        Returns:
            True if deleted, False if not found
        """
        if context_id in self.contexts:
            del self.contexts[context_id]
            return True
        return False

    def list_contexts(self) -> list[Context]:
        """List all active contexts.

        Returns:
            List of all Context objects
        """
        return list(self.contexts.values())

    def clear_all(self) -> None:
        """Remove all contexts."""
        self.contexts.clear()

    def get_context_message_count(self, context_id: str) -> int:
        """Get message count for a context.

        Args:
            context_id: ID of context

        Returns:
            Number of messages, 0 if context not found
        """
        if context := self.get_context(context_id):
            return len(context.messages)
        return 0

    def __repr__(self) -> str:
        return f"ContextManager(contexts={len(self.contexts)})"
