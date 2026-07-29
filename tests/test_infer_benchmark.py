import json
from collections import Counter

import pytest

from benchmarks.infer_loop.runner import (
    AttemptResult,
    BenchmarkConfig,
    BenchmarkMesh,
    CaseResult,
    LocalTraceRecorder,
    _cache_probe,
    _distribution,
    _llm_call_fieldnames,
    _prompt_source_hash,
    _suite_hash,
    _trace_metrics,
    _validate_attempt,
    _write_csv,
    _write_html_report,
    compare_with_baseline,
    generate_cases,
    run_attempt,
    run_benchmark,
)
from protolink import Task
from protolink.llms import MockLLM
from protolink.telemetry.local import TraceEvent, TraceRecord


def _scripted_action(case):
    action = case.expected_actions[0]
    if action.kind == "local_tool":
        return {"type": "tool_call", "tool": action.tool, "args": action.args}
    if action.kind == "agent_tool":
        return {
            "type": "agent_call",
            "agent": action.agent,
            "action": "tool_call",
            "tool": action.tool,
            "args": action.args,
        }
    if action.kind == "agent_infer":
        return {
            "type": "agent_call",
            "agent": action.agent,
            "action": "infer",
            "prompt": " ".join(action.prompt_contains),
        }
    raise AssertionError(f"Unsupported test action: {action.kind}")


def _scripted_responses(cases):
    responses = []
    for case in cases:
        for action in case.expected_actions:
            synthetic_case = type("SyntheticCase", (), {"expected_actions": (action,)})
            responses.append(_scripted_action(synthetic_case))
        responses.append({"type": "final", "content": case.expected_final})
    return responses


def test_generated_suites_are_stable_unique_and_closed_world():
    smoke = generate_cases(12, seed=1337)
    full = generate_cases(200, seed=1337)

    assert len(smoke) == 12
    assert len(full) == 200
    assert len({case.id for case in full}) == 200
    assert [case.to_dict() for case in smoke] == [case.to_dict() for case in full[:12]]
    assert _suite_hash(smoke) == _suite_hash(generate_cases(12, seed=1337))
    assert _suite_hash(smoke) != _suite_hash(generate_cases(12, seed=7331))

    local_case = smoke[1]
    receipt = local_case.expected_final.rsplit("=", 1)[-1]
    assert receipt.startswith("BENCH-")
    assert receipt not in local_case.prompt

    assert Counter(case.category for case in smoke)["routing_choice"] == 2
    assert Counter(case.category for case in full) == {
        "direct_final": 30,
        "local_tool": 30,
        "delegated_tool": 30,
        "delegated_infer": 30,
        "multi_step": 30,
        "grounding_trap": 30,
        "routing_choice": 20,
    }


def test_routing_choice_variants_omit_target_identifiers_and_cover_every_action_mode():
    routing_cases = [case for case in generate_cases(200, seed=1337) if case.category == "routing_choice"][:8]

    assert len(routing_cases) == 8
    modes = set()
    for case in routing_cases:
        if not case.expected_actions:
            modes.add("direct")
            continue
        action = case.expected_actions[0]
        modes.add(action.kind)
        assert action.agent not in case.prompt
        if action.tool:
            assert action.tool not in case.prompt

    assert modes == {"direct", "local_tool", "agent_tool", "agent_infer"}

    core_routing = [case for case in generate_cases(40, seed=1337) if case.category == "routing_choice"]
    core_modes = {case.expected_actions[0].kind if case.expected_actions else "direct" for case in core_routing}
    assert core_modes == {"direct", "local_tool", "agent_tool", "agent_infer"}


def test_repository_local_runner_hashes_package_prompt_sources():
    assert _prompt_source_hash() != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.asyncio
async def test_runtime_mesh_scores_clean_local_tool_attempt_strictly():
    case = generate_cases(2, seed=1337)[1]
    llm = MockLLM(
        sequential_responses=[
            _scripted_action(case),
            {"type": "final", "content": case.expected_final},
        ]
    )
    recorder = LocalTraceRecorder()
    mesh = BenchmarkMesh(llm=llm, recorder=recorder, namespace="test-clean-local")
    await mesh.start()
    try:
        result = await run_attempt(
            mesh=mesh,
            recorder=recorder,
            case=case,
            repetition=1,
            attempt=1,
            timeout=5,
        )
    finally:
        mesh.stop()

    assert result.strict_pass is True
    assert result.functional_pass is True
    assert result.protocol_clean is True
    assert result.llm_steps == 2
    assert result.llm_calls == 2
    assert len(result.llm_call_timings) == 2
    assert result.latency_ms >= result.llm_latency_ms >= 0
    assert result.non_llm_latency_ms >= 0
    assert result.timing_complete is True
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.observed_actions == result.trace_actions


