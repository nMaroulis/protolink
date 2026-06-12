import pytest

from protolink.agents import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task, TaskState
from protolink.tools import BaseTool


class EchoTool(BaseTool):
    def __init__(self):
        self.name = "echo"
        self.description = "Echo input"
        self.input_schema = {}
        self.output_schema = {}
        self.tags = []

    async def __call__(self, **kwargs):
        return kwargs


def test_task_direct_construction_sets_last_item():
    message = Message.user("hello")
    task = Task(messages=[message])

    assert task.get_last_item() is message


def test_task_update_state_rejects_invalid_transition():
    task = Task.create(Message.user("hello"))

    with pytest.raises(ValueError, match="submitted -> completed"):
        task.update_state(TaskState.COMPLETED)


def test_task_complete_uses_valid_transition_path():
    task = Task.create(Message.user("hello"))

    task.complete("done")

    assert task.state is TaskState.COMPLETED
    assert [entry["new_state"] for entry in task.metadata["state_history"]] == ["working", "completed"]


@pytest.mark.asyncio
async def test_agent_execute_task_marks_completed():
    agent = Agent(AgentCard(name="agent", description="test", url="runtime://agent"))
    task = Task.create_tool_call(tool_name="echo", args={"message": "hello"})
    agent.add_tool(EchoTool())

    result = await agent.execute_task(task)

    assert result.state is TaskState.COMPLETED
    assert result.artifacts[-1].parts[-1].as_tool_output().result == {"message": "hello"}


@pytest.mark.asyncio
async def test_agent_execute_task_marks_failed_on_tool_error_output():
    agent = Agent(AgentCard(name="agent", description="test", url="runtime://agent"))
    task = Task.create_tool_call(tool_name="missing")

    result = await agent.execute_task(task)

    assert result.state is TaskState.FAILED
    assert result.metadata["error"] == "Tool 'missing' not found"
