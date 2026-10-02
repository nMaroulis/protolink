"""Core restoration preserves saved identities and generates missing defaults."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import protolink.utils.id_generator as id_generator_module
from protolink.core.artifact import Artifact
from protolink.core.events import (
    TaskArtifactUpdateEvent,
    TaskErrorEvent,
    TaskLLMStreamEvent,
    TaskProgressEvent,
    TaskStatusUpdateEvent,
)
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task
from protolink.utils.id_generator import IDGenerator

EVENT_TYPES = (
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TaskProgressEvent,
    TaskLLMStreamEvent,
    TaskErrorEvent,
)


@pytest.mark.parametrize(
    "moment,expected",
    [
        (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "20260102030405"),
        (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), "20261231235959"),
    ],
)
def test_identifier_timestamp_keeps_compact_utc_format(monkeypatch, moment, expected) -> None:
    monkeypatch.setattr(id_generator_module, "datetime", SimpleNamespace(now=lambda tz: moment.astimezone(tz)))
    assert IDGenerator._generate_timestamp() == expected


def test_restoration_does_not_generate_discarded_defaults(monkeypatch) -> None:
    task = Task.create_tool_call("echo", {"text": "hello"})
    task.add_artifact(Artifact(parts=[Part.tool_output(call_id="saved-call", result="hello")]))
    payload = task.to_dict()
    events = [(event_type, event_type(task_id=task.id).to_dict()) for event_type in EVENT_TYPES]

    def unexpected_default():
        raise AssertionError("Restoration should retain the serialized field")

    monkeypatch.setattr(IDGenerator, "_generate_timestamp", unexpected_default)
    for module in ("task", "message", "artifact", "events"):
        monkeypatch.setattr(f"protolink.core.{module}.utc_now", unexpected_default)
    monkeypatch.setattr("protolink.core.events.uuid.uuid4", unexpected_default)

    assert Task.from_dict(payload).to_dict() == payload
    for event_type, event_payload in events:
        assert event_type.from_dict(event_payload).to_dict() == event_payload


def test_restoration_generates_missing_identifiers_and_timestamps() -> None:
    task = Task.from_dict({})
    message = Message.from_dict({})
    artifact = Artifact.from_dict({})
    call = Part.from_dict({"type": "tool_call", "content": {"tool_name": "echo"}}).as_tool_call()
    output = Part.from_dict({"type": "tool_output", "content": {}}).as_tool_output()

    assert task.id.startswith("task_") and task.created_at
    assert message.id.startswith("msg_") and message.timestamp
    assert artifact.id.startswith("art_") and artifact.timestamp
    assert call.call_id.startswith("tool_call_")
    assert output.call_id.startswith("tool_output_")
    for event_type in EVENT_TYPES:
        event = event_type.from_dict({})
        assert event.event_id and event.timestamp


@pytest.mark.parametrize("value", [None, ""])
def test_restoration_preserves_explicit_empty_identity_fields(value) -> None:
    assert Task.from_dict({"id": value, "created_at": value}).id == value
    assert Message.from_dict({"id": value, "timestamp": value}).timestamp == value
    assert Artifact.from_dict({"id": value, "timestamp": value}).id == value
    for event_type in EVENT_TYPES:
        event = event_type.from_dict({"event_id": value, "timestamp": value})
        assert event.event_id == value and event.timestamp == value
