"""Resource revisions and recovery records, separate from conversation/run state."""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

from protolink.storage.base import Storage
from protolink.utils.id_generator import IDGenerator


@dataclass(frozen=True)
class ResourceRevision:
    """A resource identity and the exact version referenced by evidence."""

    resource_id: str
    version: str

    def to_dict(self) -> dict[str, str]:
        """Serialize the resource/version pair."""
        return {"resource_id": self.resource_id, "version": self.version}


@dataclass(frozen=True)
class ResourceSnapshot:
    """Recoverable bytes and POSIX mode for one resource version.

    ``data=None`` denotes absence. Identity metadata binds preparation to the
    resource's containing directory as well as its preimage.
    """

    revision: ResourceRevision
    data: bytes | None
    mode: int | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Encode arbitrary original bytes losslessly for existing JSON storage."""
        return {
            "revision": self.revision.to_dict(),
            "data_base64": base64.b64encode(self.data).decode() if self.data is not None else None,
            "mode": self.mode,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceSnapshot:
        """Restore bytes, mode, and revision from a recovery record."""
        encoded = data.get("data_base64")
        return cls(
            ResourceRevision(**data["revision"]),
            base64.b64decode(encoded, validate=True) if encoded is not None else None,
            data.get("mode"),
            dict(data.get("metadata") or {}),
        )


class Resource(Protocol):
    """Small compare-and-replace interface for a recoverable resource backend."""

    def read(self, resource_id: str) -> ResourceSnapshot:
        """Read the current bytes, permission metadata, and revision."""
        ...

    def replace(self, expected: ResourceSnapshot, data: bytes | None, mode: int | None) -> ResourceSnapshot:
        """Replace only if the resource still matches the prepared snapshot."""
        ...


class ResourceConflictError(RuntimeError):
    """The approved target or its preimage no longer matches current state."""


@dataclass(frozen=True)
class ResourceChange:
    """Durable recovery information for one write; never a multi-write transaction.

    ``prepared`` records are saved before mutation. ``uncertain`` means the
    process may have interrupted a write or its durable receipt. Approval and
    read-only inspection cannot resolve this uncertainty by replaying effects.
    """

    before: ResourceSnapshot
    after: ResourceSnapshot | None
    state: str
    action_id: str
    run_id: str
    task_id: str | None = None
    change_id: str = field(default_factory=lambda: IDGenerator.generate_context_id(prefix="change_"))
    error: str | None = None
    restored_revision: ResourceRevision | None = None
    restore_action_id: str | None = None
    restore_run_id: str | None = None
    restore_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize recovery bytes and execution correlation identifiers."""
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict() if self.after else None,
            "state": self.state,
            "action_id": self.action_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "change_id": self.change_id,
            "error": self.error,
            "restored_revision": self.restored_revision.to_dict() if self.restored_revision else None,
            "restore_action_id": self.restore_action_id,
            "restore_run_id": self.restore_run_id,
            "restore_task_id": self.restore_task_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceChange:
        """Load a recovery record without inspecting or mutating its resource."""
        return cls(
            before=ResourceSnapshot.from_dict(data["before"]),
            after=ResourceSnapshot.from_dict(data["after"]) if data.get("after") else None,
            state=data["state"],
            action_id=data["action_id"],
            run_id=data["run_id"],
            task_id=data.get("task_id"),
            change_id=data["change_id"],
            error=data.get("error"),
            restore_action_id=data.get("restore_action_id"),
            restore_run_id=data.get("restore_run_id"),
            restore_task_id=data.get("restore_task_id"),
            restored_revision=ResourceRevision(**data["restored_revision"]) if data.get("restored_revision") else None,
        )


class CheckpointStore(Protocol):
    """Recovery storage whose save must complete durably before a mutation starts."""

    def save(self, change: ResourceChange) -> None:
        """Persist one complete resource change or raise before returning."""
        ...

    def get(self, change_id: str) -> ResourceChange | None:
        """Read one recovery record without executing a continuation."""
        ...

    def list_changes(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        state: str | None = None,
        resource_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> list[ResourceChange]:
        """List recovery records in reverse insertion order with exact, combined filters.

        Pagination applies after filtering. Run/task filters refer to the original
        write, not a later restoration. Results include protected recovery bytes;
        reading them never resolves uncertainty or executes a continuation.
        """
        ...


class StorageCheckpointStore:
    """Resource recovery adapter over a dedicated existing ``Storage`` namespace.

    One live writer owns the namespace. SQLiteStorage provides durable local
    saves; in-memory Storage is useful for tests but cannot recover after exit.
    Raw recovery bytes must be protected by the application's storage policy.
    """

    def __init__(self, storage: Storage) -> None:
        """Use an application-supplied storage namespace exclusively for changes."""
        self.storage = storage

    def save(self, change: ResourceChange) -> None:
        """Persist before-images and state with one storage save."""
        records = self.storage.load() or {}
        records[change.change_id] = change.to_dict()
        self.storage.save(records)

    def get(self, change_id: str) -> ResourceChange | None:
        """Load a detached change record, preserving interrupted states for inspection."""
        data = (self.storage.load() or {}).get(change_id)
        return ResourceChange.from_dict(deepcopy(data)) if data is not None else None

    def list_changes(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        state: str | None = None,
        resource_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> list[ResourceChange]:
        """Return detached recovery records, most recently inserted first.

        All supplied filters match exactly and are combined with AND. ``run_id``
        and ``task_id`` identify the original write. ``limit`` and ``offset`` must
        be nonnegative; pagination applies after filtering. Updating a record does
        not change its position. The underlying namespace is loaded once per call.

        Results contain raw recovery bytes and require the same access protection
        as ``get()``. Inspection never mutates a resource or changes a record state.
        """
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        if limit == 0:
            return []
        result: list[ResourceChange] = []
        for data in reversed((self.storage.load() or {}).values()):
            if any(
                expected is not None and data.get(key) != expected
                for key, expected in (("state", state), ("run_id", run_id), ("task_id", task_id))
            ):
                continue
            if resource_id is not None and data["before"]["revision"]["resource_id"] != resource_id:
                continue
            if offset:
                offset -= 1
                continue
            result.append(ResourceChange.from_dict(deepcopy(data)))
            if len(result) == limit:
                break
        return result
