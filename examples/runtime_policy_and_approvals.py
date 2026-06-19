"""Runtime actions, capability policy, approvals, and events.

This provider-free example demonstrates the Phase 2 runtime lifecycle:

1. A mock model requests a tool call.
2. Protolink validates the tool arguments and prepares a ``RunAction``.
3. The tool's ``action_builder`` attaches a structured preview artifact.
4. ``CapabilityPolicy`` requires approval for the declared capability.
5. The application-owned approval handler renders the request and approves it.
6. Protolink executes the tool and emits normalized ``RunEvent`` objects.
7. A second run is denied by ``RunContext.permissions`` before the tool executes.

The example uses generic records rather than coding-specific concepts. The same
contracts can represent database mutations, browser actions, outbound messages,
file operations, business workflows, or any other application side effect.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    CapabilityPolicy,
    InMemoryEventSink,
    Part,
    RunAction,
    RunContext,
    Task,
    create_llm,
)

# This dictionary stands in for any mutable external system. Keeping it local
# makes the example deterministic and lets us prove that denied actions do not run.
RECORDS = {
    "record-42": {
        "status": "draft",
        "title": "Quarterly summary",
    }
}


def build_update_preview(arguments: dict[str, Any], context: RunContext) -> RunAction:
    """Prepare the concrete action and a preview for the approval interface.

    ``action_builder`` runs after argument validation but before policy
    evaluation or tool execution. It is application code: Protolink does not
    need to know what a record or status means.
    """
    record_id = arguments["record_id"]
    new_status = arguments["status"]
    current_status = RECORDS[record_id]["status"]

    preview = Artifact(
        kind="preview",
        name=f"Update {record_id}",
        media_type="application/json",
        parts=[
            Part.json(
                {
                    "record_id": record_id,
                    "before": {"status": current_status},
                    "after": {"status": new_status},
                }
            )
        ],
        metadata={"purpose": "approval_preview"},
    )

    return RunAction(
        kind="record.update",
        name="update_record_status",
        payload={"arguments": arguments},
        artifacts=(preview,),
        description=f"Change {record_id} from {current_status} to {new_status}",
        metadata={"prepared_for_run": context.run_id},
    )


async def approve_action(request: ApprovalRequest, context: RunContext) -> ApprovalDecision:
    """Render an approval request and return the application's decision.

    A real CLI could pause for keyboard input here; a web application could
    await a UI response; a service could consult a separate approval system.
    Protolink only requires a correlated ``ApprovalDecision``.
    """
    print("\nApproval checkpoint")
    print(f"  Run: {context.run_id}")
    print(f"  Action: {request.action.name}")
    print(f"  Reason: {request.policy_decision.reason}")

    for artifact in request.action.artifacts:
        print(f"  Preview ({artifact.name}):")
        for part in artifact.parts:
            print(json.dumps(part.content, indent=4, sort_keys=True))

    # The example approves deterministically so it can run in tests. Replace
    # this with an interactive or remote decision in a real application.
    return ApprovalDecision(
        approved=True,
        request_id=request.request_id,
        reason="Approved by the example application",
        decided_by="example-operator",
    )


async def main() -> None:
    """Run one approved model action and one denied direct action."""
    llm = create_llm(
        "mock",
        sequential_responses=[
            {
                "type": "tool_call",
                "tool": "update_record_status",
                "args": {"record_id": "record-42", "status": "published"},
            },
            {"type": "final", "content": "The record was published."},
        ],
    )

    agent = Agent(
        AgentCard(
            name="record_agent",
            description="Updates generic records",
            url="runtime://record-agent",
            capabilities={"streaming": True},
        ),
        llm=llm,
        policy=CapabilityPolicy(
            {
                "records.read": "allow",
                "records.write": "require_approval",
                "records.delete": "deny",
            }
        ),
        approval_handler=approve_action,
        verbosity=0,
    )

    @agent.tool(
        name="update_record_status",
        description="Update the status of one record",
        capabilities=["records.write"],
        action_builder=build_update_preview,
    )
    def update_record_status(record_id: str, status: str) -> dict[str, str]:
        """Apply the side effect after Protolink has authorized the action."""
        RECORDS[record_id]["status"] = status
        return {"record_id": record_id, "status": status}

    print("Initial record:", RECORDS["record-42"])

    # Context permissions say "allow", but they cannot weaken the agent's
    # stricter runtime-owned "require_approval" policy.
    task = Task.create_infer(prompt="Publish record-42")
    RunContext(
        run_id="run_approved_example",
        session_id="session_runtime_example",
        permissions={"records.write": "allow"},
        metadata={"source": "example"},
    ).attach_to_task(task)

    sink = InMemoryEventSink()
    async for task_event in agent.handle_task_streaming(task):
        await sink.emit_task_event(task_event, context=RunContext.from_task(task))

    print("\nNormalized action events")
    for event in sink.events:
        if event.type.startswith(("action.", "approval.")):
            print(f"  {event.sequence:02d}  {event.type:<20} {event.summary}")

    print("\nRecord after approved run:", RECORDS["record-42"])

    # A per-run deny is more restrictive than the agent policy. The approval
    # handler is not called and the tool body never executes.
    denied_context = RunContext(
        run_id="run_denied_example",
        permissions={"records.write": "deny"},
    )
    try:
        await agent.call_tool_in_context(
            "update_record_status",
            denied_context,
            record_id="record-42",
            status="archived",
        )
    except ActionDeniedError as exc:
        print("\nDenied action")
        print(f"  {exc}")

    print("Record after denied run:", RECORDS["record-42"])


if __name__ == "__main__":
    asyncio.run(main())
