"""Runtime action, capability policy, and approval regression tests."""

from __future__ import annotations

from typing import Any

import pytest

from protolink import (
    ActionAuthorization,
    ActionAuthorizer,
    ActionDeniedError,
    Agent,
    AgentCard,
    ApprovalDecision,
    ApprovalRequiredError,
    Artifact,
    CapabilityPolicy,
    InMemoryEventSink,
    Part,
    PolicyEffect,
    RunAction,
    RunContext,
    Task,
    create_llm,
)


def test_run_action_and_structured_artifacts_round_trip():
    """Action previews should preserve typed artifact descriptors and correlation."""
    preview = Artifact(
        id="art_preview",
        parts=[Part.text("proposed change")],
        kind="preview",
        name="operation preview",
        uri="memory://preview/1",
        media_type="text/plain",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    action = RunAction(
        action_id="action_round_trip",
        kind="resource.update",
        name="update_record",
        payload={"arguments": {"record_id": "42"}},
        capabilities=frozenset({"records.read", "records.write"}),
        description="Update one generic record",
        metadata={"source": "test"},
        created_at="2026-01-01T00:00:01+00:00",
    ).with_artifacts([preview])

    restored = RunAction.from_dict(action.to_dict())

    assert restored.to_dict() == action.to_dict()
    assert restored.artifacts[0].action_id == "action_round_trip"
    assert restored.artifacts[0].kind == "preview"
    assert restored.artifacts[0].media_type == "text/plain"


@pytest.mark.asyncio
async def test_capability_policy_uses_specific_rules_and_strongest_effect():
    """Deny should outrank approval and allow across required capabilities."""
    policy = CapabilityPolicy(
        {
            "records.*": PolicyEffect.REQUIRE_APPROVAL,
            "records.read": PolicyEffect.ALLOW,
            "records.delete": PolicyEffect.DENY,
        }
    )
    action = RunAction(
        kind="tool.call",
        name="delete_record",
        capabilities=frozenset({"records.read", "records.delete"}),
    )

    decision = await policy.evaluate(action, RunContext(run_id="run_policy"))

    assert decision.effect is PolicyEffect.DENY
    assert decision.matched_capabilities == ("records.delete",)
    assert decision.metadata["sources"] == {
        "records.delete": "policy",
        "records.read": "policy",
    }


@pytest.mark.asyncio
async def test_capability_policy_reads_run_context_permissions():
    """Per-run permission rules should work without a custom policy implementation."""
    action = RunAction(
        kind="tool.call",
        name="publish",
        capabilities=frozenset({"network.send"}),
    )
    context = RunContext(
        run_id="run_context_policy",
        permissions={"capabilities": {"network.*": "require_approval"}},
    )

    decision = await CapabilityPolicy().evaluate(action, context)

    assert decision.effect is PolicyEffect.REQUIRE_APPROVAL
    assert decision.matched_capabilities == ("network.send",)
    assert decision.metadata["sources"]["network.send"] == "context"


@pytest.mark.asyncio
async def test_capability_policy_configuration_round_trip():
    """First-party rules should round-trip through declarative safe data."""
    policy = CapabilityPolicy(
        {
            "records.read": PolicyEffect.DENY,
            "records.write": "require_approval",
            "network.read": False,
            "workspace.read": {
                "effect": PolicyEffect.ALLOW,
                "scope": {"paths": ["/workspace"], "recursive": True},
            },
        },
        default_effect=PolicyEffect.REQUIRE_APPROVAL,
        name="release_policy",
    )

    serialized = policy.to_dict()
    restored = CapabilityPolicy.from_dict(serialized)

    assert serialized == {
        "type": "capability",
        "rules": {
            "records.read": "deny",
            "records.write": "require_approval",
            "network.read": False,
            "workspace.read": {
                "effect": "allow",
                "scope": {"paths": ["/workspace"], "recursive": True},
            },
        },
        "default_effect": "require_approval",
        "name": "release_policy",
    }
    assert restored.rules == serialized["rules"]
    assert restored.default_effect is PolicyEffect.REQUIRE_APPROVAL
    assert restored.name == "release_policy"
    expected_effects = {
        "records.read": PolicyEffect.DENY,
        "records.write": PolicyEffect.REQUIRE_APPROVAL,
        "network.read": PolicyEffect.DENY,
        "workspace.read": PolicyEffect.ALLOW,
        "unmatched.capability": PolicyEffect.REQUIRE_APPROVAL,
    }
    for capability, expected_effect in expected_effects.items():
        decision = await restored.evaluate(
            RunAction(kind="tool.call", name="round_trip", capabilities=frozenset({capability})),
            RunContext(run_id=f"run_{capability}"),
        )
        assert decision.effect is expected_effect


def test_capability_policy_configuration_rejects_executable_type_hints():
    """Policy configuration must never resolve an application object path."""
    with pytest.raises(ValueError, match="Unsupported serialized policy type"):
        CapabilityPolicy.from_dict(
            {
                "type": "python",
                "module": "application.security",
                "class": "CustomPolicy",
            }
        )

    with pytest.raises(ValueError, match="Unsupported policy effect"):
        CapabilityPolicy.from_dict(
            {
                "type": "capability",
                "rules": {"network.read": {"effect": "application.CustomPolicy"}},
            }
        )


@pytest.mark.asyncio
async def test_context_permissions_cannot_weaken_runtime_policy():
    """Caller-provided grants must not override a stricter runtime-owned rule."""
    action = RunAction(
        kind="tool.call",
        name="publish",
        capabilities=frozenset({"network.send"}),
    )
    context = RunContext(
        run_id="run_restricted_policy",
        permissions={"network.send": "allow"},
    )

    decision = await CapabilityPolicy({"network.send": "require_approval"}).evaluate(action, context)

    assert decision.effect is PolicyEffect.REQUIRE_APPROVAL
    assert decision.metadata["sources"]["network.send"] == "policy"


@pytest.mark.asyncio
async def test_action_authorizer_requires_and_records_approval():
    """The authorizer should fail closed or preserve an explicit approval record."""
    action = RunAction(
        action_id="action_approval",
        kind="resource.update",
        name="publish",
        capabilities=frozenset({"network.send"}),
    )
    context = RunContext(run_id="run_approval")
    policy = CapabilityPolicy({"network.send": "require_approval"})

    with pytest.raises(ApprovalRequiredError) as missing_handler:
        await ActionAuthorizer(policy=policy).authorize(action, context)

    assert missing_handler.value.request.action.action_id == "action_approval"
    assert missing_handler.value.request.run_id == "run_approval"

    requests = []

    async def approve(request, _context):
        requests.append(request)
        return ApprovalDecision(
            approved=True,
            request_id=request.request_id,
            reason="Approved in test",
            decided_by="tester",
            decided_at="2026-01-01T00:00:02+00:00",
        )

    authorization = await ActionAuthorizer(policy=policy, approval_handler=approve).authorize(action, context)

    assert requests == [authorization.approval_request]
    assert authorization.approval_decision is not None
    assert authorization.approval_decision.approved is True
    assert authorization.policy_decision.effect is PolicyEffect.REQUIRE_APPROVAL
    assert ActionAuthorization.from_dict(authorization.to_dict()).to_dict() == authorization.to_dict()


@pytest.mark.asyncio
async def test_task_tool_execution_enforces_context_policy_before_side_effect():
    """Task metadata permissions must be enforced at the actual tool boundary."""
    executions: list[str] = []
    agent = Agent(
        AgentCard(name="policy_agent", description="Policy test", url="runtime://policy-agent"),
        verbosity=0,
    )

    @agent.tool(
        name="publish",
        description="Publish a value",
        capabilities=["network.send"],
    )
    def publish(value: str) -> str:
        executions.append(value)
        return value

    task = Task.create_tool_call(tool_name="publish", args={"value": "blocked"})
    RunContext(
        run_id="run_denied_tool",
        permissions={"network.send": False},
    ).attach_to_task(task)

    with pytest.raises(ActionDeniedError):
        await agent.execute_task(task)

    with pytest.raises(ActionDeniedError):
        await agent.call_tool_in_context(
            "publish",
            RunContext(run_id="run_denied_direct", permissions={"network.send": "deny"}),
            value="blocked-direct",
        )

    assert executions == []
    assert task.state.value == "failed"


@pytest.mark.asyncio
async def test_golden_approval_stream_includes_action_artifact_and_policy_events():
    """A model-selected side effect should expose a stable approval lifecycle."""
    executions: list[str] = []
    approval_actions: list[RunAction] = []

    def build_preview(arguments: dict[str, Any], _context: RunContext) -> RunAction:
        preview = Artifact(
            id="art_golden_preview",
            parts=[Part.text(f"publish: {arguments['value']}")],
            kind="preview",
            name="publish preview",
            media_type="text/plain",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        return RunAction(
            action_id="action_golden_approval",
            kind="tool.call",
            name="publish",
            payload={"arguments": arguments},
            capabilities=frozenset({"network.send"}),
            artifacts=(preview,),
            created_at="2026-01-01T00:00:01+00:00",
        )

    async def approve(request, _context):
        approval_actions.append(request.action)
        return ApprovalDecision(
            approved=True,
            request_id=request.request_id,
            decided_by="golden-approver",
            decided_at="2026-01-01T00:00:02+00:00",
        )

    llm = create_llm(
        "mock",
        sequential_responses=[
            {"type": "tool_call", "tool": "publish", "args": {"value": "approved"}},
            {"type": "final", "content": "published"},
        ],
    )
    agent = Agent(
        AgentCard(
            name="approval_agent",
            description="Generic approval golden test",
            url="runtime://approval-agent",
            capabilities={"streaming": True},
        ),
        llm=llm,
        policy=CapabilityPolicy({"network.send": "require_approval"}),
        approval_handler=approve,
        verbosity=0,
    )

    @agent.tool(
        name="publish",
        description="Publish a generic value",
        capabilities=["network.send"],
        action_builder=build_preview,
    )
    def publish(value: str) -> str:
        executions.append(value)
        return f"published:{value}"

    task = Task.create_infer(prompt="publish the value")
    RunContext(run_id="run_golden_approval", session_id="session_golden_approval").attach_to_task(task)
    sink = InMemoryEventSink()

    async for task_event in agent.handle_task_streaming(task):
        await sink.emit_task_event(task_event, context=RunContext.from_task(task))

    stream = sink.to_list()
    llm_events = [
        event["payload"].get("llm_event_type") if event["type"] == "llm.stream" else event["type"]
        for event in stream
        if event["type"] == "llm.stream"
        or event["type"].startswith(("action.", "approval.", "budget.", "context.", "llm.call"))
    ]

    assert llm_events == [
        "llm_step",
        "context.prepared",
        "llm_context",
        "llm.call.started",
        "llm_chunk",
        "llm_call_metrics",
        "llm.call.completed",
        "llm_response",
        "llm_action",
        "action.requested",
        "action.policy",
        "approval.required",
        "approval.decided",
        "action.started",
        "action.completed",
        "llm_step",
        "context.prepared",
        "llm_context",
        "llm.call.started",
        "llm_chunk",
        "llm_call_metrics",
        "llm.call.completed",
        "llm_response",
        "llm_action",
        "llm_final",
    ]
    assert executions == ["approved"]
    assert len(approval_actions) == 1
    assert approval_actions[0].action_id == "action_golden_approval"
    assert approval_actions[0].artifacts[0].to_dict() == {
        "id": "art_golden_preview",
        "parts": [{"type": "text", "content": "publish: approved"}],
        "metadata": {},
        "timestamp": "2026-01-01T00:00:00+00:00",
        "kind": "preview",
        "name": "publish preview",
        "uri": None,
        "media_type": "text/plain",
        "action_id": "action_golden_approval",
    }
    approval_event = next(event for event in stream if event["type"] == "approval.required")
    assert approval_event["severity"] == "warning"
    assert approval_event["payload"]["request"]["action"]["artifacts"][0]["id"] == "art_golden_preview"
