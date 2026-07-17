"""Normalized run-report regression comparison tests."""

from __future__ import annotations

import copy

import pytest

from protolink import (
    Agent,
    AgentCard,
    RedactionPolicy,
    RunContext,
    RunRecorder,
    RunReplay,
    RunReport,
    RunReportDiffConfig,
    RunReportTolerance,
    Task,
    assert_run_matches,
    create_llm,
    diff_run_reports,
    normalize_run_report,
)


def test_fresh_runtime_identifiers_and_timestamps_normalize_without_hiding_business_values() -> None:
    baseline = _report_payload(
        run_id="run_baseline",
        task_id="task_baseline",
        event_id="event_baseline",
        message_id="message_baseline",
        timestamp="2026-07-17T08:00:00Z",
        business_id="order-42",
        business_timestamp="2030-01-01T00:00:00Z",
    )
    candidate = _report_payload(
        run_id="run_candidate",
        task_id="task_candidate",
        event_id="event_candidate",
        message_id="message_candidate",
        timestamp="2026-07-17T09:00:00Z",
        business_id="order-42",
        business_timestamp="2030-01-01T00:00:00Z",
    )

    comparison = diff_run_reports(baseline, candidate)

    assert comparison.matches
    assert comparison.differences == ()

    candidate["events"][0]["payload"]["result"]["id"] = "order-99"
    business_id_diff = diff_run_reports(baseline, candidate)
    assert not business_id_diff.matches
    assert any(difference.path == "/events/0/payload/result/id" for difference in business_id_diff.differences)

    candidate["events"][0]["payload"]["result"]["id"] = "order-42"
    candidate["events"][0]["payload"]["result"]["timestamp"] = "2031-01-01T00:00:00Z"
    business_time_diff = diff_run_reports(baseline, candidate)
    assert any(difference.path == "/events/0/payload/result/timestamp" for difference in business_time_diff.differences)


def test_identifier_canonicalization_preserves_runtime_relationships() -> None:
    baseline = _report_payload(run_id="run_a", task_id="task_a", event_id="event_a")
    candidate = _report_payload(run_id="run_b", task_id="task_b", event_id="event_b")

    assert diff_run_reports(baseline, candidate).matches

    candidate["events"][0]["run_id"] = "different_candidate_run"
    result = diff_run_reports(baseline, candidate)

    assert not result.matches
    assert any(difference.path == "/events/0/run_id" for difference in result.differences)


def test_action_and_span_correlation_relationship_changes_are_detected() -> None:
    baseline = RunReport.from_dict(
        {
            "events": [
                {
                    "type": "action.completed",
                    "action_id": "shared-correlation",
                    "span_id": "shared-correlation",
                }
            ]
        }
    )
    candidate = RunReport.from_dict(
        {
            "events": [
                {
                    "type": "action.completed",
                    "action_id": "candidate-action",
                    "span_id": "candidate-span",
                }
            ]
        }
    )

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert not result.matches
    assert any(difference.path in {"/events/0/action_id", "/events/0/span_id"} for difference in result.differences)


def test_task_and_final_task_identifier_relationship_changes_are_detected() -> None:
    baseline = {
        "events": [{"type": "task.status", "task_id": "baseline-task"}],
        "final_task": {"id": "baseline-task"},
    }
    candidate = {
        "events": [{"type": "task.status", "task_id": "wrong-event-task"}],
        "final_task": {"id": "candidate-task"},
    }

    result = diff_run_reports(baseline, candidate)

    assert not result.matches
    assert {difference.path for difference in result.differences} == {
        "/events/0/task_id",
        "/final_task/id",
    }


def test_approval_request_and_decision_identifier_relationship_changes_are_detected() -> None:
    baseline = {
        "approvals": [
            {
                "type": "approval.decided",
                "request": {"request_id": "baseline-request"},
                "decision": {"request_id": "baseline-request"},
            }
        ]
    }
    candidate = {
        "approvals": [
            {
                "type": "approval.decided",
                "request": {"request_id": "candidate-request"},
                "decision": {"request_id": "wrong-decision-request"},
            }
        ]
    }

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("approvals",)),
    )

    assert not result.matches
    assert {difference.path for difference in result.differences} == {
        "/approvals/0/decision/request_id",
        "/approvals/0/request/request_id",
    }


