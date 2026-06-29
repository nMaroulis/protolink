from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class LLMMessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class LLMMessage:
    """
    Canonical message format used internally across all LLM providers.
    """

    role: LLMMessageRole
    content: str

    # Optional but strongly recommended
    name: str | None = None  # tool name / function name
    metadata: dict[str, Any] = field(default_factory=dict)

    # Observability & tracing
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # provider specific fields
    tool_calls: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert message to a JSON-serializable dictionary."""
        return {
            "role": self.role.value,
            "content": self.content,
            "name": self.name,
            "metadata": self.metadata,
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "tool_calls": self.tool_calls,
            "tool_name": self.tool_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMMessage:
        """Create a message from a dictionary."""
        return cls(
            role=LLMMessageRole(data["role"]),
            content=data["content"],
            name=data.get("name"),
            metadata=data.get("metadata", {}),
            id=data.get("id", str(uuid4())),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(timezone.utc),
            tool_calls=data.get("tool_calls", {}),
            tool_name=data.get("tool_name"),
        )


class ConversationHistory:
    """
    Manages conversation state in a provider-agnostic way.

    This implementation uses a `collections.deque` as the underlying data structure
    to optimize for frequent prepending of system messages and message truncation.

    Time Complexity:
        - add_*: O(1)
        - set_system: O(1) when prepending (was O(N) with list)
        - truncate: O(M) where M is the number of messages to remove
        - messages (property): O(N) due to serialization

    Space Complexity:
        - O(N) where N is the number of messages in history.
    """

    __slots__ = ("_messages",)

    def __init__(self, system_prompt: str | None = None):
        """Initialize the conversation history.

        Args:
            system_prompt: Optional initial system instruction.
        """
        self._messages: deque[LLMMessage] = deque()
        if system_prompt:
            self.add_system(system_prompt)

    # ----------------------------------------------------------------------
    # append helpers
    # ----------------------------------------------------------------------

    def add_system(self, content: str) -> None:
        """Add a system message to the history.

        Time: O(1)
        """
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=content,
            )
        )

    def add_user(self, content: str, **metadata: Any) -> None:
        """Add a user message to the history.

        Time: O(1)
        """
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.USER,
                content=content,
                metadata=metadata,
            )
        )

    def add_assistant(self, content: str, **metadata: Any) -> None:
        """Add an assistant message to the history.

        Time: O(1)
        """
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.ASSISTANT,
                content=content,
                metadata=metadata,
            )
        )

    def add_tool(
        self,
        content: str,
        tool_name: str,
        **metadata: Any,
    ) -> None:
        """Add a tool response to the history.

        Time: O(1)
        """
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.TOOL,
                content=content,
                name=tool_name,
                metadata=metadata,
            )
        )

    def add_raw(self, message: dict[str, Any]) -> None:
        """Add a raw message to the conversation history.

        Time: O(1)
        """
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole(message["role"]),
                content=message.get("content", ""),
                tool_calls=message.get("tool_calls", {}),
            )
        )

    def reset_to_system(self, content: str) -> None:
        """Reset the conversation history to only include the system prompt.

        Time: O(1)
        """
        self._messages.clear()
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=content,
            )
        )

    def set_system(self, content: str) -> None:
        """Set or update the system prompt without wiping the rest of the history.

        If a system message exists at the beginning, it is updated in-place.
        Otherwise, a new system message is prepended to the deque.

        Time: O(1) (Improved from O(N) by using deque.appendleft)
        """
        if self._messages and self._messages[0].role == LLMMessageRole.SYSTEM:
            self._messages[0] = LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=content,
            )
        else:
            self._messages.appendleft(
                LLMMessage(
                    role=LLMMessageRole.SYSTEM,
                    content=content,
                ),
            )

    # ----------------------------------------------------------------------
    # accessors
    # ----------------------------------------------------------------------

    def messages_raw(self) -> list[LLMMessage]:
        """Return a shallow copy of messages as a list.

        Time: O(N)
        """
        return list(self._messages)

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Convert messages to standard LLM readable format.

        Returns:
            List of dictionaries in the format expected by most LLM APIs.

        Time: O(N)
        """
        return [
            {"role": msg.role.value, "content": msg.content, **({"name": msg.name} if msg.name else {})}
            for msg in self._messages
        ]

    def to_list(self) -> list[dict[str, Any]]:
        """Convert entire history to a list of full message dictionaries.

        Time: O(N)
        """
        return [msg.to_dict() for msg in self._messages]

    def copy(self) -> ConversationHistory:
        """Return an independent copy of this conversation history.

        The copied history preserves every canonical message field, including
        provider-specific metadata such as tool-call payloads. Agents use this
        when a run needs an isolated working history without mutating the
        LLM's default history object.

        Time: O(N)
        """
        return ConversationHistory.from_list(self.to_list())

    def replace(self, messages_data: Iterable[dict[str, Any]]) -> None:
        """Replace all messages while preserving this history object's identity.

        This is primarily useful for transformations such as history
        compaction. Rebuilding the internal deque in one operation keeps
        external references to the ``ConversationHistory`` instance valid and
        rehydrates every message through the canonical ``LLMMessage`` model.

        Args:
            messages_data: Full message dictionaries in chronological order,
                such as the output of :meth:`to_list`.

        Time: O(N)
        """
        self._messages = deque(LLMMessage.from_dict(message) for message in messages_data)

    @classmethod
    def from_list(cls, messages_data: list[dict[str, Any]]) -> ConversationHistory:
        """Create a history instance from a list of full message dictionaries.

        Time: O(N)
        """
        history = cls()
        history._messages = deque(LLMMessage.from_dict(m) for m in messages_data)
        return history

    def __iter__(self) -> Iterable[LLMMessage]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    # ----------------------------------------------------------------------
    # advanced controls
    # ----------------------------------------------------------------------

    def truncate(self, max_messages: int) -> None:
        """
        Truncate history while ALWAYS preserving the system prompt.

        Args:
            max_messages: Maximum number of messages to retain (including system prompt).

        Time: O(M) where M is the number of messages to remove (popleft is O(1)).
        """
        if max_messages < 2:
            raise ValueError("max_messages must be >= 2")

        if len(self._messages) <= max_messages:
            return

        system = self._messages.popleft()
        # Keep only the last (max_messages - 1) messages
        while len(self._messages) >= max_messages:
            self._messages.popleft()

        self._messages.appendleft(system)
