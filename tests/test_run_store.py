"""Tests for durable task and run-report storage."""

from __future__ import annotations

import sqlite3

import pytest

from protolink import RunContext, RunEvent, RunReport, SQLiteRunStore, Task, TaskState
from protolink.storage import SQLiteStorage


def test_sqlite_run_store_persists_task_snapshots_and_reports(tmp_path) -> None:
    """SQLiteRunStore should round-trip tasks, index records, and run reports."""
    store = SQLiteRunStore(tmp_path / "runs.db")
    task = Task.create_infer(prompt="persist this")
    context = RunContext(run_id="run-store-1", session_id="session-store", trace_id="trace-store")
    context.attach_to_task(task)
    task.complete("done")

    task_record = store.save_task(task, context=context, agent_name="store-agent", metadata={"source": "test"})
    loaded_task = store.get_task(task.id)
    listed_tasks = store.list_task_records(session_id="session-store", state=TaskState.COMPLETED)

    assert task_record.task_id == task.id
    assert loaded_task is not None
    assert loaded_task.state is TaskState.COMPLETED
    assert listed_tasks[0].metadata == {"source": "test"}

    report = RunReport.from_events(
        [
            RunEvent(
                type="task.status",
                run_id=context.run_id,
                task_id=task.id,
                agent_name="store-agent",
                final=True,
            )
        ],
        context=context,
        final_task=task.to_dict(),
        metadata={"kind": "golden"},
    )
    report_record = store.save_report(report, agent_name="store-agent", metadata={"suite": "unit"})
    loaded_report = store.get_report("run-store-1")
    listed_reports = store.list_report_records(session_id="session-store")

    assert report_record.run_id == "run-store-1"
    assert loaded_report is not None
    assert loaded_report.context is not None
    assert loaded_report.context.session_id == "session-store"
    assert listed_reports[0].metadata == {"suite": "unit"}


def test_sqlite_stores_close_every_short_lived_connection(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SQLite adapters should never depend on garbage collection to close handles."""
    run_connections: list[sqlite3.Connection] = []
    original_run_connect = SQLiteRunStore._connect

    def tracked_run_connect(store: SQLiteRunStore) -> sqlite3.Connection:
        connection = original_run_connect(store)
        run_connections.append(connection)
        return connection

    monkeypatch.setattr(SQLiteRunStore, "_connect", tracked_run_connect)
    run_store = SQLiteRunStore(tmp_path / "runs.db")
    task = Task.create_infer(prompt="close connections")
    run_store.save_task(task)
    assert run_store.get_task(task.id) is not None
    assert run_store.list_task_records()
    run_store.delete_task(task.id)

    storage_connections: list[sqlite3.Connection] = []
    original_storage_connect = sqlite3.connect

    def tracked_storage_connect(*args, **kwargs) -> sqlite3.Connection:
        connection = original_storage_connect(*args, **kwargs)
        storage_connections.append(connection)
        return connection

    monkeypatch.setattr("protolink.storage.sqlite.sqlite3.connect", tracked_storage_connect)
    storage = SQLiteStorage(db_path=str(tmp_path / "storage.db"))
    storage.save({"ready": True})
    assert storage.load() == {"ready": True}
    storage.delete()

    for connection in [*run_connections, *storage_connections]:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
