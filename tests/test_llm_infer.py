import json
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from protolink.core.part import ToolOutput
from protolink.llms.actions import FinalAction, LLMActionResult, ToolCallAction, action_to_json
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.models import AgentCard, AgentSkill
from protolink.tools.base import BaseTool


class MockLLM(LLM):
    model_type = "mock"
    provider = "mock"
    model = "mock-model"
    model_params: ClassVar[dict] = {}

    def __init__(self, responses: list[str]):
        super().__init__(model="mock-model", model_params={})
        self.responses = responses
        self.call_count = 0

    def call(self, history: ConversationHistory) -> str:
        if self.call_count >= len(self.responses):
            return json.dumps({"type": "final", "content": "No more responses"})
        response = self.responses[self.call_count]
        self.call_count += 1
        return response

    async def call_stream(self, history: ConversationHistory):
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


class MockTool(BaseTool):
    def __init__(self, name="test_tool"):
        self.name = name
        self.description = "Test tool"
        self.input_schema = {"type": "object", "properties": {"input": {"type": "string"}}}
        self.output_schema = {"type": "string"}
        self.tags = []
        self.mock_call = AsyncMock(return_value="tool_result")

    async def __call__(self, **kwargs):
        return await self.mock_call(**kwargs)


class NativeActionMockLLM(LLM):
    model_type = "mock"
    provider = "mock-native"

    def __init__(self, actions):
        super().__init__(model="mock-model", model_params={})
        self.actions = actions
        self.call_count = 0

    def call(self, history: ConversationHistory) -> str:
        raise AssertionError("native action path should not call text fallback")

    async def call_stream(self, history: ConversationHistory):
        yield ""

    @property
    def uses_native_action_prompt(self) -> bool:
        return True

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available=False,
        agent_cards=None,
    ):
        action = self.actions[self.call_count]
        self.call_count += 1
        return LLMActionResult(action=action, raw_response=action_to_json(action), native=True)

    def validate_connection(self) -> bool:
        return True


class NativeStreamingActionMockLLM(NativeActionMockLLM):
    @property
    def supports_native_action_stream(self) -> bool:
        return True

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available=False,
        agent_cards=None,
        chunk_callback=None,
    ):
        action = self.actions[self.call_count]
        self.call_count += 1
        if isinstance(action, FinalAction) and chunk_callback is not None:
            await chunk_callback(action.content)
        return LLMActionResult(
            action=action,
            raw_response=action_to_json(action),
            native=True,
            metadata={"streaming": True},
        )


def test_default_prompt_uses_simple_json_action_contract():
    llm = MockLLM([])
    prompt = llm.build_system_prompt(
        tools="Tool: test_tool",
        agent_cards="Agent 1: helper",
    )

    assert "Output Schema Requirements" in prompt
    assert "The response MUST be a single valid JSON object" in prompt
    assert '"type": "tool_call"' in prompt
    assert "provider tool interface" not in prompt


def test_native_prompt_uses_provider_tool_contract_without_json_actions():
    llm = NativeActionMockLLM([])
    prompt = llm.build_system_prompt(
        tools="Tool: test_tool",
        agent_cards="Agent 1: helper",
    )

    assert "provider tool interface" in prompt
    assert "Available agents:" in prompt
    assert "Output Schema Requirements" not in prompt
    assert "The response MUST be a single valid JSON object" not in prompt
    assert '"type": "tool_call"' not in prompt


def test_native_prompt_can_be_forced_to_json_for_streaming_parser():
    llm = NativeActionMockLLM([])
    prompt = llm.build_system_prompt(
        tools="Tool: test_tool",
        agent_cards="Agent 1: helper",
        action_mode="json",
    )

    assert "Output Schema Requirements" in prompt
    assert "The response MUST be a single valid JSON object" in prompt
    assert "provider tool interface" not in prompt


@pytest.mark.asyncio
async def test_infer_final_success():
    responses = [json.dumps({"thought": "I am done", "type": "final", "content": "Hello world"})]
    llm = MockLLM(responses)
    result = await llm.infer(query="Hi", tools={})

    assert result.type == "infer_output"
    assert result.content == "Hello world"
    assert llm.call_count == 1


@pytest.mark.asyncio
async def test_infer_tool_call_loop():
    responses = [
        json.dumps(
            {"thought": "I need a tool", "type": "tool_call", "tool": "test_tool", "args": {"input": "test_val"}}
        ),
        json.dumps({"thought": "Got the result", "type": "final", "content": "Finished with tool"}),
    ]
    llm = MockLLM(responses)
    tool = MockTool()

    result = await llm.infer(query="Use tool", tools={"test_tool": tool})

    assert result.content == "Finished with tool"
    assert llm.call_count == 2
    tool.mock_call.assert_awaited_once_with(input="test_val")


