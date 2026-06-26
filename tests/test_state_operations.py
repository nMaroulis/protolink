import pytest

from protolink import (
    Agent,
    AgentCard,
    ApprovalDecision,
    CapabilityPolicy,
    RunAction,
    RunContext,
    StateOperationResult,
    Task,
    create_llm,
)
from protolink.client import AgentClient
from protolink.core.policy import PolicyEffect
from protolink.llms.history import ConversationHistory
from protolink.transport.runtime_transport import RuntimeTransport


async def _seed_conversation(agent: Agent, session_id: str, prompt: str = "remember this") -> None:
    task = Task.create_infer(prompt=prompt)
    RunContext(session_id=session_id).attach_to_task(task)
    await agent.handle_task(task)


@pytest.mark.asyncio
async def test_agent_describe_and_reset_state_reports_conversation_session() -> None:
    agent = Agent(
        AgentCard(name="stateful", description="state test", url="runtime://stateful"),
        llm=create_llm("mock", default_response="stored"),
        state=["conversation"],
        verbosity=0,
    )
    await _seed_conversation(agent, "session_state")

    described = await agent.describe_state("session_state")

    assert described.operation == "describe"
    assert described.session_id == "session_state"
    assert described.missing == ()
    conversation_report = described.stores[0]
    assert conversation_report.name == "conversation"
    assert conversation_report.enabled is True
    assert conversation_report.exists is True
    assert conversation_report.message_count is not None
    assert conversation_report.message_count >= 3

    reset = await agent.reset_state("session_state")
    assert reset.cleared == ("conversation",)
    assert reset.stores[0].cleared is True

    after = await agent.describe_state("session_state")
    assert after.stores[0].exists is False
    assert after.stores[0].message_count is None


@pytest.mark.asyncio
async def test_agent_compact_state_compacts_persisted_conversation_session() -> None:
    llm = create_llm("mock", default_response="unused")
    agent = Agent(
        AgentCard(name="state_compactor", description="state compaction test", url="runtime://state-compactor"),
        llm=llm,
        state=["conversation"],
        verbosity=0,
    )
    history = ConversationHistory("system")
    for index in range(6):
        history.add_user(f"user {index}")
        history.add_assistant(f"assistant {index}")
    assert agent._state.conversation is not None
    agent._state.conversation.save_history("session_compact", history)

    result = await agent.compact_state("session_compact", strategy="recent", max_messages=4)

    assert result.operation == "compact"
    assert result.session_id == "session_compact"
    assert result.compacted == ("conversation",)
    report = result.stores[0]
    assert report.compacted is True
    assert report.message_count == 4
    assert report.metadata["compaction"]["after_messages"] == 4
    after = await agent.describe_state("session_compact")
    assert after.stores[0].message_count == 4


@pytest.mark.asyncio
async def test_state_operations_use_runtime_policy_boundary() -> None:
    approval_actions: list[RunAction] = []

    async def approve(request, _context):
        approval_actions.append(request.action)
        return ApprovalDecision(
            approved=True,
            request_id=request.request_id,
            reason="test approves reset",
            decided_by="tester",
        )

    agent = Agent(
        AgentCard(name="state_policy", description="state policy test", url="runtime://state-policy"),
        llm=create_llm("mock", default_response="stored"),
        state=["conversation"],
        policy=CapabilityPolicy({"state.reset": PolicyEffect.REQUIRE_APPROVAL}),
        approval_handler=approve,
        verbosity=0,
    )
    await _seed_conversation(agent, "session_policy")

    result = await agent.reset_state("session_policy")

    assert result.cleared == ("conversation",)
    assert len(approval_actions) == 1
    assert approval_actions[0].kind == "state.reset"
    assert approval_actions[0].capabilities == frozenset({"state.reset"})


@pytest.mark.asyncio
async def test_agent_client_state_operations_use_request_spec_endpoints() -> None:
    agent = Agent(
        AgentCard(name="remote_state", description="remote state test", url="runtime://remote-state"),
        transport=RuntimeTransport(url="runtime://remote-state"),
        llm=create_llm("mock", default_response="stored"),
        state=["conversation"],
        verbosity=0,
    )
    client = AgentClient(RuntimeTransport(url="runtime://state-client"))
    assert agent.server is not None
    await agent.server.start()

    try:
        for index in range(4):
            await _seed_conversation(agent, "session_remote", prompt=f"remember remote {index}")
        described = await client.describe_state(
            "runtime://remote-state",
            session_id="session_remote",
            include_data=True,
        )
        compacted = await client.compact_state(
            "runtime://remote-state",
            session_id="session_remote",
            strategy="recent",
            max_messages=4,
        )
        after_compact = await client.describe_state("runtime://remote-state", session_id="session_remote")
        reset = await client.reset_state("runtime://remote-state", session_id="session_remote")
        after = await client.describe_state("runtime://remote-state", session_id="session_remote")
    finally:
        await agent.server.stop()

    assert isinstance(described, StateOperationResult)
    assert described.stores[0].exists is True
    assert described.stores[0].data is not None
    assert compacted.stores[0].metadata["compaction"]["strategy"] == "recent"
    assert compacted.stores[0].metadata["compaction"]["after_messages"] == 4
    assert after_compact.stores[0].message_count == 4
    assert reset.cleared == ("conversation",)
    assert after.stores[0].exists is False
