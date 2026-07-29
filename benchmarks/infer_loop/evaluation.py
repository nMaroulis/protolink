"""Attempt execution, trace parsing, and validation for the infer-loop benchmark."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from protolink import Task, TaskState
from protolink.telemetry import LocalTraceRecorder, TraceRecord

from .mesh import BenchmarkMesh
from .models import (
    SUITE_VERSION,
    AttemptResult,
    BenchmarkCase,
    ExpectedAction,
    LedgerEntry,
    LLMCallResult,
)


def _event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _numeric(value)
    return int(number) if number is not None else None


def _find_nested_number(value: Any, keys: tuple[str, ...]) -> float | None:
    """Find the first named numeric field in nested provider metadata."""
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                number = _numeric(value[key])
                if number is not None:
                    return number
        for nested in value.values():
            number = _find_nested_number(nested, keys)
            if number is not None:
                return number
    elif isinstance(value, list):
        for nested in value:
            number = _find_nested_number(nested, keys)
            if number is not None:
                return number
    return None


def _ollama_duration_ms(details: Any, key: str, *, provider: str) -> float | None:
    """Convert an Ollama nanosecond duration to milliseconds."""
    if provider.casefold() != "ollama":
        return None
    duration_ns = _find_nested_number(details, (key,))
    return round(duration_ns / 1_000_000, 3) if duration_ns is not None else None


def _llm_call_result(payload: dict[str, Any], call_index: int) -> LLMCallResult:
    raw_metrics = payload.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
    raw_usage = metrics.get("usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    details = usage.get("details")
    provider = str(payload.get("provider") or metrics.get("provider") or "")

    input_tokens = _integer(usage.get("input_tokens"))
    output_tokens = _integer(usage.get("output_tokens"))
    total_tokens = _integer(usage.get("total_tokens"))
    provider_prompt_tokens = _integer(_find_nested_number(details, ("prompt_eval_count", "prompt_token_count")))
    provider_output_tokens = _integer(_find_nested_number(details, ("eval_count", "completion_token_count")))
    cached_input_tokens = _integer(
        _find_nested_number(
            details,
            (
                "cached_tokens",
                "cache_read_input_tokens",
                "cached_content_token_count",
                "cache_read_tokens",
            ),
        )
    )
    cache_write_input_tokens = _integer(
        _find_nested_number(
            details,
            (
                "cache_creation_input_tokens",
                "cache_write_input_tokens",
                "cache_creation_tokens",
            ),
        )
    )
    provider_total_ms = _ollama_duration_ms(details, "total_duration", provider=provider)
    provider_load_ms = _ollama_duration_ms(details, "load_duration", provider=provider)
    provider_prompt_eval_ms = _ollama_duration_ms(details, "prompt_eval_duration", provider=provider)
    provider_generation_ms = _ollama_duration_ms(details, "eval_duration", provider=provider)

    prompt_rate = None
    if provider_prompt_tokens is not None and provider_prompt_eval_ms and provider_prompt_eval_ms > 0:
        prompt_rate = round(provider_prompt_tokens / (provider_prompt_eval_ms / 1000), 3)
    output_rate = None
    if provider_output_tokens is not None and provider_generation_ms and provider_generation_ms > 0:
        output_rate = round(provider_output_tokens / (provider_generation_ms / 1000), 3)

    return LLMCallResult(
        call_index=call_index,
        step=_integer(payload.get("step")) or call_index,
        physical_attempts=max(_integer(payload.get("attempts")) or 1, 1),
        latency_ms=round(_numeric(payload.get("latency_ms")) or 0.0, 3),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        usage_estimated=bool(usage.get("estimated")) if usage else None,
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
        provider_total_ms=provider_total_ms,
        provider_load_ms=provider_load_ms,
        provider_prompt_eval_ms=provider_prompt_eval_ms,
        provider_generation_ms=provider_generation_ms,
        provider_prompt_tokens=provider_prompt_tokens,
        provider_output_tokens=provider_output_tokens,
        prompt_tokens_per_second=prompt_rate,
        output_tokens_per_second=output_rate,
    )


def _trace_metrics(trace: TraceRecord | None) -> tuple[dict[str, Any], list[LLMCallResult]]:
    metrics: dict[str, Any] = {
        "llm_steps": 0,
        "llm_calls": 0,
        "provider_attempts": 0,
        "completed_provider_attempts": 0,
        "llm_latency_ms": 0.0,
        "first_llm_latency_ms": 0.0,
        "mean_llm_call_latency_ms": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "usage_estimated_calls": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "provider_total_ms": 0.0,
        "provider_load_ms": 0.0,
        "provider_prompt_eval_ms": 0.0,
        "provider_generation_ms": 0.0,
        "prompt_tokens_per_second": None,
        "output_tokens_per_second": None,
        "provider_timing_calls": 0,
        "parse_errors": 0,
        "provider_retries": 0,
        "duplicate_retries": 0,
        "invalid_tool_attempts": 0,
        "invalid_agent_attempts": 0,
    }
    if trace is None:
        return metrics, []
    completed_calls: list[dict[str, Any]] = []
    for event in trace.events:
        payload = _event_payload(event)
        if event.type == "llm_step":
            metrics["llm_steps"] += 1
        elif event.type == "llm_call_completed":
            completed_calls.append(payload)
        elif event.type == "llm_call_started":
            metrics["provider_attempts"] += 1
        elif event.type == "llm_parse_error":
            metrics["parse_errors"] += 1
        elif event.type == "llm_retry":
            reason = payload.get("reason")
            if reason == "transient_error":
                metrics["provider_retries"] += 1
            elif reason == "duplicate_action":
                metrics["duplicate_retries"] += 1
        elif event.type == "tool_error" and payload.get("phase") == "validation":
            metrics["invalid_tool_attempts"] += 1
        elif event.type == "agent_call_error" and payload.get("recoverable", False):
            metrics["invalid_agent_attempts"] += 1

    calls = [_llm_call_result(payload, index) for index, payload in enumerate(completed_calls, start=1)]
    metrics["llm_calls"] = len(calls)
    metrics["completed_provider_attempts"] = sum(call.physical_attempts for call in calls)
    call_latencies = [call.latency_ms for call in calls]
    metrics["llm_latency_ms"] = round(sum(call_latencies), 3)
    metrics["first_llm_latency_ms"] = call_latencies[0] if call_latencies else 0.0
    metrics["mean_llm_call_latency_ms"] = round(sum(call_latencies) / len(call_latencies), 3) if call_latencies else 0.0
    for name in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
    ):
        metrics[name] = sum(int(getattr(call, name) or 0) for call in calls)
    metrics["usage_estimated_calls"] = sum(call.usage_estimated is True for call in calls)
    for name in (
        "provider_total_ms",
        "provider_load_ms",
        "provider_prompt_eval_ms",
        "provider_generation_ms",
    ):
        metrics[name] = round(sum(float(getattr(call, name) or 0.0) for call in calls), 3)
    metrics["provider_timing_calls"] = sum(
        any(
            value is not None
            for value in (
                call.provider_total_ms,
                call.provider_load_ms,
                call.provider_prompt_eval_ms,
                call.provider_generation_ms,
            )
        )
        for call in calls
    )
    prompt_tokens = sum(int(call.provider_prompt_tokens or 0) for call in calls)
    prompt_ms = float(metrics["provider_prompt_eval_ms"])
    if prompt_tokens and prompt_ms > 0:
        metrics["prompt_tokens_per_second"] = round(prompt_tokens / (prompt_ms / 1000), 3)
    output_tokens = sum(int(call.provider_output_tokens or 0) for call in calls)
    generation_ms = float(metrics["provider_generation_ms"])
    if output_tokens and generation_ms > 0:
        metrics["output_tokens_per_second"] = round(output_tokens / (generation_ms / 1000), 3)
    return metrics, calls


def _successful_trace_actions(trace: TraceRecord | None) -> list[dict[str, Any]]:
    if trace is None:
        return []
    starts: dict[str, dict[str, Any]] = {}
    successful: list[dict[str, Any]] = []
    for event in trace.events:
        payload = _event_payload(event)
        action_id = str(payload.get("action_id") or "")
        if event.type == "tool_start":
            starts[action_id] = {
                "kind": "local_tool",
                "agent": "benchmark_coordinator",
                "tool": payload.get("tool"),
                "args": payload.get("args") or {},
                "prompt": None,
            }
        elif event.type == "agent_call_start":
            raw_model_payload = payload.get("payload")
            model_payload: dict[str, Any] = raw_model_payload if isinstance(raw_model_payload, dict) else {}
            delegated_action = payload.get("action")
            starts[action_id] = {
                "kind": "agent_infer" if delegated_action == "infer" else "agent_tool",
                "agent": payload.get("agent"),
                "tool": model_payload.get("tool"),
                "args": model_payload.get("args") or {},
                "prompt": model_payload.get("prompt"),
            }
        elif event.type in {"tool_result", "agent_call_result"}:
            action = starts.get(action_id)
            if action is not None:
                successful.append(action)
    return successful


def _model_actions(trace: TraceRecord | None) -> list[dict[str, Any]]:
    """Return every normalized model decision, including actions that later failed."""
    if trace is None:
        return []
    decisions: list[dict[str, Any]] = []
    for event in trace.events:
        payload = _event_payload(event)
        if event.type == "llm_action":
            decisions.append(
                {
                    "step": _integer(payload.get("step")),
                    "type": "action",
                    "action": payload.get("action"),
                    "payload": payload.get("payload"),
                }
            )
        elif event.type == "llm_parse_error":
            decisions.append(
                {
                    "step": _integer(payload.get("step")),
                    "type": "parse_error",
                    "message": payload.get("message"),
                    "recoverable": bool(payload.get("recoverable")),
                }
            )
    return decisions


def _action_matches(expected: ExpectedAction, observed: dict[str, Any]) -> bool:
    if expected.kind != observed.get("kind") or expected.agent != observed.get("agent"):
        return False
    if expected.tool != observed.get("tool"):
        return False
    if expected.args is not None and expected.args != observed.get("args"):
        return False
    prompt = str(observed.get("prompt") or "")
    return all(fragment in prompt for fragment in expected.prompt_contains)


def _action_list_matches(
    expected: tuple[ExpectedAction, ...],
    observed: list[dict[str, Any]],
    *,
    ordered: bool,
) -> bool:
    if len(expected) != len(observed):
        return False
    if ordered:
        return all(_action_matches(wanted, actual) for wanted, actual in zip(expected, observed, strict=True))

    remaining = list(observed)
    for wanted in expected:
        for index, actual in enumerate(remaining):
            if _action_matches(wanted, actual):
                remaining.pop(index)
                break
        else:
            return False
    return not remaining


def _find_infer_output(task: Task | None) -> str:
    if task is None:
        return ""
    candidates: list[tuple[str, Any]] = []
    for item in (*task.messages, *task.artifacts):
        for part in item.parts:
            if part.type == "infer_output":
                candidates.append((item.timestamp, part.content))
    if not candidates:
        return ""
    return str(max(candidates, key=lambda value: value[0])[1]).strip()


def _task_state(task: Task | None) -> str:
    if task is None:
        return "exception"
    return task.state.value if isinstance(task.state, TaskState) else str(task.state)


def _find_trace(
    recorder: LocalTraceRecorder,
    *,
    task_id: str,
    cursor: int,
) -> TraceRecord | None:
    for trace in reversed(recorder.traces[cursor:]):
        if trace.task_id == task_id and trace.agent_name == "benchmark_coordinator":
            return trace
    return None


def _validate_attempt(
    *,
    case: BenchmarkCase,
    repetition: int,
    attempt: int,
    task: Task | None,
    trace: TraceRecord | None,
    ledger_entries: list[LedgerEntry],
    latency_ms: float,
    error: Exception | None,
    timed_out: bool,
) -> AttemptResult:
    state = _task_state(task)
    final_output = _find_infer_output(task)
    output_match = final_output == case.expected_final and not any(
        forbidden in final_output for forbidden in case.forbidden_final
    )
    observed_actions = [entry.action_dict() for entry in ledger_entries]
    trace_actions = _successful_trace_actions(trace)
    model_actions = _model_actions(trace)
    ledger_match = _action_list_matches(case.expected_actions, observed_actions, ordered=case.ordered_actions)
    trace_match = _action_list_matches(case.expected_actions, trace_actions, ordered=case.ordered_actions)
    metrics, call_timings = _trace_metrics(trace)
    timing_complete = bool(
        trace is not None
        and error is None
        and not timed_out
        and metrics["provider_attempts"] == metrics["completed_provider_attempts"]
    )
    metrics["timing_complete"] = timing_complete
    metrics["non_llm_latency_ms"] = (
        round(max(latency_ms - float(metrics["llm_latency_ms"]), 0.0), 3) if timing_complete else None
    )
    protocol_clean = not any(
        (
            metrics["parse_errors"],
            metrics["duplicate_retries"],
            metrics["invalid_tool_attempts"],
            metrics["invalid_agent_attempts"],
        )
    )

    failure_codes: list[str] = []
    if state != TaskState.COMPLETED.value:
        failure_codes.append("task_not_completed")
    if not final_output:
        failure_codes.append("missing_final_output")
    elif not output_match:
        failure_codes.append("final_output_mismatch")
    if not ledger_match:
        failure_codes.append("execution_ledger_mismatch")
    if not trace_match:
        failure_codes.append("trace_action_mismatch")
    if metrics["parse_errors"]:
        failure_codes.append("parse_recovery")
    if metrics["duplicate_retries"]:
        failure_codes.append("duplicate_action")
    if metrics["invalid_tool_attempts"]:
        failure_codes.append("invalid_tool_action")
    if metrics["invalid_agent_attempts"]:
        failure_codes.append("invalid_agent_action")
    if timed_out:
        failure_codes.append("timeout")
    if error is not None:
        failure_codes.append("exception")
    failure_codes = list(dict.fromkeys(failure_codes))

    functional_pass = (
        state == TaskState.COMPLETED.value
        and bool(final_output)
        and output_match
        and ledger_match
        and trace_match
        and error is None
        and not timed_out
    )
    strict_pass = functional_pass and protocol_clean
    unexpected_action = not ledger_match or not trace_match
    hallucinated_action = bool(
        unexpected_action
        or metrics["invalid_tool_attempts"]
        or metrics["invalid_agent_attempts"]
        or (case.category == "grounding_trap" and not output_match)
    )
    action_receipts = (
        sum(1 for artifact in task.artifacts if artifact.kind == "action_result") if task is not None else 0
    )
    crashed = bool(error is not None or state in {TaskState.FAILED.value, TaskState.CANCELED.value, "exception"})
    return AttemptResult(
        case_id=case.id,
        category=case.category,
        repetition=repetition,
        attempt=attempt,
        task_id=task.id if task is not None else "",
        strict_pass=strict_pass,
        functional_pass=functional_pass,
        protocol_clean=protocol_clean,
        output_match=output_match,
        ledger_match=ledger_match,
        trace_match=trace_match,
        task_state=state,
        final_output=final_output,
        failure_codes=failure_codes,
        error_type=type(error).__name__ if error is not None else None,
        error_message=str(error) if error is not None else None,
        latency_ms=round(latency_ms, 3),
        action_receipts=action_receipts,
        hallucinated_action=hallucinated_action,
        timed_out=timed_out,
        crashed=crashed,
        expected_actions=[action.to_dict() for action in case.expected_actions],
        observed_actions=observed_actions,
        trace_actions=trace_actions,
        model_actions=model_actions,
        llm_call_timings=[call.to_dict() for call in call_timings],
        **metrics,
    )


async def run_attempt(
    *,
    mesh: BenchmarkMesh,
    recorder: LocalTraceRecorder,
    case: BenchmarkCase,
    repetition: int,
    attempt: int,
    timeout: float,
) -> AttemptResult:
    """Run and validate one fresh task."""
    task = Task.create_infer(prompt=case.prompt)
    task.metadata.update(
        {
            "benchmark": SUITE_VERSION,
            "benchmark_case_id": case.id,
            "benchmark_repetition": repetition,
            "benchmark_attempt": attempt,
        }
    )
    ledger_cursor = mesh.ledger.mark()
    trace_cursor = len(recorder.traces)
    started = time.perf_counter()
    result_task: Task | None = None
    error: Exception | None = None
    timed_out = False
    try:
        result_task = await asyncio.wait_for(
            mesh.client.send_task(mesh.coordinator.card.url, task),
            timeout=timeout,
        )
    except TimeoutError as exc:
        error = exc
        timed_out = True
    except Exception as exc:
        error = exc
    latency_ms = (time.perf_counter() - started) * 1000
    trace = _find_trace(recorder, task_id=task.id, cursor=trace_cursor)
    return _validate_attempt(
        case=case,
        repetition=repetition,
        attempt=attempt,
        task=result_task or task,
        trace=trace,
        ledger_entries=mesh.ledger.since(ledger_cursor),
        latency_ms=latency_ms,
        error=error,
        timed_out=timed_out,
    )
