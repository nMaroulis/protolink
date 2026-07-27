from dataclasses import dataclass, field
from typing import Any

from protolink.core.part import Part
from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator


@dataclass
class Artifact:
    """Structured output or preview produced during a run.

    Artifacts represent task results, generated resources, diagnostics, action previews, or any other durable output.
    The original ``parts`` and ``metadata`` fields remain the content boundary; the optional descriptive fields make
    common runtime relationships explicit without prescribing a domain-specific artifact taxonomy.

    Attributes:
        id: Unique artifact identifier.
        parts: Ordered content parts carried by the artifact.
        metadata: Extensible application metadata.
        timestamp: ISO timestamp recording artifact creation.
        kind: Stable application-defined category such as ``"result"``, ``"preview"``, or ``"diagnostic"``.
        name: Optional display or resource name.
        uri: Optional URI identifying the represented resource.
        media_type: Optional MIME type describing the artifact as a whole.
        action_id: Optional ID of the ``RunAction`` that produced or proposes this artifact.
    """

    id: str = field(default_factory=lambda: IDGenerator.generate_artifact_id())
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: utc_now())
    kind: str = "result"
    name: str | None = None
    uri: str | None = None
    media_type: str | None = None
    action_id: str | None = None

    def add_part(self, part: Part) -> "Artifact":
        """Append a content part and return this artifact for chaining."""
        self.parts.append(part)
        return self

    def add_text(self, text: str) -> "Artifact":
        """Append a text part and return this artifact for chaining."""
        self.parts.append(Part.text(text))
        return self

    def for_action(self, action_id: str) -> "Artifact":
        """Associate this artifact with a runtime action.

        The method mutates the artifact consistently with ``add_part`` and ``add_text``. It is useful when an
        application builds a preview before the final ``RunAction`` identifier is known.

        Args:
            action_id: Identifier of the related runtime action.

        Returns:
            This artifact instance.
        """
        self.action_id = action_id
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialize the artifact into a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "parts": [p.to_dict() for p in self.parts],
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "name": self.name,
            "uri": self.uri,
            "media_type": self.media_type,
            "action_id": self.action_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        """Create an artifact from serialized data.

        Payloads emitted before the structured descriptor fields were added remain valid and default to a generic
        ``"result"`` artifact.
        """
        parts = [Part.from_dict(p) for p in data.get("parts", [])]
        return cls(
            id=data.get("id", IDGenerator.generate_artifact_id()),
            parts=parts,
            metadata=dict(data.get("metadata") or {}),
            timestamp=data.get("timestamp", utc_now()),
            kind=str(data.get("kind") or "result"),
            name=_optional_str(data.get("name")),
            uri=_optional_str(data.get("uri")),
            media_type=_optional_str(data.get("media_type")),
            action_id=_optional_str(data.get("action_id")),
        )


def _optional_str(value: Any) -> str | None:
    """Return ``value`` as a string while preserving ``None``."""
    if value is None:
        return None
    return str(value)
