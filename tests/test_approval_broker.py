"""Approval correlation, lifecycle, and reconnect behavior without UI dependencies."""

import asyncio

import pytest

from protolink import (
    ActionAuthorizer,
    Agent,
    AgentCard,
    ApprovalBroker,
    ApprovalDecision,
    ApprovalScope,
    CapabilityPolicy,
    RunAction,
    RunContext,
    RunHandle,
    Task,
)
from protolink.storage import SQLiteStorage


async def wait_pending(broker, scope, count=1):
    async with asyncio.timeout(2):
        while len(broker.pending(scope)) != count:
            await asyncio.sleep(0)
    return broker.pending(scope)


@pytest.mark.asyncio
async def test_concurrent_scoped_decisions_duplicates_and_stale(tmp_path):
    broker = ApprovalBroker(storage=SQLiteStorage(str(tmp_path / "approvals.db")))
    authorizer = ActionAuthorizer(CapabilityPolicy(default_effect="require_approval"), broker)
    context = RunContext()
    scope = ApprovalScope(frozenset({context.run_id}))
    tasks = [
        asyncio.create_task(
            authorizer.authorize(RunAction("tool.call", str(i), capabilities=frozenset({"execute"})), context)
        )
        for i in range(2)
    ]
    records = await wait_pending(broker, scope, 2)
    for record in records:
        decision = ApprovalDecision(approved=True, request_id=record.request.request_id)
        assert (
            broker.resolve(decision, scope=ApprovalScope(frozenset()), fingerprint=record.fingerprint).status
            == "unknown"
        )
        assert broker.resolve(decision, scope=scope, fingerprint="old").status == "stale"
        assert broker.resolve(decision, scope=scope, fingerprint=record.fingerprint).status == "approved"
        assert broker.resolve(decision, scope=scope, fingerprint=record.fingerprint).status == "duplicate"
    authorizations = await asyncio.gather(*tasks)
    assert {auth.action.action_id for auth in authorizations} == {record.request.action.action_id for record in records}
    assert broker.pending(scope) == ()
    restarted = ApprovalBroker(storage=broker.storage)
    assert all(record.effect_state == "unknown" for record in restarted.records(scope))
    with pytest.raises(ValueError, match="replayed"):
        await restarted(records[0].request, context)


@pytest.mark.asyncio
async def test_cancel_unblocks_approval_and_never_executes(tmp_path):
    broker = ApprovalBroker(storage=SQLiteStorage(str(tmp_path / "approvals.db")))
    a = Agent(
        AgentCard(name="approval", description="test", url="runtime://approval"),
        policy=CapabilityPolicy(default_effect="require_approval"),
        approval_handler=broker,
        verbosity=0,
    )
    effects = []

    @a.tool(capabilities=["execute"])
    def effect() -> str:
        effects.append(1)
        return "done"

    task = Task.create_tool_call(tool_name="effect", args={})
    context = RunContext.ensure_task_context(task)
    scope = ApprovalScope(frozenset({context.run_id}))
    handle = RunHandle.start(a, task)
    (record,) = await wait_pending(broker, scope)
    # A client can disconnect and reopen its subscription to the same broker.
    stream = broker.events(scope)
    assert (await anext(stream)).request.request_id == record.request.request_id
    await stream.aclose()
    await handle.cancel()
    assert (await handle.result()).status == "canceled"
    decision = ApprovalDecision(approved=True, request_id=record.request.request_id)
    assert broker.resolve(decision, scope=scope, fingerprint=record.fingerprint).status == "already_resolved"
    assert effects == []
    assert broker.records(scope)[0].status == "canceled"


@pytest.mark.asyncio
async def test_expiry_and_orphan_recovery(tmp_path):
    storage = SQLiteStorage(str(tmp_path / "approvals.db"))
    broker = ApprovalBroker(storage=storage, timeout_seconds=0.05)
    context = RunContext()
    scope = ApprovalScope(frozenset({context.run_id}))
    authorizer = ActionAuthorizer(CapabilityPolicy(default_effect="require_approval"), broker)
    task = asyncio.create_task(
        authorizer.authorize(RunAction("tool.call", "example", capabilities=frozenset({"execute"})), context)
    )
    (record,) = await wait_pending(broker, scope)
    recovered = ApprovalBroker(storage=storage)
    assert recovered.records(scope)[0].status == "uncertain"
    decision = ApprovalDecision(approved=True, request_id=record.request.request_id)
    assert recovered.resolve(decision, scope=scope, fingerprint=record.fingerprint).status == "already_resolved"
    from protolink import ActionDeniedError

    with pytest.raises(ActionDeniedError):
        await task
    assert broker.records(scope)[0].status == "expired"


@pytest.mark.asyncio
async def test_mutating_approval_artifact_rejects_execution():
    async def mutate(request, context):
        request.action.payload["arguments"]["value"] = "substituted"
        return True

    authorizer = ActionAuthorizer(CapabilityPolicy(default_effect="require_approval"), mutate)
    with pytest.raises(ValueError, match="changed"):
        await authorizer.authorize(
            RunAction(
                "tool.call", "test", capabilities=frozenset({"execute"}), payload={"arguments": {"value": "original"}}
            ),
            RunContext(),
        )
