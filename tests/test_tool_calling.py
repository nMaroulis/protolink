import json
from typing import ClassVar

import pytest

from protolink.llms.actions import AgentCallAction, ToolCallAction
from protolink.llms.tool_calling import (
    AGENT_INFER_TOOL_NAME,
    AGENT_TOOL_CALL_TOOL_NAME,
    ChatCompletionStreamAccumulator,
    build_runtime_tool_schemas,
    chat_completion_stream_delta,
    native_tool_call_to_action,
    normalize_tool_parameters,
    should_include_agent_tools,
)


class DummyTool:
    name = "book"
    description = "Book something."
    input_schema: ClassVar[dict] = {
        "location": {"type": "string", "required": True},
        "guests": {"type": "integer", "required": False, "default": 2},
    }
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


def test_normalize_flat_tool_schema_to_json_schema_object():
    schema = normalize_tool_parameters(DummyTool.input_schema)

    assert schema == {
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "guests": {"type": "integer", "default": 2},
        },
        "required": ["location"],
        "additionalProperties": False,
    }


def test_build_runtime_tool_schemas_includes_agent_synthetic_tools():
    schemas = build_runtime_tool_schemas({"book": DummyTool()}, include_agent_tools=True)

    assert "book" in schemas
    assert AGENT_INFER_TOOL_NAME in schemas
    assert AGENT_TOOL_CALL_TOOL_NAME in schemas
    assert schemas[AGENT_TOOL_CALL_TOOL_NAME]["properties"]["args_json"]["type"] == "string"


def test_agent_tool_exposure_requires_callback_and_discovered_agents():
    assert should_include_agent_tools(agent_callback_available=False, agent_cards=[object()]) is False
    assert should_include_agent_tools(agent_callback_available=True, agent_cards=None) is False
    assert should_include_agent_tools(agent_callback_available=True, agent_cards=[]) is False
    assert should_include_agent_tools(agent_callback_available=True, agent_cards=[object()]) is True


def test_native_tool_call_to_local_tool_action():
    action = native_tool_call_to_action("book", {"location": "Athens"})

    assert isinstance(action, ToolCallAction)
    assert action.tool == "book"
    assert action.args == {"location": "Athens"}


def test_native_tool_call_to_agent_actions():
    infer = native_tool_call_to_action(AGENT_INFER_TOOL_NAME, {"agent": "planner", "prompt": "plan"})
    assert isinstance(infer, AgentCallAction)
    assert infer.action == "infer"
    assert infer.prompt == "plan"

    tool = native_tool_call_to_action(
        AGENT_TOOL_CALL_TOOL_NAME,
        {"agent": "booking", "tool": "book", "args_json": json.dumps({"city": "Athens"})},
    )
    assert isinstance(tool, AgentCallAction)
    assert tool.action == "tool_call"
    assert tool.args == {"city": "Athens"}


def test_native_agent_tool_call_rejects_non_object_args_json():
    with pytest.raises(ValueError):
        native_tool_call_to_action(AGENT_TOOL_CALL_TOOL_NAME, {"agent": "a", "tool": "t", "args_json": "[]"})


def test_native_tool_call_rejects_missing_name():
    with pytest.raises(ValueError, match="missing a function/tool name"):
        native_tool_call_to_action("", {})


def test_chat_completion_stream_helpers_collect_tool_call_deltas():
    event = {
        "choices": [
            {
                "delta": {
                    "content": "Thinking",
                    "tool_calls": [
                        {"function": {"name": "book", "arguments": '{"location":'}},
                        {"function": {"arguments": '"Athens"}'}},
                    ],
                }
            }
        ]
    }

    text, deltas = chat_completion_stream_delta(event)
    accumulator = ChatCompletionStreamAccumulator()
    for delta in deltas:
        accumulator.add_delta(delta)

    assert text == "Thinking"
    action = accumulator.to_action()
    assert isinstance(action, ToolCallAction)
    assert action.tool == "book"
    assert action.args == {"location": "Athens"}
