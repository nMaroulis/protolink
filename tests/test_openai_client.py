from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from protolink.llms.actions import ToolCallAction
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.history import ConversationHistory
from protolink.llms.tool_calling import AGENT_INFER_TOOL_NAME, AGENT_TOOL_CALL_TOOL_NAME


class DummyTool:
    name = "lookup"
    description = "Look up a value."
    input_schema: ClassVar[dict] = {"key": {"type": "string", "required": True}}
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


def test_openai_call_action_uses_responses_tools_not_response_format():
    llm = OpenAILLM.__new__(OpenAILLM)
    llm.model = "gpt-test"
    llm._model_params = {}
    llm.history = ConversationHistory()
    llm.system_prompt = ""
    llm._client = MagicMock()

    function_call = MagicMock()
    function_call.type = "function_call"
    function_call.name = "lookup"
    function_call.arguments = '{"key": "alpha"}'
    function_call.call_id = "call_123"

    response = MagicMock()
    response.output = [function_call]
    llm._client.responses.create.return_value = response

    history = ConversationHistory()
    history.add_user("Find alpha")
    result = llm.call_action(history, tools={"lookup": DummyTool()}, agent_callback_available=True)

    kwargs = llm._client.responses.create.call_args.kwargs
    tool_names = {tool["name"] for tool in kwargs["tools"]}
    assert "response_format" not in kwargs
    assert tool_names == {"lookup"}
    assert AGENT_INFER_TOOL_NAME not in tool_names
    assert AGENT_TOOL_CALL_TOOL_NAME not in tool_names
    assert kwargs["parallel_tool_calls"] is False
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert result.metadata["call_id"] == "call_123"


@pytest.mark.asyncio
async def test_openai_call_action_stream_collects_function_argument_deltas():
    llm = OpenAILLM.__new__(OpenAILLM)
    llm.model = "gpt-test"
    llm._model_params = {}
    llm.history = ConversationHistory()
    llm.system_prompt = ""
    llm._client = MagicMock()
    llm._client.responses.create.return_value = [
        SimpleNamespace(type="response.function_call_arguments.delta", delta='{"key":'),
        SimpleNamespace(type="response.function_call_arguments.delta", delta='"alpha"}'),
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(type="function_call", name="lookup", call_id="call_stream"),
        ),
    ]

    history = ConversationHistory()
    history.add_user("Find alpha")
    result = await llm.call_action_stream(history, tools={"lookup": DummyTool()}, agent_callback_available=False)

    kwargs = llm._client.responses.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["parallel_tool_calls"] is False
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert result.metadata["call_id"] == "call_stream"
    assert result.metadata["streaming"] is True
