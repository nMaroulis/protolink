"""Resolve approvals from a separate application adapter coroutine."""

import asyncio
import sys
import tempfile

from protolink import (
    Agent,
    AgentCard,
    ApprovalBroker,
    ApprovalDecision,
    ApprovalScope,
    CapabilityPolicy,
    RunContext,
    RunHandle,
    Task,
)
from protolink.tools.builtins import process_tool


async def adapter(broker, scope):
    async for record in broker.events(scope):
        if record.status == "pending":
            # The application authenticates the caller and chooses the scope.
            # The request ID plus fingerprint come from the displayed preview.
            print(record.request.action.name)
            broker.resolve(
                ApprovalDecision(approved=True, request_id=record.request.request_id),
                scope=scope,
                fingerprint=record.fingerprint,
            )
            return


async def main():
    broker = ApprovalBroker(timeout_seconds=30)
    agent = Agent(
        AgentCard(name="approved", description="Application approvals", url="runtime://approved"),
        policy=CapabilityPolicy({"process.execute": "require_approval"}),
        approval_handler=broker,
        verbosity=0,
    )
    agent.add_tool(process_tool())
    with tempfile.TemporaryDirectory() as directory:
        task = Task.create_tool_call(
            tool_name="execute_command",
            args={
                "argv": [sys.executable, "-c", "print('approved')"],
                "cwd": directory,
                "env": {},
            },
        )
        context = RunContext.ensure_task_context(task)
        scope = ApprovalScope(frozenset({context.run_id}))
        ui = asyncio.create_task(adapter(broker, scope))
        result = await RunHandle.start(agent, task).result()
        await ui
        print(result.status)


if __name__ == "__main__":
    asyncio.run(main())
