from dataclasses import asdict, dataclass
from typing import Any

from protolink.types import PartType


@dataclass
class Part:
    """Atomic content unit within a message.

    Attributes:
        type: Content type (e.g., 'text', 'image', 'file')
        content: The actual content data
    """

    type: PartType
    content: Any

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Part":
        """Create from dictionary."""
        return cls(**data)

    @classmethod
    def text(cls, content: str) -> "Part":
        """Create a text part (convenience method)."""
        return cls(type="text", content=content)

    @classmethod
    def json(cls, content: dict) -> "Part":
        return cls(type="json", content=content)

    @classmethod
    def error(cls, code: str, message: str, *, retryable: bool = False) -> "Part":
        return cls(
            type="error",
            content={
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        )

    @classmethod
    def status(cls, state: str, message: str | None = None) -> "Part":
        return cls(
            type="status",
            content={"state": state, "message": message},
        )
