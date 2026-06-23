import json
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest

from protolink import HistoryCompactionResult, HistoryCompactionStrategy
from protolink.core import ActionAuthorization, PolicyDecision, PolicyEffect, RunAction
from protolink.llms.base import LLM
from protolink.llms.compaction import HISTORY_COMPACTION_TOOL_NAME
from protolink.llms.history import ConversationHistory
from protolink.llms.metrics import estimate_token_count


class CompactionLLM(LLM):
    """Small deterministic LLM used to exercise shared compaction behavior."""

    model_type = "mock"
    provider = "mock"
    model_params: ClassVar[dict] = {}

    def __init__(self, responses: list[str] | None = None):
        super().__init__(model="mock-model", model_params={})
        self.responses = list(responses or [])
        self.call_histories: list[ConversationHistory] = []

    def call(self, history: ConversationHistory) -> str:
        self.call_histories.append(history)
        if not self.responses:
            raise RuntimeError("no mock response configured")
        return self.responses.pop(0)

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        yield self.call(history)

    def validate_connection(self) -> bool:
        return True


def _seed_history(llm: LLM, count: int = 6) -> None:
    llm.history.reset_to_system("system instructions")
    for index in range(count):
        role = llm.history.add_user if index % 2 == 0 else llm.history.add_assistant
        role(f"message-{index} " + ("context " * 20))


def test_compaction_types_are_part_of_public_api() -> None:
    strategy: HistoryCompactionStrategy = "recent"
    assert strategy == "recent"
    assert HistoryCompactionResult.__name__ == "HistoryCompactionResult"


def test_recent_compaction_preserves_system_and_newest_messages() -> None:
    llm = CompactionLLM()
    _seed_history(llm)
    original_history = llm.history

    result = llm.compact_history("recent", max_messages=3)

    assert llm.history is original_history
    assert [message["content"].split()[0] for message in llm.history.messages] == [
        "system",
        "message-4",
        "message-5",
    ]
    assert result.strategy == "recent"
    assert result.before_messages == 7
    assert result.after_messages == 3
    assert result.removed_messages == 4
    assert result.changed is True
    assert result.summary_created is False


def test_token_compaction_keeps_protected_recent_suffix_within_budget() -> None:
    llm = CompactionLLM()
    _seed_history(llm)
    provider_messages = llm.history.messages
    budget = estimate_token_count([provider_messages[0], *provider_messages[-2:]], model=llm.model)

    result = llm.compact_history("tokens", max_tokens=budget, preserve_recent=2)

    assert [message["content"].split()[0] for message in llm.history.messages] == [
        "system",
        "message-4",
        "message-5",
    ]
    assert result.after_tokens <= budget
    assert result.removed_messages == 4


def test_summary_compaction_uses_isolated_call_and_preserves_recent_messages() -> None:
    llm = CompactionLLM([json.dumps({"summary": "The user chose Athens; the booking is unresolved."})])
    _seed_history(llm)
    live_history = llm.history

    result = llm.compact_history("summary", preserve_recent=2, summary_max_tokens=100)

    assert llm.history is live_history
    assert len(llm.call_histories) == 1
    assert llm.call_histories[0] is not live_history
    assert "Return exactly one JSON object" in llm.call_histories[0].messages[0]["content"]
    assert llm.history.messages[1] == {
        "role": "system",
        "content": "Compacted conversation summary:\nThe user chose Athens; the booking is unresolved.",
    }
    assert [message["content"].split()[0] for message in llm.history.messages[-2:]] == [
        "message-4",
        "message-5",
    ]
    assert result.summary_created is True
    assert result.removed_messages == 4
    assert result.after_messages == 4


def test_summary_compaction_is_atomic_when_model_call_fails() -> None:
    llm = CompactionLLM()
    _seed_history(llm)
    before = llm.history.to_list()

    with pytest.raises(RuntimeError, match="no mock response configured"):
        llm.compact_history("summary", preserve_recent=2)

    assert llm.history.to_list() == before


@pytest.mark.asyncio
async def test_agent_request_can_dispatch_builtin_history_compaction() -> None:
    llm = CompactionLLM(
        [
            json.dumps(
                {
                    "type": "tool_call",
                    "tool": HISTORY_COMPACTION_TOOL_NAME,
                    "args": {"strategy": "recent", "max_messages": 3},
                }
            ),
            json.dumps({"type": "final", "content": "History compacted."}),
        ]
    )
    _seed_history(llm, count=4)
    authorized_actions: list[RunAction] = []

    async def authorize(action: RunAction) -> ActionAuthorization:
        authorized_actions.append(action)
        return ActionAuthorization(
            action=action,
            policy_decision=PolicyDecision(
                effect=PolicyEffect.ALLOW,
                reason="test allows compaction",
                policy_name="test",
            ),
        )

    result = await llm.infer(
        query="Compact your history using the simple strategy.",
        tools={},
        action_authorizer=authorize,
    )

    assert result.content == "History compacted."
    assert authorized_actions[0].kind == "llm.history.compact"
    assert authorized_actions[0].capabilities == frozenset({"llm.history.compact"})
    assert all("message-0" not in message["content"] for message in llm.history.messages)
    assert HISTORY_COMPACTION_TOOL_NAME in llm.system_prompt


@pytest.mark.asyncio
async def test_builtin_history_tool_name_is_reserved() -> None:
    llm = CompactionLLM()

    with pytest.raises(ValueError, match="is reserved by the LLM runtime"):
        await llm.infer(
            query="hello",
            tools={HISTORY_COMPACTION_TOOL_NAME: object()},  # type: ignore[dict-item]
        )


def test_invalid_compaction_options_do_not_mutate_history() -> None:
    llm = CompactionLLM()
    _seed_history(llm)
    before = llm.history.to_list()

    with pytest.raises(ValueError, match="strategy must be one of"):
        llm.compact_history("unknown")  # type: ignore[arg-type]

    assert llm.history.to_list() == before