def test_action_span_and_delegation_share_one_correlation_namespace() -> None:
    baseline = {
        "events": [
            {
                "type": "action.completed",
                "action_id": "baseline-correlation",
                "span_id": "baseline-correlation",
                "delegation_id": "baseline-correlation",
            }
        ]
    }
    candidate = {
        "events": [
            {
                "type": "action.completed",
                "action_id": "candidate-correlation",
                "span_id": "candidate-correlation",
                "delegation_id": "wrong-delegation",
            }
        ]
    }

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert [difference.path for difference in result.differences] == ["/events/0/delegation_id"]


def test_session_artifact_and_message_relationship_changes_are_detected() -> None:
    baseline = {
        "context": {"run_id": "run-a", "session_id": "session-a"},
        "context_manifests": [{"session_id": "session-a"}],
        "events": [
            {
                "type": "task.status",
                "metadata": {"source_type": "task_status_update"},
                "payload": {
                    "metadata": {
                        "task": {
                            "messages": [{"id": "message-a"}],
                        }
                    }
                },
            }
        ],
        "artifacts": [{"id": "artifact-a"}],
        "final_task": {
            "messages": [{"id": "message-a"}],
            "artifacts": [{"id": "artifact-a"}],
        },
    }
    candidate = copy.deepcopy(baseline)
    candidate["context"]["session_id"] = "session-b"
    candidate["context_manifests"][0]["session_id"] = "wrong-manifest-session"
    candidate["events"][0]["payload"]["metadata"]["task"]["messages"][0]["id"] = "wrong-event-message"
    candidate["artifacts"][0]["id"] = "artifact-b"
    candidate["final_task"]["messages"][0]["id"] = "message-b"
    candidate["final_task"]["artifacts"][0]["id"] = "wrong-final-artifact"

    result = diff_run_reports(baseline, candidate)

    assert not result.matches
    changed_paths = {difference.path for difference in result.differences}
    assert "/context/session_id" in changed_paths
    assert "/context_manifests/0/session_id" in changed_paths
    assert "/events/0/payload/metadata/task/messages/0/id" in changed_paths
    assert "/artifacts/0/id" in changed_paths
    assert "/final_task/messages/0/id" in changed_paths
    assert "/final_task/artifacts/0/id" in changed_paths


@pytest.mark.asyncio
async def test_separately_recorded_equivalent_mock_agent_runs_match() -> None:
    baseline = await _record_mock_run("run_baseline")
    candidate = await _record_mock_run("run_candidate")

    result = diff_run_reports(baseline, candidate)

    assert result.matches, result.format(max_differences=100, redaction_policy=None)


def test_custom_event_payload_identifiers_and_timestamps_remain_behavioral() -> None:
    baseline = RunReport.from_dict(
        {
            "events": [
                {
                    "type": "application.checkpoint",
                    "payload": {
                        "task_id": "business-task-a",
                        "timestamp": "2030-01-01T00:00:00Z",
                    },
                }
            ]
        }
    )
    candidate = RunReport.from_dict(
        {
            "events": [
                {
                    "type": "application.checkpoint",
                    "payload": {
                        "task_id": "business-task-b",
                        "timestamp": "2031-01-01T00:00:00Z",
                    },
                }
            ]
        }
    )

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert {difference.path for difference in result.differences} == {
        "/events/0/payload/task_id",
        "/events/0/payload/timestamp",
    }


def test_nested_custom_event_payload_runtime_shaped_values_remain_behavioral() -> None:
    baseline = {
        "events": [
            {
                "type": "application.audit",
                "payload": {
                    "request": {"run_id": "order-a"},
                    "action": {"created_at": "2030-01-01T00:00:00Z"},
                    "artifact": {"id": "invoice-a"},
                },
            }
        ]
    }
    candidate = copy.deepcopy(baseline)
    candidate["events"][0]["payload"]["request"]["run_id"] = "order-b"
    candidate["events"][0]["payload"]["action"]["created_at"] = "2031-01-01T00:00:00Z"
    candidate["events"][0]["payload"]["artifact"]["id"] = "invoice-b"

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert {difference.path for difference in result.differences} == {
        "/events/0/payload/action/created_at",
        "/events/0/payload/artifact/id",
        "/events/0/payload/request/run_id",
    }


def test_inserted_event_is_aligned_without_cascading_later_events() -> None:
    baseline = RunReport.from_dict(
        {
            "events": [
                {"type": "llm.call.started", "payload": {"model": "mock"}},
                {"type": "llm.call.completed", "payload": {"model": "mock", "result": "done"}},
            ]
        }
    )
    candidate = RunReport.from_dict(
        {
            "events": [
                {"type": "llm.call.started", "payload": {"model": "mock"}},
                {"type": "task.progress", "payload": {"percent": 50}},
                {"type": "llm.call.completed", "payload": {"model": "mock", "result": "done"}},
            ]
        }
    )

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert len(result.differences) == 1
    assert result.differences[0].kind == "added"
    assert result.differences[0].path == "/events/1"


