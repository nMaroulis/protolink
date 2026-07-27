"""
ProtoLink - Events

Event classes for task streaming and real-time updates.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from protolink.core.redaction import RedactionPolicy
from protolink.core.run_context import RUN_CONTEXT_METADATA_KEY, RunContext
from protolink.utils import utc_now

RUN_EVENT_VERSION = "1.0"
"""Current version of the stable Protolink run-event envelope."""

_EVENT_TYPE_MAP = {
    "task_status_update": "task.status",
    "task_artifact_update": "task.artifact",
    "task_progress": "task.progress",
    "task_llm_stream": "llm.stream",
    "task_error": "task.error",
}

_RUNTIME_LLM_EVENT_TYPE_MAP = {
    "context_prepared": "context.prepared",
    "llm_call_started": "llm.call.started",
    "llm_call_completed": "llm.call.completed",
    "budget_warning": "budget.warning",
    "budget_exceeded": "budget.exceeded",
    "action_requested": "action.requested",
    "policy_decision": "action.policy",
    "approval_required": "approval.required",
    "approval_decision": "approval.decided",
    "action_denied": "action.denied",
    "tool_start": "action.started",
    "tool_result": "action.completed",
    "tool_error": "action.failed",
    "agent_call_start": "action.started",
    "agent_call_result": "action.completed",
    "agent_call_error": "action.failed",
}
"""Stable run-event types promoted from inference runtime activity."""


@dataclass
class RunEvent:
    """Versioned runtime event emitted by a Protolink run.

    ``RunEvent`` is the stable application-facing envelope for task execution streams. Existing task stream events
    remain available for wire/backward compatibility; this type gives applications one normalized event shape with
    sequence numbers, severity, summaries, run IDs, task IDs, agent names, step numbers, payloads, and final-result
    markers.

    Attributes:
        type: Stable event type such as ``"task.status"`` or ``"llm.stream"``.
        run_id: Logical run identifier from ``RunContext``.
        task_id: Task correlated with the event.
        agent_name: Agent that emitted or handled the event.
        sequence: Monotonic sequence number assigned by an event sink.
        step: Optional inference/runtime step number.
        span_id: Optional causal span identifier for UI trees and traces.
        parent_span_id: Optional parent span identifier.
        action_id: Optional runtime action identifier related to the event.
        parent_action_id: Optional parent action identifier for nested actions.
        delegation_id: Optional delegated-agent operation identifier.
        severity: Event severity for renderers and logs.
        summary: Short human-readable summary suitable for progress UIs.
        payload: Full structured event payload.
        final: Whether this event closes the run stream.
        metadata: Envelope metadata that should not be interpreted as payload.
        event_id: Unique event identifier.
        version: Run-event envelope version.
        timestamp: ISO timestamp.
    """

    type: str
    run_id: str | None = None
    task_id: str | None = None
    agent_name: str | None = None
    sequence: int | None = None
    step: int | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    action_id: str | None = None
    parent_action_id: str | None = None
    delegation_id: str | None = None
    severity: str = "info"
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: str = RUN_EVENT_VERSION
    timestamp: str = field(default_factory=lambda: utc_now())

    def to_dict(self, *, redaction_policy: RedactionPolicy | None = None) -> dict[str, Any]:
        """Serialize the event into a JSON-compatible dictionary.

        Args:
            redaction_policy: Optional policy used to mask secrets before the dictionary is returned.
        """
        data = {
            "event_id": self.event_id,
            "version": self.version,
            "type": self.type,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "sequence": self.sequence,
            "step": self.step,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "action_id": self.action_id,
            "parent_action_id": self.parent_action_id,
            "delegation_id": self.delegation_id,
            "severity": self.severity,
            "summary": self.summary,
            "payload": self.payload,
            "final": self.final,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
        if redaction_policy is not None:
            return redaction_policy.redact(data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunEvent":
        """Create a run event from serialized data."""
        return cls(
            event_id=str(data.get("event_id") or uuid.uuid4()),
            version=str(data.get("version") or RUN_EVENT_VERSION),
            type=str(data.get("type") or "run.event"),
            run_id=_optional_str(data.get("run_id")),
            task_id=_optional_str(data.get("task_id")),
            agent_name=_optional_str(data.get("agent_name")),
            sequence=_optional_int(data.get("sequence")),
            step=_optional_int(data.get("step")),
            span_id=_optional_str(data.get("span_id")),
            parent_span_id=_optional_str(data.get("parent_span_id")),
            action_id=_optional_str(data.get("action_id")),
            parent_action_id=_optional_str(data.get("parent_action_id")),
            delegation_id=_optional_str(data.get("delegation_id")),
            severity=str(data.get("severity") or "info"),
            summary=_optional_str(data.get("summary")),
            payload=dict(data.get("payload") or {}),
            final=bool(data.get("final", False)),
            timestamp=str(data.get("timestamp") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_task_event(
        cls,
        event: Any,
        *,
        context: RunContext | dict[str, Any] | None = None,
        sequence: int | None = None,
    ) -> "RunEvent":
        """Normalize an existing task-stream event into a ``RunEvent``.

        Args:
            event: A task event object with ``to_dict()`` or a dictionary event emitted by a transport.
            context: Optional run context. If omitted, the method attempts toread ``run_context`` from the event's
                final-task payload.
            sequence: Optional sequence number assigned by the caller.

        Returns:
            A normalized run event that preserves the original event dictionary in ``payload``.
        """
        payload = _event_to_dict(event)
        source_type = str(payload.get("type") or "run.event")
        event_type = _normalized_event_type(source_type, payload)
        payload = _promote_runtime_payload(payload)
        run_context = _coerce_context(context) or _context_from_payload(payload)
        relationships = _relationships_from_payload(payload)

        return cls(
            type=event_type,
            run_id=run_context.run_id if run_context else _run_id_from_payload(payload),
            task_id=_optional_str(payload.get("task_id")),
            agent_name=_agent_name_from_payload(payload, run_context),
            sequence=sequence,
            step=_optional_int(payload.get("step")),
            span_id=relationships["span_id"],
            parent_span_id=relationships["parent_span_id"],
            action_id=relationships["action_id"],
            parent_action_id=relationships["parent_action_id"],
            delegation_id=relationships["delegation_id"],
            severity=_severity_for_payload(source_type, payload),
            summary=_summary_for_payload(source_type, payload),
            payload=payload,
            final=bool(payload.get("final", False)),
            metadata={"source_type": source_type},
        )


class EventSink(Protocol):
    """Protocol for objects that consume normalized ``RunEvent`` objects."""

    async def emit(self, event: RunEvent) -> None:
        """Consume one normalized run event."""
        ...


class InMemoryEventSink:
    """Simple event sink that records run events in memory.

    The sink is intentionally small and dependency-free so tests, CLIs, and local applications can capture a canonical
    event stream without a telemetry backend. It assigns monotonic sequence numbers when incoming events do not already
    have one.
    """

    def __init__(self) -> None:
        """Initialize an empty event buffer."""
        self._events: list[RunEvent] = []
        self._next_sequence = 1

    @property
    def events(self) -> tuple[RunEvent, ...]:
        """Return recorded events as an immutable tuple."""
        return tuple(self._events)

    async def emit(self, event: RunEvent) -> None:
        """Record one run event and assign a sequence number if missing."""
        if event.sequence is None:
            event.sequence = self._next_sequence
        self._next_sequence = max(self._next_sequence, event.sequence + 1)
        self._events.append(event)

    async def emit_task_event(
        self,
        event: Any,
        *,
        context: RunContext | dict[str, Any] | None = None,
    ) -> RunEvent:
        """Normalize and record a legacy task-stream event.

        Returns:
            The normalized ``RunEvent`` that was appended to the sink.
        """
        run_event = RunEvent.from_task_event(event, context=context)
        await self.emit(run_event)
        return run_event

    def to_list(self) -> list[dict[str, Any]]:
        """Return recorded events as serialized dictionaries."""
        return [event.to_dict() for event in self._events]

    def clear(self) -> None:
        """Clear recorded events and reset sequence numbering."""
        self._events.clear()
        self._next_sequence = 1


def _event_to_dict(event: Any) -> dict[str, Any]:
    if hasattr(event, "to_dict"):
        return dict(event.to_dict())
    if isinstance(event, dict):
        return dict(event)
    return {"type": "run.event", "content": event}


def _coerce_context(context: RunContext | dict[str, Any] | None) -> RunContext | None:
    if context is None:
        return None
    if isinstance(context, RunContext):
        return context
    return RunContext.from_dict(context)


def _context_from_payload(payload: dict[str, Any]) -> RunContext | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    task_data = metadata.get("task")
    if not isinstance(task_data, dict):
        return None
    task_metadata = task_data.get("metadata")
    if not isinstance(task_metadata, dict):
        return None
    context_data = task_metadata.get(RUN_CONTEXT_METADATA_KEY)
    if not isinstance(context_data, dict):
        return None
    return RunContext.from_dict(context_data)


def _run_id_from_payload(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        run_id = metadata.get("run_id")
        if run_id is not None:
            return str(run_id)
    return None


def _agent_name_from_payload(payload: dict[str, Any], context: RunContext | None) -> str | None:
    agent_name = payload.get("agent_name")
    if agent_name:
        return str(agent_name)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("agent"):
        return str(metadata["agent"])
    if context and context.agent_chain:
        return context.agent_chain[-1]
    return None


def _severity_for_payload(source_type: str, payload: dict[str, Any]) -> str:
    if source_type == "task_error":
        return "error"
    if source_type == "task_llm_stream" and payload.get("llm_event_type") in {
        "action_denied",
        "agent_call_error",
        "budget_exceeded",
        "llm_error",
        "tool_error",
    }:
        return "error"
    if source_type == "task_llm_stream" and payload.get("llm_event_type") in {
        "approval_required",
        "budget_warning",
        "llm_parse_error",
        "llm_retry",
    }:
        return "warning"
    return "info"


def _summary_for_payload(source_type: str, payload: dict[str, Any]) -> str | None:
    if source_type == "task_status_update":
        state = payload.get("new_state") or "unknown"
        if payload.get("final"):
            return f"Task finished with state {state}"
        return f"Task state changed to {state}"

    if source_type == "task_artifact_update":
        artifact = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
        artifact_id = artifact.get("id") if artifact else None
        return f"Artifact produced{f': {artifact_id}' if artifact_id else ''}"

    if source_type == "task_progress":
        message = payload.get("message")
        if message:
            return str(message)
        progress = payload.get("progress")
        return f"Task progress {progress}%"

    if source_type == "task_llm_stream":
        llm_type = payload.get("llm_event_type") or "llm_event"
        metadata = _dict_value(payload.get("metadata"))
        if llm_type == "context_prepared":
            manifest = _dict_value(metadata.get("manifest"))
            total = manifest.get("total_estimated_tokens")
            if total is not None:
                return f"Context prepared: {total} estimated tokens"
            return "Context prepared"
        if llm_type == "llm_call_started":
            model = metadata.get("model") or "model"
            return f"LLM call started: {model}"
        if llm_type == "llm_call_completed":
            model = metadata.get("model") or "model"
            latency = metadata.get("latency_ms")
            return f"LLM call completed: {model}{f' in {latency} ms' if latency is not None else ''}"
        if llm_type in {"budget_warning", "budget_exceeded"}:
            decision = _dict_value(metadata.get("decision"))
            return _optional_str(decision.get("message")) or str(llm_type)
        if llm_type == "action_requested":
            action = _dict_value(metadata.get("action"))
            return f"Action requested: {action.get('name', 'unnamed')}"
        if llm_type == "policy_decision":
            decision = _dict_value(metadata.get("decision"))
            return f"Policy decision: {decision.get('effect', 'unknown')}"
        if llm_type == "approval_required":
            request = _dict_value(metadata.get("request"))
            action = _dict_value(request.get("action"))
            return f"Approval required: {action.get('name', 'unnamed')}"
        if llm_type == "approval_decision":
            decision = _dict_value(metadata.get("decision"))
            return "Approval granted" if decision.get("approved") else "Approval denied"
        if llm_type == "action_denied":
            return _optional_str(metadata.get("message")) or "Action denied"
        if llm_type in {"tool_start", "agent_call_start"}:
            target = metadata.get("tool") or metadata.get("agent") or "unnamed"
            return f"Action started: {target}"
        if llm_type in {"tool_result", "agent_call_result"}:
            target = metadata.get("tool") or metadata.get("agent") or "unnamed"
            return f"Action completed: {target}"
        if llm_type in {"tool_error", "agent_call_error"}:
            return _optional_str(metadata.get("message")) or "Action failed"
        content = payload.get("content")
        if payload.get("final") and content is not None:
            return _trim_summary(f"{llm_type}: {content}")
        return str(llm_type)

    if source_type == "task_error":
        return _optional_str(payload.get("error_message")) or "Task failed"

    return _optional_str(payload.get("summary"))


def _normalized_event_type(source_type: str, payload: dict[str, Any]) -> str:
    """Return the stable run-event type for a task-stream payload."""
    if source_type == "task_llm_stream":
        llm_type = str(payload.get("llm_event_type") or "")
        runtime_type = _RUNTIME_LLM_EVENT_TYPE_MAP.get(llm_type)
        if runtime_type is not None:
            return runtime_type
    return _EVENT_TYPE_MAP.get(source_type, source_type)


def _promote_runtime_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Promote stable action fields while preserving the original task event."""
    if payload.get("type") != "task_llm_stream":
        return payload

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return payload

    promoted = dict(payload)
    for key in (
        "action",
        "action_id",
        "decision",
        "delegation_id",
        "manifest",
        "parent_action_id",
        "parent_span_id",
        "request",
        "span_id",
    ):
        if key in metadata:
            promoted[key] = metadata[key]
    return promoted


