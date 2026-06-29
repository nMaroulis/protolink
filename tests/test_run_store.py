"""Tests for durable task and run-report storage."""

from __future__ import annotations

from protolink import RunContext, RunEvent, RunReport, SQLiteRunStore, Task, TaskState


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
