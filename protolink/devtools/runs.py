"""Run-store inspection and replay helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protolink.core.report import RunReplay
from protolink.devtools.models import RunReplayItem, RunReplayView
from protolink.storage import SQLiteRunStore


def list_run_store_records(
    store_path: str | Path,
    *,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """List recent task and run-report records from a SQLite run store."""
    store = SQLiteRunStore(store_path)
    return {
        "tasks": [record.to_dict() for record in store.list_task_records(limit=limit)],
        "reports": [record.to_dict() for record in store.list_report_records(limit=limit)],
    }


def build_run_replay_view(store_path: str | Path, run_id: str) -> RunReplayView:
    """Build a replay projection from a stored report or task snapshot."""
    store = SQLiteRunStore(store_path)
    report_record = store.get_report_record(run_id)
    if report_record is not None:
        report = store.get_report(run_id)
        if report is None:
            return RunReplayView(run_id=run_id, source="missing")
        replay = RunReplay(report)
        items = tuple(_event_to_item(event.to_dict()) for event in replay.events)
        context = report.context
        return RunReplayView(
            run_id=run_id,
            session_id=context.session_id if context else report_record.session_id,
            trace_id=context.trace_id if context else report_record.trace_id,
            agent_name=report_record.agent_name,
            final_task=report.final_task,
            items=items,
            source="report",
        )

    task_record = store.get_task_record(run_id)
    if task_record is None:
        candidates = store.list_task_records(run_id=run_id, limit=20)
        task_record = candidates[0] if candidates else None
    if task_record is None:
        return RunReplayView(run_id=run_id, source="missing")

    item = RunReplayItem(
        event_type="task.snapshot",
        summary=f"Task {task_record.task_id} is {task_record.state}",
        timestamp=task_record.updated_at,
        task_id=task_record.task_id,
        agent_name=task_record.agent_name,
        payload=task_record.task,
    )
    return RunReplayView(
        run_id=task_record.run_id or task_record.task_id,
        session_id=task_record.session_id,
        trace_id=task_record.trace_id,
        agent_name=task_record.agent_name,
        final_task=task_record.task,
        items=(item,),
        source="task",
    )


def _event_to_item(event: dict[str, Any]) -> RunReplayItem:
    """Convert a serialized ``RunEvent`` to a compact timeline item."""
    event_type = str(event.get("type") or "event")
    summary = event.get("summary")
    raw_payload = event.get("payload")
    payload = {str(key): value for key, value in raw_payload.items()} if isinstance(raw_payload, dict) else {}
    if not summary:
        summary = _default_summary(event_type, payload)
    return RunReplayItem(
        event_type=event_type,
        summary=str(summary),
        timestamp=event.get("timestamp"),
        severity=str(event.get("severity") or "info"),
        task_id=event.get("task_id"),
        agent_name=event.get("agent_name"),
        payload=payload,
    )


def _default_summary(event_type: str, payload: dict[str, Any]) -> str:
    """Build a concise fallback summary for a run event."""
    if event_type == "task.status":
        old = payload.get("previous_state")
        new = payload.get("new_state")
        if old and new:
            return f"{old} -> {new}"
        if new:
            return f"state {new}"
    if event_type.startswith("llm.call"):
        provider = payload.get("provider")
        model = payload.get("model")
        if provider or model:
            return " ".join(str(value) for value in (provider, model) if value)
    if event_type.startswith("action."):
        action = payload.get("action")
        if isinstance(action, dict):
            return str(action.get("name") or action.get("kind") or event_type)
    return event_type