def _relationships_from_payload(payload: dict[str, Any]) -> dict[str, str | None]:
    """Extract causal IDs from promoted runtime payloads."""
    metadata = _dict_value(payload.get("metadata"))
    action = _dict_value(payload.get("action")) or _dict_value(metadata.get("action"))
    request = _dict_value(payload.get("request")) or _dict_value(metadata.get("request"))
    request_action = _dict_value(request.get("action"))
    decision = _dict_value(payload.get("decision")) or _dict_value(metadata.get("decision"))

    sources = (payload, metadata, action, request, request_action, decision)

    def first_string(key: str) -> str | None:
        for source in sources:
            value = source.get(key)
            if value is not None:
                return str(value)
        return None

    action_id = first_string("action_id")
    parent_action_id = first_string("parent_action_id")
    delegation_id = first_string("delegation_id")
    llm_type = payload.get("llm_event_type")
    if delegation_id is None and llm_type in {"agent_call_start", "agent_call_result", "agent_call_error"}:
        delegation_id = action_id

    span_id = first_string("span_id")
    if (
        span_id is None
        and action_id is not None
        and str(payload.get("llm_event_type", "")).startswith(
            ("action_", "approval_", "policy_", "tool_", "agent_call_")
        )
    ):
        span_id = action_id

    parent_span_id = first_string("parent_span_id") or parent_action_id

    return {
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "action_id": action_id,
        "parent_action_id": parent_action_id,
        "delegation_id": delegation_id,
    }


