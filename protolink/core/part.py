from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Part:
    """Atomic content unit within a message.

    Attributes:
        type: Content type (e.g., 'text', 'image', 'file')
        content: The actual content data
    """

    type: str
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
