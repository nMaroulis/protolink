from __future__ import annotations

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


class ConversationHistory:
    """
    Manages conversation state in a provider-agnostic way.
    """

    __slots__ = ("_messages",)

    def __init__(self, system_prompt: str | None = None):
        self._messages: list[LLMMessage] = []
        if system_prompt:
            self.add_system(system_prompt)

    # ----------------------------------------------------------------------
    # append helpers
    # ----------------------------------------------------------------------

    def add_system(self, content: str) -> None:
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=content,
            )
        )

    def add_user(self, content: str, **metadata: Any) -> None:
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.USER,
                content=content,
                metadata=metadata,
            )
        )

    def add_assistant(self, content: str, **metadata: Any) -> None:
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
        self._messages.append(
            LLMMessage(
                role=LLMMessageRole.TOOL,
                content=content,
                name=tool_name,
                metadata=metadata,
            )
        )

    def reset_to_system(self, content: str) -> None:
        """Reset the conversation history to only include the system prompt."""
        self._messages = [
            LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=content,
            )
        ]

    # ----------------------------------------------------------------------
    # accessors
    # ----------------------------------------------------------------------

    def messages_raw(self) -> list[LLMMessage]:
        """Return a shallow copy to prevent mutation."""
        return list(self._messages)

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Convert messages to standard LLM readable format.

        Returns:
            List of dictionaries in the format expected by most LLM APIs:
            [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        return [
            {"role": msg.role.value, "content": msg.content, **({"name": msg.name} if msg.name else {})}
            for msg in self._messages
        ]

    def __iter__(self) -> Iterable[LLMMessage]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    # ----------------------------------------------------------------------
    # advanced controls (important later)
    # ----------------------------------------------------------------------

    def truncate(self, max_messages: int) -> None:
        """
        Truncate history while ALWAYS preserving the system prompt.
        """
        if max_messages < 2:
            raise ValueError("max_messages must be >= 2")

        system = self._messages[0]
        rest = self._messages[1:][-(max_messages - 1) :]
        self._messages = [system, *rest]
