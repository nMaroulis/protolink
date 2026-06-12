import json
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from protolink.core.part import ToolOutput
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
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
