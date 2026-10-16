"""Typed workers, live activity, preparation correction and bounded continuation.

Run ``python examples/worker_execution.py`` from an installed checkout.
Every model response is scripted; no API key, server or external service is used.
Only the temporary SQLite checkpoint file is written to disk.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from protolink import Agent, RunAction, RunBudget, RunContext, RunHandoff, Task, ToolRejectedError
from protolink.llms import MockLLM
from protolink.tools.prepared import PreparedTool


async def typed_worker() -> None:
    """Expose one child's typed tool and consume its activity while it runs."""

    async def lookup_customer(customer_id: int) -> dict[str, str]:
        """Look up a customer in the application's local sample data."""
        return {"name": "Ada", "plan": "team"}

    worker = Agent(name="customers", tools=[lookup_customer], verbosity=0)
    parent = Agent(
        name="assistant",
        subagents=[worker],
        llm=MockLLM(
            sequential_responses=[
                {"type": "tool_call", "tool": "lookup_customer", "args": {"customer_id": 7}},
                "Ada uses the team plan.",
            ]
        ),
        verbosity=0,
    )
    parent.add_worker_tool("customers", tool="lookup_customer", name="lookup_customer")
    handle = parent.start_run("Find customer 7.", budget=RunBudget(max_tool_calls=1, max_llm_calls=2))
    child_events = []
    async for event in handle.events():
        if event.agent_name == "customers":
            child_events.append(event)
            print("Child activity:", event.type, event.agent_name)
    result = await handle.result()
    assert result.status == "completed", result.error
    assert child_events
    print(result.output)


async def bounded_work(directory: Path) -> None:
    """Correct preparation, yield after settled work and explicitly continue."""
    saved: list[str] = []

    def save_check(check_id: str) -> str:
        """Save one valid check to the application's sample plan."""
        raise AssertionError("PreparedTool uses this signature only for its schema")

    def prepare(arguments, context):
        if arguments["check_id"] not in {"lint", "tests"}:
            raise ToolRejectedError(
                "Unknown check.",
                code="invalid_check",
                details={"valid_ids": ["lint", "tests"]},
                suggestion="Choose a valid check ID.",
            )
        return RunAction(kind="tool.call", name="save_check", payload={"arguments": arguments})

    async def execute(execution):
        execution.check()
        check_id = execution.authorization.action.payload["arguments"]["check_id"]
        saved.append(check_id)
        return f"Saved {check_id}."

    tool = PreparedTool(save_check, prepare=prepare, execute=execute, capabilities=("plan.save",))
    agent = Agent(
        name="planner",
        tools=[tool],
        llm=MockLLM(
            sequential_responses=[
                {"type": "tool_call", "tool": "save_check", "args": {"check_id": "unknown"}},
                {"type": "tool_call", "tool": "save_check", "args": {"check_id": "lint"}},
                {"type": "tool_call", "tool": "save_check", "args": {"check_id": "tests"}},
                "Saved both checks.",
            ]
        ),
        durability=directory / "runs.sqlite",
        yield_after_steps=2,
        verbosity=0,
    )
    context = RunContext(budget=RunBudget(max_steps=5, max_llm_calls=5, max_tool_calls=2))
    task = Task.create_infer("Save lint and tests.", context=context)
    task = await agent.run_task(task)
    handoff = RunHandoff.from_task(task)
    assert handoff is not None and handoff.steps == 2
    assert handoff.usage.tool_calls == 1  # Preparation rejection executed no tool.
    assert len(handoff.completed_action_ids) == 1
    print("Yielded progress:", handoff.to_dict())
    assert saved == ["lint"]

    # The application reviews progress and explicitly grants one more slice.
    # Retain the ROOT context ID even when a nested worker supplies the handoff.
    task = await agent.resume_task(context.run_id)
    task.raise_for_status()
    assert saved == ["lint", "tests"]  # The first effect was not repeated.
    assert RunHandoff.from_task(task) is None
    print(task.get_output())


async def main() -> None:
    """Run both examples with bounded budgets and temporary persistence."""
    await typed_worker()
    with TemporaryDirectory(prefix="protolink-worker-demo-") as directory:
        await bounded_work(Path(directory))


if __name__ == "__main__":
    asyncio.run(main())
