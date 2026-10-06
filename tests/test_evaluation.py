"""Datasets evaluate real runs, including failed execution and async checks."""

import asyncio
import json

import pytest

from protolink import Agent, EchoAgent, EvaluationCase, EvaluationScore, compare_evaluations, evaluate, tool_used
from protolink.llms import MockLLM
from protolink.tools import calculator


@pytest.mark.asyncio
async def test_repeatable_dataset_report_and_quality_regression(tmp_path):
    cases = [EvaluationCase("first", "hello", "hello"), EvaluationCase("second", "bye", "bye")]
    baseline = await evaluate(lambda: EchoAgent(verbosity=0), cases, repetitions=2, concurrency=2)
    assert baseline.passed and len(baseline.samples) == 4
    path = tmp_path / "experiment.json"
    baseline.save(path)
    assert json.loads(path.read_text())["scores"]["exact_match"] == 1
    candidate = await evaluate(Agent(name="wrong", llm=MockLLM(default_response="wrong"), verbosity=0), cases)
    diff = compare_evaluations(baseline, candidate)
    assert not diff["passed"]
    assert len(diff["regressions"]) == 2
    assert candidate.to_dict()["total_usage"]["llm_calls"] == 2


@pytest.mark.asyncio
async def test_tool_receipt_and_async_judge_are_scored():
    async def judge(sample):
        await asyncio.sleep(0)
        return EvaluationScore("judge", 0.8, "Custom rubric")

    def make():
        return Agent(
            name="calculator",
            llm=MockLLM(
                sequential_responses=[{"type": "tool_call", "tool": "calculator", "args": {"expression": "1+1"}}, "2"]
            ),
            tools=[calculator()],
            verbosity=0,
        )

    result = await evaluate(make, [EvaluationCase("sum", "calculate", "2")], checks=[tool_used("calculator"), judge])
    scores = result.to_dict()["scores"]
    assert scores == {"execution_completed": 1, "tool_used:calculator": 1, "judge": 0.8}
    assert result.to_dict()["total_usage"]["tool_calls"] == 1
    assert compare_evaluations(result, result)["passed"]


@pytest.mark.asyncio
async def test_jsonl_errors_and_evaluator_errors_remain_visible(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"name": "c", "prompt": "hello", "expected": "hello"}) + "\n")

    def bad_judge(sample):
        raise ValueError("broken rubric")

    report = await evaluate(EchoAgent(verbosity=0), path, checks=[bad_judge])
    assert not report.passed
    assert "broken rubric" in report.samples[0].error
    with pytest.raises(ValueError, match="factory"):
        await evaluate(EchoAgent(verbosity=0), path, concurrency=2)
    with pytest.raises(ValueError, match="unique"):
        await evaluate(EchoAgent(verbosity=0), [EvaluationCase("c", "a"), EvaluationCase("c", "b")])


@pytest.mark.asyncio
async def test_cancellation_propagates_to_in_flight_evaluation():
    stopped = asyncio.Event()

    class Slow(MockLLM):
        async def call_stream(self, history):
            try:
                await asyncio.sleep(30)
                yield "never"
            finally:
                stopped.set()

    running = asyncio.create_task(
        evaluate(lambda: Agent(name="slow", llm=Slow(), verbosity=0), [EvaluationCase("c", "go")])
    )
    await asyncio.sleep(0.02)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert stopped.is_set()
