"""Completed tool evidence derived from the existing run-event stream."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from protolink.core.events import RunEvent

_Outcome = Literal["completed", "rejected", "failed", "canceled"]
_TERMINAL_OUTCOMES: dict[str, _Outcome] = {
    "action.completed": "completed",
    "action.rejected": "rejected",
    "action.denied": "rejected",
    "action.failed": "failed",
    "action.canceled": "canceled",
}


@dataclass(frozen=True)
class ToolEvidence:
    """One terminal tool action, including actions performed by delegated agents.

    ``arguments`` contains validated inputs, or ``None`` when validation did not
    complete or an older event omitted them. ``result_omitted`` distinguishes a
    private or unavailable result from a tool that actually returned ``None``.
    Inference results are private unless the owning Agent explicitly enables
    ``expose_tool_results``. When exposed, results reflect the tool's return
    before hooks or context limits transform model history. A rejected action
    may never have started.

    IDs retain the executing child's identity; ``parent_action_id`` and
    ``delegation_id`` connect it to its coordinator. Timestamps are ISO strings,
    and ``duration_seconds`` is unknown when no start timestamp was observed.
    This is a view of run events, not another execution log.
    """

    tool_name: str
    arguments: dict[str, Any] | None
    result: Any
    outcome: _Outcome
    run_id: str | None
    task_id: str | None
    agent_name: str | None
    action_id: str | None
    parent_action_id: str | None
    delegation_id: str | None
    started_at: str | None
    finished_at: str
    duration_seconds: float | None
    result_omitted: bool = False
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-compatible representation of this evidence."""
        return asdict(self)


def collect_tool_evidence(events: Iterable[RunEvent | dict[str, Any]]) -> tuple[ToolEvidence, ...]:
    """Collect one terminal observation per tool action from existing events.

    The first terminal receipt wins, including when delegation forwards both a
    live event and a final task snapshot. Agent-call envelopes are excluded;
    actual child tool actions remain included with their correlation IDs.
    """
    collector = _ToolEvidenceCollector()
    results = []
    for event in events:
        evidence = collector.add(event if isinstance(event, RunEvent) else RunEvent.from_dict(event))
        if evidence is not None:
            results.append(evidence)
    return tuple(results)


class _ToolEvidenceCollector:
    """Incrementally derive the same view used by completed run reports."""

    def __init__(self) -> None:
        self._actions: dict[tuple[str | None, str], dict[str, Any]] = {}
        self._finished: set[tuple[str | None, str]] = set()

    def add(self, event: RunEvent) -> ToolEvidence | None:
        """Consume an event and return newly completed evidence, if any."""
        if not event.type.startswith("action."):
            return None
        payload = event.payload
        if str(payload.get("llm_event_type", "")).startswith("agent_call_"):
            return None
        metadata = payload.get("metadata")
        data = {**(metadata if isinstance(metadata, dict) else {}), **payload}
        action = data.get("action")
        action = action if isinstance(action, dict) else {}
        if action.get("kind") and action["kind"] != "tool.call":
            return None
        action_id = event.action_id or action.get("action_id") or data.get("action_id")
        key = (event.run_id, str(action_id or event.event_id))
        if key in self._finished:
            return None
        state = self._actions.setdefault(key, {})
        if action.get("kind") == "tool.call":
            state["tool_name"] = action.get("name")
            arguments = action.get("payload", {}).get("arguments")
            if isinstance(arguments, dict):
                state["arguments"] = deepcopy(arguments)
        if data.get("tool"):
            state["tool_name"] = str(data["tool"])
        arguments = data.get("args")
        # Validation failures retain their rejection details, not unvalidated
        # model input presented as if it had passed the tool's schema.
        if isinstance(arguments, dict) and data.get("phase") != "validation":
            state["arguments"] = deepcopy(arguments)
        if event.type == "action.started":
            state.setdefault("started_at", event.timestamp)
        outcome = _TERMINAL_OUTCOMES.get(event.type)
        if outcome is None or not state.get("tool_name"):
            return None
        self._finished.add(key)
        self._actions.pop(key, None)
        error = data.get("error") or data.get("rejection")
        if not isinstance(error, dict):
            error = data.get("decision") if event.type == "action.denied" else None
        if not isinstance(error, dict) and data.get("message"):
            error = {"message": str(data["message"])}
        started_at = state.get("started_at")
        return ToolEvidence(
            tool_name=str(state["tool_name"]),
            arguments=state.get("arguments"),
            result=deepcopy(data.get("result")),
            outcome=outcome,
            run_id=event.run_id,
            task_id=event.task_id,
            agent_name=event.agent_name,
            action_id=str(action_id) if action_id is not None else None,
            parent_action_id=event.parent_action_id,
            delegation_id=event.delegation_id,
            started_at=started_at,
            finished_at=event.timestamp,
            duration_seconds=_duration(started_at, event.timestamp),
            result_omitted=bool(data.get("result_omitted")) or "result" not in data,
            error=deepcopy(error) if isinstance(error, dict) else None,
        )


def _duration(started_at: str | None, finished_at: str) -> float | None:
    if started_at is None:
        return None
    try:
        return max(0.0, (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds())
    except (TypeError, ValueError):
        return None
