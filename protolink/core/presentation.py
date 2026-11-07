"""Small, allowlisted progress views of native runtime events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from protolink.core.events import RunEvent
from protolink.core.redaction import RedactionPolicy

_Kind = Literal["model", "tool", "consultation", "approval", "action", "run"]
_Status = Literal[
    "requested",
    "started",
    "completed",
    "retrying",
    "failed",
    "rejected",
    "denied",
    "canceled",
    "required",
    "approved",
    "submitted",
    "working",
    "input-required",
    "queued",
    "running",
    "expired",
    "unknown",
]
_ACTION_STATUSES: dict[str, _Status] = {
    "action.requested": "requested",
    "action.started": "started",
    "action.completed": "completed",
    "action.failed": "failed",
    "action.rejected": "rejected",
    "action.denied": "denied",
    "action.canceled": "canceled",
}
_RUN_STATUSES: dict[str, _Status] = {
    "run.queued": "queued",
    "run.admitted": "running",
    "run.rejected": "rejected",
    "run.expired": "expired",
    "run.canceled": "canceled",
}
_TASK_STATUSES: dict[str, _Status] = {
    value: value for value in ("submitted", "working", "input-required", "completed", "failed", "rejected", "canceled")
}


@dataclass(frozen=True)
class PresentationEvent:
    """An allowlisted activity update suitable for application progress views.

    ``type`` identifies the activity and ``status`` distinguishes requests,
    approval decisions and execution outcomes. An approved action has not yet
    executed. ``final`` closes a run stream, rather than a model call or tool.

    Names are configured tool, model or agent labels; render them as untrusted
    text. Summaries are fixed runtime phrases. Prompts, reasoning, arguments,
    results, artifacts, policy reasons and diagnostic errors are never copied.
    Correlation IDs and source sequence numbers are preserved for replay and
    parent/child displays. ``activity_id`` falls back to run/task/step for model
    activity when the source has no span ID; it groups retries of that step.
    """

    type: _Kind
    status: _Status
    summary: str
    name: str | None
    activity_id: str | None
    event_id: str
    run_id: str | None
    task_id: str | None
    agent_name: str | None
    sequence: int | None
    step: int | None
    action_id: str | None
    parent_action_id: str | None
    delegation_id: str | None
    span_id: str | None
    parent_span_id: str | None
    approval_id: str | None
    timestamp: str
    final: bool = False

    def to_dict(self, *, redaction_policy: RedactionPolicy | None = None) -> dict[str, Any]:
        """Return detached display fields, optionally masking known secrets."""
        data = asdict(self)
        return redaction_policy.redact(data) if redaction_policy is not None else data

    @classmethod
    def from_run_event(
        cls, event: RunEvent, *, redaction_policy: RedactionPolicy | None = None
    ) -> PresentationEvent | None:
        """Project recognized activity without exposing the source payload.

        Text chunks, final answers, context preparation and unknown events are
        omitted. Use the answer stream for answer text and native reports for
        diagnostics. Missing source identities remain unknown; this method
        never invents execution evidence or performs an action.
        """
        data = {**_mapping(event.payload.get("metadata")), **event.payload}
        llm_type = data.get("llm_event_type")
        action = _mapping(data.get("action"))
        request = _mapping(data.get("request"))
        decision = _mapping(data.get("decision"))
        approval_id = _text(request.get("request_id")) or _text(decision.get("request_id"))
        kind: _Kind
        status: _Status
        name: str | None = None
        if event.type in {"llm.call.started", "llm.call.completed"}:
            kind, status = "model", "started" if event.type.endswith("started") else "completed"
            name = _text(data.get("model"))
        elif llm_type in {"llm_retry", "llm_error"}:
            kind, status = "model", "retrying" if llm_type == "llm_retry" else "failed"
            name = _text(data.get("model"))
        elif event.type in {"approval.required", "approval.decided"}:
            kind = "approval"
            if event.type == "approval.required":
                status = "required"
            else:
                status = (
                    "approved"
                    if decision.get("approved") is True
                    else ("denied" if decision.get("approved") is False else "unknown")
                )
            name = _text(_mapping(request.get("action")).get("name"))
        elif event.type in _ACTION_STATUSES:
            status = _ACTION_STATUSES[event.type]
            if str(llm_type or "").startswith("agent_call_") or action.get("kind") == "agent.call":
                kind = "consultation"
                name = _text(data.get("agent")) or _text(action.get("name"))
            elif str(llm_type or "").startswith("tool_") or action.get("kind") == "tool.call":
                kind = "tool"
                name = _text(data.get("tool")) or _text(action.get("name"))
            else:
                kind, name = "action", _text(action.get("name"))
        elif event.type == "task.status":
            kind = "run"
            state = data.get("new_state")
            status = _TASK_STATUSES.get(state, "unknown") if isinstance(state, str) else "unknown"
        elif event.type in _RUN_STATUSES:
            kind, status = "run", _RUN_STATUSES[event.type]
        elif event.type == "task.error":
            kind, status = "run", "failed"
        else:
            return None

        activity_id = event.action_id or event.delegation_id or event.span_id
        if kind == "approval":
            activity_id = approval_id or activity_id
        elif kind == "model" and activity_id is None:
            if event.run_id is not None or event.task_id is not None:
                activity_id = f"{event.run_id or ''}:{event.task_id or ''}:model:{event.step or 0}"
        elif kind == "run":
            activity_id = event.run_id or event.task_id

        def identity(value: str | None) -> str | None:
            return redaction_policy.redact(value) if redaction_policy is not None else value

        return cls(
            type=kind,
            status=status,
            summary=f"{kind.capitalize()} {status}",
            name=identity(name),
            activity_id=identity(activity_id),
            event_id=identity(event.event_id) or "",
            run_id=identity(event.run_id),
            task_id=identity(event.task_id),
            agent_name=identity(event.agent_name),
            sequence=event.sequence,
            step=event.step,
            action_id=identity(event.action_id),
            parent_action_id=identity(event.parent_action_id),
            delegation_id=identity(event.delegation_id),
            span_id=identity(event.span_id),
            parent_span_id=identity(event.parent_span_id),
            approval_id=identity(approval_id),
            timestamp=event.timestamp,
            final=event.final and (event.type == "task.status" or event.type in _RUN_STATUSES),
        )


def collect_presentation_events(
    events: Iterable[RunEvent | dict[str, Any]], *, redaction_policy: RedactionPolicy | None = None
) -> tuple[PresentationEvent, ...]:
    """Project a recorded sequence using the same contract as live progress."""
    updates = []
    for event in events:
        source = event if isinstance(event, RunEvent) else RunEvent.from_dict(event)
        update = PresentationEvent.from_run_event(source, redaction_policy=redaction_policy)
        if update is not None:
            updates.append(update)
    return tuple(updates)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None
