"""Application-defined acceptance with at most three measurement attempts."""

import asyncio

from protolink import Agent, AgentCard, CompletionCheck, RepeatUntil, RunReport, Task, ToolStep


async def main() -> None:
    """Repeat a normal tool task until its execution evidence passes a check."""
    agent = Agent(
        AgentCard(name="measurements", description="Sample measurements", url="runtime://measurements"), verbosity=0
    )
    readings = iter([3, 7])

    @agent.tool
    def measure() -> int:
        """Return the next application-supplied measurement."""
        return next(readings)

    workflow = RepeatUntil(
        ToolStep(agent, "measure"),
        CompletionCheck("minimum measurement", lambda evidence: evidence.outcomes[-1].result >= 5),
        max_attempts=3,
    )
    result = await workflow.execute(Task.create_infer(prompt="Find an acceptable measurement"))
    print(RunReport.from_task(result).validations[-1])
    # Exhaustion raises WorkflowLimitError. Execution errors never trigger replay.
    # Use Graph with explicit edges for custom branching, repair, or routing.


if __name__ == "__main__":
    asyncio.run(main())
