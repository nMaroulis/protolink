"""Application-defined acceptance and a maximum of three measurement attempts."""

import asyncio

from protolink import Agent, AgentCard, CompletionCheck, CompletionValidator, Graph, Message, RunReport, Task, TaskState
from protolink.flows import Flow


async def main():
    agent = Agent(
        AgentCard(name="measurements", description="Sample measurements", url="runtime://measurements"), verbosity=0
    )
    readings = iter([3, 7])

    @agent.tool
    def measure() -> int:
        """Return the next application-supplied measurement."""
        return next(readings)

    class Measure(Flow):
        async def execute(self, task):
            task.add_message(Message.tool_call(tool_name="measure", args={}))
            return await agent.run_task(task)

    class Accept(Flow):
        async def execute(self, task):
            validator = CompletionValidator(
                [
                    CompletionCheck(
                        "minimum measurement",
                        lambda evidence: evidence.outcomes[-1].result >= 5,
                    )
                ]
            )
            results = await validator.validate(task)
            task.metadata["accepted"] = all(result.passed for result in results)
            task.begin()
            task.update_state(TaskState.COMPLETED)
            return task

    workflow = Graph(max_iterations=6, max_node_visits={"measure": 3})
    workflow.add_node("measure", Measure()).add_node("accept", Accept())
    workflow.add_edge("measure", "accept")
    workflow.add_conditional_edge(
        "accept",
        lambda task: "done" if task.metadata["accepted"] else "retry",
        {"done": workflow.finish_point, "retry": "measure"},
    )
    workflow.set_entry_point("measure")
    result = await workflow.execute(Task.create(Message.user("Find an acceptable measurement")))
    print(RunReport.from_task(result).validations[-1])
    # If all three attempts fail acceptance, WorkflowLimitError stops traversal.
    # A denied action raises immediately; transport errors never trigger replay.


if __name__ == "__main__":
    asyncio.run(main())