@pytest.mark.asyncio
async def test_recovered_unknown_tool_is_functional_but_not_strict():
    case = generate_cases(2, seed=1337)[1]
    llm = MockLLM(
        sequential_responses=[
            {"type": "tool_call", "tool": "invented_tool", "args": {}},
            _scripted_action(case),
            {"type": "final", "content": case.expected_final},
        ]
    )
    recorder = LocalTraceRecorder()
    mesh = BenchmarkMesh(llm=llm, recorder=recorder, namespace="test-recovered-local")
    await mesh.start()
    try:
        result = await run_attempt(
            mesh=mesh,
            recorder=recorder,
            case=case,
            repetition=1,
            attempt=1,
            timeout=5,
        )
    finally:
        mesh.stop()

    assert result.functional_pass is True
    assert result.strict_pass is False
    assert result.invalid_tool_attempts == 1
    assert "invalid_tool_action" in result.failure_codes
    assert result.hallucinated_action is True


@pytest.mark.asyncio
async def test_runtime_mesh_validates_delegated_tool_execution():
    case = generate_cases(3, seed=1337)[2]
    llm = MockLLM(
        sequential_responses=[
            _scripted_action(case),
            {"type": "final", "content": case.expected_final},
        ]
    )
    recorder = LocalTraceRecorder()
    mesh = BenchmarkMesh(llm=llm, recorder=recorder, namespace="test-delegated-tool")
    await mesh.start()
    try:
        result = await run_attempt(
            mesh=mesh,
            recorder=recorder,
            case=case,
            repetition=1,
            attempt=1,
            timeout=5,
        )
    finally:
        mesh.stop()

    assert result.strict_pass is True
    assert result.action_receipts == 1
    assert result.observed_actions[0]["agent"] == "workspace_agent"
    assert result.observed_actions[0]["tool"] == "read_file"


@pytest.mark.asyncio
async def test_all_generated_action_variants_pass_with_a_perfect_script():
    cases = generate_cases(24, seed=2026)
    llm = MockLLM(sequential_responses=_scripted_responses(cases))
    recorder = LocalTraceRecorder()
    mesh = BenchmarkMesh(llm=llm, recorder=recorder, namespace="test-all-generated-variants")
    await mesh.start()
    try:
        results = [
            await run_attempt(
                mesh=mesh,
                recorder=recorder,
                case=case,
                repetition=1,
                attempt=1,
                timeout=5,
            )
            for case in cases
        ]
    finally:
        mesh.stop()

    failures = [(result.case_id, result.failure_codes) for result in results if not result.strict_pass]
    assert failures == []


@pytest.mark.asyncio
async def test_all_routing_choice_variants_pass_with_a_perfect_script():
    cases = [case for case in generate_cases(200, seed=2026) if case.category == "routing_choice"][:8]
    llm = MockLLM(sequential_responses=_scripted_responses(cases))
    recorder = LocalTraceRecorder()
    mesh = BenchmarkMesh(llm=llm, recorder=recorder, namespace="test-routing-choice-variants")
    await mesh.start()
    try:
        results = [
            await run_attempt(
                mesh=mesh,
                recorder=recorder,
                case=case,
                repetition=1,
                attempt=1,
                timeout=5,
            )
            for case in cases
        ]
    finally:
        mesh.stop()

    assert [(result.case_id, result.failure_codes) for result in results if not result.strict_pass] == []


@pytest.mark.asyncio
async def test_routing_choice_scores_the_selected_agent_even_when_decoy_output_matches():
    case = next(case for case in generate_cases(12, seed=1337) if case.category == "routing_choice")
    expected = case.expected_actions[0]
    llm = MockLLM(
        sequential_responses=[
            {
                "type": "agent_call",
                "agent": "workspace_archive_agent",
                "action": "tool_call",
                "tool": expected.tool,
                "args": expected.args,
            },
            {"type": "final", "content": case.expected_final},
        ]
    )
    recorder = LocalTraceRecorder()
    mesh = BenchmarkMesh(llm=llm, recorder=recorder, namespace="test-routing-choice-decoy")
    await mesh.start()
    try:
        result = await run_attempt(
            mesh=mesh,
            recorder=recorder,
            case=case,
            repetition=1,
            attempt=1,
            timeout=5,
        )
    finally:
        mesh.stop()

    assert result.output_match is True
    assert result.ledger_match is False
    assert result.trace_match is False
    assert result.functional_pass is False
    assert result.observed_actions[0]["agent"] == "workspace_archive_agent"
    assert result.model_actions[0]["payload"]["agent"] == "workspace_archive_agent"


