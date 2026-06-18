from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, Field

from protolink.agents import Agent
from protolink.models import AgentCard, Part
from protolink.tools import Tool


class Address(BaseModel):
    city: str
    zip_code: int


class BookingRequest(BaseModel):
    address: Address
    nights: int = Field(gt=0)
    amenities: list[str] = []


async def make_booking(booking: BookingRequest, guests: int = 1) -> dict[str, Any]:
    assert isinstance(booking, BookingRequest)
    return {
        "city": booking.address.city,
        "zip_code": booking.address.zip_code,
        "nights": booking.nights,
        "guests": guests,
    }


@pytest.mark.asyncio
async def test_tool_infers_full_json_schema_and_coerces_pydantic_args():
    tool = Tool(
        name="make_booking",
        description="Make a booking",
        input_schema=None,
        output_schema=None,
        tags=[],
        func=make_booking,
    )

    booking_schema = tool.input_schema["properties"]["booking"]
    assert tool.input_schema["type"] == "object"
    assert "booking" in tool.input_schema["required"]
    assert booking_schema["type"] == "object"
    assert booking_schema["properties"]["address"]["properties"]["zip_code"]["type"] == "integer"
    assert tool.output_schema["type"] == "object"

    result = await tool(
        booking={
            "address": {"city": "Athens", "zip_code": "10557"},
            "nights": "2",
            "amenities": ["wifi"],
        },
        guests="3",
    )

    assert result == {"city": "Athens", "zip_code": 10557, "nights": 2, "guests": 3}


@pytest.mark.asyncio
async def test_tool_validates_nested_explicit_json_schema():
    async def search(filters: dict[str, Any]) -> dict[str, Any]:
        return {"filters": filters}

    tool = Tool(
        name="search",
        description="Search with nested filters",
        input_schema={
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tags"],
                    "additionalProperties": False,
                }
            },
            "required": ["filters"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "additionalProperties": True},
        tags=[],
        func=search,
    )

    assert await tool(filters={"tags": ["docs"], "limit": "5"}) == {"filters": {"tags": ["docs"], "limit": 5}}

    with pytest.raises(ValueError, match="unexpected field"):
        await tool(filters={"tags": ["docs"], "unknown": True})


@pytest.mark.asyncio
async def test_agent_validates_custom_base_tool_args_from_schema():
    class CounterTool:
        name = "count"
        description = "Count things"
        input_schema: ClassVar[dict[str, Any]] = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        }
        output_schema: ClassVar[dict[str, Any]] = {"type": "integer"}
        tags: ClassVar[list[str]] = []

        async def __call__(self, **kwargs):
            return kwargs["count"]

    agent = Agent(AgentCard(name="counter", description="Counter", url="runtime://counter"))
    agent.add_tool(CounterTool())

    result = await agent.execute_tool(Part.tool_call(tool_name="count", args={"count": "4"}))

    assert result.as_tool_output().result == 4

    failed = await agent.execute_tool(Part.tool_call(tool_name="count", args={"count": "not-a-number"}))
    assert "must be an integer" in failed.as_tool_output().error["message"]


def test_tool_examples_are_published_as_agent_skill_examples():
    agent = Agent(AgentCard(name="example-agent", description="Example", url="runtime://example"))

    @agent.tool(
        name="echo",
        description="Echo text",
        examples=[{"text": "hello"}],
    )
    def echo(text: str) -> str:
        return text

    skill = next(skill for skill in agent.card.skills if skill.id == "echo")
    assert skill.examples == [{"text": "hello"}]
    assert skill.input_schema["properties"]["text"]["type"] == "string"
