"""Concurrency coverage for task-local LLM histories."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import pytest

from protolink import Agent, AgentCard, RunContext, Task
from protolink.llms.actions import FinalAction, LLMActionResult, action_to_json
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.tools import BaseTool


def _user_messages(history: ConversationHistory) -> list[str]:
    """Return serialized user messages from a conversation history."""
    return [str(message["content"]) for message in history.messages if message.get("role") == "user"]


class PausingEchoLLM(LLM):
    """Mock LLM that forces concurrent inference calls to overlap."""

    model_type: ClassVar[str] = "mock"
    provider: ClassVar[str] = "mock-pausing"

    def __init__(self) -> None:
        super().__init__(model="mock-pausing", model_params={})
        self.started = 0
        self.all_started = asyncio.Event()
        self.observed: list[tuple[str, str, int]] = []

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        _ = tools, agent_callback_available, agent_cards, chunk_callback
        before = _user_messages(history)[-1]
        self.started += 1
        if self.started == 2:
            self.all_started.set()
        await asyncio.wait_for(self.all_started.wait(), timeout=1)
        after = _user_messages(history)[-1]
        self.observed.append((before, after, id(history)))
        action = FinalAction(content=f"echo:{after}")
        return LLMActionResult(action=action, raw_response=action_to_json(action))

    def call(self, history: ConversationHistory) -> str:
        return json.dumps({"type": "final", "content": _user_messages(history)[-1]})

    async def call_stream(self, history: ConversationHistory):
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


class CountingHistoryLLM(LLM):
    """Mock LLM that records the user-message snapshot seen by each call."""

    model_type: ClassVar[str] = "mock"
    provider: ClassVar[str] = "mock-counting"

    def __init__(self) -> None:
        super().__init__(model="mock-counting", model_params={})
        self.snapshots: list[tuple[str, ...]] = []

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        _ = tools, agent_callback_available, agent_cards, chunk_callback
        await asyncio.sleep(0.01)
        users = tuple(_user_messages(history))
        self.snapshots.append(users)
        action = FinalAction(content=f"users:{len(users)}")
        return LLMActionResult(action=action, raw_response=action_to_json(action))

    def call(self, history: ConversationHistory) -> str:
        return json.dumps({"type": "final", "content": f"users:{len(_user_messages(history))}"})

    async def call_stream(self, history: ConversationHistory):
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_stateless_agent_runs_use_task_local_llm_history() -> None:
    """Concurrent stateless tasks must not overwrite a shared LLM history."""
    llm = PausingEchoLLM()
    agent = Agent(
        AgentCard(name="history-isolated", description="history isolation", url="runtime://history-isolated"),
        llm=llm,
        verbosity=0,
    )

    alpha = Task.create_infer(prompt="alpha")
    beta = Task.create_infer(prompt="beta")

    result_alpha, result_beta = await asyncio.gather(_run_stream(agent, alpha), _run_stream(agent, beta))

    assert result_alpha.get_last_part_content() == "echo:alpha"
    assert result_beta.get_last_part_content() == "echo:beta"
    assert all(before == after for before, after, _ in llm.observed)
    assert len({history_id for _, _, history_id in llm.observed}) == 2


@pytest.mark.asyncio
async def test_persistent_same_session_runs_are_serialized_before_save() -> None:
    """Same-session persistent tasks should merge history instead of losing updates."""
    llm = CountingHistoryLLM()
    agent = Agent(
        AgentCard(name="history-persistent", description="history persistence", url="runtime://history-persistent"),
        llm=llm,
        state=["conversation"],
        verbosity=0,
    )
    session_id = "shared-session"
    first = Task.create_infer(prompt="first")
    second = Task.create_infer(prompt="second")
    RunContext(session_id=session_id).attach_to_task(first)
    RunContext(session_id=session_id).attach_to_task(second)

    await asyncio.gather(_run_stream(agent, first), _run_stream(agent, second))

    assert sorted(len(snapshot) for snapshot in llm.snapshots) == [1, 2]
    assert agent._state.conversation is not None
    history = agent._state.conversation.get_history(session_id, default_system_prompt=llm.system_prompt)
    users = _user_messages(history)
    assistants = [message for message in history.messages if message.get("role") == "assistant"]
    assert sorted(users) == ["first", "second"]
    assert len(assistants) == 2


async def _run_stream(agent: Agent, task: Task) -> Task:
    """Execute a task through the streaming path and return the mutated task."""
    async for _event in agent.handle_task_streaming(task):
        pass
    return task
