"""Grow from simple calls to controlled runs without changing runtime contracts.

Run: python examples/progressive_control.py
Optional MCP demo: python examples/progressive_control.py --mcp

The default uses only the base package: no provider, account, or ports.
The MCP option needs protolink[mcp] and starts the bundled local demo server.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import BaseModel

from protolink import (
    Agent,
    AgentCard,
    AgentGroup,
    CompletionCheck,
    Pipeline,
    RepeatUntil,
    RunBudget,
    RunContext,
    Step,
    Task,
    ToolStep,
    create_llm,
)
from protolink.transport import RuntimeTransport, TransportConfig, TransportLimits


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


class ReleasePlan(BaseModel):
    """A response contract validated independently of the model provider."""

    version: str
    steps: list[str]


async def main(*, mcp: bool = False) -> None:
    """Demonstrate each convenience layer and retain access to complete tasks."""
    agent = Agent(
        AgentCard(name="helper", description="Demonstrates progressive control", url="runtime://helper"),
        transport="runtime",
        llm=create_llm("mock", default_response="Ready to help."),
        verbosity=0,
    )
    agent.add_tools([add])
    print("Tool:", await agent.call_tool("add", a=2, b=3))
    print("Answer:", await agent.invoke("Hello"))

    # Keep the complete Task when you need state, artifacts, or correlation IDs.
    tool_task = Task.create_tool_call("add", {"a": 2, "b": 3}, budget=RunBudget(max_tool_calls=1))
    tool_result = await agent.run_task(tool_task)
    print("Task output:", tool_result.raise_for_status().get_output())
    part = tool_result.get_last_part()
    if part is not None and part.type == "tool_output":
        print("Tool call ID:", part.as_tool_output().call_id)

    infer_task = Task.create_infer("Hello again", session_id="planning")
    print("Before execution:", infer_task.get_output("No answer yet"))
    infer_result = await agent.run_task(infer_task)
    print("Inference task:", infer_result.raise_for_status().get_output())
    # Task.create("text") creates plain user text for a custom handler, not an infer instruction.

    # Add just the controls you need. The context remains application-owned.
    print(
        "Controlled:",
        await agent.invoke(
            "Give a concise answer",
            budget=RunBudget(max_llm_calls=1),
            context=RunContext(session_id="release-planning", permissions={"files.write": "deny"}),
        ),
    )

    handle = agent.start_run("Stream a greeting")
    print("Raw model chunks: ", end="")
    async for chunk in handle.chunks():
        print(chunk, end="", flush=True)
    result = await handle.result()
    print("\nFinal answer:", result.output)
    print("Run:", result.status, "Events:", len(result.report.events))
    # handle.events() exposes all typed events; await handle.cancel() stops work.

    def label(task: Task) -> Task:
        """Adapt an ordinary function into a deterministic flow step."""
        return task.complete(f"Reviewed: {task.get_last_part_content()}")

    flow = Pipeline([agent, Step(label)])
    print("Flow:", await flow.invoke("Draft a release note"))

    readings = iter([3, 7])

    @agent.tool
    def measure() -> int:
        """Return the next deterministic sample."""
        return next(readings)

    measurements = RepeatUntil(
        ToolStep(agent, "measure"),
        CompletionCheck("minimum", lambda evidence: evidence.outcomes[-1].result >= 5),
        max_attempts=3,
    )
    measurement = await measurements.invoke("Find a measurement", budget=RunBudget(max_tool_calls=3))
    print("Accepted measurement:", measurement.result)

    agent.llm = create_llm("mock", default_response='{"version":"0.7.4","steps":["test","document"]}')
    plan = await agent.invoke_typed("Prepare a release plan", ReleasePlan)
    print("Typed response:", plan.version, plan.steps)
    # max_attempts=2 explicitly permits one validation repair, which may rerun tools.
    # Use run_task(Task.create_infer(...)) when you need every task field.

    if mcp:
        server = Path(__file__).parent / "mcp" / "mcp_server.py"
        await agent.add_mcp(command=sys.executable, args=[str(server)], include=["add"], prefix="mcp_")
        print("MCP tool:", await agent.call_tool("mcp_add", a=2, b=3))

    # The helper uses an alias; the caller supplies a configured transport object.
    # HTTP follows the same pattern: transport="http" or HTTPTransport(url=card.url, ...).
    caller_card = AgentCard(name="caller", description="Calls the helper", url="runtime://caller")
    transport = RuntimeTransport(
        url=caller_card.url,
        config=TransportConfig(limits=TransportLimits(max_concurrent_requests=10)),
    )
    caller = Agent(
        caller_card,
        transport=transport,
        verbosity=0,
    )
    async with AgentGroup([agent, caller]):
        peer = caller.peer(agent.card)
        print("Peer tool:", await peer.call_tool("add", a=10, b=20))
        print("Peer answer:", await peer.invoke("Hello from another agent"))
    # Use caller.peer("helper") when a registry is configured, or bind a URL.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp", action="store_true", help="Also discover tools from the bundled MCP server")
    asyncio.run(main(mcp=parser.parse_args().mcp))
