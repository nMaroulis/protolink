import json
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import ClassVar

import pytest

from protolink import (
    Agent,
    AgentCard,
    ApprovalDecision,
    CapabilityPolicy,
    HistoryCompactionRequest,
    HistoryCompactionResult,
    HistoryCompactionStrategy,
    HistoryCompactor,
    PolicyEffect,
    RunAction,
)
from protolink.client import AgentClient
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.llms.metrics import estimate_token_count
from protolink.transport import RuntimeTransport


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
    llm = CompactionLLM()

    assert strategy == "recent"
    assert HistoryCompactionRequest(strategy="tokens").strategy == "tokens"
    assert HistoryCompactionResult.__name__ == "HistoryCompactionResult"
    assert HistoryCompactionResult.from_dict({"strategy": "recent"}).strategy == "recent"
    assert isinstance(llm.compactor, HistoryCompactor)


def test_compactor_follows_history_replaced_for_a_persistent_session() -> None:
    llm = CompactionLLM()
    compactor = llm.compactor
    llm.history = ConversationHistory(system_prompt="resumed session")
    for index in range(4):
        llm.history.add_user(f"resumed-{index}")

    result = compactor.compact("recent", max_messages=2)

    assert result.after_messages == 2
    assert [message["content"] for message in llm.history.messages] == ["resumed session", "resumed-3"]


def test_copied_llm_compactor_stays_bound_to_copied_owner() -> None:
    llm = CompactionLLM()
    _seed_history(llm, count=4)
    copied_llm = deepcopy(llm)

    copied_llm.compactor.compact(strategy="recent", max_messages=2)

    assert len(copied_llm.history) == 2
    assert len(llm.history) == 5


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
async def test_agent_compact_history_request_dispatches_without_model_tool() -> None:
    llm = CompactionLLM()
    _seed_history(llm, count=4)
    agent = Agent(AgentCard(name="compactor", description="test", url="runtime://compactor"), llm=llm, verbosity=0)

    result = await agent.compact_history(HistoryCompactionRequest(strategy="recent", max_messages=3))

    assert result.after_messages == 3
    assert llm.call_histories == []
    assert all("message-0" not in message["content"] for message in llm.history.messages)
    assert "protolink_compact_history" not in llm.system_prompt


@pytest.mark.asyncio
async def test_agent_compact_history_request_uses_runtime_policy_boundary() -> None:
    llm = CompactionLLM()
    _seed_history(llm, count=4)
    approval_actions: list[RunAction] = []

    async def approve(request, _context):
        approval_actions.append(request.action)
        return ApprovalDecision(
            approved=True,
            request_id=request.request_id,
            reason="test approves compaction",
            decided_by="tester",
        )

    agent = Agent(
        AgentCard(name="policy_compactor", description="test", url="runtime://policy-compactor"),
        llm=llm,
        policy=CapabilityPolicy({"llm.history.compact": PolicyEffect.REQUIRE_APPROVAL}),
        approval_handler=approve,
        verbosity=0,
    )

    result = await agent.compact_history(HistoryCompactionRequest(strategy="recent", max_messages=2))

    assert result.after_messages == 2
    assert approval_actions[0].kind == "llm.history.compact"
    assert approval_actions[0].capabilities == frozenset({"llm.history.compact"})


@pytest.mark.asyncio
async def test_agent_client_compact_history_uses_request_spec_endpoint() -> None:
    llm = CompactionLLM()
    _seed_history(llm, count=4)
    agent = Agent(
        AgentCard(name="remote_compactor", description="test", url="runtime://remote-compactor"),
        transport=RuntimeTransport(url="runtime://remote-compactor"),
        llm=llm,
        verbosity=0,
    )
    client = AgentClient(RuntimeTransport(url="runtime://compaction-client"))
    assert agent.server is not None
    await agent.server.start()

    try:
        result = await client.compact_history(
            "runtime://remote-compactor",
            strategy="recent",
            max_messages=2,
        )
    finally:
        await agent.server.stop()

    assert isinstance(result, HistoryCompactionResult)
    assert result.after_messages == 2
    assert llm.call_histories == []


@pytest.mark.asyncio
async def test_llm_infer_does_not_reserve_or_prompt_history_compaction_tool() -> None:
    llm = CompactionLLM([json.dumps({"type": "final", "content": "ok"})])
    old_builtin_name = "protolink_compact_history"

    response = await llm.infer(
        query="hello",
        tools={old_builtin_name: object()},  # type: ignore[dict-item]
    )
    llm.build_system_prompt(tools="")

    assert response.content == "ok"
    assert old_builtin_name not in llm.system_prompt


def test_invalid_compaction_options_do_not_mutate_history() -> None:
    llm = CompactionLLM()
    _seed_history(llm)
    before = llm.history.to_list()

    with pytest.raises(ValueError, match="strategy must be one of"):
        llm.compact_history("unknown")  # type: ignore[arg-type]

    assert llm.history.to_list() == before