def test_inserted_repeated_event_and_new_task_id_do_not_shift_later_items() -> None:
    baseline = RunReport.from_dict(
        {
            "events": [
                {
                    "type": "task.status",
                    "task_id": "task-a",
                    "payload": {"state": "working"},
                },
                {
                    "type": "task.status",
                    "task_id": "task-a",
                    "payload": {"state": "completed"},
                },
            ]
        }
    )
    candidate = RunReport.from_dict(
        {
            "events": [
                {
                    "type": "task.status",
                    "task_id": "inserted-task",
                    "payload": {"state": "submitted"},
                },
                {
                    "type": "task.status",
                    "task_id": "candidate-task",
                    "payload": {"state": "working"},
                },
                {
                    "type": "task.status",
                    "task_id": "candidate-task",
                    "payload": {"state": "completed"},
                },
            ]
        }
    )

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert len(result.differences) == 1
    assert result.differences[0].kind == "added"
    assert result.differences[0].path == "/events/0"


def test_changed_event_payload_has_a_precise_json_pointer_path() -> None:
    baseline = RunReport.from_dict({"events": [{"type": "llm.call.completed", "payload": {"model": "mock-v1"}}]})
    candidate = RunReport.from_dict({"events": [{"type": "llm.call.completed", "payload": {"model": "mock-v2"}}]})

    result = diff_run_reports(
        baseline,
        candidate,
        config=RunReportDiffConfig(sections=("events",)),
    )

    assert [difference.path for difference in result.differences] == ["/events/0/payload/model"]
    assert result.differences[0].baseline == "mock-v1"
    assert result.differences[0].candidate == "mock-v2"


def test_final_task_action_approval_and_artifact_changes_are_compared() -> None:
    baseline = RunReport.from_dict(
        {
            "actions": [
                {
                    "action_id": "action_a",
                    "kind": "tool.call",
                    "name": "publish",
                    "payload": {"arguments": {"draft": True}},
                    "capabilities": ["workspace.write"],
                    "created_at": "2026-07-17T08:00:00Z",
                }
            ],
            "approvals": [
                {
                    "type": "approval.decided",
                    "decision": {
                        "approved": True,
                        "request_id": "approval_a",
                        "reason": "reviewed",
                        "decided_at": "2026-07-17T08:00:01Z",
                    },
                }
            ],
            "artifacts": [
                {
                    "id": "artifact_a",
                    "kind": "result",
                    "name": "output",
                    "media_type": "text/plain",
                    "parts": [{"type": "text", "content": "old"}],
                    "timestamp": "2026-07-17T08:00:02Z",
                }
            ],
            "final_task": {
                "id": "task_a",
                "state": "completed",
                "messages": [
                    {
                        "id": "message_a",
                        "role": "agent",
                        "parts": [{"type": "text", "content": "old"}],
                        "timestamp": "2026-07-17T08:00:03Z",
                    }
                ],
                "artifacts": [],
                "metadata": {},
                "flow_state": {},
                "created_at": "2026-07-17T08:00:00Z",
            },
        }
    )
    candidate_data = copy.deepcopy(baseline.to_dict())
    candidate_data["actions"][0]["payload"]["arguments"]["draft"] = False
    candidate_data["approvals"][0]["decision"]["approved"] = False
    candidate_data["artifacts"][0]["parts"][0]["content"] = "new"
    candidate_data["final_task"]["messages"][0]["parts"][0]["content"] = "new"

    result = diff_run_reports(baseline, candidate_data)

    assert set(result.changed_sections) == {
        "actions",
        "approvals",
        "artifacts",
        "final_task",
    }


