import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from protolink.core.part import Part


@dataclass
class Artifact:
    """Output produced by a task (NEW in v0.2.0).

    Artifacts represent results from task execution - files, structured data,
    analysis results, etc. Multiple artifacts can be produced per task.

    Attributes:
        artifact_id: Unique artifact identifier
        parts: Content parts of the artifact
        metadata: Artifact metadata (type, size, etc.)
        created_at: When artifact was created
    """

    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

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
            "artifact_id": self.artifact_id,
            "parts": [p.to_dict() for p in self.parts],
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        """Create from dictionary."""
        parts = [Part.from_dict(p) for p in data.get("parts", [])]
        return cls(
            artifact_id=data.get("artifact_id", str(uuid.uuid4())),
            parts=parts,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )
