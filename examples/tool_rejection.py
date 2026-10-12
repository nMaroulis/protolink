"""Correct a no-change tool rejection inside one agent run, entirely offline.

Run with ``python examples/tool_rejection.py`` from an installed checkout.
The scripted model first selects an unavailable check, receives the tool's
valid IDs, then proposes an accepted selection. Only the accepted request
changes the plan. Replace MockLLM with a configured provider in an application.
"""

from __future__ import annotations

import asyncio

from protolink import Agent, RunBudget, ToolRejectedError, create_llm


async def main() -> None:
    """Show structured correction feedback and distinct execution outcomes."""
    checks = {"lint": "Check source style", "tests": "Run the test suite"}
    plan: list[str] = []

    def plan_task(check_id: str) -> dict[str, str]:
        """Select a known check; reject unknown IDs before changing the plan."""
        if check_id not in checks:
            raise ToolRejectedError(
                "Unknown check selection.",
                code="invalid_check_selection",
                details={"valid_ids": list(checks)},
                suggestion="Select one of the advertised check IDs.",
            )
        plan.append(check_id)
        return {"check_id": check_id, "description": checks[check_id]}

    llm = create_llm(
        "mock",
        max_tool_corrections=2,
        sequential_responses=[
            {"type": "tool_call", "tool": "plan_task", "args": {"check_id": "unknown"}},
            {"type": "tool_call", "tool": "plan_task", "args": {"check_id": "lint"}},
            "Planned the lint check.",
        ],
    )
    agent = Agent(name="planner", llm=llm, tools=[plan_task], verbosity=0)
    handle = agent.start_run("Choose a check.", budget=RunBudget(max_llm_calls=3, max_tool_calls=2))
    async for event in handle.events():
        if event.type == "action.rejected":
            print(event.summary)
            print(event.payload["rejection"])
    result = await handle.result()
    assert result.status == "completed", result.error
    assert plan == ["lint"]
    print(result.output)
    print(f"Accepted plan: {plan}")


if __name__ == "__main__":
    asyncio.run(main())
