"""Owned local specialists with the existing agent_call action; no server or API key.

Run from a source checkout: uv run python examples/subagents.py
Replace MockLLM with your preferred provider when using a real model.
"""

import asyncio

from protolink import Agent, RunBudget
from protolink.llms import MockLLM


async def main() -> None:
    researcher = Agent(
        name="researcher",
        description="Find the evidence needed for a short answer.",
        llm=MockLLM(default_response="Evidence: ProtoLink supports local and remote agents."),
        verbosity=0,
    )
    assistant = Agent(
        name="assistant",
        llm=MockLLM(
            sequential_responses=[
                {"type": "agent_call", "agent": "researcher", "action": "infer", "prompt": "Find ProtoLink evidence."},
                "ProtoLink can run agents locally and communicate with remote agents.",
            ]
        ),
        subagents=[researcher],
        verbosity=0,
    )
    run = assistant.start_run("Explain ProtoLink", budget=RunBudget(max_llm_calls=4))
    result = await run.result()
    result.task.raise_for_status()
    print(result.output)
    print("Owned child:", result.task.metadata["subagent_runs"][0]["agent"])


if __name__ == "__main__":
    asyncio.run(main())
