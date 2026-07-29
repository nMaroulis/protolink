"""Persistent task and run-report storage.

The run store is intentionally separate from the generic ``Storage`` key/value interface. Agents use it for durable
execution snapshots: final or intermediate ``Task`` state, correlated ``RunContext`` identifiers, and optional
``RunReport`` documents for replay/debugging.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from protolink.core.report import RunReport
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState
from protolink.utils import utc_now


@dataclass(frozen=True)
class TaskRecord:
    """Durable index record for one task snapshot.

    Attributes:
        task_id: Stable task identifier.
        state: Serialized task lifecycle state.
        run_id: Optional run identifier from ``RunContext``.
        session_id: Optional session identifier from ``RunContext``.
        trace_id: Optional trace identifier from ``RunContext``.
        agent_name: Agent that stored the snapshot, if known.
        task: Serialized task payload.
        metadata: Application-owned metadata attached by the caller.
        created_at: Timestamp copied from the task when available.
        updated_at: Timestamp of this persisted snapshot.
    """

    task_id: str
    state: str
    run_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    agent_name: str | None = None
    task: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str = field(default_factory=lambda: utc_now())

    def to_dict(self) -> dict[str, Any]:
        """Serialize this record into a JSON-compatible dictionary."""
        return {
            "task_id": self.task_id,
            "state": self.state,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class RunReportRecord:
    """Durable index record for one stored ``RunReport``."""

    run_id: str
    session_id: str | None = None
    trace_id: str | None = None
    agent_name: str | None = None
    report: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())

    def to_dict(self) -> dict[str, Any]:
        """Serialize this record into a JSON-compatible dictionary."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "report": self.report,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class RunStore(Protocol):
    """Protocol for durable task snapshots and run reports."""

    def save_task(
        self,
        task: Task,
        *,
        context: RunContext | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        """Persist one task snapshot and return its index record."""
        ...

    def get_task(self, task_id: str) -> Task | None:
        """Load one task snapshot by task ID."""
        ...

    def get_task_record(self, task_id: str) -> TaskRecord | None:
        """Load one task index record by task ID."""
        ...

    def list_task_records(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        run_id: str | None = None,
        state: str | TaskState | None = None,
        agent_name: str | None = None,
    ) -> list[TaskRecord]:
        """List recent task records, newest first."""
        ...

    def save_report(
        self,
        report: RunReport,
        *,
        run_id: str | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunReportRecord:
        """Persist one run report and return its index record."""
        ...

    def get_report(self, run_id: str) -> RunReport | None:
        """Load one run report by run ID."""
        ...

    def get_report_record(self, run_id: str) -> RunReportRecord | None:
        """Load one run-report index record by run ID."""
        ...

    def list_report_records(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        agent_name: str | None = None,
    ) -> list[RunReportRecord]:
        """List recent run-report records, newest first."""
        ...


class SQLiteRunStore:
    """SQLite-backed ``RunStore`` implementation.

    The store uses two JSON payload tables with relational indexes for common
    queries. It is intentionally dependency-free, process-local, and suitable
    for local CLIs, notebooks, tests, and lightweight services. Larger systems
    can implement the same ``RunStore`` protocol against Postgres, object
    storage, or an application database.
    """

    def __init__(
        self,
        db_path: str | Path = "runs.db",
        *,
        table_prefix: str = "protolink",
        read_only: bool = False,
    ) -> None:
        """Initialize a SQLite run store.

        Args:
            db_path: SQLite database path.
            table_prefix: Prefix for task/report tables. Must be a valid
                identifier so table names cannot inject SQL.
            read_only: Open an existing database without creating tables or
                permitting writes. Intended for inspection surfaces.
        """
        if not table_prefix.isidentifier():
            raise ValueError(f"Invalid table_prefix: {table_prefix!r}")
        self.db_path = str(db_path)
        self.table_prefix = table_prefix
        self.tasks_table = f"{table_prefix}_tasks"
        self.reports_table = f"{table_prefix}_run_reports"
        self.read_only = bool(read_only)
        if self.read_only:
            path = Path(self.db_path).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Run store not found: {path}")
            self.db_path = str(path.resolve())
        else:
            self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with row dictionaries enabled."""
        if self.read_only:
            uri = Path(self.db_path).as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create storage tables and indexes when missing."""
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.tasks_table} (
                    task_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    run_id TEXT,
                    session_id TEXT,
                    trace_id TEXT,
                    agent_name TEXT,
                    task_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.tasks_table}_run_id ON {self.tasks_table}(run_id)")
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.tasks_table}_session_id ON {self.tasks_table}(session_id)"
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.tasks_table}_state ON {self.tasks_table}(state)")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.reports_table} (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    trace_id TEXT,
                    agent_name TEXT,
                    report_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.reports_table}_session_id ON {self.reports_table}(session_id)"
            )
            conn.commit()

    def save_task(
        self,
        task: Task,
        *,
        context: RunContext | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        """Persist one task snapshot and return its record."""
        active_context = context or RunContext.from_task(task)
        task_payload = task.to_dict()
        state = task.state.value if isinstance(task.state, TaskState) else str(task.state)
        record = TaskRecord(
            task_id=task.id,
            state=state,
            run_id=active_context.run_id,
            session_id=active_context.session_id,
            trace_id=active_context.trace_id,
            agent_name=agent_name,
            task=task_payload,
            metadata=dict(metadata or {}),
            created_at=task.created_at,
            updated_at=utc_now(),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self.tasks_table}
                (task_id, state, run_id, session_id, trace_id, agent_name, task_json, metadata_json, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.state,
                    record.run_id,
                    record.session_id,
                    record.trace_id,
                    record.agent_name,
                    json.dumps(record.task),
                    json.dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        return record

    def get_task(self, task_id: str) -> Task | None:
        """Load one task snapshot by task ID."""
        record = self.get_task_record(task_id)
        return Task.from_dict(record.task) if record else None

    def get_task_record(self, task_id: str) -> TaskRecord | None:
        """Load one task record by task ID."""
        with closing(self._connect()) as conn:
            row = conn.execute(f"SELECT * FROM {self.tasks_table} WHERE task_id = ?", (task_id,)).fetchone()
        return _task_record_from_row(row) if row else None

    def list_task_records(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        run_id: str | None = None,
        state: str | TaskState | None = None,
        agent_name: str | None = None,
    ) -> list[TaskRecord]:
        """List recent task records, newest first."""
        clauses: list[str] = []
        values: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            values.append(session_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            values.append(run_id)
        if state is not None:
            clauses.append("state = ?")
            values.append(state.value if isinstance(state, TaskState) else str(state))
        if agent_name is not None:
            clauses.append("agent_name = ?")
            values.append(agent_name)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.tasks_table} {where} ORDER BY updated_at DESC LIMIT ?",
                tuple(values),
            ).fetchall()
        return [_task_record_from_row(row) for row in rows]

    def list_task_record_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List task index columns without loading task or metadata JSON."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT task_id, state, run_id, session_id, trace_id, agent_name, created_at, updated_at
                FROM {self.tasks_table}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_report(
        self,
        report: RunReport,
        *,
        run_id: str | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunReportRecord:
        """Persist one run report and return its record."""
        report_payload = report.to_dict()
        context = report.context
        active_run_id = run_id or (context.run_id if context else None)
        if not active_run_id:
            raise ValueError("run_id is required when the report has no context")

        record = RunReportRecord(
            run_id=active_run_id,
            session_id=context.session_id if context else None,
            trace_id=context.trace_id if context else None,
            agent_name=agent_name,
            report=report_payload,
            metadata=dict(metadata or {}),
            created_at=utc_now(),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self.reports_table}
                (run_id, session_id, trace_id, agent_name, report_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.session_id,
                    record.trace_id,
                    record.agent_name,
                    json.dumps(record.report),
                    json.dumps(record.metadata),
                    record.created_at,
                ),
            )
            conn.commit()
        return record

    def get_report(self, run_id: str) -> RunReport | None:
        """Load one run report by run ID."""
        record = self.get_report_record(run_id)
        return RunReport.from_dict(record.report) if record else None

    def get_report_record(self, run_id: str) -> RunReportRecord | None:
        """Load one run report record by run ID."""
        with closing(self._connect()) as conn:
            row = conn.execute(f"SELECT * FROM {self.reports_table} WHERE run_id = ?", (run_id,)).fetchone()
        return _report_record_from_row(row) if row else None

    def list_report_records(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        agent_name: str | None = None,
    ) -> list[RunReportRecord]:
        """List recent run-report records, newest first."""
        clauses: list[str] = []
        values: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            values.append(session_id)
        if agent_name is not None:
            clauses.append("agent_name = ?")
            values.append(agent_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.reports_table} {where} ORDER BY created_at DESC LIMIT ?",
                tuple(values),
            ).fetchall()
        return [_report_record_from_row(row) for row in rows]

    def list_report_record_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List compact report metadata without materializing report JSON."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, session_id, trace_id, agent_name, created_at
                FROM {self.reports_table}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{**dict(row), "state": None, "event_count": None} for row in rows]

    def delete_task(self, task_id: str) -> None:
        """Delete one task snapshot by task ID."""
        with closing(self._connect()) as conn:
            conn.execute(f"DELETE FROM {self.tasks_table} WHERE task_id = ?", (task_id,))
            conn.commit()

    def delete_report(self, run_id: str) -> None:
        """Delete one run report by run ID."""
        with closing(self._connect()) as conn:
            conn.execute(f"DELETE FROM {self.reports_table} WHERE run_id = ?", (run_id,))
            conn.commit()


