from dataclasses import dataclass, field
from typing import Any

from protolink.core.part import Part
from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator


@dataclass
class Artifact:
    """Output produced by a task (NEW in v0.2.0).

    Artifacts represent results from task execution - files, structured data,
    analysis results, etc. Multiple artifacts can be produced per task.

    Attributes:
        id: Unique artifact identifier
        parts: Content parts of the artifact
        metadata: Artifact metadata (type, size, etc.)
        timestamp: When artifact was created
    """

    id: str = field(default_factory=lambda: IDGenerator.generate_artifact_id())
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: utc_now())

    def add_part(self, part: Part) -> "Artifact":
        """Add content part to artifact."""
        self.parts.append(part)
        return self

    def add_text(self, text: str) -> "Artifact":
        """Add text content (convenience method)."""
        self.parts.append(Part.text(text))
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "parts": [p.to_dict() for p in self.parts],
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        """Create from dictionary."""
        parts = [Part.from_dict(p) for p in data.get("parts", [])]
        return cls(
            id=data.get("id", IDGenerator.generate_artifact_id()),
            parts=parts,
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", utc_now()),
        )