def test_numeric_tolerances_are_opt_in_and_do_not_treat_booleans_as_numbers() -> None:
    baseline = RunReport.from_dict(
        {
            "metrics": [
                {
                    "provider": "mock",
                    "model": "mock",
                    "latency_ms": 100.0,
                    "usage": {"total_tokens": 10},
                    "cached": False,
                }
            ]
        }
    )
    candidate = RunReport.from_dict(
        {
            "metrics": [
                {
                    "provider": "mock",
                    "model": "mock",
                    "latency_ms": 104.0,
                    "usage": {"total_tokens": 10},
                    "cached": 0,
                }
            ]
        }
    )
    config = RunReportDiffConfig(
        sections=("metrics",),
        tolerances=(
            RunReportTolerance(
                "/metrics/*/latency_ms",
                absolute_tolerance=5.0,
            ),
            RunReportTolerance(
                "/metrics/*/cached",
                absolute_tolerance=1.0,
            ),
        ),
    )

    result = diff_run_reports(baseline, candidate, config=config)

    assert [difference.path for difference in result.differences] == ["/metrics/0/cached"]

    candidate.metrics[0]["cached"] = False
    assert diff_run_reports(baseline, candidate, config=config).matches

    candidate.metrics[0]["latency_ms"] = 106.0
    outside_tolerance = diff_run_reports(baseline, candidate, config=config)
    assert [difference.path for difference in outside_tolerance.differences] == ["/metrics/0/latency_ms"]


def test_numeric_json_equivalence_and_large_integer_tolerances_do_not_overflow() -> None:
    config = RunReportDiffConfig(
        sections=("metadata",),
        tolerances=(
            RunReportTolerance(
                "/metadata/huge",
                relative_tolerance=0.000001,
            ),
        ),
    )
    huge = 10**1000

    result = diff_run_reports(
        {"metadata": {"number": 1, "huge": huge}},
        {"metadata": {"number": 1.0, "huge": huge + 1}},
        config=config,
    )

    assert result.matches


def test_custom_ignore_paths_and_strict_volatile_comparison() -> None:
    baseline = _report_payload(run_id="run_a", task_id="task_a", event_id="event_a")
    candidate = _report_payload(run_id="run_b", task_id="task_b", event_id="event_b")
    candidate["events"][0]["payload"]["debug"] = {"request": "candidate-only"}
    baseline["events"][0]["payload"]["debug"] = {"request": "baseline-only"}

    ignored = RunReportDiffConfig(
        sections=("events",),
        ignore_paths=("/events/*/payload/debug",),
    )
    assert diff_run_reports(baseline, candidate, config=ignored).matches

    strict = RunReportDiffConfig(
        sections=("events",),
        normalize_volatile=False,
        ignore_paths=("/events/*/payload/debug",),
    )
    result = diff_run_reports(baseline, candidate, config=strict)
    assert not result.matches
    assert "/events/0/event_id" in {difference.path for difference in result.differences}


def test_missing_and_explicit_null_are_distinct_in_serialized_differences() -> None:
    added = diff_run_reports(
        {"metadata": {}},
        {"metadata": {"flag": None}},
        config=RunReportDiffConfig(sections=("metadata",)),
    ).to_dict()
    difference = added["differences"][0]

    assert difference["kind"] == "added"
    assert "baseline" not in difference
    assert difference["candidate"] is None

    removed = diff_run_reports(
        {"metadata": {"flag": None}},
        {"metadata": {}},
        config=RunReportDiffConfig(sections=("metadata",)),
    ).to_dict()["differences"][0]
    assert removed["kind"] == "removed"
    assert removed["baseline"] is None
    assert "candidate" not in removed


def test_dictionary_order_is_ignored_but_list_order_is_behavioral() -> None:
    baseline = {"metadata": {"mapping": {"a": 1, "b": 2}, "order": ["a", "b"]}}
    candidate = {"metadata": {"order": ["a", "b"], "mapping": {"b": 2, "a": 1}}}
    config = RunReportDiffConfig(sections=("metadata",))

    assert diff_run_reports(baseline, candidate, config=config).matches

    candidate["metadata"]["order"] = ["b", "a"]
    result = diff_run_reports(baseline, candidate, config=config)
    assert [difference.path for difference in result.differences] == [
        "/metadata/order/0",
        "/metadata/order/1",
    ]


def test_sources_are_not_mutated_and_replay_and_old_dict_inputs_are_supported() -> None:
    baseline = _report_payload(run_id="run_a", task_id="task_a", event_id="event_a")
    candidate = copy.deepcopy(baseline)
    original = copy.deepcopy(baseline)
    replay = RunReplay(RunReport.from_dict(candidate))

    assert diff_run_reports(baseline, replay).matches
    assert baseline == original
    assert normalize_run_report({"events": []}) == normalize_run_report(RunReport.from_dict({"events": []}))


