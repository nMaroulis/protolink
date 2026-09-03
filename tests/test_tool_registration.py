"""Public tool registration keeps Python ergonomics and runtime controls aligned."""

import inspect
from typing import Annotated, Any

import pytest
from pydantic import Field

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    CapabilityPolicy,
    RunAction,
    RunContext,
    Task,
    TaskState,
    Tool,
    create_knowledge,
)


@pytest.fixture
def agent() -> Agent:
    return Agent(AgentCard(name="tools", description="Tool registration", url="runtime://tools"), verbosity=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("parentheses", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_minimal_decorators_preserve_callable_and_infer_metadata(agent, parentheses, asynchronous):
    if asynchronous:

        async def add(left: int, right: int = 1) -> int:
            """Add two integers.

            Uses one for the second operand when omitted.
            """
            return left + right

    else:

        def add(left: int, right: int = 1) -> int:
            """Add two integers.

            Uses one for the second operand when omitted.
            """
            return left + right

    original = add
    decorator = agent.tool() if parentheses else agent.tool
    registered = decorator(add)

    assert registered is original
    assert inspect.signature(registered) == inspect.signature(original)
    assert inspect.iscoroutinefunction(registered) is asynchronous
    assert agent.tools["add"].description == ("Add two integers.\n\nUses one for the second operand when omitted.")
    assert agent.tools["add"].input_schema["properties"]["left"]["type"] == "integer"
    assert agent.tools["add"].input_schema["required"] == ["left"]
    assert agent.tools["add"].output_schema["type"] == "integer"
    assert await agent.call_tool("add", left="2") == 3
    with pytest.raises(ValueError, match="must be an integer"):
        await agent.call_tool("add", left="invalid")


def test_keyword_metadata_overrides_inference_and_updates_skill(agent):
    @agent.tool(name="public_echo", description="Public purpose", tags=["text"], examples=[{"text": "hello"}])
    def echo(text: str) -> str:
        """An implementation-specific description."""
        return text

    tool = agent.tools["public_echo"]
    skill = next(skill for skill in agent.card.skills if skill.id == "public_echo")

    assert tool.func is echo
    assert tool.description == skill.description == "Public purpose"
    assert skill.tags == ["text"]
    assert skill.examples == [{"text": "hello"}]
    assert skill.input_schema["properties"]["text"]["type"] == "string"


def test_missing_docstring_has_useful_default(agent):
    @agent.tool
    def ping() -> str:
        return "pong"

    @agent.tool(name="health")
    def check() -> bool:
        return True

    assert agent.tools["ping"].description == "Call ping."
    assert agent.tools["health"].description == "Call health."


@pytest.mark.asyncio
async def test_legacy_positional_metadata_keeps_schema_and_policy_behavior(agent):
    prepared: list[dict[str, Any]] = []
    executed: list[int] = []

    def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
        prepared.append(arguments)
        return RunAction(kind="tool.call", name="save", payload={"arguments": arguments})

    input_schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    output_schema = {"type": "integer", "description": "Saved record count"}

    @agent.tool(
        "save", "Save records", input_schema, output_schema, ["records"], [{"count": 2}], ["records.write"], prepare
    )
    def save(count: int) -> int:
        executed.append(count)
        return count

    context = RunContext(permissions={"capabilities": {"records.write": "deny"}})
    with pytest.raises(ActionDeniedError):
        await agent.call_tool_in_context("save", context, count="2")

    assert prepared == [{"count": 2}]
    assert executed == []
    assert agent.tools["save"].input_schema["additionalProperties"] is False
    assert agent.tools["save"].output_schema["description"] == "Saved record count"
    assert agent.tools["save"].action_builder is prepare
    assert agent.tools["save"].capabilities == ("records.write",)
    assert await agent.call_tool("save", count="3") == 3
    assert executed == [3]


@pytest.mark.asyncio
async def test_from_callable_is_reusable_with_inferred_schemas_and_explicit_policy(agent):
    def double(value: int) -> int:
        """Double an integer."""
        return value * 2

    tool = Tool.from_callable(double, capabilities={"numbers.calculate"})
    agent.add_tool(tool)
    restricted = Agent(
        AgentCard(name="restricted", description="Restricted tools", url="runtime://restricted"),
        policy=CapabilityPolicy({"numbers.calculate": "deny"}),
        verbosity=0,
    )
    restricted.add_tool(tool)

    assert agent.tools["double"] is tool
    assert restricted.tools["double"] is tool
    assert tool.func is double
    assert tool.name == "double"
    assert tool.description == "Double an integer."
    assert tool.input_schema["properties"]["value"]["type"] == "integer"
    assert tool.output_schema["type"] == "integer"
    assert await agent.call_tool("double", value="4") == 8
    with pytest.raises(ActionDeniedError):
        await restricted.call_tool("double", value=4)


def test_from_callable_rejects_non_callable():
    with pytest.raises(TypeError, match="requires a callable"):
        Tool.from_callable("not a function")


@pytest.mark.parametrize(
    ("name", "error"),
    [("", ValueError), (" \t\n", ValueError), (42, TypeError)],
)
def test_from_callable_rejects_invalid_name_before_registration(agent, name, error):
    def ping() -> str:
        return "pong"

    with pytest.raises(error, match="Tool name"):
        agent.add_tool(Tool.from_callable(ping, name=name))

    assert agent.tools == {}


@pytest.mark.asyncio
async def test_from_callable_accepts_dotted_names_and_callable_instances(agent):
    class Increment:
        """Increment an integer."""

        def __call__(self, value: Annotated[int, Field(gt=0)]) -> int:
            return value + 1

    function = Increment()
    inferred = Tool.from_callable(function)
    dotted = Tool.from_callable(function, name="math.increment")
    agent.add_tool(inferred)
    agent.add_tool(dotted)

    assert inferred.func is function
    assert inferred.name == "Increment"
    assert inferred.description == "Increment an integer."
    assert inferred.output_schema["type"] == "integer"
    assert dotted.name == "math.increment"
    assert await agent.call_tool("Increment", value="2") == 3
    assert await agent.call_tool("math.increment", value="4") == 5
    with pytest.raises(ValueError, match="greater than 0"):
        await agent.call_tool("Increment", value=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_add_tool_wraps_functions_without_executing_them(agent, asynchronous):
    calls: list[int] = []
    if asynchronous:

        async def double(value: int) -> int:
            """Double an integer."""
            calls.append(value)
            return value * 2

    else:

        def double(value: int) -> int:
            """Double an integer."""
            calls.append(value)
            return value * 2

    assert agent.add_tool(double) is None
    tool = agent.tools["double"]
    assert isinstance(tool, Tool)
    assert tool.func is double
    assert tool.description == "Double an integer."
    assert tool.input_schema["properties"]["value"]["type"] == "integer"
    assert tool.output_schema["type"] == "integer"
    assert calls == []

    with pytest.raises(ValueError, match="must be an integer"):
        await agent.call_tool("double", value="invalid")
    assert calls == []
    assert await agent.call_tool("double", value="3") == 6
    result = await agent.run_task(Task.create_tool_call(tool_name="double", args={"value": "4"}))
    assert result.state is TaskState.COMPLETED
    assert result.get_last_part_content().result == 8
    assert calls == [3, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_method", [False, True])
async def test_add_tool_accepts_callable_instances_and_bound_methods(agent, bound_method):
    class Increment:
        """Increment an integer."""

        name = "unrelated application attribute"

        async def increment(self, value: Annotated[int, Field(gt=0)]) -> int:
            """Increment a positive integer."""
            return value + 1

        __call__ = increment

    instance = Increment()
    function = instance.increment if bound_method else instance
    name = "increment" if bound_method else "Increment"
    agent.add_tool(function)

    assert agent.tools[name].func is function
    assert agent.tools[name].output_schema["type"] == "integer"
    assert await agent.call_tool(name, value="2") == 3
    with pytest.raises(ValueError, match="greater than 0"):
        await agent.call_tool(name, value=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("function_wrapper", [False, True])
async def test_add_tool_preserves_legacy_structural_tools_and_metadata_functions(agent, function_wrapper):
    async def execute(value: int) -> int:
        return value + 1

    class CustomTool:
        async def __call__(self, value: int) -> int:
            return await execute(value)

    tool = execute if function_wrapper else CustomTool()
    metadata = {
        "name": "custom_increment",
        "description": "Existing tool metadata",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "integer"},
        "tags": ["custom"],
    }
    for name, value in metadata.items():
        setattr(tool, name, value)
    # Legacy tools and metadata-bearing functions may omit these optional fields.
    assert not hasattr(tool, "examples")
    assert not hasattr(tool, "capabilities")
    agent.add_tool(tool)

    assert agent.tools["custom_increment"] is tool
    skill = next(skill for skill in agent.card.skills if skill.id == "custom_increment")
    assert skill.description == metadata["description"]
    assert skill.input_schema == metadata["input_schema"]
    assert skill.tags == ["custom"]
    assert await agent.call_tool("custom_increment", value="2") == 3

    tool.capabilities = ("numbers.calculate",)
    context = RunContext(permissions={"capabilities": {"numbers.calculate": "deny"}})
    with pytest.raises(ActionDeniedError):
        await agent.call_tool_in_context("custom_increment", context, value=2)


def test_add_tool_callable_replaces_existing_tool_and_updates_one_skill(agent):
    def previous(value: str) -> str:
        return value

    agent.add_tool(Tool.from_callable(previous, name="double", description="Old description"))

    def double(value: int) -> int:
        """Double an integer."""
        return value * 2

    agent.add_tool(double)
    agent.add_tool(double)

    assert agent.tools["double"].func is double
    skills = [skill for skill in agent.card.skills if skill.id == "double"]
    assert len(skills) == 1
    assert skills[0].description == "Double an integer."
    assert skills[0].input_schema["properties"]["value"]["type"] == "integer"


def test_add_tool_callable_cannot_replace_knowledge_tool(agent):
    agent.add_knowledge(create_knowledge("memory"))
    original = agent.tools["search_knowledge"]
    skills = list(agent.card.skills)

    def search_knowledge(query: str) -> str:
        return query

    with pytest.raises(ValueError, match="cannot be replaced"):
        agent.add_tool(search_knowledge)

    assert agent.tools["search_knowledge"] is original
    assert agent.card.skills == skills


@pytest.mark.parametrize("invalid", [None, "not a callable", 42, {}, object()])
def test_add_tool_rejects_noncallables_without_mutation(agent, invalid):
    skills = list(agent.card.skills)
    with pytest.raises(TypeError, match="tool instance or a Python callable"):
        agent.add_tool(invalid)
    assert agent.tools == {}
    assert agent.card.skills == skills


def test_add_tool_callable_inference_failure_keeps_previous_registration(agent):
    def double(value: int) -> int:
        return value * 2

    agent.add_tool(double)
    original = agent.tools["double"]
    skills = list(agent.card.skills)
    double.__signature__ = object()

    with pytest.raises(TypeError, match="__signature__"):
        agent.add_tool(double)

    assert agent.tools["double"] is original
    assert agent.card.skills == skills
