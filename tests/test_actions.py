import pytest
from pydantic import TypeAdapter, ValidationError

from protolink.llms.actions import (
    AgentCallAction,
    FinalAction,
    LLMAction,
    ToolCallAction,
    inline_refs,
    prompt_action_schema,
)


def test_final_action():
    # Valid
    action = FinalAction(content="hello")
    assert action.type == "final"
    assert action.content == "hello"
    assert action.thought is None

    # Invalid - missing content
    with pytest.raises(ValidationError):
        FinalAction()


def test_tool_call_action():
    # Valid
    action = ToolCallAction(tool="my_tool", args={"x": 1})
    assert action.type == "tool_call"
    assert action.tool == "my_tool"
    assert action.args == {"x": 1}

    # Valid - empty args by default
    action_default = ToolCallAction(tool="my_tool")
    assert action_default.args == {}

    # Invalid - missing tool
    with pytest.raises(ValidationError):
        ToolCallAction()


def test_agent_call_action_infer():
    # Valid
    action = AgentCallAction(agent="my_agent", action="infer", prompt="solve this")
    assert action.type == "agent_call"
    assert action.agent == "my_agent"
    assert action.action == "infer"
    assert action.prompt == "solve this"

    # Invalid - missing prompt
    with pytest.raises(ValidationError):
        AgentCallAction(agent="my_agent", action="infer")


def test_agent_call_action_tool_call():
    # Valid
    action = AgentCallAction(agent="my_agent", action="tool_call", tool="his_tool", args={"y": 2})
    assert action.type == "agent_call"
    assert action.agent == "my_agent"
    assert action.action == "tool_call"
    assert action.tool == "his_tool"
    assert action.args == {"y": 2}

    # Invalid - missing tool name
    with pytest.raises(ValidationError):
        AgentCallAction(agent="my_agent", action="tool_call", args={"y": 2})


def test_llm_action_union_parsing():
    adapter = TypeAdapter(LLMAction)

    # Parse final
    obj = adapter.validate_python({"type": "final", "content": "finished"})
    assert isinstance(obj, FinalAction)
    assert obj.content == "finished"

    # Parse tool call
    obj = adapter.validate_python({"type": "tool_call", "tool": "calc", "args": {"val": 10}})
    assert isinstance(obj, ToolCallAction)
    assert obj.tool == "calc"
    assert obj.args == {"val": 10}

    # Parse agent call
    obj = adapter.validate_python(
        {
            "type": "agent_call",
            "agent": "subagent",
            "action": "infer",
            "prompt": "do it",
        }
    )
    assert isinstance(obj, AgentCallAction)
    assert obj.agent == "subagent"
    assert obj.prompt == "do it"

    # Invalid type
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "unknown_type"})

    # Invalid extra fields: the runtime contract must not silently drop model mistakes.
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "tool_call", "tool": "calc", "arguments": {"val": 10}})


def test_inline_refs():
    schema = {
        "$defs": {"Sub": {"type": "object", "properties": {"val": {"type": "integer"}}}},
        "type": "object",
        "properties": {"item": {"$ref": "#/$defs/Sub"}},
    }
    inlined = inline_refs(schema)
    assert "$defs" not in inlined
    assert inlined["properties"]["item"] == {"type": "object", "properties": {"val": {"type": "integer"}}}


def test_prompt_action_schema_is_root_object():
    schema = prompt_action_schema()

    assert schema["type"] == "object"
    assert "oneOf" not in schema
    assert schema["additionalProperties"] is False
    assert schema["properties"]["args"]["anyOf"][0]["additionalProperties"] is True