@pytest.mark.asyncio
async def test_infer_native_action_path_dispatches_without_prompt_parsing():
    llm = NativeActionMockLLM(
        [
            ToolCallAction(tool="test_tool", args={"input": "native_val"}),
            FinalAction(content="Finished natively"),
        ]
    )
    tool = MockTool()
    events = []

    async def capture(event):
        events.append(event)

    result = await llm.infer(
        query="Use native tool",
        tools={"test_tool": tool},
        event_callback=capture,
    )

    assert result.content == "Finished natively"
    assert llm.call_count == 2
    tool.mock_call.assert_awaited_once_with(input="native_val")
    assert any(event["type"] == "llm_response" and event["native"] is True for event in events)


@pytest.mark.asyncio
async def test_infer_native_streaming_action_path_dispatches_without_prompt_parsing():
    llm = NativeStreamingActionMockLLM(
        [
            ToolCallAction(tool="test_tool", args={"input": "stream_native_val"}),
            FinalAction(content="Finished through native stream"),
        ]
    )
    tool = MockTool()
    events = []

    async def capture(event):
        events.append(event)

    result = await llm.infer(
        query="Use native streaming tool",
        tools={"test_tool": tool},
        streaming=True,
        event_callback=capture,
    )

    assert result.content == "Finished through native stream"
    assert llm.call_count == 2
    tool.mock_call.assert_awaited_once_with(input="stream_native_val")
    assert any(
        event["type"] == "llm_chunk" and event["content"] == "Finished through native stream" for event in events
    )
    assert all("Invalid JSON" not in str(message["content"]) for message in llm.history.messages)


@pytest.mark.asyncio
async def test_infer_agent_call_loop():
    payload = {
        "thought": "Ask someone else",
        "type": "agent_call",
        "agent": "other_agent",
        "action": "infer",
        "prompt": "delegated prompt",
    }
    responses = [
        json.dumps(payload),
        json.dumps({"thought": "Agent replied", "type": "final", "content": "Finished with agent"}),
    ]
    llm = MockLLM(responses)
    agent_callback = AsyncMock(return_value="agent_result")

    result = await llm.infer(query="Ask agent", tools={}, agent_callback=agent_callback)

    assert result.content == "Finished with agent"
    assert llm.call_count == 2
    # The callback receives the entire payload
    agent_callback.assert_awaited_once_with("other_agent", "infer", payload)


@pytest.mark.asyncio
async def test_infer_agent_call_serializes_tool_output_result():
    payload = {
        "thought": "Ask a tool-owning agent",
        "type": "agent_call",
        "agent": "hotel_agent",
        "action": "tool_call",
        "tool": "book_hotel",
        "args": {"location": "Santorini"},
    }
    responses = [
        json.dumps(payload),
        json.dumps({"thought": "Hotel booked", "type": "final", "content": "Finished with agent tool"}),
    ]
    llm = MockLLM(responses)
    agent_callback = AsyncMock(
        return_value=ToolOutput(
            call_id="call_hotel",
            result={"status": "confirmed", "booking_id": "HTL-123"},
        )
    )

    result = await llm.infer(query="Book a hotel", tools={}, agent_callback=agent_callback)

    assert result.content == "Finished with agent tool"
    agent_result_message = next(
        json.loads(message["content"])
        for message in llm.history.messages
        if '"type": "agent_result"' in message["content"]
    )
    assert agent_result_message["result"] == {
        "call_id": "call_hotel",
        "result": {"status": "confirmed", "booking_id": "HTL-123"},
        "error": None,
    }


@pytest.mark.asyncio
async def test_infer_repairs_unambiguous_agent_tool_prompt_shorthand():
    responses = [
        json.dumps({"type": "agent_call", "action": "tool_call", "prompt": "list_directory(path='.')"}),
        json.dumps({"type": "final", "content": "Listed files"}),
    ]
    llm = MockLLM(responses)
    agent_callback = AsyncMock(return_value={"success": True, "entries": ["utils.py"]})
    coder_card = AgentCard(
        name="coder",
        description="File operations",
        url="http://coder",
        skills=[AgentSkill(id="list_directory", description="List files")],
    )

    result = await llm.infer(
        query="Inspect files",
        tools={},
        agent_callback=agent_callback,
        agent_cards=[coder_card],
    )

    assert result.content == "Listed files"
    agent_callback.assert_awaited_once_with(
        "coder",
        "tool_call",
        {
            "type": "agent_call",
            "agent": "coder",
            "action": "tool_call",
            "tool": "list_directory",
            "args": {"path": "."},
        },
    )


@pytest.mark.asyncio
async def test_infer_parsing_error_correction():
    responses = ["NOT JSON", json.dumps({"thought": "Fixed it", "type": "final", "content": "Recovery success"})]
    llm = MockLLM(responses)

    result = await llm.infer(query="Trigger error", tools={})

    assert result.content == "Recovery success"
    assert llm.call_count == 2
    # Verify history length:
    # 1 (initial system) + 1 (user query) + 1 (error feedback system message) + 1 (final assistant response)
    assert len(llm.history) == 4


