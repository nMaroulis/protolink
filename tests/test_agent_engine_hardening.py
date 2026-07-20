"""Focused regression tests for inference-engine lifecycle guardrails."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    BudgetExceededError,
    Message,
    Part,
    RunBudget,
    RunContext,
    SQLiteRunStore,
    Task,
    TaskState,
    create_llm,
)
from protolink.client import RegistryClient


def _card(name: str) -> AgentCard:
    return AgentCard(
        name=name,
        description="Inference engine hardening test agent",
        url=f"runtime://{name}",
    )


@pytest.mark.asyncio
async def test_precanceled_context_stops_unary_inference_before_model_call(tmp_path):
    model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        return {"type": "final", "content": "unexpected"}

    store = SQLiteRunStore(tmp_path / "runs.db")
    llm = create_llm("mock", response_callback=respond)
    agent = Agent(_card("precanceled-infer"), llm=llm, run_store=store, verbosity=0)
    task = Task.create_infer(prompt="do not run")
    RunContext(run_id="run_precanceled_infer").cancel("canceled before dispatch").attach_to_task(task)
    history_before = list(llm.history.messages)

    result = await agent.handle_task(task)

    assert result is task
    assert task.state is TaskState.CANCELED
    assert model_calls == 0
    assert llm.history.messages == history_before
    assert store.get_task(task.id).state is TaskState.CANCELED


@pytest.mark.asyncio
async def test_precanceled_context_stops_streaming_tool_before_execution(tmp_path):
    executions: list[bool] = []
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("precanceled-stream"), run_store=store, verbosity=0)

    @agent.tool(name="side_effect", description="Record an execution")
    def side_effect() -> str:
        executions.append(True)
        return "unexpected"

    task = Task.create_tool_call(tool_name="side_effect")
    RunContext(run_id="run_precanceled_stream").cancel("already stopped").attach_to_task(task)

    events = [event async for event in agent.handle_task_streaming(task)]

    assert executions == []
    assert task.state is TaskState.CANCELED
    assert len(events) == 1
    assert events[0].final is True
    assert events[0].new_state == TaskState.CANCELED.value
    assert store.get_task(task.id).state is TaskState.CANCELED


@pytest.mark.asyncio
async def test_closing_stream_early_cancels_and_persists_working_task(tmp_path):
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("closed-stream"), run_store=store, verbosity=0)
    task = Task.create_infer(prompt="do not leave this task working")

    stream = agent.handle_task_streaming(task)
    first_event = await anext(stream)
    await stream.aclose()

    assert first_event.new_state == TaskState.WORKING.value
    assert task.state is TaskState.CANCELED
    assert task.metadata["cancel_reason"] == "Streaming consumer closed before task completion"
    assert store.get_task(task.id).state is TaskState.CANCELED


@pytest.mark.asyncio
async def test_telemetry_hook_failures_do_not_change_inference_or_tool_outcomes():
    telemetry = MagicMock()
    for hook_name in (
        "on_task_start",
        "on_task_end",
        "on_llm_start",
        "on_llm_event",
        "on_llm_end",
        "on_tool_start",
        "on_tool_end",
    ):
        setattr(telemetry, hook_name, AsyncMock(side_effect=RuntimeError(f"{hook_name} unavailable")))

    model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {"type": "tool_call", "tool": "increment", "args": {}}
        return {"type": "final", "content": "completed despite telemetry"}

    executions = 0
    agent = Agent(
        _card("broken-telemetry"),
        llm=create_llm("mock", response_callback=respond),
        telemetry=telemetry,
        verbosity=0,
    )

    @agent.tool(name="increment", description="Increment a counter")
    def increment() -> int:
        nonlocal executions
        executions += 1
        return executions

    infer_task = Task.create_infer(prompt="use the tool")
    tool_task = Task.create_tool_call(tool_name="increment")

    infer_result = await agent.handle_task(infer_task)
    tool_result = await agent.handle_task(tool_task)

    assert infer_result.state is TaskState.COMPLETED
    assert tool_result.state is TaskState.COMPLETED
    assert executions == 2


@pytest.mark.asyncio
async def test_failed_unary_task_is_persisted_before_policy_error_is_reraised(tmp_path):
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("persist-failure"), run_store=store, verbosity=0)

    @agent.tool(
        name="publish",
        description="Publish a record",
        capabilities=["records.write"],
    )
    def publish() -> str:
        return "unexpected"

    task = Task.create_tool_call(tool_name="publish")
    RunContext(
        run_id="run_persist_failure",
        permissions={"records.write": "deny"},
    ).attach_to_task(task)

    with pytest.raises(ActionDeniedError):
        await agent.handle_task(task)

    persisted = store.get_task(task.id)
    assert task.state is TaskState.FAILED
    assert persisted is not None
    assert persisted.state is TaskState.FAILED
    assert persisted.metadata["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "context", "message"),
    [
        (
            "https://untrusted.example/agent",
            RunContext(agent_chain=["coordinator"]),
            "Direct URL delegation is not allowed",
        ),
        (
            "planner",
            RunContext(agent_chain=["planner", "coordinator"]),
            "Delegation cycle detected",
        ),
    ],
)
async def test_model_delegation_rejects_untrusted_urls_and_ancestor_cycles(target, context, message):
    agent = Agent(_card("coordinator"), verbosity=0)

    with pytest.raises(ValueError, match=message):
        await agent._handle_agent_call(
            target,
            "infer",
            {"prompt": "delegated work"},
            parent_context=context,
        )


@pytest.mark.asyncio
async def test_registry_failure_degrades_prompt_to_no_delegates():
    registry = MagicMock(spec=RegistryClient)
    registry.discover = AsyncMock(side_effect=ConnectionError("registry offline"))
    logger = MagicMock()
    llm = create_llm("mock", default_response="local result")
    infer = AsyncMock(return_value=Part.infer_output(content="local result"))
    llm.infer = infer
    agent = Agent(
        _card("registry-fallback"),
        registry=registry,
        llm=llm,
        logger=logger,
        verbosity=0,
    )
    logger.reset_mock()

    result = await agent.call_llm(Part.infer(prompt="work locally"))

    assert result.content == "local result"
    assert infer.await_args.kwargs["agent_callback"] is None
    assert infer.await_args.kwargs["agent_cards"] is None
    assert any("continuing inference without delegation targets" in str(call) for call in logger.warning.call_args_list)


@pytest.mark.asyncio
async def test_task_budget_is_shared_across_multiple_infer_parts():
    model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        return {"type": "final", "content": f"response {model_calls}"}

    llm = create_llm("mock", response_callback=respond)
    agent = Agent(_card("shared-infer-budget"), llm=llm, verbosity=0)
    task = Task.create(
        Message(
            role="user",
            parts=[Part.infer(prompt="first"), Part.infer(prompt="second")],
        )
    )
    RunContext(
        run_id="run_shared_infer_budget",
        budget=RunBudget(max_llm_calls=1),
    ).attach_to_task(task)

    with pytest.raises(BudgetExceededError):
        await agent.handle_task(task)

    assert model_calls == 1
    assert task.state is TaskState.FAILED


@pytest.mark.asyncio
async def test_task_budget_blocks_explicit_tool_parts_before_execution():
    executions = 0
    agent = Agent(_card("explicit-tool-budget"), verbosity=0)

    @agent.tool(name="count_execution", description="Count one execution")
    def count_execution() -> str:
        nonlocal executions
        executions += 1
        return "unexpected"

    task = Task.create_tool_call(tool_name="count_execution")
    RunContext(
        run_id="run_explicit_tool_budget",
        budget=RunBudget(max_tool_calls=0),
    ).attach_to_task(task)

    with pytest.raises(BudgetExceededError):
        await agent.handle_task(task)

    assert executions == 0
    assert task.state is TaskState.FAILED


@pytest.mark.asyncio
async def test_task_budget_plumbing_preserves_legacy_agent_override_signatures():
    class LegacyOverrideAgent(Agent):
        async def execute_tool(self, part, *, task=None, cancellation_token=None):
            return Part.tool_output(call_id=part.as_tool_call().call_id, result="legacy tool")

        async def call_llm(
            self,
            infer_part,
            task=None,
            *,
            streaming=False,
            event_callback=None,
            cancellation_token=None,
        ):
            return Part.infer_output(content="legacy inference")

        async def call_llm_stream(self, infer_part, task=None, *, cancellation_token=None):
            yield {"__protolink_part__": Part.infer_output(content="legacy stream").to_dict()}

    agent = LegacyOverrideAgent(_card("legacy-overrides"), verbosity=0)
    unary_task = Task.create(
        Message(
            role="user",
            parts=[
                Part.tool_call(tool_name="legacy", call_id="legacy-call"),
                Part.infer(prompt="legacy"),
            ],
        )
    )

    unary_result = await agent.handle_task(unary_task)
    stream_task = Task.create_infer(prompt="legacy stream")
    stream_events = [event async for event in agent.handle_task_streaming(stream_task)]

    assert unary_result.state is TaskState.COMPLETED
    assert stream_task.state is TaskState.COMPLETED
    assert stream_events[-1].final is True


@pytest.mark.asyncio
async def test_inline_nested_task_uses_its_own_budget_context():
    child_model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal child_model_calls
        child_model_calls += 1
        return {"type": "final", "content": "unexpected"}

    child = Agent(_card("nested-child"), llm=create_llm("mock", response_callback=respond), verbosity=0)
    child_task = Task.create_infer(prompt="must remain blocked")
    RunContext(
        run_id="run_nested_child",
        budget=RunBudget(max_llm_calls=0),
    ).attach_to_task(child_task)

    class InlineParentAgent(Agent):
        async def handle_task(self, task):
            return await child.handle_task(child_task)

    parent = InlineParentAgent(_card("nested-parent"), verbosity=0)
    parent_task = Task.create_infer(prompt="delegate inline")
    RunContext(
        run_id="run_nested_parent",
        budget=RunBudget(max_llm_calls=10),
    ).attach_to_task(parent_task)

    with pytest.raises(BudgetExceededError):
        await parent.run_task(parent_task)

    assert child_model_calls == 0
    assert child_task.state is TaskState.FAILED


@pytest.mark.asyncio
async def test_external_unary_coroutine_cancellation_is_persisted_and_reraised(tmp_path):
    started = asyncio.Event()
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("external-unary-cancel"), run_store=store, verbosity=0)

    @agent.tool(name="wait", description="Wait until the caller cancels")
    async def wait() -> str:
        started.set()
        await asyncio.sleep(60)
        return "unexpected"

    task = Task.create_tool_call(tool_name="wait")
    running = asyncio.create_task(agent.execute_task(task))
    await asyncio.wait_for(started.wait(), timeout=1)

    running.cancel("runtime shutdown")
    with pytest.raises(asyncio.CancelledError, match="runtime shutdown"):
        await running

    persisted = store.get_task(task.id)
    assert task.state is TaskState.CANCELED
    assert task.metadata["cancel_reason"] == "runtime shutdown"
    assert persisted is not None
    assert persisted.state is TaskState.CANCELED


@pytest.mark.asyncio
async def test_external_stream_coroutine_cancellation_is_persisted_and_reraised(tmp_path):
    started = asyncio.Event()
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("external-stream-cancel"), run_store=store, verbosity=0)

    @agent.tool(name="wait", description="Wait until the stream consumer cancels")
    async def wait() -> str:
        started.set()
        await asyncio.sleep(60)
        return "unexpected"

    task = Task.create_tool_call(tool_name="wait")
    events: list[Any] = []

    async def consume() -> None:
        async for event in agent.handle_task_streaming(task):
            events.append(event)

    running = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)

    running.cancel("stream consumer shutdown")
    with pytest.raises(asyncio.CancelledError, match="stream consumer shutdown"):
        await running

    persisted = store.get_task(task.id)
    assert task.state is TaskState.CANCELED
    assert task.metadata["cancel_reason"] == "stream consumer shutdown"
    assert persisted is not None
    assert persisted.state is TaskState.CANCELED
    assert not any(getattr(event, "final", False) for event in events)
