"""Tests for Part serialization and content accessors."""

import pytest

from protolink.agents import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.part import Part, ToolCall, ToolOutput
from protolink.tools import BaseTool


def test_tool_call_roundtrip():
    original = Part.tool_call(tool_name="add", args={"a": 1, "b": 2}, call_id="call_abc")
    restored = Part.from_dict(original.to_dict())
    tc = restored.as_tool_call()
    assert isinstance(tc, ToolCall)
    assert tc.tool_name == "add"
    assert tc.args == {"a": 1, "b": 2}
    assert tc.call_id == "call_abc"


def test_tool_output_roundtrip():
    original = Part.tool_output(call_id="call_abc", result=42)
    restored = Part.from_dict(original.to_dict())
    out = restored.as_tool_output()
    assert isinstance(out, ToolOutput)
    assert out.call_id == "call_abc"
    assert out.result == 42


def test_from_dict_hydrates_tool_call():
    data = {"type": "tool_call", "content": {"tool_name": "echo", "args": {"msg": "hi"}, "call_id": "x1"}}
    part = Part.from_dict(data)
    assert isinstance(part.content, ToolCall)
    assert part.as_tool_call().tool_name == "echo"


def test_from_dict_hydrates_tool_output():
    data = {"type": "tool_output", "content": {"call_id": "x1", "result": 42}}
    part = Part.from_dict(data)
    assert isinstance(part.content, ToolOutput)
    assert part.as_tool_output().result == 42


def test_as_tool_call_wrong_type_raises():
    with pytest.raises(ValueError, match="tool_call"):
        Part.text("hello").as_tool_call()


@pytest.mark.asyncio
async def test_execute_tool_with_deserialized_part():
    """Simulates network path: tool_call arrives as dict via from_dict."""

    class EchoTool(BaseTool):
        name = "echo"
        description = "echo"
        input_schema = {}
        output_schema = {}
        tags: list[str] = []

        async def __call__(self, **kwargs):
            return kwargs.get("msg", "")

    card = AgentCard(name="t", description="t", url="http://t.local")
    agent = Agent(card, transport="runtime")
    agent.tools["echo"] = EchoTool()

    raw = {"type": "tool_call", "content": {"tool_name": "echo", "args": {"msg": "ping"}, "call_id": "c1"}}
    part = Part.from_dict(raw)
    result = await agent.execute_tool(part)

    assert result.type == "tool_output"
    assert result.as_tool_output().result == "ping"
    assert result.as_tool_output().call_id == "c1"

