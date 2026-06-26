"""Local replayable telemetry for Protolink task execution.

This module provides an observability backend that does not depend on a hosted
service. It mirrors the same task, LLM, tool, and delegation lifecycle used by
external providers, but stores traces locally as structured Python objects and,
optionally, JSONL records. The implementation uses ``contextvars`` so nested
spans remain associated with the correct task even when execution crosses async
boundaries.
"""

from __future__ import annotations

import contextvars
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protolink.core.redaction import DEFAULT_REDACTION_POLICY
from protolink.models import Part, Task
from protolink.telemetry.base import Telemetry
from protolink.utils.id_generator import IDGenerator

Redactor = Callable[[Any], Any]

_current_trace: contextvars.ContextVar[Any] = contextvars.ContextVar("protolink_local_trace", default=None)
_current_span_stack: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "protolink_local_span_stack",
    default=(),
)


def _utc_now() -> str:
    """Return a timezone-aware ISO-8601 timestamp for trace records."""
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started_at: str, ended_at: str | None) -> float | None:
    """Compute an elapsed duration in milliseconds from serialized timestamps."""
    if not ended_at:
        return None
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(ended_at)
    return round((end - start).total_seconds() * 1000, 3)


def _estimate_tokens(value: Any) -> int:
    """Estimate token count for providers that do not report usage metadata.

    The estimate intentionally uses a simple four-character heuristic. It is
    not a billing-grade tokenizer, but it gives local traces a useful relative
    signal without pulling in provider-specific tokenization dependencies.
    """
    text = "" if value is None else str(value)
    if not text:
        return 0
    return max(1, len(text) // 4)


def _numeric(value: Any) -> float | None:
    """Best-effort numeric conversion for telemetry aggregation."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_jsonable(value: Any) -> Any:
    """Convert framework and dataclass objects into JSON-compatible values.

    Trace persistence should never fail simply because a provider or tool
    returned a rich Python object. This helper recursively normalizes common
    Protolink models, dataclasses, containers, and fallback values.
    """
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def default_redactor(value: Any) -> Any:
    """Mask common secret-bearing fields in nested trace payloads.

    Redaction happens after JSON normalization and before data is attached to a
    trace. Callers may layer a custom redactor on top through
    ``LocalTraceTelemetry(redactor=...)`` for application-specific policy.
    """
    return DEFAULT_REDACTION_POLICY.redact(value)


@dataclass
class TraceEvent:
    """A point-in-time event emitted during task execution.

    Events capture detailed activity that does not need its own duration, such
    as parsed LLM actions, streamed chunks, parse retries, and final outputs.
    When a span is active, the event stores that span ID for replay tooling.
    """

    type: str
    timestamp: str = field(default_factory=_utc_now)
    span_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event into a JSON-compatible dictionary."""
        return asdict(self)


@dataclass
class TraceSpan:
    """A timed execution span inside a local Protolink trace.

    Spans represent operations with duration: tasks, LLM calls, tool calls, and
    delegated agent calls. Parent IDs form a replayable hierarchy without
    needing provider-specific trace objects.
    """

    id: str
    trace_id: str
    name: str
    kind: str
    parent_id: str | None = None
    started_at: str = field(default_factory=_utc_now)
    ended_at: str | None = None
    status: str = "ok"
    input: Any | None = None
    output: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[TraceEvent] = field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        """Return the span duration once the span has ended."""
        return _duration_ms(self.started_at, self.ended_at)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the span, including computed duration and child events."""
        data = asdict(self)
        data["duration_ms"] = self.duration_ms
        data["events"] = [event.to_dict() for event in self.events]
        return data


@dataclass
class TraceRecord:
    """Replayable local trace for one task execution.

    A trace record is the top-level artifact produced by
    ``LocalTraceTelemetry``. It contains task metadata, a flat span list with
    parent IDs, and a chronological event list suitable for local inspection or
    JSONL persistence.
    """

    trace_id: str
    task_id: str
    agent_name: str
    started_at: str = field(default_factory=_utc_now)
    ended_at: str | None = None
    status: str = "running"
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[TraceSpan] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        """Return total trace duration after task completion."""
        return _duration_ms(self.started_at, self.ended_at)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete trace into a replayable dictionary."""
        data = asdict(self)
        data["duration_ms"] = self.duration_ms
        data["spans"] = [span.to_dict() for span in self.spans]
        data["events"] = [event.to_dict() for event in self.events]
        return data


class LocalTraceRecorder:
    """In-process recorder for local trace replay and debugging.

    Traces are kept in memory and may also be appended to a JSONL file. The
    JSONL format makes it easy to inspect, diff, or replay task executions
    without an external observability service.
    """

    def __init__(self, path: str | Path | None = None, *, max_traces: int = 1000) -> None:
        """Initialize the recorder.

        Args:
            path: Optional JSONL destination. When provided, completed traces
                are appended as one JSON object per line.
            max_traces: Maximum number of traces retained in memory. Set to
                ``0`` or a negative value to disable in-memory truncation.
        """
        self.path = Path(path).expanduser() if path else None
        self.max_traces = max_traces
        self.traces: list[TraceRecord] = []

    def record(self, trace: TraceRecord) -> None:
        """Persist a completed trace in memory and optionally to JSONL.

        The recorder stores the original ``TraceRecord`` object in memory so
        tests and local tooling can inspect structured spans without a
        deserialize/serialize cycle. File output is normalized through
        ``TraceRecord.to_dict()`` to keep JSONL records stable.
        """
        self.traces.append(trace)
        if self.max_traces > 0 and len(self.traces) > self.max_traces:
            self.traces = self.traces[-self.max_traces :]

        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(trace.to_dict(), ensure_ascii=False) + "\n")

    def clear(self) -> None:
        """Remove all in-memory traces without touching any JSONL file."""
        self.traces.clear()

    def replay(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        """Return serialized traces for local debugging or replay UIs.

        Args:
            trace_id: Optional trace ID filter. When omitted, all retained
                in-memory traces are returned in completion order.
        """
        records = self.traces
        if trace_id is not None:
            records = [trace for trace in records if trace.trace_id == trace_id]
        return [trace.to_dict() for trace in records]

    @classmethod
    def load_jsonl(cls, path: str | Path) -> list[dict[str, Any]]:
        """Load previously persisted trace records from a JSONL file.

        Missing files return an empty list, which keeps local replay tools easy
        to call during development before any trace file exists.
        """
        jsonl_path = Path(path).expanduser()
        if not jsonl_path.exists():
            return []
        records = []
        with jsonl_path.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if stripped:
                    records.append(json.loads(stripped))
        return records


class LocalTraceTelemetry(Telemetry):
    """Built-in local tracer for Protolink task execution.

    It records trace IDs, parent/child spans, model metadata, token estimates,
    cost fields when supplied by providers, raw action payloads, retry counts,
    redacted inputs/outputs, and replayable JSON records.
    """

    def __init__(
        self,
        recorder: LocalTraceRecorder | None = None,
        *,
        path: str | Path | None = None,
        redactor: Redactor | None = None,
        capture_payloads: bool = True,
        max_traces: int = 1000,
    ) -> None:
        """Initialize local telemetry.

        Args:
            recorder: Optional recorder instance. Pass one to share trace
                storage across agents or tests.
            path: Optional JSONL output path used when ``recorder`` is not
                provided.
            redactor: Optional callable applied after default secret masking.
            capture_payloads: Whether inputs, outputs, and event payloads are
                stored. Disable this for metadata-only traces.
            max_traces: Maximum in-memory trace count for the default recorder.
        """
        self.recorder = recorder or LocalTraceRecorder(path=path, max_traces=max_traces)
        self.redactor = redactor
        self.capture_payloads = capture_payloads

    def _redact(self, value: Any) -> Any:
        """Apply default and user-provided redaction to trace payload data."""
        redacted = default_redactor(value)
        if self.redactor is not None:
            return self.redactor(redacted)
        return redacted

    def _trace(self) -> TraceRecord | None:
        """Return the active task trace bound to the current context."""
        return _current_trace.get()

    def _span_by_id(self, span_id: str) -> TraceSpan | None:
        """Resolve a span from the active trace by ID."""
        trace = self._trace()
        if not trace:
            return None
        for span in trace.spans:
            if span.id == span_id:
                return span
        return None

    def _current_span(self) -> TraceSpan | None:
        """Return the top-most active span for the current task context."""
        stack: tuple[str, ...] = _current_span_stack.get()
        if not stack:
            return None
        return self._span_by_id(stack[-1])

    def _record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Attach a point-in-time event to the active trace and span."""
        trace = self._trace()
        if not trace:
            return
        span = self._current_span()
        event = TraceEvent(
            type=event_type,
            span_id=span.id if span else None,
            payload=self._redact(payload) if self.capture_payloads else {},
        )
        trace.events.append(event)
        if span:
            span.events.append(event)

    def _merge_llm_metrics(self, metrics: dict[str, Any]) -> None:
        """Aggregate per-call LLM metrics into the active LLM span and trace."""
        trace = self._trace()
        span = self._current_span()
        if not trace or not span:
            return

        targets = [span.metadata, trace.metadata]
        for metadata in targets:
            rollup = metadata.setdefault(
                "llm_metrics",
                {
                    "call_count": 0,
                    "total_latency_ms": 0.0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_token_calls": 0,
                    "total_cost": None,
                    "currency": None,
                    "max_context_used_percent": None,
                    "max_context_used_tokens": 0,
                    "context_window_tokens": None,
                },
            )
            rollup["call_count"] = int(rollup.get("call_count", 0)) + 1

            latency_ms = _numeric(metrics.get("latency_ms"))
            if latency_ms is not None:
                rollup["total_latency_ms"] = round(float(rollup.get("total_latency_ms", 0.0)) + latency_ms, 3)

            usage = metrics.get("usage") if isinstance(metrics.get("usage"), dict) else {}
            if usage:
                if usage.get("estimated"):
                    rollup["estimated_token_calls"] = int(rollup.get("estimated_token_calls", 0)) + 1
                for source_key, target_key in (
                    ("input_tokens", "total_input_tokens"),
                    ("output_tokens", "total_output_tokens"),
                    ("total_tokens", "total_tokens"),
                ):
                    value = _numeric(usage.get(source_key))
                    if value is not None:
                        rollup[target_key] = int(rollup.get(target_key, 0)) + int(value)

            context = metrics.get("context") if isinstance(metrics.get("context"), dict) else {}
            if context:
                used_tokens = _numeric(context.get("used_tokens"))
                if used_tokens is not None:
                    rollup["max_context_used_tokens"] = max(
                        int(rollup.get("max_context_used_tokens", 0)),
                        int(used_tokens),
                    )
                used_percent = _numeric(context.get("used_percent"))
                if used_percent is not None:
                    current_percent = _numeric(rollup.get("max_context_used_percent"))
                    rollup["max_context_used_percent"] = round(
                        max(current_percent or 0.0, used_percent),
                        3,
                    )
                window_tokens = _numeric(context.get("window_tokens"))
                if window_tokens is not None:
                    rollup["context_window_tokens"] = int(window_tokens)

            cost = metrics.get("cost") if isinstance(metrics.get("cost"), dict) else {}
            if cost:
                total_cost = _numeric(cost.get("total_cost"))
                if total_cost is not None:
                    existing_cost = _numeric(rollup.get("total_cost")) or 0.0
                    rollup["total_cost"] = round(existing_cost + total_cost, 8)
                if cost.get("currency"):
                    rollup["currency"] = cost.get("currency")

    def _start_span(
        self,
        *,
        name: str,
        kind: str,
        span_input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceSpan | None:
        """Open a child span under the current active span.

        Span nesting is maintained with a context-local stack of IDs. This
        avoids passing span objects through the agent runtime while still
        preserving parent-child relationships in async execution.
        """
        trace = self._trace()
        if not trace:
            return None

        stack: tuple[str, ...] = _current_span_stack.get()
        span = TraceSpan(
            id=IDGenerator.generate_uuid(),
            trace_id=trace.trace_id,
            parent_id=stack[-1] if stack else None,
            name=name,
            kind=kind,
            input=self._redact(span_input) if self.capture_payloads else None,
            metadata=self._redact(metadata or {}),
        )
        trace.spans.append(span)
        _current_span_stack.set((*stack, span.id))
        return span

    def _end_span(
        self,
        *,
        kind: str | None = None,
        output: Any | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Close the nearest active span matching ``kind``.

        Closing by kind lets detailed LLM-loop events finish tool or delegated
        agent spans even when they are nested inside the broader LLM span.
        """
        trace = self._trace()
        if not trace:
            return

        stack: tuple[str, ...] = _current_span_stack.get()
        target_idx: int | None = None
        target_span: TraceSpan | None = None
        for idx in range(len(stack) - 1, -1, -1):
            span = self._span_by_id(stack[idx])
            if span and span.ended_at is None and (kind is None or span.kind == kind):
                target_idx = idx
                target_span = span
                break

        if target_span is None or target_idx is None:
            return

        target_span.ended_at = _utc_now()
        target_span.output = self._redact(output) if self.capture_payloads else None
        if error:
            target_span.status = "error"
            target_span.error = error
        if metadata:
            target_span.metadata.update(self._redact(metadata))

        _current_span_stack.set(stack[:target_idx] + stack[target_idx + 1 :])

    async def on_task_start(self, task: Task, agent_name: str) -> Any:
        """Start a trace and root task span for an agent task."""
        trace_id = task.metadata.get("trace_id") or IDGenerator.generate_uuid()
        task.metadata["trace_id"] = trace_id

        trace = TraceRecord(
            trace_id=trace_id,
            task_id=task.id,
            agent_name=agent_name,
            metadata={
                "agent_name": agent_name,
                "task_state": task.state.value if hasattr(task.state, "value") else str(task.state),
            },
        )
        _current_trace.set(trace)
        _current_span_stack.set(())
        self._start_span(
            name=f"Task: {agent_name}",
            kind="task",
            span_input=task.to_dict(),
            metadata={"task_id": task.id, "trace_id": trace_id},
        )

    async def on_task_end(self, task: Task, result: Task, agent_name: str) -> Any:
        """Finalize the root task span and commit the completed trace."""
        trace = self._trace()
        if not trace:
            return
        error = result.metadata.get("error") if isinstance(result.metadata, dict) else None
        self._end_span(
            kind="task",
            output=result.to_dict(),
            error=str(error) if error else None,
            metadata={"final_state": result.state.value if hasattr(result.state, "value") else str(result.state)},
        )
        trace.ended_at = _utc_now()
        trace.status = "error" if error else "ok"
        trace.metadata["final_state"] = result.state.value if hasattr(result.state, "value") else str(result.state)
        trace.metadata["retry_count"] = trace.metadata.get("retry_count", 0)
        self.recorder.record(trace)
        _current_trace.set(None)
        _current_span_stack.set(())

    async def on_llm_start(
        self,
        prompt: str,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Start an LLM span with model metadata and input usage estimates."""
        span_metadata = {
            "model": model,
            "cost": (metadata or {}).get("cost"),
            "usage": {
                "input_chars": len(prompt),
                "input_tokens_estimate": _estimate_tokens(prompt),
            },
        }
        if metadata:
            span_metadata.update(metadata)
        self._start_span(name="LLM Call", kind="llm", span_input={"prompt": prompt}, metadata=span_metadata)

    async def on_llm_end(self, response: Part) -> Any:
        """Close the active LLM span and attach output usage estimates."""
        content = response.content if hasattr(response, "content") else response
        self._end_span(
            kind="llm",
            output=content,
            metadata={
                "output_usage": {
                    "output_chars": len(str(content)),
                    "output_tokens_estimate": _estimate_tokens(content),
                }
            },
        )

    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Start a tool span for explicit task-level tool execution."""
        self._start_span(
            name=f"Tool: {tool_name}",
            kind="tool",
            span_input=args,
            metadata={"tool_name": tool_name, "source": "task"},
        )

    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
        """Close a task-level tool span with result or error information."""
        self._end_span(
            kind="tool",
            output={"result": result},
            error=error,
            metadata={"tool_name": tool_name},
        )

    async def on_llm_event(self, event: dict[str, Any]) -> Any:
        """Record fine-grained events emitted by the LLM inference loop.

        This hook turns action-level events into replayable observability data:
        tool calls and delegated agent calls become child spans, parse failures
        update retry metadata, and all events are appended chronologically to
        the trace.
        """
        event_type = str(event.get("type", "llm_event"))
        payload = dict(event)

        if event_type == "context_prepared":
            span = self._current_span()
            manifest = event.get("manifest")
            if span and isinstance(manifest, dict):
                span.metadata["context_manifest"] = self._redact(manifest)
        elif event_type == "llm_context":
            span = self._current_span()
            context = event.get("context")
            if span and isinstance(context, dict):
                span.metadata["context"] = self._redact(context)
        elif event_type in {"budget_warning", "budget_exceeded"}:
            trace = self._trace()
            decision = event.get("decision")
            if trace and isinstance(decision, dict):
                trace.metadata.setdefault("budget_decisions", []).append(self._redact(decision))
        elif event_type == "llm_call_metrics":
            metrics = {key: value for key, value in payload.items() if key != "type"}
            self._merge_llm_metrics(metrics)
        elif event_type == "tool_start":
            self._start_span(
                name=f"Tool: {event.get('tool', 'unknown')}",
                kind="tool",
                span_input=event.get("args", {}),
                metadata={"tool_name": event.get("tool"), "source": "llm_loop", "step": event.get("step")},
            )
        elif event_type in {"tool_result", "tool_error"}:
            self._record_event(event_type, payload)
            self._end_span(
                kind="tool",
                output={"result": event.get("result")},
                error=event.get("message") if event_type == "tool_error" else None,
                metadata={"tool_name": event.get("tool"), "step": event.get("step")},
            )
            return
        elif event_type == "agent_call_start":
            self._start_span(
                name=f"Agent: {event.get('agent', 'unknown')}",
                kind="agent_call",
                span_input=event.get("payload", {}),
                metadata={"agent": event.get("agent"), "action": event.get("action"), "step": event.get("step")},
            )
        elif event_type in {"agent_call_result", "agent_call_error"}:
            self._record_event(event_type, payload)
            self._end_span(
                kind="agent_call",
                output={"result": event.get("result")},
                error=event.get("message") if event_type == "agent_call_error" else None,
                metadata={"agent": event.get("agent"), "action": event.get("action"), "step": event.get("step")},
            )
            return
        elif event_type == "llm_parse_error":
            trace = self._trace()
            if trace:
                trace.metadata["retry_count"] = max(
                    int(trace.metadata.get("retry_count", 0)),
                    int(event.get("retry_count", event.get("parse_failures", 0))),
                )
        elif event_type == "llm_retry":
            trace = self._trace()
            if trace:
                trace.metadata["retry_count"] = int(trace.metadata.get("retry_count", 0)) + 1

        self._record_event(event_type, payload)