def test_redacted_formatting_and_assertion_errors_do_not_expose_secrets() -> None:
    config = RunReportDiffConfig(sections=("metadata",))
    result = diff_run_reports(
        {"metadata": {"api_key": "baseline-secret"}},
        {"metadata": {"api_key": "candidate-secret"}},
        config=config,
    )

    assert "baseline-secret" in str(result.to_dict())
    redacted = result.to_dict(redaction_policy=RedactionPolicy())
    assert redacted["differences"][0]["baseline"] == "[REDACTED]"
    formatted = result.format()
    assert "baseline-secret" not in formatted
    assert "candidate-secret" not in formatted
    assert "[REDACTED]" in formatted

    with pytest.raises(AssertionError, match="Run reports differ") as exc_info:
        assert_run_matches(
            {"metadata": {"api_key": "baseline-secret"}},
            {"metadata": {"api_key": "candidate-secret"}},
            config=config,
        )
    assert "baseline-secret" not in str(exc_info.value)

    nested = diff_run_reports(
        {"metadata": {"credentials": {"client_id": "baseline-client"}}},
        {"metadata": {"credentials": {"client_id": "candidate-client"}}},
        config=config,
    ).format()
    assert "baseline-client" not in nested
    assert "candidate-client" not in nested
    assert "[REDACTED]" in nested


def test_json_pointer_escapes_application_keys() -> None:
    result = diff_run_reports(
        {"metadata": {"a/b~c": "old"}},
        {"metadata": {"a/b~c": "new"}},
        config=RunReportDiffConfig(sections=("metadata",)),
    )

    assert result.differences[0].path == "/metadata/a~1b~0c"


def test_invalid_diff_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown run-report sections"):
        RunReportDiffConfig(sections=("unknown",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="RFC 6901"):
        RunReportDiffConfig(ignore_paths=("events.*.timestamp",))
    with pytest.raises(ValueError, match="Invalid RFC 6901 escape"):
        RunReportDiffConfig(ignore_paths=("/events/~2/timestamp",))
    with pytest.raises(ValueError, match="non-negative"):
        RunReportTolerance("/metrics/*/latency_ms", absolute_tolerance=-1)


def _report_payload(
    *,
    run_id: str,
    task_id: str,
    event_id: str,
    message_id: str = "message",
    timestamp: str = "2026-07-17T08:00:00Z",
    business_id: str = "order-42",
    business_timestamp: str = "2030-01-01T00:00:00Z",
) -> dict:
    return {
        "context": {
            "run_id": run_id,
            "session_id": f"session-{run_id}",
            "trace_id": f"trace-{run_id}",
            "agent_chain": ["tester"],
            "permissions": {},
            "budget": {},
            "metadata": {},
            "created_at": timestamp,
        },
        "events": [
            {
                "event_id": event_id,
                "type": "tool.result",
                "run_id": run_id,
                "task_id": task_id,
                "sequence": 1,
                "timestamp": timestamp,
                "metadata": {"source_type": "task_llm_stream"},
                "payload": {
                    "task_id": task_id,
                    "timestamp": timestamp,
                    "result": {
                        "id": business_id,
                        "timestamp": business_timestamp,
                    },
                },
            }
        ],
        "final_task": {
            "id": task_id,
            "state": "completed",
            "messages": [
                {
                    "id": message_id,
                    "role": "agent",
                    "parts": [{"type": "text", "content": "done"}],
                    "timestamp": timestamp,
                }
            ],
            "artifacts": [],
            "metadata": {
                "run_id": run_id,
                "session_id": f"session-{run_id}",
                "trace_id": f"trace-{run_id}",
                "state_history": [
                    {
                        "previous_state": "working",
                        "new_state": "completed",
                        "timestamp": timestamp,
                    }
                ],
            },
            "flow_state": {},
            "created_at": timestamp,
        },
        "metadata": {"suite": "regression"},
    }


async def _record_mock_run(run_id: str) -> RunReport:
    agent = Agent(
        AgentCard(
            name="regression-agent",
            description="Provider-free run comparison fixture",
            url="runtime://regression-agent",
        ),
        llm=create_llm("mock", default_response="stable answer"),
        verbosity=0,
    )
    task = Task.create_infer(prompt="produce the stable answer")
    context = RunContext(
        run_id=run_id,
        session_id=f"session-{run_id}",
        trace_id=f"trace-{run_id}",
        agent_chain=["test-client"],
    )
    context.attach_to_task(task)
    recorder = RunRecorder(context=context)
    async for event in agent.handle_task_streaming(task):
        await recorder.record_task_event(event)
    return recorder.to_report(metadata={"suite": "recorded-regression"})