@pytest.mark.asyncio
async def test_run_writes_csv_summary_and_supports_baseline(tmp_path):
    case = generate_cases(1, seed=44)[0]
    config = BenchmarkConfig(
        provider="mock",
        count=1,
        seed=44,
        output_root=tmp_path,
        run_name="first",
        preflight=False,
        warmup=1,
        quiet=True,
    )
    run = await run_benchmark(
        config,
        llm=MockLLM(
            sequential_responses=[
                {"type": "final", "content": "BENCH-WARMUP-1"},
                {"type": "final", "content": case.expected_final},
            ]
        ),
    )

    assert run.summary["scores"]["strict"] == 1
    assert run.summary["schema_version"] == 3
    assert run.summary["case_definitions"][0]["prompt"] == case.prompt
    assert run.summary["timing"]["warmup"]["completed"] == 1
    assert run.summary["performance_fingerprint"]["warmup_completed"] == 1
    assert run.summary["performance_fingerprint"]["warmup_failed"] == 0
    assert run.summary["timing"]["first_attempt_e2e_ms"]["count"] == 1
    assert (run.output_dir / "results.csv").read_text(encoding="utf-8").startswith("case_id,")
    assert (run.output_dir / "llm_calls.csv").read_text(encoding="utf-8").startswith("case_id,")
    assert (run.output_dir / "failures.csv").read_text(encoding="utf-8").startswith("case_id,")
    assert json.loads((run.output_dir / "summary.json").read_text(encoding="utf-8"))["scores"]["strict"] == 1
    assert (run.output_dir / "traces.jsonl").is_file()
    report = (run.output_dir / "report.html").read_text(encoding="utf-8")
    assert report.startswith("<!doctype html>")
    assert "Correctness by category" in report
    assert "Latency distributions" in report
    assert "No external assets or requests" in report

    comparison = compare_with_baseline(
        current_cases=run.cases,
        current_suite_hash=run.summary["suite"]["hash"],
        baseline_path=run.output_dir / "summary.json",
        current_timing=run.summary["timing"],
        current_performance_fingerprint=run.summary["performance_fingerprint"],
    )
    assert comparison["delta"] == 0
    assert comparison["stable_pass"] == ["direct-final-0001#r1"]
    assert comparison["performance"]["e2e"]["matched_pairs"] == 1
    assert comparison["performance"]["e2e"]["median_paired_delta_ms"] == 0
    assert comparison["performance"]["provider_prompt_eval"]["matched_pairs"] == 0
    assert comparison["performance"]["fingerprint_match"] is True

    retry_baseline = json.loads((run.output_dir / "summary.json").read_text(encoding="utf-8"))
    retry_baseline["case_results"][0]["attempts"][0]["provider_retries"] = 1
    retry_baseline_path = tmp_path / "retry-baseline.json"
    retry_baseline_path.write_text(json.dumps(retry_baseline), encoding="utf-8")
    retry_comparison = compare_with_baseline(
        current_cases=run.cases,
        current_suite_hash=run.summary["suite"]["hash"],
        baseline_path=retry_baseline_path,
    )
    assert retry_comparison["performance"]["e2e"]["matched_pairs"] == 0
    assert retry_comparison["performance"]["excluded_retry_or_incomplete_pairs"] == 1