@pytest.mark.asyncio
async def test_infer_max_iterations():
    # Infinite loop of thoughts without final action
    responses = [json.dumps({"thought": "thinking...", "type": "tool_call", "tool": "none", "args": {}})] * 20
    llm = MockLLM(responses)

    # We need a dummy tool to avoid "tool not found" errors which might stop the loop differently
    tool = MockTool(name="none")

    # The current implementation raises RuntimeError when MAX_INFER_STEPS is reached
    with pytest.raises(RuntimeError) as excinfo:
        await llm.infer(query="Loop", tools={"none": tool})

    assert "Maximum inference steps" in str(excinfo.value)
    assert llm.call_count == 10  # Default MAX_INFER_STEPS


@pytest.mark.asyncio
async def test_infer_validation_error_correction():
    # Test that a validation error (missing 'prompt' on agent_call) triggers self-correction feedback
    responses = [
        # Missing 'prompt' key for an 'infer' agent_call action
        json.dumps({"type": "agent_call", "agent": "helper_agent", "action": "infer"}),
        json.dumps({"type": "final", "content": "Corrected and done"}),
    ]
    llm = MockLLM(responses)
    result = await llm.infer(query="Run", tools={})

    assert result.content == "Corrected and done"
    assert llm.call_count == 2
    # Verify that the self-correction feedback was injected into the history
    assert any("Action validation failed" in msg["content"] for msg in llm.history.messages)


def test_llm_schema_helpers():
    llm = MockLLM([])

    schema = llm.get_action_schema()
    assert "$defs" in schema or "definitions" in schema or "anyOf" in schema

    prompt_schema = llm.get_prompt_action_schema()
    assert prompt_schema["type"] == "object"
    assert "oneOf" not in prompt_schema
    assert prompt_schema["properties"]["args"]["anyOf"][0]["additionalProperties"] is True

    openai_schema = llm.get_openai_action_schema()
    assert openai_schema == prompt_schema

    inlined_schema = llm.get_inlined_action_schema()
    assert "$defs" not in inlined_schema


def test_parse_validation_error_formatting():
    llm = MockLLM([])
    invalid_data = '{"type": "agent_call", "agent": "helper_agent", "action": "infer"}'
    with pytest.raises(ValueError) as excinfo:
        llm._parse_infer_response(invalid_data)

    err_msg = str(excinfo.value)
    assert "Action validation failed. Field-level errors:" in err_msg
    assert "agent_call" in err_msg
    assert "prompt" in err_msg


@pytest.mark.asyncio
async def test_call_with_retry_success():
    llm = MockLLM([])
    call_count = 0

    async def successful_fn(arg):
        nonlocal call_count
        call_count += 1
        return f"success {arg}"

    res = await llm._call_with_retry(successful_fn, "test")
    assert res == "success test"
    assert call_count == 1


@pytest.mark.asyncio
async def test_call_with_retry_transient_failure_then_success(monkeypatch):
    import asyncio

    sleep_calls = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)
        return

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    llm = MockLLM([])
    call_count = 0

    class TransientError(Exception):
        status_code = 429

    async def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TransientError("Rate limit reached")
        return "success"

    res = await llm._call_with_retry(fn, max_retries=3)
    assert res == "success"
    assert call_count == 3
    assert len(sleep_calls) == 2
    # delay for attempt 0: base_delay * 1 = 1.0 (plus jitter up to 0.5)
    # delay for attempt 1: base_delay * 2 = 2.0 (plus jitter up to 1.0)
    assert 1.0 <= sleep_calls[0] <= 1.5
    assert 2.0 <= sleep_calls[1] <= 3.0


@pytest.mark.asyncio
async def test_call_with_retry_non_transient_raises_immediately():
    llm = MockLLM([])
    call_count = 0

    class NonTransientError(Exception):
        status_code = 400

    async def fn():
        nonlocal call_count
        call_count += 1
        raise NonTransientError("Bad Request")

    with pytest.raises(NonTransientError):
        await llm._call_with_retry(fn, max_retries=3)

    assert call_count == 1


def test_is_transient_error():
    llm = MockLLM([])

    # Test status code checking
    class StatusError(Exception):
        def __init__(self, code):
            self.status_code = code

    assert llm._is_transient_error(StatusError(429)) is True
    assert llm._is_transient_error(StatusError(502)) is True
    assert llm._is_transient_error(StatusError(400)) is False

    # Test class name checking
    class RateLimitError(Exception):
        pass

    class OverloadedError(Exception):
        pass

    assert llm._is_transient_error(RateLimitError()) is True
    assert llm._is_transient_error(OverloadedError()) is True

    # Test connection level errors
    assert llm._is_transient_error(TimeoutError("Connection timed out")) is True
    assert llm._is_transient_error(ConnectionResetError("Connection reset")) is True

    # Test message checks
    assert llm._is_transient_error(Exception("Some rate limit happened")) is True
    assert llm._is_transient_error(Exception("API request timed out")) is True
    assert llm._is_transient_error(Exception("Regular error message")) is False
