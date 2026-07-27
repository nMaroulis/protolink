"""Typed state control-plane request and result models.

These models describe state operations without coupling them to one transport
or one state backend. Agents use them for local control methods and servers use
the same objects for remote request specs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from protolink.llms.compaction import HistoryCompactionStrategy

StateOperation = Literal["describe", "reset", "compact"]
"""Supported state control-plane operations."""

StateStoreName = Literal["conversation", "tools", "task", "flow"]
"""Built-in state store names."""


@dataclass(frozen=True)
class StateOperationRequest:
    """Transport-neutral request for inspecting or mutating agent state.

    Args:
        session_id: Optional session to target. Conversation state is currently
            the only built-in session-keyed store.
        stores: Optional subset of stores. Empty means the operation chooses a
            sensible default: all enabled stores for describe/reset and
            conversation for compact.
        include_data: Whether ``describe`` should include store payloads.
        strategy: Compaction strategy used by ``compact``.
        max_messages: Retained-message limit for recent compaction.
        max_tokens: Estimated token ceiling for token compaction.
        preserve_recent: Newest messages protected by token/summary strategies.
        summary_max_tokens: Requested maximum summary length.
        metadata: Application-owned operation metadata.
    """

    session_id: str | None = None
    stores: tuple[str, ...] = ()
    include_data: bool = False
    strategy: HistoryCompactionStrategy = "tokens"
    max_messages: int = 20
    max_tokens: int = 4_000
    preserve_recent: int = 6
    summary_max_tokens: int = 512
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize store names and reject invalid compaction values early."""
        object.__setattr__(self, "stores", tuple(str(store) for store in self.stores if str(store)))
        if self.strategy not in {"recent", "tokens", "summary"}:
            raise ValueError("strategy must be one of: recent, tokens, summary")
        if self.max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        if self.preserve_recent < 0:
            raise ValueError("preserve_recent must be non-negative")
        if self.summary_max_tokens < 1:
            raise ValueError("summary_max_tokens must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the request into a JSON-compatible dictionary."""
        return {
            "session_id": self.session_id,
            "stores": list(self.stores),
            "include_data": self.include_data,
            "strategy": self.strategy,
            "max_messages": self.max_messages,
            "max_tokens": self.max_tokens,
            "preserve_recent": self.preserve_recent,
            "summary_max_tokens": self.summary_max_tokens,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StateOperationRequest:
        """Create a request from serialized data."""
        data = data or {}
        stores = data.get("stores") or ()
        if isinstance(stores, str):
            stores = (stores,)
        strategy = str(data.get("strategy") or "tokens")
        if strategy not in {"recent", "tokens", "summary"}:
            raise ValueError("strategy must be one of: recent, tokens, summary")
        return cls(
            session_id=_optional_str(data.get("session_id")),
            stores=tuple(str(store) for store in stores),
            include_data=bool(data.get("include_data", False)),
            strategy=strategy,
            max_messages=int(data.get("max_messages", 20)),
            max_tokens=int(data.get("max_tokens", 4_000)),
            preserve_recent=int(data.get("preserve_recent", 6)),
            summary_max_tokens=int(data.get("summary_max_tokens", 512)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class StateStoreReport:
    """Report for one state store touched by an operation."""

    name: str
    enabled: bool
    exists: bool = False
    item_count: int | None = None
    message_count: int | None = None
    cleared: bool = False
    compacted: bool = False
    data: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report into a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateStoreReport:
        """Create a report from serialized data."""
        return cls(
            name=str(data.get("name") or "unknown"),
            enabled=bool(data.get("enabled", False)),
            exists=bool(data.get("exists", False)),
            item_count=_coerce_optional_int(data.get("item_count")),
            message_count=_coerce_optional_int(data.get("message_count")),
            cleared=bool(data.get("cleared", False)),
            compacted=bool(data.get("compacted", False)),
            data=data.get("data"),
            metadata=dict(data.get("metadata") or {}),
            error=_optional_str(data.get("error")),
        )


@dataclass(frozen=True)
class StateOperationResult:
    """Structured result for state describe, reset, and compact operations."""

    operation: StateOperation
    session_id: str | None = None
    stores: tuple[StateStoreReport, ...] = ()
    cleared: tuple[str, ...] = ()
    compacted: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result into a JSON-compatible dictionary."""
        return {
            "operation": self.operation,
            "session_id": self.session_id,
            "stores": [store.to_dict() for store in self.stores],
            "cleared": list(self.cleared),
            "compacted": list(self.compacted),
            "missing": list(self.missing),
            "errors": [dict(error) for error in self.errors],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateOperationResult:
        """Create a result from serialized data."""
        operation = str(data.get("operation") or "describe")
        if operation not in {"describe", "reset", "compact"}:
            raise ValueError("operation must be one of: describe, reset, compact")
        return cls(
            operation=operation,
            session_id=_optional_str(data.get("session_id")),
            stores=tuple(StateStoreReport.from_dict(store) for store in data.get("stores") or []),
            cleared=tuple(str(item) for item in data.get("cleared") or []),
            compacted=tuple(str(item) for item in data.get("compacted") or []),
            missing=tuple(str(item) for item in data.get("missing") or []),
            errors=tuple(dict(error) for error in data.get("errors") or []),
            metadata=dict(data.get("metadata") or {}),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
