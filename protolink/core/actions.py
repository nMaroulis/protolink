"""Domain-neutral runtime action primitives.

Language-model actions describe what a model requested. ``RunAction`` instead
describes the concrete operation that the runtime is about to authorize and
execute. Keeping those layers separate lets non-LLM callers, deterministic
flows, remote agents, and local applications use the same policy boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from protolink.core.artifact import Artifact
from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator


@dataclass(frozen=True)
class RunAction:
    """Concrete side-effect intent evaluated by the runtime policy layer.

    A run action is created after an application or model has selected an
    operation but before that operation executes. Policies inspect its declared
    capabilities, payload, previews, and run context. Approval handlers receive
    the same object, giving user interfaces a stable structure to render without
    parsing tool-specific nested dictionaries.

    Attributes:
        kind: Extensible operation category, for example ``"tool.call"`` or
            ``"agent.call"``. Applications may define additional categories.
        name: Human-readable operation or target name.
        payload: Structured operation input. Tool actions conventionally place
            validated keyword arguments under ``"arguments"``.
        capabilities: Permission capabilities required before execution.
            Capability names are application-defined strings and may use dotted
            namespaces such as ``"workspace.read"``.
        artifacts: Immutable tuple of outputs or previews associated with the
            action. Approval UIs can render these before execution.
        description: Optional concise explanation for logs and approval prompts.
        metadata: Extensible runtime or application metadata.
        action_id: Stable action identifier used by events and artifacts.
        created_at: ISO timestamp recording when the action was prepared.
    """

    kind: str
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    artifacts: tuple[Artifact, ...] = field(default_factory=tuple)
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: IDGenerator.generate_context_id(prefix="action_"))
    created_at: str = field(default_factory=lambda: utc_now())

    def __post_init__(self) -> None:
        """Normalize iterable fields and reject incomplete action identities."""
        if not self.kind.strip():
            raise ValueError("RunAction.kind must not be empty")
        if not self.name.strip():
            raise ValueError("RunAction.name must not be empty")

        object.__setattr__(self, "capabilities", frozenset(str(item) for item in self.capabilities if str(item)))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))

    def with_artifacts(self, artifacts: Iterable[Artifact]) -> RunAction:
        """Return a copy with artifacts attached and correlated to this action.

        Existing artifact action IDs are preserved when they intentionally
        reference another action. Missing IDs are filled with this action's ID.

        Args:
            artifacts: Artifacts or previews to attach.

        Returns:
            A new immutable ``RunAction``.
        """
        attached = tuple(
            artifact if artifact.action_id else replace(artifact, action_id=self.action_id) for artifact in artifacts
        )
        return replace(self, artifacts=attached)

    def with_capabilities(self, capabilities: Iterable[str]) -> RunAction:
        """Return a copy requiring the union of current and supplied capabilities."""
        return replace(self, capabilities=self.capabilities.union(str(item) for item in capabilities if str(item)))

    def with_payload(self, payload: dict[str, Any]) -> RunAction:
        """Return a copy with a replacement structured payload."""
        return replace(self, payload=dict(payload))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the action into a JSON-compatible dictionary."""
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "name": self.name,
            "payload": self.payload,
            "capabilities": sorted(self.capabilities),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "description": self.description,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunAction:
        """Create a runtime action from serialized data."""
        return cls(
            action_id=str(data.get("action_id") or IDGenerator.generate_context_id(prefix="action_")),
            kind=str(data.get("kind") or "action"),
            name=str(data.get("name") or "unnamed"),
            payload=dict(data.get("payload") or {}),
            capabilities=frozenset(_string_items(data.get("capabilities"))),
            artifacts=tuple(Artifact.from_dict(item) for item in data.get("artifacts") or []),
            description=_optional_str(data.get("description")),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or utc_now()),
        )


def _optional_str(value: Any) -> str | None:
    """Return ``value`` as a string while preserving ``None``."""
    if value is None:
        return None
    return str(value)


def _string_items(value: Any) -> tuple[str, ...]:
    """Normalize one string or an iterable of values into strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)
