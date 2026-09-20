"""Read-only database tools and a bounded SQLite implementation."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Protocol, TypeVar

from pydantic import Field

from protolink.tools.builtins._integration import integration_tool
from protolink.tools.prepared import PreparedTool

_T = TypeVar("_T")
_Rows = Annotated[int, Field(ge=1, le=1000)]
_SQL = Annotated[str, Field(min_length=1, max_length=65536)]


class DatabaseBackend(Protocol):
    """Async read-only database contract; adapters own connections and credentials.

    query returns columns (names), rows (parallel arrays), and truncated. Preserve
    duplicate column names by keeping positional rows. Values must be JSON-safe.
    Enforce read-only access in the backend, limit work/output, and honor cancellation.
    """

    async def describe_schema(self) -> dict[str, Any]:
        """Return bounded table/view metadata without exposing credentials."""
        ...

    async def query(self, *, sql: str, parameters: list[Any] | dict[str, Any] | None, max_rows: int) -> dict[str, Any]:
        """Execute one read-only statement with bound parameters and bounded results."""
        ...


class SQLiteDatabase:
    """Query an existing SQLite file with a fresh read-only connection per call.

    Args:
        path: Application-selected database file. Construction resolves the path
            but does not open or create a database. In-memory databases are not supported.
        timeout_seconds: Positive query deadline and lock timeout, default 5 seconds.
        max_result_bytes: JSON output byte limit, default 1 MiB; also limits SQLite
            string/blob size before transferring values into Python.
        max_tables: Maximum schema tables/views returned, default 100.

    Uses mode=ro and a SQLite authorizer: writes, ATTACH, PRAGMA statements,
    transactions, and extension loading are denied. Parameter values are bound,
    never interpolated. Queries run on workers; cancellation uses interrupt() and
    a progress handler. Rows retain column order; blobs become {"base64": "..."}.
    Tables/views are read in one connection snapshot. This is a data-access adapter,
    not an OS sandbox for malformed database files. No extra dependencies required.
    """

    def __init__(
        self, path: str | Path, *, timeout_seconds: float = 5, max_result_bytes: int = 1048576, max_tables: int = 100
    ) -> None:
        if str(path) == ":memory:":
            raise ValueError("SQLiteDatabase requires an existing file")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        for limit in (max_result_bytes, max_tables):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError("Database limits must be positive integers")
        self.path = Path(path).resolve()
        self._timeout, self._max_bytes, self._max_tables = timeout_seconds, max_result_bytes, max_tables

    async def _run(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        stop = threading.Event()
        lock = threading.Lock()
        active: list[sqlite3.Connection] = []
        deadline = time.monotonic() + self._timeout

        def run() -> _T:
            if stop.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("Database operation canceled or timed out")
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=self._timeout)
            with lock:
                active.append(connection)
            try:
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, self._max_bytes)
                connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
                connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 256)
                connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
                connection.set_progress_handler(lambda: int(stop.is_set() or time.monotonic() >= deadline), 1000)
                if stop.is_set():
                    raise TimeoutError("Database operation canceled")
                return operation(connection)
            except sqlite3.Error:
                if stop.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError("Database operation canceled or timed out") from None
                raise
            finally:
                with lock:
                    active.clear()
                    connection.close()

        worker = asyncio.create_task(asyncio.to_thread(run))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            stop.set()
            with lock:
                for connection in active:
                    connection.interrupt()
            worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            raise

    async def describe_schema(self) -> dict[str, Any]:
        """Describe bounded tables/views and their columns, with a truncation marker."""

        def operation(connection: sqlite3.Connection) -> dict[str, Any]:
            connection.execute("BEGIN")
            cursor = connection.execute(
                "SELECT name, type FROM sqlite_schema WHERE type IN ('table', 'view') "
                "AND substr(name, 1, 7) != 'sqlite_' ORDER BY name LIMIT ?",
                (self._max_tables + 1,),
            )
            objects = cursor.fetchall()
            tables = []
            used = len(json.dumps({"tables": [], "truncated": False}).encode())
            truncated = len(objects) > self._max_tables
            for name, kind in objects[: self._max_tables]:
                columns = [
                    {"name": row[1], "type": row[2], "nullable": not bool(row[3]), "primary_key": bool(row[5])}
                    for row in connection.execute("SELECT * FROM pragma_table_info(?)", (name,))
                ]
                item = {"name": name, "type": kind, "columns": columns}
                used += len(json.dumps(item).encode()) + 2
                if used > self._max_bytes:
                    truncated = True
                    break
                tables.append(item)
            return {"tables": tables, "truncated": truncated}

        return await self._run(operation)

    async def query(
        self, *, sql: str, parameters: list[Any] | dict[str, Any] | None = None, max_rows: int = 100
    ) -> dict[str, Any]:
        """Execute one SELECT/CTE with parameters; reject mutation at SQLite's authorizer boundary."""
        _validate_query({"sql": sql, "parameters": parameters})
        if not 1 <= max_rows <= 1000:
            raise ValueError("max_rows must be between 1 and 1000")

        def operation(connection: sqlite3.Connection) -> dict[str, Any]:
            def authorize(
                code: int, first: str | None, second: str | None, database: str | None, trigger: str | None
            ) -> int:
                if code not in {
                    sqlite3.SQLITE_SELECT,
                    sqlite3.SQLITE_READ,
                    sqlite3.SQLITE_FUNCTION,
                    sqlite3.SQLITE_RECURSIVE,
                }:
                    return sqlite3.SQLITE_DENY
                if code == sqlite3.SQLITE_FUNCTION and (second or "").lower() in {
                    "load_extension",
                    "readfile",
                    "writefile",
                }:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            cursor = connection.execute(sql, parameters if parameters is not None else ())
            columns = [description[0] for description in cursor.description or ()]
            used = len(json.dumps({"columns": columns, "rows": [], "truncated": False}).encode())
            if used > self._max_bytes:
                raise ValueError("Database columns exceed max_result_bytes")
            rows = []
            truncated = False
            for row in cursor:
                if len(rows) == max_rows:
                    truncated = True
                    break
                values = [
                    {"base64": base64.b64encode(value).decode()} if isinstance(value, bytes) else value for value in row
                ]
                try:
                    used += len(json.dumps(values, allow_nan=False).encode()) + 2
                except ValueError:
                    raise ValueError("Query returned a non-finite number; cast it to text in SQL") from None
                if used > self._max_bytes:
                    truncated = True
                    break
                rows.append(values)
            return {"columns": columns, "rows": rows, "truncated": truncated}

        return await self._run(operation)


