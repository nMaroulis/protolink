"""Task shortcuts preserve protocol payloads and distinguish inputs from outputs."""

import copy

import pytest

from protolink import (
    Agent,
    AgentCard,
    Artifact,
    Message,
    Part,
    RunBudget,
    RunContext,
    Task,
    TaskExecutionError,
    create_llm,
)


def test_task_factories_preserve_plain_text_and_explicit_parts():
    plain = Task.create("Hello")
    assert plain.messages[0].role == "user"
    assert plain.get_last_part().type == "text"
    assert plain.get_last_part_content() == "Hello"
    assert plain.metadata == {}
    assert plain.get_output("pending") == "pending"

    message = Message.user("Existing message")
    assert Task.create(message).get_last_item() is message
    assert Task.create("").get_last_part_content() == ""
    assert Task.create_infer().get_last_part_content() == {}
    assert Task.create_infer("Hello").get_last_part_content() == {"prompt": "Hello"}
    assert Task.create_infer(prompt="Hello").get_last_part().type == "infer"
    assert isinstance(Task.infer(prompt="Hello"), Part)
    assert isinstance(Task.tool_call(tool_name="add"), Part)


@pytest.mark.parametrize("factory", [Task.create, Task.create_infer, Task.create_tool_call])
def test_factory_controls_copy_and_override_without_changing_input(factory):
    context = RunContext(
        session_id="original",
        trace_id="trace",
        permissions={"files": {"read": True}},
        budget=RunBudget(max_llm_calls=5),
    )
    budget = RunBudget(max_tool_calls=2, metadata={"tags": ["test"]})
    task = factory("input", context=context, session_id="override", budget=budget)
    restored = Task.from_dict(task.to_dict())
    active = RunContext.from_task(restored)
    assert active.session_id == "override"
    assert active.trace_id == "trace"
    assert active.budget.max_tool_calls == 2
    assert active.budget.max_llm_calls is None

    task.metadata["run_context"]["permissions"]["files"]["read"] = False
    task.metadata["run_context"]["budget"]["metadata"]["tags"].append("changed")
    assert context.permissions == {"files": {"read": True}}
    assert context.session_id == "original"
    assert context.budget.max_llm_calls == 5
    assert budget.metadata == {"tags": ["test"]}

    inherited = RunContext.from_task(factory("input", context=context))
    assert inherited.session_id == "original"
    assert inherited.budget.max_llm_calls == 5
    assert RunContext.from_task(factory("input", session_id="standalone")).session_id == "standalone"


def test_factory_controls_do_not_collide_with_operation_arguments():
    schema = {"type": "integer"}
    infer = Task.create_infer("Count", user="account", metadata={"model_hint": "fast"}, output_schema=schema)
    assert infer.metadata == {}
    assert infer.get_last_part_content() == {
        "prompt": "Count",
        "user": "account",
        "metadata": {"model_hint": "fast"},
        "output_schema": schema,
    }
    tool = Task.create_tool_call(
        "plan", {"budget": 100, "session_id": "tool-value"}, call_id="call-1", session_id="run-session"
    )
    call = tool.get_last_part().as_tool_call()
    assert call.args == {"budget": 100, "session_id": "tool-value"}
    assert call.call_id == "call-1"
    assert RunContext.from_task(tool).session_id == "run-session"
    assert Task.create_tool_call(tool_name="plan", args={}).get_last_part().as_tool_call().args == {}


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}, {"nested": [1]}])
@pytest.mark.parametrize("serialized", [False, True])
def test_output_unwraps_tool_values_and_preserves_protocol_access(value, serialized):
    part = Part.tool_output(call_id="call", result=value)
    task = Task().add_artifact(Artifact(parts=[part]))
    if serialized:
        task = Task.from_dict(task.to_dict())
    before = copy.deepcopy(task.to_dict())
    assert task.get_output("missing") == value
    assert task.get_last_part_content().call_id == "call"
    assert task.get_last_part_content().result == value
    assert task.to_dict() == before


@pytest.mark.parametrize(
    "item",
    [
        Message.agent("answer"),
        Message.assistant("answer"),
        Message(role="agent", parts=[Part.json({"answer": 42})]),
        Artifact(parts=[Part.infer_output(content="answer")]),
        Artifact(parts=[Part.json({"answer": 42})]),
        Artifact(parts=[Part.text("answer")]),
    ],
)
def test_output_reads_native_answers(item):
    task = Task()
    if isinstance(item, Message):
        task.add_message(item)
    else:
        task.add_artifact(item)
    assert task.get_output() == item.parts[-1].content


@pytest.mark.parametrize(
    "item",
    [
        Message.user("new request"),
        Message.infer(prompt="new request"),
        Message.tool_call(tool_name="add"),
        Message(role="system", parts=[Part.text("instructions")]),
        Message(role="agent"),
        Artifact(),
        Artifact(kind="preview", parts=[Part.text("proposed answer")]),
        Artifact(kind="diagnostic", parts=[Part.infer_output(content="diagnostic")]),
        Artifact(parts=[Part.error("failed", "tool failed")]),
        Artifact(parts=[Part.tool_output(error={"message": "failed"}, result="partial")]),
    ],
)
def test_output_never_falls_back_to_stale_answers(item):
    task = Task.create("first request").complete("old answer")
    if isinstance(item, Message):
        task.add_message(item)
    else:
        task.add_artifact(item)
    assert task.get_output("missing") == "missing"


def test_output_reads_only_last_part_and_does_not_check_lifecycle():
    task = Task()
    assert task.get_last_part() is None
    assert task.get_last_part_content() is None
    assert task.get_output("pending") == "pending"
    task.add_artifact(Artifact(parts=[Part.text("first"), Part.tool_output(result=2)]))
    assert task.get_output() == 2
    task.fail("interrupted")
    assert task.get_output() == 2  # Partial outputs are inspectable after failure.
    with pytest.raises(TaskExecutionError):
        task.raise_for_status().get_output()


@pytest.mark.asyncio
async def test_convenience_tasks_execute_through_normal_agent_paths():
    agent = Agent(
        AgentCard(name="task-helper", description="Task helper", url="runtime://task-helper"),
        llm=create_llm("mock", default_response="Hello back"),
        verbosity=0,
    )

    @agent.tool
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    result = await agent.run_task(Task.create_tool_call("add", {"a": 1, "b": 2}, budget=RunBudget(max_tool_calls=1)))
    assert result.raise_for_status().get_output() == 3
    answer = await agent.run_task(Task.create_infer("Hello", session_id="chat", budget=RunBudget(max_llm_calls=1)))
    assert answer.raise_for_status().get_output() == "Hello back"
    assert RunContext.from_task(answer).session_id == "chat"