def _task_record_from_row(row: sqlite3.Row) -> TaskRecord:
    """Build a ``TaskRecord`` from a SQLite row."""
    return TaskRecord(
        task_id=str(row["task_id"]),
        state=str(row["state"]),
        run_id=row["run_id"],
        session_id=row["session_id"],
        trace_id=row["trace_id"],
        agent_name=row["agent_name"],
        task=_load_json_object(row["task_json"], label="task payload"),
        metadata=_load_json_object(row["metadata_json"], label="task metadata"),
        created_at=row["created_at"],
        updated_at=str(row["updated_at"]),
    )


def _report_record_from_row(row: sqlite3.Row) -> RunReportRecord:
    """Build a ``RunReportRecord`` from a SQLite row."""
    return RunReportRecord(
        run_id=str(row["run_id"]),
        session_id=row["session_id"],
        trace_id=row["trace_id"],
        agent_name=row["agent_name"],
        report=_load_json_object(row["report_json"], label="run-report payload"),
        metadata=_load_json_object(row["metadata_json"], label="run-report metadata"),
        created_at=str(row["created_at"]),
    )


def _load_json_object(value: str | bytes | bytearray, *, label: str) -> dict[str, Any]:
    """Decode one stored JSON object with a stable, payload-free error."""
    try:
        payload = json.loads(value)
    except (ValueError, UnicodeDecodeError, RecursionError, TypeError) as exc:
        raise ValueError(f"Stored {label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Stored {label} must be a JSON object")
    return payload
