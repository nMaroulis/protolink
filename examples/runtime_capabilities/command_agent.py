"""A tool-only command agent with an application-owned approval callback."""

import asyncio
import sys
import tempfile

from protolink import Agent, AgentCard, ApprovalDecision, CapabilityPolicy
from protolink.tools.builtins import process_tool


async def approve(request, context):
    # Replace this application decision with your authenticated UI adapter.
    print(request.action.artifacts[0].to_dict())
    return ApprovalDecision(approved=True, request_id=request.request_id, decided_by="example")


async def main():
    agent = Agent(
        AgentCard(name="commands", description="Explicit command execution", url="runtime://commands"),
        policy=CapabilityPolicy({"process.execute": "require_approval"}),
        approval_handler=approve,
        verbosity=0,
    )
    agent.add_tool(process_tool())  # Registration executes nothing; no LLM needed.
    with tempfile.TemporaryDirectory() as directory:
        result = await agent.call_tool(
            "execute_command",
            argv=[sys.executable, "-c", "print('hello')"],
            cwd=directory,
            env={},
        )
    print(result.exit_code, result.stdout.strip())


if __name__ == "__main__":
    asyncio.run(main())
