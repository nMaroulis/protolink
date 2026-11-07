"""Progress views expose stable activity fields without copying runtime data."""

import json

import pytest

from protolink.core.events import RunEvent, TaskLLMStreamEvent, TaskStatusUpdateEvent
from protolink.core.presentation import PresentationEvent, collect_presentation_events
from protolink.core.redaction import RedactionPolicy


def activity(llm_event_type, **metadata):
    return RunEvent.from_task_event(
        TaskLLMStreamEvent(
            task_id="child-task", agent_name="worker", llm_event_type=llm_event_type, step=2, metadata=metadata
        ),
        context={"run_id": "child-run", "parent_run_id": "root-run"},
        sequence=8,
    )


@pytest.mark.parametrize(
    ("source", "kind", "status", "name"),
    [
        ("llm_call_started", "model", "started", "local-model"),
        ("llm_call_completed", "model", "completed", "local-model"),
        ("llm_retry", "model", "retrying", "local-model"),
        ("llm_error", "model", "failed", "local-model"),
        ("tool_start", "tool", "started", "lookup"),
        ("tool_result", "tool", "completed", "lookup"),
        ("tool_error", "tool", "failed", "lookup"),
        ("tool_rejected", "tool", "rejected", "lookup"),
        ("tool_canceled", "tool", "canceled", "lookup"),
        ("agent_call_start", "consultation", "started", "researcher"),
        ("agent_call_result", "consultation", "completed", "researcher"),
        ("agent_call_error", "consultation", "failed", "researcher"),
        ("agent_call_rejected", "consultation", "rejected", "researcher"),
        ("agent_call_canceled", "consultation", "canceled", "researcher"),
    ],
)
def test_model_tool_and_consultation_activity_has_allowlisted_typed_fields(source, kind, status, name):
    event = activity(
        source,
        model="local-model",
        tool="lookup",
        agent="researcher",
        action_id="child-action",
        parent_action_id="parent-action",
        delegation_id="parent-delegation",
        prompt="private-marker",
        args={"token": "private-marker"},
        result="private-marker",
        message="private-marker",
        reasoning="private-marker",
        credentials="private-marker",
    )
    event.summary = "private-marker"
    update = PresentationEvent.from_run_event(event)
    assert (update.type, update.status, update.name) == (kind, status, name)
    assert update.event_id == event.event_id
    assert update.run_id == "child-run" and update.task_id == "child-task"
    assert update.agent_name == "worker" and update.sequence == 8 and update.step == 2
    assert update.action_id == "child-action"
    assert update.parent_action_id == "parent-action" and update.delegation_id == "parent-delegation"
    assert update.span_id == event.span_id and update.parent_span_id == "parent-action"
    assert "private-marker" not in json.dumps(update.to_dict())
    assert not update.final


def test_requested_action_and_approval_never_present_authorization_as_execution():
    action = {
        "kind": "tool.call",
        "name": "remove",
        "action_id": "remove-action",
        "payload": {"arguments": {"token": "private-marker"}},
        "description": "private-marker",
        "artifacts": [{"text": "private-marker"}],
    }
    requested, required, approved, denied = collect_presentation_events(
        [
            activity("action_requested", action=action),
            activity("approval_required", request={"request_id": "approval-1", "action": action}),
            activity("approval_decision", decision={"request_id": "approval-1", "approved": True}),
            activity("action_denied", action_id="remove-action", message="private-marker"),
        ]
    )
    assert (requested.type, requested.status, requested.name) == ("tool", "requested", "remove")
    assert (required.type, required.status, required.name) == ("approval", "required", "remove")
    assert required.approval_id == approved.approval_id == "approval-1"
    assert required.activity_id == approved.activity_id == "approval-1"
    assert approved.status == "approved" and denied.status == "denied"
    assert denied.action_id == "remove-action"
    assert all(event.status != "completed" for event in (requested, required, approved, denied))
    assert "private-marker" not in json.dumps([event.to_dict() for event in (requested, required, approved, denied)])


def test_model_calls_share_step_identity_without_inventing_missing_source_ids():
    started = activity("llm_call_started", model="local-model")
    completed = activity("llm_call_completed", model="local-model")
    first = PresentationEvent.from_run_event(started)
    last = PresentationEvent.from_run_event(completed)
    assert first.activity_id == last.activity_id == "child-run:child-task:model:2"
    assert PresentationEvent.from_run_event(RunEvent(type="llm.call.started")).activity_id is None


@pytest.mark.parametrize("state", ["completed", "canceled", "failed", "rejected", "input-required"])
def test_task_outcomes_keep_terminal_states_distinct(state):
    source = RunEvent.from_task_event(TaskStatusUpdateEvent(task_id="task", new_state=state, final=True))
    update = PresentationEvent.from_run_event(source)
    assert update.type == "run" and update.status == state and update.final


@pytest.mark.parametrize(
    ("source", "status"),
    [
        ("run.queued", "queued"),
        ("run.admitted", "running"),
        ("run.expired", "expired"),
        ("run.rejected", "rejected"),
        ("run.canceled", "canceled"),
    ],
)
def test_admission_activity_preserves_source_cursor(source, status):
    update = PresentationEvent.from_run_event(RunEvent(type=source, run_id="run", sequence=3))
    assert update.type == "run" and update.status == status
    assert update.activity_id == "run" and update.sequence == 3


def test_private_and_unknown_events_are_omitted_and_missing_states_are_not_denials():
    events = [
        activity(kind, prompt="private-marker", content="private-marker")
        for kind in ("llm_chunk", "llm_final", "llm_response", "llm_context", "context_prepared", "reasoning")
    ]
    events += [RunEvent(type="task.artifact", payload={"artifact": "private-marker"}), RunEvent(type="custom")]
    assert collect_presentation_events(events) == ()
    assert PresentationEvent.from_run_event(activity("approval_decision")).status == "unknown"
    assert PresentationEvent.from_run_event(RunEvent(type="task.status", payload={"new_state": {}})).status == "unknown"
    assert PresentationEvent.from_run_event(activity("tool_start", tool={"secret": "private-marker"})).name is None


def test_known_secrets_in_display_labels_are_redacted_and_replay_is_deterministic():
    source = activity("tool_start", tool="lookup-secret-value", action_id="action-secret-value")
    policy = RedactionPolicy(sensitive_values=frozenset({"secret-value"}))
    update = PresentationEvent.from_run_event(source, redaction_policy=policy)
    assert update.name == "lookup-[REDACTED]" and update.action_id == "action-[REDACTED]"
    assert collect_presentation_events([source.to_dict()], redaction_policy=policy) == (update,)
    detached = update.to_dict()
    detached["name"] = "changed"
    assert update.name == "lookup-[REDACTED]"
