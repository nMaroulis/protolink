"""Public convenience calls preserve results and the full task lifecycle."""

from __future__ import annotations

import asyncio
import gc
import json
from typing import Any

import pytest

from protolink import (
    Agent,
    AgentCard,
    Artifact,
    Part,
    RunContext,
    SQLiteRunStore,
    Task,
    TaskExecutionError,
    TaskState,
    create_knowledge,
    create_llm,
)
from protolink.core.part import ToolOutput


def make_agent(agent_type: type[Agent] = Agent, **kwargs: Any) -> Agent:
    """Provide both convenience methods with valid, provider-free dependencies."""
    return agent_type(
        AgentCard(name="convenience", description="Test agent", url="runtime://convenience"),
        llm=create_llm("mock", default_response="ok"),
        knowledge=create_knowledge("memory", name="notes"),
        verbosity=0,
        **kwargs,
    )


@pytest.mark.parametrize("state", list(TaskState))
def test_raise_for_status_preserves_task_and_partial_results(state: TaskState) -> None:
    task = Task(
        state=state,
        artifacts=[Artifact(parts=[Part.text("partial result")])],
        metadata={"error": "tool failed", "cancel_reason": "stopped by user"},
    )

    if state in {TaskState.FAILED, TaskState.CANCELED}:
        with pytest.raises(TaskExecutionError) as raised:
            task.raise_for_status()
        assert raised.value.task is task
        assert task.id in str(raised.value)
        assert ("tool failed" if state is TaskState.FAILED else "stopped by user") in str(raised.value)
        assert raised.value.task.get_last_part_content() == "partial result"
    else:
        assert task.raise_for_status() is task


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["invoke", "ask"])
@pytest.mark.parametrize("content", ["", 0, False, {}, []])
async def test_convenience_preserves_falsey_response_content(content: Any, method: str) -> None:
    class OutputAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            task.begin().add_artifact(Artifact(parts=[Part(type="json", content=content)]))
            return task.update_state(TaskState.COMPLETED)

    result = await getattr(make_agent(OutputAgent), method)("respond")
    if method == "ask":
        assert result.text == (content if isinstance(content, str) else json.dumps(content))
    else:
        assert result == content
        assert type(result) is type(content)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["invoke", "ask"])
@pytest.mark.parametrize("append_empty_output", [False, True])
async def test_convenience_does_not_return_an_unchanged_request(method: str, *, append_empty_output: bool) -> None:
    class EmptyAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            task.begin()
            if append_empty_output:
                task.add_artifact(Artifact(parts=[Part(type="json", content=None)]))
            return task.update_state(TaskState.COMPLETED)

    result = await getattr(make_agent(EmptyAgent), method)("private input")
    assert (result if method == "invoke" else result.text) == "No response generated"


@pytest.mark.asyncio
async def test_invoke_keeps_successful_tool_output_contract_and_raises_for_failure() -> None:
    agent = make_agent()

    @agent.tool
    def zero() -> int:
        """Return zero."""
        return 0

    result = await agent.invoke("", part_type="tool_call", tool_name="zero")
    assert isinstance(result, ToolOutput)
    assert result.result == 0

    with pytest.raises(TaskExecutionError, match="not found") as raised:
        await agent.invoke("", part_type="tool_call", tool_name="missing")
    assert raised.value.task.state is TaskState.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["invoke", "ask"])
@pytest.mark.parametrize("state", [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED])
async def test_custom_convenience_handler_is_registered_and_persisted(tmp_path, method: str, state: TaskState) -> None:
    class CustomAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            assert task.id in self.active_task_ids
            assert RunContext.from_task(task).session_id == "separate-conversation"
            if state is TaskState.FAILED:
                return task.fail("cannot answer")
            if state is TaskState.CANCELED:
                return task.cancel("user stopped")
            return task.complete("answer")

    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = make_agent(CustomAgent, run_store=store)
    if state is TaskState.COMPLETED:
        result = await getattr(agent, method)("question", session_id="separate-conversation")
        assert (result if method == "invoke" else result.text) == "answer"
    else:
        with pytest.raises(TaskExecutionError):
            await getattr(agent, method)("question", session_id="separate-conversation")
    records = store.list_task_records(session_id="separate-conversation")
    assert len(records) == 1
    assert store.get_task(records[0].task_id).state is state
    assert agent.active_task_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["invoke", "ask"])
async def test_convenience_preserves_handler_exception_and_failed_snapshot(tmp_path, method: str) -> None:
    original = ValueError("original handler error")

    class BrokenAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            raise original

    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = make_agent(BrokenAgent, run_store=store)
    with pytest.raises(ValueError) as raised:
        await getattr(agent, method)("question")
    assert raised.value is original
    record = store.list_task_records()[0]
    assert store.get_task(record.task_id).state is TaskState.FAILED
    assert agent.active_task_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["invoke", "ask"])
async def test_custom_convenience_handler_can_be_canceled(method: str) -> None:
    started = asyncio.Event()

    class WaitingAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            started.set()
            await asyncio.Event().wait()
            return task.complete("unreachable")

    agent = make_agent(WaitingAgent)
    pending = asyncio.create_task(getattr(agent, method)("wait"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task_id = agent.active_task_ids[0]
    await agent.cancel_task(task_id, reason="stop convenience call")
    with pytest.raises(TaskExecutionError, match="stop convenience call") as raised:
        await asyncio.wait_for(pending, timeout=1)
    assert raised.value.task.state is TaskState.CANCELED
    assert agent.active_task_ids == ()


def test_sync_tool_returns_raw_values_and_validates_arguments() -> None:
    agent = make_agent()
    calls: list[int] = []

    @agent.tool
    async def record(value: int) -> int:
        """Record an integer."""
        calls.append(value)
        return value

    assert agent.sync.call_tool("record", value="0") == 0
    with pytest.raises(ValueError):
        agent.sync.call_tool("record", value="not an integer")
    assert calls == [0]


def test_sync_run_task_keeps_failure_inspectable() -> None:
    task = Task.create_tool_call(tool_name="missing")
    result = make_agent().sync.run_task(task)
    assert result is task
    assert result.state is TaskState.FAILED
    with pytest.raises(TaskExecutionError):
        result.raise_for_status()


def test_sync_tool_accepts_method_argument() -> None:
    agent = make_agent()

    @agent.tool
    def request(method: str) -> str:
        """Return the requested method."""
        return method

    assert agent.sync.call_tool("request", method="GET") == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("invoke", ("hello",)),
        ("ask", ("hello",)),
        ("call_tool", ("missing",)),
        ("run_task", (Task.create_infer(prompt="hello"),)),
        ("discover_agents", ()),
        ("call_agent", ("runtime://peer", Task.create_infer(prompt="hello"))),
        ("cancel_task", ("missing",)),
    ],
)
async def test_sync_methods_explain_async_usage_without_coroutine_warnings(method: str, args: tuple, recwarn) -> None:
    agent = make_agent()
    with pytest.raises(RuntimeError, match=rf"Use await agent\.{method}\("):
        getattr(agent.sync, method)(*args)
    gc.collect()
    assert not [warning for warning in recwarn if "was never awaited" in str(warning.message)]