def _validate_query(arguments: dict[str, Any]) -> None:
    sql, parameters = arguments["sql"], arguments["parameters"]
    if not sql.strip() or len(sql.encode()) > 65536 or "\x00" in sql:
        raise ValueError("SQL must be nonblank, contain no NUL, and fit in 65536 bytes")
    values = parameters.values() if isinstance(parameters, dict) else parameters or []
    if len(values) > 1000:
        raise ValueError("At most 1000 SQL parameters are supported")
    if any(value is not None and not isinstance(value, (str, int, float)) for value in values):
        raise ValueError("SQL parameters must be strings, numbers, booleans, or null")
    if any(isinstance(value, float) and not math.isfinite(value) for value in values):
        raise ValueError("SQL parameters must be finite")


def database_tools(backend: DatabaseBackend, *, timeout_seconds: float = 30) -> tuple[PreparedTool, ...]:
    """Expose database_schema/query_database with the ``database.read`` capability.

    The backend is responsible for enforcing read-only queries and bounded work.
    SQLiteDatabase supplies those guarantees for SQLite; applications can implement
    DatabaseBackend for other databases. Connections/credentials are never tool
    arguments. SQL and bound parameters appear in approval previews and reports.
    """

    async def database_schema() -> dict[str, Any]:
        """Inspect tables/views and columns before composing a database query."""
        return await backend.describe_schema()

    async def query_database(
        sql: _SQL, parameters: list[Any] | dict[str, Any] | None = None, max_rows: _Rows = 100
    ) -> dict[str, Any]:
        """Run one read-only query using bound parameters; return columns, positional rows, and truncated."""
        return await backend.query(sql=sql, parameters=parameters, max_rows=max_rows)

    return (
        integration_tool(
            database_schema, capability="database.read", target=type(backend).__name__, timeout_seconds=timeout_seconds
        ),
        integration_tool(
            query_database,
            capability="database.read",
            target=type(backend).__name__,
            timeout_seconds=timeout_seconds,
            validate=_validate_query,
        ),
    )
