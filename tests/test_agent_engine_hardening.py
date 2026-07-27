"""Focused regression tests for inference-engine lifecycle guardrails."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
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
from protolink.llms.base import LLM


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
async def test_external_event_observer_failure_does_not_disable_action_receipts():
    model_calls = 0
    executions = 0
    observer_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {"type": "tool_call", "tool": "publish", "args": {}}
        return {"type": "final", "content": "done"}

    agent = Agent(
        _card("broken-event-observer"),
        llm=create_llm("mock", response_callback=respond),
        verbosity=0,
    )

    @agent.tool(name="publish", description="Commit one write")
    def publish() -> str:
        nonlocal executions
        executions += 1
        return "private result"

    async def broken_observer(_event):
        nonlocal observer_calls
        observer_calls += 1
        raise RuntimeError("observer unavailable")

    task = Task.create_infer(prompt="publish")
    result = await agent.call_llm(
        task.messages[-1].parts[0],
        task=task,
        event_callback=broken_observer,
    )

    assert result.content == "done"
    assert executions == 1
    assert observer_calls == 1
    assert len([artifact for artifact in task.artifacts if artifact.kind == "action_result"]) == 1


@pytest.mark.asyncio
async def test_internal_receipt_callback_does_not_activate_optional_metrics(monkeypatch):
    def unexpected_metrics(*_args, **_kwargs):
        raise AssertionError("internal receipt callback must not activate metrics")

    monkeypatch.setattr("protolink.llms.base.build_call_metrics", unexpected_metrics)
    agent = Agent(
        _card("internal-receipt-metrics"),
        llm=create_llm("mock", default_response="completed"),
        verbosity=0,
    )
    task = Task.create_infer(prompt="finish without an observer")

    result = await agent.handle_task(task)

    assert result.state is TaskState.COMPLETED
    assert result.artifacts[-1].parts[0].content == "completed"


@pytest.mark.asyncio
async def test_streamed_action_receipt_omits_private_internal_result():
    model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {"type": "tool_call", "tool": "get_secret", "args": {}}
        return {"type": "final", "content": "secret processed"}

    agent = Agent(
        _card("private-stream-result"),
        llm=create_llm("mock", response_callback=respond),
        verbosity=0,
    )

    @agent.tool(name="get_secret", description="Read an internal credential")
    def get_secret() -> dict[str, str]:
        return {"api_key": "do-not-expose"}

    task = Task.create_infer(prompt="process the secret")
    events = [event async for event in agent.handle_task_streaming(task)]

    tool_result_event = next(event for event in events if getattr(event, "llm_event_type", None) == "tool_result")
    assert tool_result_event.metadata["result_omitted"] is True
    assert "result" not in tool_result_event.metadata
    assert "do-not-expose" not in str(tool_result_event.to_dict())
    assert "do-not-expose" not in str(task.to_dict())


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
@pytest.mark.parametrize(
    ("state", "error_type", "message"),
    [
        (TaskState.FAILED, RuntimeError, "failed: remote crashed"),
        (TaskState.CANCELED, RuntimeError, "was canceled: remote stopped"),
        (TaskState.INPUT_REQUIRED, ValueError, "requires additional input"),
        (TaskState.WORKING, RuntimeError, "non-terminal task state 'working'"),
    ],
)
async def test_delegation_rejects_unsuccessful_remote_task_states(state, error_type, message):
    remote_task = Task.create_infer(prompt="original child prompt")
    remote_task.begin()
    if state is TaskState.FAILED:
        remote_task.fail("remote crashed")
    elif state is TaskState.CANCELED:
        remote_task.cancel("remote stopped")
    elif state is TaskState.INPUT_REQUIRED:
        remote_task.require_input(Message.agent("need more details"))

    agent = Agent(_card("delegation-state-parent"), verbosity=0)
    agent._resolve_agent_url = AsyncMock(return_value="runtime://delegation-state-child")
    agent.call_agent = AsyncMock(return_value=remote_task)

    with pytest.raises(error_type, match=message):
        await agent._handle_agent_call(
            "delegation-state-child",
            "infer",
            {"prompt": "original child prompt"},
        )


@pytest.mark.asyncio
async def test_delegation_returns_only_a_completed_remote_output():
    remote_task = Task.create_infer(prompt="original child prompt")
    remote_task.complete("actual child output")
    agent = Agent(_card("delegation-success-parent"), verbosity=0)
    agent._resolve_agent_url = AsyncMock(return_value="runtime://delegation-success-child")
    agent.call_agent = AsyncMock(return_value=remote_task)

    result = await agent._handle_agent_call(
        "delegation-success-child",
        "infer",
        {"prompt": "original child prompt"},
    )

    assert result == "actual child output"


@pytest.mark.asyncio
async def test_delegation_accepts_completed_response_only_task():
    remote_task = Task(
        state=TaskState.COMPLETED,
        messages=[Message.agent("actual response-only output")],
    )
    agent = Agent(_card("delegation-response-only-parent"), verbosity=0)
    agent._resolve_agent_url = AsyncMock(return_value="runtime://delegation-response-only-child")
    agent.call_agent = AsyncMock(return_value=remote_task)

    result = await agent._handle_agent_call(
        "delegation-response-only-child",
        "infer",
        {"prompt": "original child prompt"},
    )

    assert result == "actual response-only output"


@pytest.mark.asyncio
async def test_delegation_rejects_completed_request_echo_without_new_output():
    async def echo_completed(_url, request_task):
        request_task.begin()
        request_task.update_state(TaskState.COMPLETED)
        return request_task

    agent = Agent(_card("delegation-echo-parent"), verbosity=0)
    agent._resolve_agent_url = AsyncMock(return_value="runtime://delegation-echo-child")
    agent.call_agent = AsyncMock(side_effect=echo_completed)

    with pytest.raises(RuntimeError, match="completed without returning an output"):
        await agent._handle_agent_call(
            "delegation-echo-child",
            "infer",
            {"prompt": "original child prompt"},
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
async def test_completed_explicit_tool_is_not_retroactively_failed_by_runtime_budget(tmp_path, monkeypatch):
    executions = 0
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "protolink.core.budget.time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
    )
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("completed-tool-overrun"), run_store=store, verbosity=0)

    @agent.tool(name="publish", description="Commit one external write")
    def publish() -> dict[str, bool]:
        nonlocal executions
        executions += 1
        clock["now"] = 2.0
        return {"published": True}

    task = Task.create_tool_call(tool_name="publish", call_id="publish-once")
    RunContext(
        run_id="run_completed_tool_overrun",
        budget=RunBudget(max_runtime_seconds=1.0),
    ).attach_to_task(task)

    result = await agent.handle_task(task)

    assert executions == 1
    assert result.state is TaskState.COMPLETED
    assert len(result.artifacts) == 1
    assert result.artifacts[-1].parts[0].as_tool_output().result == {"published": True}
    assert result.metadata["completed_action_budget_overruns"][0]["call_id"] == "publish-once"
    persisted = store.get_task(task.id)
    assert persisted is not None
    assert persisted.state is TaskState.COMPLETED


@pytest.mark.asyncio
async def test_explicit_tool_result_is_preserved_once_when_canceled_during_end_telemetry(tmp_path):
    telemetry = MagicMock()
    telemetry.on_tool_start = AsyncMock(return_value=None)
    telemetry_started = asyncio.Event()

    async def slow_tool_end(*_args, **_kwargs):
        telemetry_started.set()
        await asyncio.sleep(60)

    telemetry.on_tool_end = AsyncMock(side_effect=slow_tool_end)
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(
        _card("cancel-during-tool-telemetry"),
        run_store=store,
        telemetry=telemetry,
        verbosity=0,
    )
    executions = 0

    @agent.tool(name="publish", description="Commit one external write")
    def publish() -> str:
        nonlocal executions
        executions += 1
        return "published"

    task = Task.create_tool_call(tool_name="publish", call_id="publish-before-cancel")
    running = asyncio.create_task(agent.execute_task(task))
    await asyncio.wait_for(telemetry_started.wait(), timeout=1)

    await agent.cancel_task(task.id, reason="cancel during telemetry")
    result = await running

    assert result is task
    assert executions == 1
    assert task.state is TaskState.CANCELED
    assert task.metadata["completed_after_cancellation"]["call_id"] == "publish-before-cancel"
    assert task.metadata["completed_after_cancellation"]["reason"] == "cancel during telemetry"
    assert len(task.artifacts) == 1
    assert task.artifacts[0].parts[0].as_tool_output().result == "published"
    persisted = store.get_task(task.id)
    assert persisted is not None
    assert persisted.state is TaskState.CANCELED
    assert len(persisted.artifacts) == 1
    assert persisted.artifacts[0].parts[0].as_tool_output().result == "published"


@pytest.mark.asyncio
async def test_runtime_overrun_preserves_first_tool_result_and_blocks_next_part(tmp_path, monkeypatch):
    executions: list[str] = []
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "protolink.core.budget.time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
    )
    store = SQLiteRunStore(tmp_path / "runs.db")
    agent = Agent(_card("multi-tool-overrun"), run_store=store, verbosity=0)

    @agent.tool(name="publish", description="Commit one external write")
    def publish() -> str:
        executions.append("publish")
        clock["now"] = 2.0
        return "published"

    @agent.tool(name="notify", description="Send a follow-up notification")
    def notify() -> str:
        executions.append("notify")
        return "notified"

    task = Task.create(
        Message(
            role="user",
            parts=[
                Part.tool_call(tool_name="publish", call_id="publish-once"),
                Part.tool_call(tool_name="notify", call_id="notify-once"),
            ],
        )
    )
    RunContext(
        run_id="run_multi_tool_overrun",
        budget=RunBudget(max_runtime_seconds=1.0),
    ).attach_to_task(task)

    with pytest.raises(BudgetExceededError):
        await agent.handle_task(task)

    assert executions == ["publish"]
    assert task.state is TaskState.FAILED
    assert len(task.artifacts) == 1
    assert task.artifacts[0].parts[0].as_tool_output().result == "published"
    persisted = store.get_task(task.id)
    assert persisted is not None
    assert persisted.artifacts[0].parts[0].as_tool_output().result == "published"


@pytest.mark.asyncio
async def test_inference_records_completed_side_effect_before_runtime_stop(tmp_path, monkeypatch):
    model_calls = 0
    executions = 0
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "protolink.core.budget.time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
    )

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {"type": "tool_call", "tool": "publish", "args": {}}
        return {"type": "final", "content": "should not make another model call"}

    store = SQLiteRunStore(tmp_path / "runs.db")
    llm = create_llm("mock", response_callback=respond)
    agent = Agent(_card("inference-tool-overrun"), llm=llm, run_store=store, verbosity=0)

    @agent.tool(name="publish", description="Commit one external write")
    def publish() -> dict[str, bool]:
        nonlocal executions
        executions += 1
        clock["now"] = 2.0
        return {"published": True}

    task = Task.create_infer(prompt="publish exactly once")
    RunContext(
        run_id="run_inference_tool_overrun",
        budget=RunBudget(max_runtime_seconds=1.0),
    ).attach_to_task(task)

    with pytest.raises(BudgetExceededError):
        await agent.handle_task(task)

    assert executions == 1
    assert model_calls == 1
    assert task.state is TaskState.FAILED
    receipts = [artifact for artifact in task.artifacts if artifact.kind == "action_result"]
    assert len(receipts) == 1
    assert receipts[0].parts[0].content["status"] == "completed"
    assert receipts[0].parts[0].content["action_kind"] == "tool.call"
    assert receipts[0].parts[0].content["result_omitted"] is True
    assert "published" not in receipts[0].parts[0].content
    assert any("published" in str(message.get("content")) for message in llm.history.messages)

    persisted = store.get_task(task.id)
    assert persisted is not None
    assert persisted.state is TaskState.FAILED
    assert len([artifact for artifact in persisted.artifacts if artifact.kind == "action_result"]) == 1


@pytest.mark.asyncio
async def test_partial_history_save_failure_does_not_mask_budget_error(monkeypatch):
    model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {"type": "tool_call", "tool": "publish", "args": {}}
        return {"type": "final", "content": "unexpected"}

    agent = Agent(
        _card("failing-history-store"),
        llm=create_llm("mock", response_callback=respond),
        state=["conversation"],
        verbosity=0,
    )

    @agent.tool(name="publish", description="Commit one external write")
    def publish() -> str:
        return "published"

    assert agent._state.conversation is not None

    def fail_save_history(_session_id, _history):
        raise OSError("conversation disk full")

    monkeypatch.setattr(agent._state.conversation, "save_history", fail_save_history)
    task = Task.create_infer(prompt="publish")
    RunContext(
        run_id="run_failing_history_store",
        session_id="failing-history-session",
        budget=RunBudget(max_llm_calls=1),
    ).attach_to_task(task)

    with pytest.raises(BudgetExceededError) as exc_info:
        await agent.handle_task(task)

    assert exc_info.value.decision.limit_name == "max_llm_calls"
    assert task.state is TaskState.FAILED
    assert "max_llm_calls" in task.metadata["error"]


@pytest.mark.asyncio
async def test_streaming_partial_history_save_failure_does_not_duplicate_terminal_errors(monkeypatch):
    model_calls = 0

    def respond(_history, _system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {"type": "tool_call", "tool": "publish", "args": {}}
        return {"type": "final", "content": "unexpected"}

    agent = Agent(
        _card("stream-failing-history-store"),
        llm=create_llm("mock", response_callback=respond),
        state=["conversation"],
        verbosity=0,
    )

    @agent.tool(name="publish", description="Commit one external write")
    def publish() -> str:
        return "published"

    assert agent._state.conversation is not None

    def fail_save_history(_session_id, _history):
        raise OSError("conversation disk full")

    monkeypatch.setattr(agent._state.conversation, "save_history", fail_save_history)
    task = Task.create_infer(prompt="publish")
    RunContext(
        run_id="run_stream_failing_history_store",
        session_id="stream-failing-history-session",
        budget=RunBudget(max_llm_calls=1),
    ).attach_to_task(task)

    events = [event async for event in agent.handle_task_streaming(task)]

    errors = [event for event in events if getattr(event, "error_code", None)]
    terminal_statuses = [
        event
        for event in events
        if getattr(event, "new_state", None) == TaskState.FAILED.value and getattr(event, "final", False)
    ]
    assert task.state is TaskState.FAILED
    assert len(errors) == 1
    assert errors[0].error_code == "llm_stream_failed"
    assert "max_llm_calls" in errors[0].error_message
    assert "disk full" not in errors[0].error_message
    assert len(terminal_statuses) == 1


@pytest.mark.asyncio
async def test_failed_stream_without_completed_action_discards_conversation_history():
    class FailingStreamLLM(LLM):
        model_type = "mock"
        provider = "mock"

        def __init__(self):
            super().__init__(model="failing-stream", model_params={})

        def call(self, history):
            raise RuntimeError("provider down")

        async def call_stream(self, history):
            raise RuntimeError("provider down")
            if False:
                yield ""

        def validate_connection(self):
            return True

    llm = FailingStreamLLM()
    agent = Agent(
        _card("failed-stream-history"),
        llm=llm,
        state=["conversation"],
        verbosity=0,
    )
    task = Task.create_infer(prompt="should-discard")
    RunContext(
        run_id="run_failed_stream_history",
        session_id="failed-stream-session",
    ).attach_to_task(task)

    events = [event async for event in agent.handle_task_streaming(task)]

    assert task.state is TaskState.FAILED
    assert any(getattr(event, "error_code", None) == "llm_stream_failed" for event in events)
    assert agent._state.conversation is not None
    history = agent._state.conversation.get_history(
        "failed-stream-session",
        default_system_prompt=llm.system_prompt,
    )
    assert not any(message.get("content") == "should-discard" for message in history.messages)


@pytest.mark.asyncio
async def test_error_part_without_completed_action_discards_conversation_history():
    class ErrorPartLLM(LLM):
        model_type = "mock"
        provider = "mock"

        def __init__(self):
            super().__init__(model="error-part", model_params={})

        def call(self, history):
            raise AssertionError("The custom infer override should be used")

        async def call_stream(self, history):
            if False:
                yield ""

        def validate_connection(self):
            return True

        async def infer(self, *, query, tools, **_kwargs):
            del tools
            self.history.add_user(query)
            return Part.error(code="provider_error", message="provider failed")

    llm = ErrorPartLLM()
    agent = Agent(
        _card("error-part-history"),
        llm=llm,
        state=["conversation"],
        verbosity=0,
    )
    task = Task.create_infer(prompt="should-not-commit")
    RunContext(
        run_id="run_error_part_history",
        session_id="error-part-session",
    ).attach_to_task(task)

    result = await agent.handle_task(task)

    assert result.state is TaskState.FAILED
    assert agent._state.conversation is not None
    history = agent._state.conversation.get_history(
        "error-part-session",
        default_system_prompt=llm.system_prompt,
    )
    assert not any(message.get("content") == "should-not-commit" for message in history.messages)


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
async def test_task_budget_plumbing_preserves_legacy_llm_infer_signature():
    class LegacyInferLLM(LLM):
        model_type = "mock"
        provider = "mock"

        def __init__(self):
            super().__init__(model="legacy", model_params={})
            self.infer_calls = 0

        def call(self, history):
            raise AssertionError("The legacy infer override should be used")

        async def call_stream(self, history):
            if False:
                yield ""

        def validate_connection(self):
            return True

        async def infer(
            self,
            *,
            query,
            tools,
            agent_callback=None,
            agent_cards=None,
            streaming=False,
            event_callback=None,
            action_authorizer=None,
            cancellation_token=None,
            run_context=None,
            budget_policy=None,
        ):
            self.infer_calls += 1
            return Part.infer_output(content="legacy inference")

    llm = LegacyInferLLM()
    agent = Agent(_card("legacy-llm-infer"), llm=llm, verbosity=0)
    task = Task.create_infer(prompt="use the legacy infer override")
    RunContext(
        run_id="run_legacy_llm_infer",
        budget=RunBudget(max_llm_calls=1),
    ).attach_to_task(task)

    result = await agent.handle_task(task)

    assert result.state is TaskState.COMPLETED
    assert llm.infer_calls == 1


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
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await running
    if sys.version_info >= (3, 11):
        assert str(exc_info.value) == "runtime shutdown"

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
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await running
    if sys.version_info >= (3, 11):
        assert str(exc_info.value) == "stream consumer shutdown"

    persisted = store.get_task(task.id)
    assert task.state is TaskState.CANCELED
    assert task.metadata["cancel_reason"] == "stream consumer shutdown"
    assert persisted is not None
    assert persisted.state is TaskState.CANCELED
    assert not any(getattr(event, "final", False) for event in events)