def test_trace_metrics_extract_ollama_provider_timings_and_cache_usage():
    trace = TraceRecord(trace_id="trace-1", task_id="task-1", agent_name="benchmark_coordinator")
    trace.events.extend(
        [
            TraceEvent(type="llm_step", payload={"step": 1}),
            TraceEvent(type="llm_call_started", payload={"step": 1, "attempt": 1}),
            TraceEvent(type="llm_call_started", payload={"step": 1, "attempt": 2}),
            TraceEvent(
                type="llm_call_completed",
                payload={
                    "step": 1,
                    "provider": "ollama",
                    "latency_ms": 75.5,
                    "attempts": 2,
                    "metrics": {
                        "usage": {
                            "input_tokens": 80,
                            "output_tokens": 20,
                            "total_tokens": 100,
                            "estimated": False,
                            "details": {
                                "details": {
                                    "prompt_eval_count": 80,
                                    "eval_count": 20,
                                    "total_duration": 70_000_000,
                                    "load_duration": 5_000_000,
                                    "prompt_eval_duration": 40_000_000,
                                    "eval_duration": 25_000_000,
                                    "cached_tokens": 60,
                                }
                            },
                        }
                    },
                },
            ),
        ]
    )

    metrics, calls = _trace_metrics(trace)

    assert metrics["llm_calls"] == 1
    assert metrics["provider_attempts"] == 2
    assert metrics["llm_latency_ms"] == 75.5
    assert metrics["provider_total_ms"] == 70.0
    assert metrics["provider_load_ms"] == 5.0
    assert metrics["provider_prompt_eval_ms"] == 40.0
    assert metrics["provider_generation_ms"] == 25.0
    assert metrics["cached_input_tokens"] == 60
    assert metrics["prompt_tokens_per_second"] == 2000.0
    assert metrics["output_tokens_per_second"] == 800.0
    assert calls[0].physical_attempts == 2


@pytest.mark.asyncio
async def test_repetitions_are_case_major_and_feed_cache_probe(tmp_path):
    cases = generate_cases(2, seed=91)
    execution_order = [cases[0], cases[0], cases[1], cases[1]]
    run = await run_benchmark(
        BenchmarkConfig(
            provider="mock",
            count=2,
            seed=91,
            repetitions=2,
            output_root=tmp_path,
            run_name="repeated",
            preflight=False,
            quiet=True,
        ),
        llm=MockLLM(sequential_responses=_scripted_responses(execution_order)),
    )

    assert [result.key for result in run.cases] == [
        f"{cases[0].id}#r1",
        f"{cases[0].id}#r2",
        f"{cases[1].id}#r1",
        f"{cases[1].id}#r2",
    ]
    assert run.summary["suite"]["repetition_order"] == "case_major"
    assert run.summary["timing"]["cache_probe"]["eligible_strict_pairs"] == 2


def test_distribution_reports_median_and_tail_without_samples():
    assert _distribution([])["count"] == 0
    stats = _distribution([10.0, 20.0, 40.0, 100.0])
    assert stats["total_ms"] == 170.0
    assert stats["mean_ms"] == 42.5
    assert stats["median_ms"] == 30.0
    assert stats["p95_ms"] == 100.0


def test_cache_probe_excludes_retries_and_recognizes_write_only_cache_metrics():
    before = generate_cases(1, seed=11)[0]
    required = {
        "case_id": before.id,
        "category": before.category,
        "attempt": 1,
        "task_id": "task",
        "strict_pass": True,
        "functional_pass": True,
        "protocol_clean": True,
        "output_match": True,
        "ledger_match": True,
        "trace_match": True,
        "task_state": "completed",
        "final_output": before.expected_final,
        "latency_ms": 20.0,
        "llm_latency_ms": 10.0,
        "first_llm_latency_ms": 10.0,
        "llm_calls": 1,
        "provider_attempts": 1,
        "completed_provider_attempts": 1,
        "timing_complete": True,
    }
    first = AttemptResult(repetition=1, **required)
    second = AttemptResult(
        repetition=2,
        provider_retries=1,
        provider_attempts=2,
        completed_provider_attempts=2,
        **{
            key: value
            for key, value in required.items()
            if key not in {"provider_attempts", "completed_provider_attempts"}
        },
    )
    probe = _cache_probe(
        [
            CaseResult(before.id, before.category, 1, [first]),
            CaseResult(before.id, before.category, 2, [second]),
        ],
        [{"cached_input_tokens": None, "cache_write_input_tokens": 50}],
    )

    assert probe["eligible_strict_pairs"] == 0
    assert probe["excluded_retry_or_incomplete_pairs"] == 1
    assert probe["explicit_cache_metrics_available"] is True
    assert probe["cache_write_input_tokens"] == 50


def test_incomplete_provider_call_does_not_become_non_llm_overhead():
    case = generate_cases(1, seed=12)[0]
    task = Task.create_infer(prompt=case.prompt)
    trace = TraceRecord(trace_id="trace-timeout", task_id=task.id, agent_name="benchmark_coordinator")
    trace.events.append(TraceEvent(type="llm_call_started", payload={"step": 1, "attempt": 1}))

    result = _validate_attempt(
        case=case,
        repetition=1,
        attempt=1,
        task=task,
        trace=trace,
        ledger_entries=[],
        latency_ms=1000.0,
        error=TimeoutError(),
        timed_out=True,
    )

    assert result.timing_complete is False
    assert result.non_llm_latency_ms is None
    assert result.provider_attempts == 1
    assert result.completed_provider_attempts == 0


