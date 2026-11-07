"""Observed root/worker usage is complete, deduplicated and honest about unknowns."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from protolink import Agent, AgentCard, AgentGroup, RunContext, RunEvent, RunReport, Task, assert_budget_under
from protolink.llms.metrics import LLMCost, LLMModelProfile, LLMUsage, calculate_cost, normalize_provider_usage
from protolink.llms.mock_client import MockLLM


class ReportedLLM(MockLLM):
    def call_action(self, history, **kwargs):
        return replace(
            super().call_action(history, **kwargs),
            metadata={"usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}},
        )

    async def call_action_stream(self, history, **kwargs):
        return replace(
            await super().call_action_stream(history, **kwargs),
            metadata={"usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [True, False])
async def test_coordinator_and_worker_preserve_usage_once(owned):
    child = Agent(
        AgentCard(
            name="usage-worker", description="test", url="runtime://usage-worker", capabilities={"streaming": True}
        ),
        llm=ReportedLLM(default_response="worker answer"),
        transport="runtime",
        verbosity=0,
    )
    parent = Agent(
        AgentCard(name="usage-root", description="test", url="runtime://usage-root", capabilities={"streaming": True}),
        llm=ReportedLLM(
            sequential_responses=[
                {"type": "agent_call", "agent": child.card.name, "action": "infer", "prompt": "work"},
                "root answer",
            ]
        ),
        subagents=[child] if owned else None,
        transport="runtime",
        verbosity=0,
    )
    if not owned:
        parent.discover_agents = AsyncMock(return_value=[child.card])
        parent._resolve_agent_url = AsyncMock(return_value=child.card.url)
    async with AgentGroup([parent, child]):
        result = await parent.start_run("consult worker").result()
    assert result.status == "completed"
    report = RunReport.from_dict(result.report.to_dict())
    assert len(report.metrics) == 3
    usage = report.usage()
    assert usage.calls == usage.reported_calls == 3
    assert usage.estimated_calls == usage.unknown_calls == 0
    assert usage.reported == LLMUsage(input_tokens=30, output_tokens=9, total_tokens=39)
    assert usage.estimated.total_tokens is None
    assert usage.costs == () and usage.unpriced_calls == 3
    assert report.usage(scope="root").reported.total_tokens == 26
    assert report.usage(scope="children").reported.total_tokens == 13
    child_id = next(metric["run_id"] for metric in report.metrics if metric["agent_name"] == child.card.name)
    assert report.usage(run_id=child_id).reported.total_tokens == 13
    assert assert_budget_under(report, max_total_tokens=39)["total_tokens"] == 39
    assert len({metric["call_id"] for metric in report.metrics}) == 3


def metric_event(run_id, usage, *, step=1, cost=None):
    return RunEvent(
        type="llm.stream",
        run_id=run_id,
        task_id=f"task-{run_id}",
        step=step,
        payload={"llm_event_type": "llm_call_metrics", "metadata": {"usage": usage, "cost": cost}},
    )


def test_rollup_keeps_estimates_unknown_values_and_currencies_separate():
    provider = metric_event(
        "root",
        {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        cost={"currency": "USD", "total_cost": 0, "estimated": False},
    )
    estimated = metric_event(
        "child",
        {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10, "source": "provider+estimate"},
        cost={"currency": "EUR", "input_cost": 1, "output_cost": 2, "total_cost": 3, "estimated": True},
    )
    incomplete = metric_event(
        "child",
        {"input_tokens": 7, "output_tokens": None, "total_tokens": None},
        step=2,
        cost={"currency": "USD", "input_cost": 1, "total_cost": None, "estimated": False},
    )
    unknown = RunEvent(type="llm.call.completed", run_id="root", step=2, payload={"metrics": None})
    report = RunReport.from_events([provider, estimated, incomplete, unknown], context=RunContext(run_id="root"))
    usage = report.usage()
    assert usage.calls == 4
    assert (usage.reported_calls, usage.estimated_calls, usage.unknown_calls) == (2, 1, 1)
    assert usage.reported.input_tokens == 7
    assert usage.reported.output_tokens is None and usage.reported.total_tokens is None
    assert usage.estimated.total_tokens == 10
    assert usage.unpriced_calls == 1
    assert usage.costs == (
        LLMCost(input_cost=1, output_cost=2, total_cost=3, currency="EUR", estimated=True),
        LLMCost(currency="USD", estimated=False),
    )
    assert usage.to_dict()["reported"]["total_tokens"] is None
    assert report.usage(run_id="absent").calls == 0
    with pytest.raises(ValueError, match="scope"):
        report.usage(scope="all")
    with pytest.raises(ValueError, match="either"):
        report.usage(scope="root", run_id="child")
    with pytest.raises(ValueError, match="context"):
        RunReport().usage(scope="root")


def test_metric_replay_and_repeated_step_numbers_are_not_double_counted():
    first = metric_event("root", {"total_tokens": 4})
    completed = RunEvent(
        type="llm.call.completed",
        run_id="root",
        task_id="task-root",
        step=1,
        payload={"metrics": {"usage": {"total_tokens": 4}}, "latency_ms": 2},
    )
    second = metric_event("root", {"total_tokens": 5})
    second_completion = RunEvent(
        type="llm.call.completed",
        run_id="root",
        task_id="task-root",
        step=1,
        payload={"metrics": {"usage": {"total_tokens": 5}}, "latency_ms": 3},
    )
    report = RunReport.from_events([first, first, completed, second, second_completion, completed])
    assert len(report.metrics) == 2
    assert report.usage().reported.total_tokens == 9
    assert [metric["call_id"] for metric in report.metrics] == [first.event_id, second.event_id]
    assert assert_budget_under(report)["runtime_seconds"] == 0.005


def test_interleaved_reused_steps_and_unmatched_completions_remain_separate():
    first = metric_event("root", {"total_tokens": 4})
    second = metric_event("root", {"total_tokens": 5})
    completions = [
        RunEvent(
            type="llm.call.completed",
            run_id="root",
            task_id="task-root",
            step=1,
            payload={"metrics": {"usage": {"total_tokens": tokens}}},
        )
        for tokens in (4, 5)
    ]
    # An earlier parse failure may emit usage without a completion. A later
    # custom inference can reuse the step and omit usage; it is a distinct call.
    failed = metric_event("root", {"total_tokens": 6})
    unknown = RunEvent(type="llm.call.completed", run_id="root", task_id="task-root", step=1)
    report = RunReport.from_events([first, second, *completions, failed, unknown])
    assert report.usage().calls == 4
    assert report.usage().unknown_calls == 1
    assert report.usage().reported.total_tokens == 15


def test_zero_reported_tokens_do_not_fall_back_to_context_estimates():
    report = RunReport.from_events(
        [
            RunEvent(type="context.prepared", payload={"manifest": {"total_estimated_tokens": 100}}),
            metric_event("root", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
        ]
    )
    usage = assert_budget_under(report, max_input_tokens=0, max_total_tokens=0)
    assert usage["input_tokens"] == usage["total_tokens"] == 0


def test_partial_pricing_and_normalized_usage_retain_unknowns_and_estimates():
    usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15, estimated=True, source="provider+estimate")
    assert normalize_provider_usage(usage) is usage
    assert normalize_provider_usage(usage.to_dict()).estimated
    cost = calculate_cost(usage, LLMModelProfile(input_cost_per_million=2))
    assert cost.input_cost == 0.00002
    assert cost.output_cost is None and cost.total_cost is None


@pytest.mark.asyncio
async def test_unobserved_unary_inference_does_not_activate_optional_estimation(monkeypatch):
    def unexpected_estimate(**kwargs):
        raise AssertionError("An internal receipt callback is not a metrics observer")

    monkeypatch.setattr("protolink.llms.base.build_call_metrics", unexpected_estimate)
    agent = Agent(name="unobserved-usage", llm=MockLLM(default_response="answer"), verbosity=0)
    result = await agent.run_task(Task.create_infer("question"))
    assert result.state.value == "completed"
