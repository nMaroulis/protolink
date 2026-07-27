"""Run reports, replay helpers, and golden-run assertions.

``RunEvent`` is the live application-facing stream. ``RunReport`` is the durable summary built from that stream: compact
enough for JSONL or SQLite, but structured enough for trace UIs, replay tools, and integration tests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from protolink.core.events import InMemoryEventSink, RunEvent
from protolink.core.redaction import RedactionPolicy
from protolink.core.run_context import RunContext
from protolink.utils import utc_now


@dataclass(frozen=True)
class RunReport:
    """Durable application-facing summary for one run.

    Args:
        context: Optional run context associated with the report.
        context_manifests: Context manifests prepared before LLM calls.
        events: Normalized run events in chronological order.
        actions: Runtime actions observed in the event stream.
        approvals: Approval checkpoints and decisions observed in the stream.
        artifacts: Artifacts emitted by task events.
        metrics: LLM call metrics and lifecycle timing payloads.
        final_task: Serialized final task payload, when available.
        metadata: Application-owned report metadata.
        created_at: ISO timestamp for report creation.
    """

    context: RunContext | None = None
    context_manifests: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    events: tuple[RunEvent, ...] = field(default_factory=tuple)
    actions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    approvals: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    metrics: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    final_task: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())

    @classmethod
    def from_events(
        cls,
        events: Iterable[RunEvent | dict[str, Any]],
        *,
        context: RunContext | dict[str, Any] | None = None,
        final_task: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunReport:
        """Build a report by extracting stable sections from run events."""
        normalized = tuple(_coerce_event(event) for event in events)
        report_context = _coerce_context(context)
        report_final_task = final_task or _final_task_from_events(normalized)
        manifests: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        metrics: list[dict[str, Any]] = []
        seen_actions: set[str] = set()

        for event in normalized:
            manifest = _manifest_from_event(event)
            if manifest is not None:
                manifests.append(manifest)

            action = _action_from_event(event)
            if action is not None:
                action_id = str(action.get("action_id") or "")
                if not action_id or action_id not in seen_actions:
                    actions.append(action)
                    if action_id:
                        seen_actions.add(action_id)

            approval = _approval_from_event(event)
            if approval is not None:
                approvals.append(approval)

            artifact = _artifact_from_event(event)
            if artifact is not None:
                artifacts.append(artifact)

            metric = _metrics_from_event(event)
            if metric is not None:
                metrics.append(metric)

        return cls(
            context=report_context,
            context_manifests=tuple(manifests),
            events=normalized,
            actions=tuple(actions),
            approvals=tuple(approvals),
            artifacts=tuple(artifacts),
            metrics=tuple(metrics),
            final_task=report_final_task,
            metadata=dict(metadata or {}),
        )

    def to_dict(self, *, redaction_policy: RedactionPolicy | None = None) -> dict[str, Any]:
        """Serialize the report into a JSON-compatible dictionary.

        Args:
            redaction_policy: Optional policy used to mask secrets before the dictionary is returned.
        """
        data = {
            "context": self.context.to_dict() if self.context else None,
            "context_manifests": list(self.context_manifests),
            "events": [event.to_dict() for event in self.events],
            "actions": list(self.actions),
            "approvals": list(self.approvals),
            "artifacts": list(self.artifacts),
            "metrics": list(self.metrics),
            "final_task": self.final_task,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
        if redaction_policy is not None:
            return redaction_policy.redact(data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunReport:
        """Create a report from serialized data."""
        context_data = data.get("context")
        return cls(
            context=RunContext.from_dict(context_data) if isinstance(context_data, dict) else None,
            context_manifests=tuple(_dict_items(data.get("context_manifests"))),
            events=tuple(RunEvent.from_dict(item) for item in _dict_items(data.get("events"))),
            actions=tuple(_dict_items(data.get("actions"))),
            approvals=tuple(_dict_items(data.get("approvals"))),
            artifacts=tuple(_dict_items(data.get("artifacts"))),
            metrics=tuple(_dict_items(data.get("metrics"))),
            final_task=dict(data["final_task"]) if isinstance(data.get("final_task"), dict) else None,
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or utc_now()),
        )

    def redacted(self, policy: RedactionPolicy | None = None) -> RunReport:
        """Return a copy with secrets masked by ``policy``."""
        redaction_policy = policy or RedactionPolicy()
        return RunReport.from_dict(self.to_dict(redaction_policy=redaction_policy))


class RunRecorder:
    """In-memory recorder for building ``RunReport`` objects from run events.

    ``RunRecorder`` intentionally mirrors ``InMemoryEventSink`` while adding the report-building API. It is suitable for
    tests, command-line apps, and local traces that need a durable summary after streaming has finished.
    """

    def __init__(self, *, context: RunContext | dict[str, Any] | None = None) -> None:
        """Initialize an empty recorder."""
        self._sink = InMemoryEventSink()
        self.context = _coerce_context(context)

    @property
    def events(self) -> tuple[RunEvent, ...]:
        """Return recorded events as an immutable tuple."""
        return self._sink.events

    async def emit(self, event: RunEvent) -> None:
        """Record one normalized run event."""
        await self._sink.emit(event)

    async def emit_task_event(
        self,
        event: Any,
        *,
        context: RunContext | dict[str, Any] | None = None,
    ) -> RunEvent:
        """Normalize and record one legacy task-stream event."""
        event_context = _coerce_context(context) or self.context
        return await self._sink.emit_task_event(event, context=event_context)

    async def record_event(self, event: RunEvent) -> RunEvent:
        """Record and return one normalized run event."""
        await self.emit(event)
        return event

    async def record_task_event(
        self,
        event: Any,
        *,
        context: RunContext | dict[str, Any] | None = None,
    ) -> RunEvent:
        """Normalize, record, and return one task-stream event."""
        return await self.emit_task_event(event, context=context)

    def to_report(
        self,
        *,
        context: RunContext | dict[str, Any] | None = None,
        final_task: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        redaction_policy: RedactionPolicy | None = None,
    ) -> RunReport:
        """Build a durable report from recorded events."""
        report = RunReport.from_events(
            self.events,
            context=_coerce_context(context) or self.context,
            final_task=final_task,
            metadata=metadata,
        )
        if redaction_policy is not None:
            return report.redacted(redaction_policy)
        return report

    def clear(self) -> None:
        """Clear recorded events and reset sequence numbering."""
        self._sink.clear()


class RunReplay:
    """Read-only replay view over a ``RunReport``.

    Replay helpers do not execute tools or model calls. They provide a stable way to iterate over recorded events,
    filter by event type, and run the same assertion helpers used by golden tests.
    """

    def __init__(self, report: RunReport | dict[str, Any] | Iterable[RunEvent | dict[str, Any]]) -> None:
        """Create a replay view from a report, report dictionary, or events."""
        if isinstance(report, RunReport):
            self.report = report
        elif isinstance(report, dict):
            self.report = RunReport.from_dict({str(key): value for key, value in report.items()})
        else:
            self.report = RunReport.from_events(report)

    @property
    def events(self) -> tuple[RunEvent, ...]:
        """Return replay events in recorded order."""
        return self.report.events

    @property
    def event_types(self) -> tuple[str, ...]:
        """Return replay event types in recorded order."""
        return tuple(event.type for event in self.events)

    def iter_events(self, event_type: str | None = None) -> Iterable[RunEvent]:
        """Iterate over all events or only events matching ``event_type``."""
        for event in self.events:
            if event_type is None or event.type == event_type:
                yield event

    def find_events(self, event_type: str) -> tuple[RunEvent, ...]:
        """Return all events matching ``event_type``."""
        return tuple(self.iter_events(event_type))

    def assert_events(
        self,
        expected_types: Sequence[str],
        *,
        ordered: bool = True,
        allow_extra: bool = True,
    ) -> None:
        """Assert that replay events contain ``expected_types``."""
        assert_run_events(self, expected_types, ordered=ordered, allow_extra=allow_extra)


def assert_run_events(
    source: RunReport | RunReplay | Iterable[RunEvent | dict[str, Any]],
    expected_types: Sequence[str],
    *,
    ordered: bool = True,
    allow_extra: bool = True,
) -> None:
    """Assert that a report, replay, or event stream contains event types.

    By default, ``expected_types`` must appear in order as a subsequence, which keeps golden tests resilient to additive
    events. Set ``allow_extra=False`` for exact ordered matching.
    """
    observed = tuple(event.type for event in _events_from_source(source))
    expected = tuple(expected_types)

    if ordered and allow_extra:
        expected_index = 0
        for event_type in observed:
            if expected_index < len(expected) and event_type == expected[expected_index]:
                expected_index += 1
        if expected_index != len(expected):
            missing = expected[expected_index:]
            raise AssertionError(
                f"Expected event sequence {expected!r}; missing ordered events {missing!r}; observed {observed!r}"
            )
        return

    if ordered and not allow_extra:
        if observed != expected:
            raise AssertionError(f"Expected exact event sequence {expected!r}; observed {observed!r}")
        return

    if allow_extra:
        missing = tuple(event_type for event_type in expected if event_type not in observed)
        if missing:
            raise AssertionError(f"Expected event types {expected!r}; missing {missing!r}; observed {observed!r}")
        return

    if Counter(observed) != Counter(expected):
        raise AssertionError(f"Expected event multiset {Counter(expected)!r}; observed {Counter(observed)!r}")


def assert_no_denied_actions(source: RunReport | RunReplay | Iterable[RunEvent | dict[str, Any]]) -> None:
    """Assert that no action policy, approval, or runtime event denied work."""
    denied: list[str] = []
    for event in _events_from_source(source):
        decision = _decision_from_event(event)
        if event.type == "action.denied":
            denied.append(_event_label(event))
        elif event.type == "action.policy" and decision.get("effect") == "deny":
            denied.append(_event_label(event))
        elif event.type == "approval.decided" and decision.get("approved") is False:
            denied.append(_event_label(event))

    if denied:
        raise AssertionError(f"Denied action events found: {denied!r}")


def assert_budget_under(
    source: RunReport | RunReplay | Iterable[RunEvent | dict[str, Any]],
    *,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_total_tokens: int | None = None,
    max_runtime_seconds: float | None = None,
) -> dict[str, int | float]:
    """Assert aggregate usage stays under supplied limits.

    Returns:
        A usage summary with ``input_tokens``, ``output_tokens``, ``total_tokens``, and ``runtime_seconds`` for
        additional test assertions or reporting.
    """
    report = _report_from_source(source)
    usage = _aggregate_budget_usage(report)
    checks: tuple[tuple[str, int | float, int | float | None], ...] = (
        ("input_tokens", usage["input_tokens"], max_input_tokens),
        ("output_tokens", usage["output_tokens"], max_output_tokens),
        ("total_tokens", usage["total_tokens"], max_total_tokens),
        ("runtime_seconds", usage["runtime_seconds"], max_runtime_seconds),
    )
    exceeded = [(name, observed, limit) for name, observed, limit in checks if limit is not None and observed > limit]
    if exceeded:
        raise AssertionError(f"Budget assertion exceeded: {exceeded!r}")
    return usage


def _coerce_context(context: RunContext | dict[str, Any] | None) -> RunContext | None:
    if context is None:
        return None
    if isinstance(context, RunContext):
        return context
    return RunContext.from_dict(context)


def _coerce_event(event: RunEvent | dict[str, Any]) -> RunEvent:
    if isinstance(event, RunEvent):
        return event
    return RunEvent.from_dict(event)


def _events_from_source(source: RunReport | RunReplay | Iterable[RunEvent | dict[str, Any]]) -> tuple[RunEvent, ...]:
    if isinstance(source, RunReplay):
        return source.events
    if isinstance(source, RunReport):
        return source.events
    return tuple(_coerce_event(event) for event in source)


def _report_from_source(source: RunReport | RunReplay | Iterable[RunEvent | dict[str, Any]]) -> RunReport:
    if isinstance(source, RunReplay):
        return source.report
    if isinstance(source, RunReport):
        return source
    return RunReport.from_events(source)


def _dict_items(value: Any) -> tuple[dict[str, Any], ...]:
    if not value:
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _metadata(event: RunEvent) -> dict[str, Any]:
    metadata = event.payload.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return {}


def _manifest_from_event(event: RunEvent) -> dict[str, Any] | None:
    manifest = event.payload.get("manifest")
    if isinstance(manifest, dict):
        return dict(manifest)
    manifest = _metadata(event).get("manifest")
    if isinstance(manifest, dict):
        return dict(manifest)
    return None


def _action_from_event(event: RunEvent) -> dict[str, Any] | None:
    action = event.payload.get("action")
    if isinstance(action, dict):
        return dict(action)
    request = event.payload.get("request")
    if isinstance(request, dict) and isinstance(request.get("action"), dict):
        return dict(request["action"])
    return None


def _approval_from_event(event: RunEvent) -> dict[str, Any] | None:
    if not event.type.startswith("approval."):
        return None
    payload = {"type": event.type}
    for key in ("request", "decision"):
        value = event.payload.get(key)
        if isinstance(value, dict):
            payload[key] = dict(value)
    return payload


def _artifact_from_event(event: RunEvent) -> dict[str, Any] | None:
    if event.type != "task.artifact":
        return None
    artifact = event.payload.get("artifact")
    if isinstance(artifact, dict):
        return dict(artifact)
    return None


def _metrics_from_event(event: RunEvent) -> dict[str, Any] | None:
    metadata = _metadata(event)
    if event.payload.get("llm_event_type") == "llm_call_metrics":
        return dict(metadata)
    if event.type == "llm.call.completed":
        metric = {key: value for key, value in metadata.items() if key not in {"manifest"}}
        for key in ("provider", "model", "latency_ms", "streaming", "native", "metrics", "budget"):
            if key in event.payload:
                metric[key] = event.payload[key]
        return metric
    return None


def _final_task_from_events(events: tuple[RunEvent, ...]) -> dict[str, Any] | None:
    for event in reversed(events):
        if not event.final:
            continue
        metadata = _metadata(event)
        task = metadata.get("task")
        if isinstance(task, dict):
            return dict(task)
    return None


def _decision_from_event(event: RunEvent) -> dict[str, Any]:
    decision = event.payload.get("decision")
    if isinstance(decision, dict):
        return decision
    return {}


def _event_label(event: RunEvent) -> str:
    return f"{event.type}:{event.action_id or event.event_id}"


def _aggregate_budget_usage(report: RunReport) -> dict[str, int | float]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    runtime_seconds = 0.0

    for metric in report.metrics:
        usage = metric.get("usage")
        if not isinstance(usage, dict) and isinstance(metric.get("metrics"), dict):
            usage = metric["metrics"].get("usage")
        if isinstance(usage, dict):
            input_tokens += _int_value(usage.get("input_tokens") or usage.get("prompt_tokens"))
            output_tokens += _int_value(usage.get("output_tokens") or usage.get("completion_tokens"))
            total_tokens += _int_value(usage.get("total_tokens"))
        latency_ms = _float_value(metric.get("latency_ms"))
        if latency_ms:
            runtime_seconds += latency_ms / 1000

    if input_tokens == 0:
        input_tokens = sum(_int_value(manifest.get("total_estimated_tokens")) for manifest in report.context_manifests)
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "runtime_seconds": round(runtime_seconds, 6),
    }


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