def test_empty_llm_call_csv_still_has_a_stable_header(tmp_path):
    path = tmp_path / "llm_calls.csv"
    _write_csv(path, [], fieldnames=_llm_call_fieldnames())

    assert path.read_text(encoding="utf-8").startswith("case_id,category,repetition,")


def test_html_report_escapes_dynamic_content_and_has_no_external_dependencies(tmp_path):
    path = tmp_path / "report.html"
    _write_html_report(
        path,
        {
            "run_id": "<script>alert('run')</script>",
            "created_at": "2026-07-28T00:00:00Z",
            "protolink_version": "test",
            "provider": {
                "name": "mock",
                "model": "<img src=x onerror=alert(1)>",
                "model_params": {},
                "action_mode": "json_prompt",
            },
            "suite": {
                "id": "smoke",
                "selected_count": 1,
                "repetitions": 1,
                "max_fresh_attempts": 1,
                "seed": 1,
                "hash": "suite",
            },
            "scores": {
                "total": 1,
                "strict": 0,
                "strict_percent": 0,
                "functional": 0,
                "functional_percent": 0,
                "first_attempt_strict": 0,
                "first_attempt_strict_percent": 0,
                "attempts_executed": 1,
                "categories": {},
            },
            "timing": {},
            "baseline_comparison": {
                "delta": -1,
                "fixed": [],
                "regressed": ["<case>"],
                "stable_pass": [],
                "stable_fail": [],
                "performance": {
                    "warning": "<b>settings differ</b>",
                    "e2e": {
                        "matched_pairs": 1,
                        "median_paired_speedup_percent": -2.5,
                    },
                },
            },
            "case_results": [
                {
                    "key": "<svg/onload=alert(2)>",
                    "case_id": "case",
                    "category": "direct_final",
                    "strict_pass": False,
                    "functional_pass": False,
                    "attempts_used": 1,
                    "selected_attempt": 1,
                    "attempts": [
                        {
                            "attempt": 1,
                            "latency_ms": 5,
                            "final_output": "<wrong final>",
                            "model_actions": [{"payload": {"prompt": "<wrong action>"}}],
                            "failure_codes": ["<b>bad</b>"],
                        }
                    ],
                },
                {
                    "key": "rescued#r1",
                    "case_id": "rescued",
                    "category": "routing_choice",
                    "strict_pass": True,
                    "functional_pass": True,
                    "attempts_used": 2,
                    "selected_attempt": 2,
                    "attempts": [
                        {
                            "attempt": 1,
                            "strict_pass": False,
                            "latency_ms": 6,
                            "final_output": "<rescued wrong>",
                            "model_actions": [{"payload": {"agent": "wrong-agent"}}],
                            "failure_codes": ["final_output_mismatch"],
                        },
                        {
                            "attempt": 2,
                            "strict_pass": True,
                            "latency_ms": 4,
                            "final_output": "expected",
                            "model_actions": [{"payload": {"content": "expected"}}],
                            "failure_codes": [],
                        },
                    ],
                },
            ],
            "case_definitions": [
                {
                    "id": "case",
                    "prompt": "<hostile request>",
                    "expected_final": "<expected answer>",
                    "expected_actions": [],
                },
                {
                    "id": "rescued",
                    "prompt": "rescue this",
                    "expected_final": "expected",
                    "expected_actions": [],
                },
            ],
        },
    )

    report = path.read_text(encoding="utf-8")
    assert "<script>alert" not in report
    assert "<img src=x" not in report
    assert "<svg/onload" not in report
    assert "&lt;script&gt;" in report
    assert "&lt;img src=x onerror=alert(1)&gt;" in report
    assert "&lt;b&gt;settings differ&lt;/b&gt;" in report
    assert "&lt;hostile request&gt;" in report
    assert "&lt;wrong final&gt;" in report
    assert "&lt;wrong action&gt;" in report
    assert "&lt;rescued wrong&gt;" in report
    assert "Rescued" in report
    assert "Attempt review" in report
    assert "Expected final output" in report
    assert "Model decisions" in report
    assert "case-chart-scroll" in report
    assert "Regressed" in report
    assert "https://" not in report
    assert "http://" not in report
