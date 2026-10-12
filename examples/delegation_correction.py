"""Recover a mistaken Planner tool request without a server or a live model.

Run with ``python examples/delegation_correction.py`` from an installed checkout.
The scripted coordinator first invents a Planner tool, receives capability
feedback, then delegates inference correctly. The bad request creates no child
and consumes no tool call. Real providers use the same validation boundaries;
scripted responses demonstrate behavior rather than live-model reliability.
"""

from __future__ import annotations

import asyncio

from protolink import Agent, RunBudget, create_llm


async def main() -> None:
    """Demonstrate automatic validation using the existing Agent API."""
    planner = Agent(
        name="planner", llm=create_llm("mock", default_response="Add clear function docstrings."), verbosity=0
    )
    coordinator = Agent(
        name="coordinator",
        subagents=[planner],
        llm=create_llm(
            "mock",
            max_tool_corrections=2,
            sequential_responses=[
                {
                    "type": "agent_call",
                    "agent": "planner",
                    "action": "tool_call",
                    "tool": "tool_call",
                    "args": {"task_description": "Suggest docstrings."},
                },
                {"type": "agent_call", "agent": "planner", "action": "infer", "prompt": "Suggest docstrings."},
                "The Planner recommends clear function docstrings.",
            ],
        ),
        verbosity=0,
    )
    handle = coordinator.start_run("Ask the Planner.", budget=RunBudget(max_llm_calls=4, max_tool_calls=0))
    async for event in handle.events():
        if event.payload.get("llm_event_type") == "agent_call_rejected":
            print(event.summary)
            print(event.payload["rejection"]["suggestion"])
    result = await handle.result()
    assert result.status == "completed", result.error
    assert len(result.task.metadata["subagent_runs"]) == 1
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
