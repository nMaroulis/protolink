import json

import pytest

from protolink import Agent, AgentCard, LLMModelProfile, LocalTraceTelemetry, Task, create_llm
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
