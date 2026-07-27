import json

import pytest

from protolink import Agent, AgentCard, LocalTraceRecorder, LocalTraceTelemetry, Part, Task, create_llm
from protolink.discovery import Registry
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.telemetry import MultiTelemetry


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


@pytest.mark.asyncio
async def test_local_trace_restores_parent_after_nested_in_process_task():
    telemetry = LocalTraceTelemetry()
    parent = Task.create_infer(prompt="delegate")
    child = Task.create_infer(prompt="respond")

    await telemetry.on_task_start(parent, "parent")
    await telemetry.on_llm_start("delegate")
    await telemetry.on_llm_event(
        {
            "type": "agent_call_start",
            "step": 1,
            "agent": "child",
            "action": "infer",
            "payload": {"prompt": "respond"},
        }
    )

    await telemetry.on_task_start(child, "child")
    child.complete("child response")
    await telemetry.on_task_end(child, child, "child")

    await telemetry.on_llm_event(
        {
            "type": "agent_call_result",
            "step": 1,
            "agent": "child",
            "action": "infer",
            "result": "child response",
        }
    )
    await telemetry.on_llm_end(Part.infer_output(content="parent response"))
    parent.complete("parent response")
    await telemetry.on_task_end(parent, parent, "parent")

    records = telemetry.recorder.replay()
    assert [record["agent_name"] for record in records] == ["child", "parent"]
    parent_trace = records[-1]
    assert parent_trace["task_id"] == parent.id
    assert "agent_call_result" in [event["type"] for event in parent_trace["events"]]
    agent_span = next(span for span in parent_trace["spans"] if span["kind"] == "agent_call")
    assert agent_span["status"] == "ok"
    assert agent_span["ended_at"] is not None


@pytest.mark.asyncio
async def test_local_trace_instances_are_isolated_inside_multi_telemetry():
    first = LocalTraceTelemetry()
    second = LocalTraceTelemetry()
    agent = Agent(
        card=AgentCard(name="multi-traced", description="Multi trace test", url="runtime://multi-traced"),
        llm=create_llm("mock", default_response="complete"),
        telemetry=MultiTelemetry([first, second]),
        verbosity=0,
    )

    result = await agent.handle_task(Task.create_infer(prompt="trace twice"))

    assert result.get_last_part_content() == "complete"
    for telemetry in (first, second):
        records = telemetry.recorder.replay()
        assert len(records) == 1
        assert [span["kind"] for span in records[0]["spans"]] == ["task", "llm"]


@pytest.mark.asyncio
async def test_local_trace_rolls_back_frame_when_task_start_fails():
    fail_redaction = False

    def redactor(value):
        if fail_redaction:
            raise RuntimeError("redaction failed")
        return value

    telemetry = LocalTraceTelemetry(redactor=redactor)
    parent = Task.create_infer(prompt="parent")
    child = Task.create_infer(prompt="child")
    await telemetry.on_task_start(parent, "parent")

    fail_redaction = True
    with pytest.raises(RuntimeError, match="redaction failed"):
        await telemetry.on_task_start(child, "child")
    fail_redaction = False
    child.complete("unused")
    with pytest.raises(RuntimeError, match=rf"`{child.id}`.*`{parent.id}` is active"):
        await telemetry.on_task_end(child, child, "child")

    await telemetry.on_llm_start("parent continues")
    await telemetry.on_llm_end(Part.infer_output(content="done"))
    parent.complete("done")
    await telemetry.on_task_end(parent, parent, "parent")

    records = telemetry.recorder.replay()
    assert [record["task_id"] for record in records] == [parent.id]
    assert [span["kind"] for span in records[0]["spans"]] == ["task", "llm"]


@pytest.mark.asyncio
async def test_local_trace_pops_frame_when_recorder_fails():
    class FailOnceRecorder(LocalTraceRecorder):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def record(self, trace) -> None:
            if self.fail:
                self.fail = False
                raise RuntimeError("recorder failed")
            super().record(trace)

    recorder = FailOnceRecorder()
    telemetry = LocalTraceTelemetry(recorder=recorder)
    failed = Task.create_infer(prompt="first")
    await telemetry.on_task_start(failed, "first")
    failed.complete("first")
    with pytest.raises(RuntimeError, match="recorder failed"):
        await telemetry.on_task_end(failed, failed, "first")

    recovered = Task.create_infer(prompt="second")
    await telemetry.on_task_start(recovered, "second")
    recovered.complete("second")
    await telemetry.on_task_end(recovered, recovered, "second")

    records = recorder.replay()
    assert [record["task_id"] for record in records] == [recovered.id]
    assert [span["kind"] for span in records[0]["spans"]] == ["task"]


@pytest.mark.asyncio
async def test_runtime_agent_delegation_records_parent_and_child_traces():
    telemetry = LocalTraceTelemetry()
    registry = Registry(
        transport="runtime",
        url="runtime://local-trace-nested/registry",
        verbosity=0,
    )
    child = Agent(
        card=AgentCard(
            name="trace_child",
            description="Nested trace child",
            url="runtime://local-trace-nested/child",
            capabilities={"delegation": False, "has_llm": True},
        ),
        transport="runtime",
        registry=registry,
        llm=create_llm("mock", default_response="child result"),
        telemetry=telemetry,
        verbosity=0,
    )
    parent = Agent(
        card=AgentCard(
            name="trace_parent",
            description="Nested trace parent",
            url="runtime://local-trace-nested/parent",
            capabilities={"delegation": True, "has_llm": True},
        ),
        transport="runtime",
        registry=registry,
        llm=create_llm(
            "mock",
            sequential_responses=[
                {
                    "type": "agent_call",
                    "agent": "trace_child",
                    "action": "infer",
                    "prompt": "answer the parent",
                },
                {"type": "final", "content": "parent result"},
            ],
        ),
        telemetry=telemetry,
        verbosity=0,
    )

    registry.start(background=True)
    child.start(background=True)
    parent.start(background=True)
    try:
        result = await parent.handle_task(Task.create_infer(prompt="delegate"))
    finally:
        parent.stop()
        child.stop()
        registry.stop()

    assert result.get_last_part_content() == "parent result"
    records = telemetry.recorder.replay()
    assert [record["agent_name"] for record in records] == ["trace_child", "trace_parent"]
    assert records[0]["trace_id"] == records[1]["trace_id"]
    parent_trace = records[-1]
    assert {"agent_call_start", "agent_call_result"} <= {event["type"] for event in parent_trace["events"]}
    agent_span = next(span for span in parent_trace["spans"] if span["kind"] == "agent_call")
    assert agent_span["status"] == "ok"
    assert agent_span["ended_at"] is not None
