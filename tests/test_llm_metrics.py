import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import protolink.llms.metrics as metrics_module
from protolink import (
    Agent,
    AgentCard,
    BudgetExceededError,
    LLMModelProfile,
    LocalTraceTelemetry,
    RunBudget,
    RunContext,
    Task,
    create_llm,
)
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory


class MetricsMockLLM(LLM):
    model_type = "api"
    provider = "metrics-mock"

    def __init__(self, responses: list[str]) -> None:
        super().__init__(model="metrics-mock-model", model_params={})
        self.responses = responses
        self.call_count = 0

    def call(self, history: ConversationHistory) -> str:
        response = self.responses[self.call_count]
        self.call_count += 1
        return response

    async def call_stream(self, history: ConversationHistory):
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


class UsageReportingLLM(MetricsMockLLM):
    def call_action(self, history, **kwargs):
        result = super().call_action(history, **kwargs)
        return replace(result, metadata={"usage": {"input_tokens": 100, "output_tokens": 40}})

    async def call_action_stream(self, history, **kwargs):
        result = await super().call_action_stream(history, **kwargs)
        return replace(result, metadata={"usage": {"input_tokens": 100, "output_tokens": 40}})


@pytest.mark.parametrize(
    ("provider_usage", "expected_counts", "input_tokens", "output_tokens", "total_tokens", "source"),
    [
        (None, ["input", "output"], 11, 7, 18, "estimate"),
        ({}, ["input", "output"], 11, 7, 18, "estimate"),
        ({"input_tokens": 100, "output_tokens": 40, "total_tokens": 150}, [], 100, 40, 150, "provider"),
        ({"input_tokens": 0, "output_tokens": 0}, [], 0, 0, 0, "provider"),
        ({"output_tokens": 40, "total_tokens": 150}, ["input"], 11, 40, 150, "provider+estimate"),
        ({"input_tokens": 100}, ["output"], 100, 7, 107, "provider+estimate"),
        ({"total_tokens": 150}, ["input", "output"], 11, 7, 150, "provider+estimate"),
    ],
)
def test_call_metrics_estimate_only_missing_usage(
    monkeypatch, provider_usage, expected_counts, input_tokens, output_tokens, total_tokens, source
):
    counted = []

    def estimate(value, *, model):
        assert model == "metrics-test"
        counted.append(value)
        return 11 if value == "input" else 7

    monkeypatch.setattr(metrics_module, "estimate_token_count", estimate)
    metrics = metrics_module.build_call_metrics(
        step=1,
        provider="test",
        model="metrics-test",
        latency_ms=1,
        input_value="input",
        output_value="output",
        provider_usage=provider_usage,
        profile=LLMModelProfile(context_window=1000, input_cost_per_million=2, output_cost_per_million=8),
    )

    assert counted == expected_counts
    assert metrics.usage.input_tokens == input_tokens
    assert metrics.usage.output_tokens == output_tokens
    assert metrics.usage.total_tokens == total_tokens
    assert metrics.usage.source == source
    assert metrics.usage.estimated is bool(expected_counts)
    assert metrics.context.used_tokens == input_tokens
    assert metrics.context.estimated is bool(expected_counts)
    assert metrics.cost is not None
    assert metrics.cost.total_cost == round((input_tokens * 2 + output_tokens * 8) / 1_000_000, 8)


def test_token_estimates_accept_history_in_standard_message_format():
    history = ConversationHistory("system prompt")
    history.add_user("question")
    history.add_tool("result", "lookup")

    assert metrics_module.estimate_usage(history, "response") == metrics_module.estimate_usage(
        history.messages, "response"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_infer_provider_usage_avoids_history_materialization(monkeypatch, streaming):
    llm = UsageReportingLLM([json.dumps({"type": "final", "content": "done"})])
    events = []

    def unexpected_messages(_history):
        raise AssertionError("Provider usage must not materialize history for metrics")

    monkeypatch.setattr(ConversationHistory, "messages", property(unexpected_messages))

    async def capture(event):
        events.append(event)

    result = await llm.infer(query="question", tools={}, event_callback=capture, streaming=streaming)

    assert result.content == "done"
    metrics = next(event for event in events if event["type"] == "llm_call_metrics")
    assert metrics["usage"]["input_tokens"] == 100
    assert metrics["usage"]["output_tokens"] == 40
    assert metrics["usage"]["total_tokens"] == 140
    assert metrics["usage"]["estimated"] is False


@pytest.mark.asyncio
async def test_provider_usage_still_enforces_output_budget_without_metrics_observer():
    llm = UsageReportingLLM([json.dumps({"type": "final", "content": "done"})])
    context = RunContext(budget=RunBudget(max_output_tokens=30))

    with pytest.raises(BudgetExceededError) as exc:
        await llm.infer(query="question", tools={}, run_context=context)

    assert exc.value.decision.limit_name == "max_output_tokens"
    assert llm.call_count == 1


@pytest.mark.parametrize("availability", ["missing", "available"])
def test_tokenizer_resolution_is_cached_per_model(monkeypatch, availability: str) -> None:
    imports = 0
    encoder = SimpleNamespace(encode=lambda _text: [1, 2, 3])

    def import_tokenizer(name: str):
        nonlocal imports
        assert name == "tiktoken"
        imports += 1
        if availability == "missing":
            raise ImportError("optional tokenizer missing")
        return SimpleNamespace(encoding_for_model=lambda _model: encoder)

    metrics_module._optional_tiktoken_encoder.cache_clear()
    monkeypatch.setattr(metrics_module.importlib, "import_module", import_tokenizer)
    try:
        expected = 3 if availability == "available" else 2
        assert metrics_module.estimate_token_count("abcdef", model="cache-test") == expected
        assert metrics_module.estimate_token_count("abcdef", model="cache-test") == expected
        assert imports == 1
    finally:
        metrics_module._optional_tiktoken_encoder.cache_clear()


def test_create_llm_accepts_optional_metrics_profile():
    llm = create_llm(
        "mock",
        metrics_profile=LLMModelProfile(
            context_window=8192,
            input_cost_per_million=1.0,
            output_cost_per_million=2.0,
        ),
    )

    assert llm.metrics_profile is not None
    assert llm.metrics_profile.context_window == 8192
    assert llm.metrics_profile.provider == "mock"
    assert llm.metrics_profile.model == "mock-gpt"


def test_create_llm_keeps_parse_limit_out_of_provider_model_params():
    llm = create_llm(
        "mock",
        model_params={"temperature": 0.2},
        max_parse_failures=5,
    )

    assert llm.max_parse_failures == 5
    assert llm._model_params == {"temperature": 0.2}


@pytest.mark.parametrize("value", [0, 11, True, 2.5, "3"])
def test_parse_failure_limit_is_validated(value):
    with pytest.raises((TypeError, ValueError)):
        create_llm("mock", max_parse_failures=value)


@pytest.mark.asyncio
async def test_infer_emits_live_llm_metrics_events():
    llm = MetricsMockLLM([json.dumps({"type": "final", "content": "done"})])
    llm.configure_metrics(
        context_window=1000,
        input_cost_per_million=2.0,
        output_cost_per_million=8.0,
    )
    events = []

    async def capture(event):
        events.append(event)

    result = await llm.infer(query="Summarize this tiny prompt", tools={}, event_callback=capture)

    assert result.content == "done"
    assert any(event["type"] == "llm_context" for event in events)
    metrics = next(event for event in events if event["type"] == "llm_call_metrics")
    assert metrics["provider"] == "metrics-mock"
    assert metrics["model"] == "metrics-mock-model"
    assert metrics["latency_ms"] >= 0
    assert metrics["usage"]["input_tokens"] > 0
    assert metrics["usage"]["output_tokens"] > 0
    assert metrics["usage"]["estimated"] is True
    assert metrics["context"]["window_tokens"] == 1000
    assert metrics["context"]["used_percent"] is not None
    assert metrics["cost"]["total_cost"] is not None


@pytest.mark.asyncio
async def test_local_trace_rolls_up_llm_metrics():
    telemetry = LocalTraceTelemetry()
    llm = create_llm(
        "mock",
        sequential_responses=[{"type": "final", "content": "observed"}],
        metrics_profile={
            "context_window": 1000,
            "input_cost_per_million": 2.0,
            "output_cost_per_million": 8.0,
        },
    )
    agent = Agent(
        card=AgentCard(name="metrics-agent", description="Metrics test agent", url="runtime://metrics"),
        llm=llm,
        telemetry=telemetry,
        verbosity=0,
    )

    result = await agent.handle_task(Task.create_infer(prompt="measure this call"))

    assert result.get_last_part_content() == "observed"
    trace = telemetry.recorder.replay()[0]
    llm_span = next(span for span in trace["spans"] if span["kind"] == "llm")
    rollup = llm_span["metadata"]["llm_metrics"]
    assert rollup["call_count"] == 1
    assert rollup["total_latency_ms"] >= 0
    assert rollup["total_input_tokens"] > 0
    assert rollup["total_output_tokens"] > 0
    assert rollup["context_window_tokens"] == 1000
    assert rollup["max_context_used_percent"] is not None
    assert rollup["total_cost"] is not None
    assert "llm_call_metrics" in [event["type"] for event in trace["events"]]