def _dict_value(value: Any) -> dict[str, Any]:
    """Return a dictionary value or an empty typed dictionary."""
    if isinstance(value, dict):
        return value
    return {}


def _trim_summary(value: str, limit: int = 140) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


@dataclass
class TaskStatusUpdateEvent:
    """Task state transition event for streaming updates.

    Emitted when a task changes state (e.g., submitted → working → completed). Can be streamed to clients via SSE for
    real-time progress visibility.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task being updated
        previous_state: State before transition (or None for initial)
        new_state: Current task state
        timestamp: When event occurred
        final: Whether this ends the stream
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    previous_state: str | None = None
    new_state: str = ""
    timestamp: str = field(default_factory=lambda: utc_now())
    final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_status_update",
            "task_id": self.task_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "timestamp": self.timestamp,
            "final": self.final,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskStatusUpdateEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state", ""),
            timestamp=data.get("timestamp", utc_now()),
            final=data.get("final", False),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskArtifactUpdateEvent:
    """New artifact available event.

    Emitted when a task produces an output artifact (file, result, etc.). Allows progressive delivery of results in
    streaming scenarios.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task
        artifact: The artifact that was produced
        timestamp: When event occurred
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    artifact: Any = None  # Artifact object
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        artifact_dict = None
        if self.artifact and hasattr(self.artifact, "to_dict"):
            artifact_dict = self.artifact.to_dict()

        return {
            "event_id": self.event_id,
            "type": "task_artifact_update",
            "task_id": self.task_id,
            "artifact": artifact_dict,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskArtifactUpdateEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            artifact=data.get("artifact"),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskProgressEvent:
    """Task progress update event.

    Emitted to report incremental progress (e.g., 50% complete). Useful for long-running tasks that want to signal
    advancement.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task
        progress: Completion percentage (0-100)
        message: Optional progress message
        timestamp: When event occurred
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    progress: int = 0  # 0-100
    message: str | None = None
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_progress",
            "task_id": self.task_id,
            "progress": self.progress,
            "message": self.message,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskProgressEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            progress=data.get("progress", 0),
            message=data.get("message"),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskLLMStreamEvent:
    """LLM inference event emitted while an agent is processing a task.

    This event carries provider-agnostic inference activity such as streamed chunks, parsed actions, tool
    starts/results, delegated agent calls, and final inference content.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    agent_name: str = ""
    llm_event_type: str = ""
    step: int | None = None
    content: Any = None
    final: bool = False
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_llm_stream",
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "llm_event_type": self.llm_event_type,
            "step": self.step,
            "content": self.content,
            "final": self.final,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskLLMStreamEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            agent_name=data.get("agent_name", ""),
            llm_event_type=data.get("llm_event_type", ""),
            step=data.get("step"),
            content=data.get("content"),
            final=data.get("final", False),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskErrorEvent:
    """Task error event.

    Emitted when a task encounters an error. Allows streaming of error details without closing connection.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task
        error_code: Error code/type
        error_message: Human-readable error description
        recoverable: Whether error is recoverable
        timestamp: When event occurred
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    error_code: str = ""
    error_message: str = ""
    recoverable: bool = False
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_error",
            "task_id": self.task_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskErrorEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            error_code=data.get("error_code", ""),
            error_message=data.get("error_message", ""),
            recoverable=data.get("recoverable", False),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )
