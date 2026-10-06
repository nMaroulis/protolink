"""Versioned execution checkpoints with fenced, process-aware SQLite ownership.

Execution data is deliberately separate from diagnostic/redacted run reports.
Stores are trusted application resources and may contain private tool results.
"""

from __future__ import annotations

import builtins
import json
import math
import os
import socket
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 1


class DurableExecutionError(RuntimeError):
    """An execution checkpoint cannot safely continue."""


class RunBusyError(DurableExecutionError):
    """Another live execution owns this checkpoint."""


class CheckpointMismatchError(DurableExecutionError):
    """The checkpoint version or configured execution contract changed."""


class UncertainExecutionError(DurableExecutionError):
    """A started operation has no committed outcome; reconcile before resuming."""


@dataclass(frozen=True)
class RunCheckpoint:
    """Detached application-owned execution record, including private state."""

    run_id: str
    agent_name: str
    status: str
    data: dict[str, Any]


class DurableStore(Protocol):
    """Small execution-store contract; all writes require a current lease token."""

    def get(self, run_id: str) -> RunCheckpoint | None: ...

    def acquire(self, run_id: str, agent_name: str, initial: dict[str, Any]) -> tuple[str, RunCheckpoint]: ...

    def save(self, run_id: str, token: str, status: str, data: dict[str, Any]) -> None: ...

    def release(self, run_id: str, token: str) -> None: ...


class SQLiteDurableStore:
    """Dependency-free checkpoints for a local application and its workers.

    Leases fence competing workers. A dead process on the same host can be
    reclaimed immediately; otherwise ownership expires after ``lease_seconds``.
    A stalled owner must renew before dispatch and cannot commit after takeover.
    This store does not implement distributed scheduling or external rollback.
    ``read_only=True`` opens an existing file for get/list inspection without
    creating tables or acquiring/writing leases. Inventory returns private
    checkpoints; management interfaces must project/redact before exporting them.
    """

    def __init__(self, path: str | Path, *, lease_seconds: float = 300.0, read_only: bool = False) -> None:
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be finite and positive")
        if str(path) == ":memory:":
            raise ValueError("Durable SQLite storage requires a file path")
        self.path = str(Path(path).expanduser())
        self.lease_seconds = lease_seconds
        self.read_only = read_only
        if read_only:
            Path(self.path).resolve(strict=True)
            return
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS protolink_checkpoints ("
                "run_id TEXT PRIMARY KEY, agent_name TEXT NOT NULL, status TEXT NOT NULL, "
                "data TEXT NOT NULL, owner TEXT, host TEXT, pid INTEGER, expires REAL)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            Path(self.path).resolve().as_uri() + "?mode=ro" if self.read_only else self.path,
            timeout=10,
            uri=self.read_only,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def list(
        self, *, status: str | None = None, agent_name: str | None = None, limit: int = 20
    ) -> builtins.list[RunCheckpoint]:
        """Inspect the newest bounded checkpoint inventory without acquiring leases."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        clauses, values = [], []
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        if agent_name is not None:
            clauses.append("agent_name=?")
            values.append(agent_name)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM protolink_checkpoints" + where + " ORDER BY rowid DESC LIMIT ?", [*values, limit]
            ).fetchall()
            return [self._record(row) for row in rows]

    def _writable(self) -> None:
        if self.read_only:
            raise DurableExecutionError("Checkpoint store is read-only")

    @staticmethod
    def _record(row: sqlite3.Row) -> RunCheckpoint:
        return RunCheckpoint(row["run_id"], row["agent_name"], row["status"], json.loads(row["data"]))

    @staticmethod
    def _alive(row: sqlite3.Row) -> bool:
        if row["owner"] is None or (row["expires"] or 0) <= time.time():
            return False
        if row["host"] != socket.gethostname():
            return True
        try:
            os.kill(row["pid"], 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def get(self, run_id: str) -> RunCheckpoint | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM protolink_checkpoints WHERE run_id=?", (run_id,)).fetchone()
        return self._record(row) if row is not None else None

    def acquire(self, run_id: str, agent_name: str, initial: dict[str, Any]) -> tuple[str, RunCheckpoint]:
        self._writable()
        payload = json.dumps(initial, allow_nan=False)
        token = uuid.uuid4().hex
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO protolink_checkpoints(run_id,agent_name,status,data) VALUES(?,?,?,?)",
                (run_id, agent_name, "ready", payload),
            )
            row = connection.execute("SELECT * FROM protolink_checkpoints WHERE run_id=?", (run_id,)).fetchone()
            assert row is not None
            if row["agent_name"] != agent_name:
                raise CheckpointMismatchError("Checkpoint belongs to a different agent")
            if self._alive(row):
                raise RunBusyError(f"Run '{run_id}' is owned by another execution")
            connection.execute(
                "UPDATE protolink_checkpoints SET owner=?,host=?,pid=?,expires=? WHERE run_id=?",
                (token, socket.gethostname(), os.getpid(), time.time() + self.lease_seconds, run_id),
            )
            record = self._record(row)
        return token, record

    def save(self, run_id: str, token: str, status: str, data: dict[str, Any]) -> None:
        self._writable()
        payload = json.dumps(data, allow_nan=False)
        with closing(self._connect()) as connection, connection:
            updated = connection.execute(
                "UPDATE protolink_checkpoints SET status=?,data=?,expires=? WHERE run_id=? AND owner=?",
                (status, payload, time.time() + self.lease_seconds, run_id, token),
            ).rowcount
            if updated != 1:
                raise RunBusyError(f"Execution lease for '{run_id}' was lost")

    def release(self, run_id: str, token: str) -> None:
        self._writable()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE protolink_checkpoints SET owner=NULL,host=NULL,pid=NULL,expires=NULL "
                "WHERE run_id=? AND owner=?",
                (run_id, token),
            )
