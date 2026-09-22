"""A local research/summarize pipeline; no registry, ports, provider, or API key.

Run: python examples/structured_flows/pipeline.py

For distributed execution, supply client/registry and replace Agent instances
with remote URLs or registered names. The Flow API stays the same.
"""

import asyncio

from protolink import Agent, AgentCard, Pipeline, Task, create_llm


async def main() -> None:
    """Start with a prompt; use execute(Task) when complete history is needed."""
    researcher = Agent(
        AgentCard(name="researcher", description="Gather facts", url="runtime://researcher"),
        llm=create_llm("mock", default_response="ProtoLink agents compose tools and communicate through tasks."),
        system_prompt="Gather useful facts for the next agent.",
        verbosity=0,
    )
    summarizer = Agent(
        AgentCard(name="summarizer", description="Summarize facts", url="runtime://summarizer"),
        llm=create_llm("mock", default_response="ProtoLink supports modular, task-based agent workflows."),
        system_prompt="Summarize the research concisely.",
        verbosity=0,
    )
    pipeline = Pipeline([researcher, summarizer])
    print("Answer:", await pipeline.invoke("Research agentic computing"))

    # The explicit Task API remains available for intermediate messages/artifacts.
    result = await pipeline.execute(Task.create_infer(prompt="Research agentic computing"))
    result.raise_for_status()
    print("Task:", result.state.value, "Artifacts:", len(result.artifacts))


if __name__ == "__main__":
    asyncio.run(main())
