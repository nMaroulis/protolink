import json

import pytest

from protolink import Agent, AgentCard, LocalTraceTelemetry, Task, create_llm
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory


class RawLLM(LLM):
    model_type = "api"
    provider = "raw"

    def __init__(self, responses):
        super().__init__(model="raw", model_params={})
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


@pytest.mark.asyncio
async def test_local_trace_records_llm_tool_spans_and_redacts_payloads():
    telemetry = LocalTraceTelemetry()
    llm = create_llm(
        "mock",
        sequential_responses=[
            {
                "type": "tool_call",
                "tool": "protected_add",
                "args": {"a": 2, "b": 3, "api_key": "secret-key"},
            },
            {"type": "final", "content": "5"},
        ],
    )
    agent = Agent(
        card=AgentCard(name="traced", description="Traced test agent", url="runtime://traced"),
        llm=llm,
        telemetry=telemetry,
        verbosity=0,
    )

    @agent.tool(name="protected_add", description="Add with a credential")
    async def protected_add(a: int, b: int, api_key: str) -> int:
        assert api_key == "secret-key"
        return a + b

    task = Task.create_infer(prompt="please add")
    result = await agent.handle_task(task)

    assert result.get_last_part_content() == "5"
    records = telemetry.recorder.replay()
    assert len(records) == 1

    trace = records[0]
    assert trace["trace_id"] == task.metadata["trace_id"]
    assert trace["metadata"]["retry_count"] == 0

    span_kinds = [span["kind"] for span in trace["spans"]]
    assert "task" in span_kinds
    assert "llm" in span_kinds
    assert "tool" in span_kinds

    event_types = [event["type"] for event in trace["events"]]
    assert "llm_action" in event_types
    assert "tool_start" in event_types
    assert "tool_result" in event_types
    assert "llm_final" in event_types

    serialized = json.dumps(trace)
    assert "secret-key" not in serialized
    assert "[REDACTED]" in serialized
    assert "input_tokens_estimate" in serialized


@pytest.mark.asyncio
async def test_local_trace_records_retry_count_for_parse_recovery():
    telemetry = LocalTraceTelemetry()
    llm = RawLLM(
        [
            "NOT JSON",
            '{"type": "final", "content": "recovered"}',
        ]
    )
    agent = Agent(
        card=AgentCard(name="retry-agent", description="Retry test agent", url="runtime://retry"),
        llm=llm,
        telemetry=telemetry,
        verbosity=0,
    )

    result = await agent.handle_task(Task.create_infer(prompt="recover"))

    assert result.get_last_part_content() == "recovered"
    trace = telemetry.recorder.replay()[0]
    assert trace["metadata"]["retry_count"] == 1
    assert "llm_parse_error" in [event["type"] for event in trace["events"]]
