from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_card import AgentCard


@dataclass
class RegistryEntry:
    """Runtime metadata for one registered agent card."""

    card: AgentCard
    last_seen: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this entry into a JSON-compatible dictionary."""
        return {
            "card": self.card.to_dict(),
            "last_seen": self.last_seen,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegistryEntry:
        """Create a registry entry from serialized data."""
        return cls(
            card=AgentCard.from_dict(dict(data["card"])),
            last_seen=float(data.get("last_seen", 0.0)),
            metadata=dict(data.get("metadata") or {}),
        )

    def is_expired(self, ttl_seconds: float | None, *, now: float) -> bool:
        """Return whether this entry exceeded the configured TTL."""
        return ttl_seconds is not None and now - self.last_seen > ttl_seconds
