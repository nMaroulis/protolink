"""Built-in starter templates used by the Protolink CLI.

Templates are stored as plain strings to keep the scaffolding path dependency
free: the CLI can create runnable starter files without importing optional LLM,
HTTP, or MCP providers. Each template should remain a complete Python module
that demonstrates the public top-level API.
"""

from __future__ import annotations

AGENT_TEMPLATE = '''"""Starter Protolink agent.

Run:
    uv run python agent.py

Set OPENAI_API_KEY to enable LLM inference. Without it, the starter still
executes the local tool call path so the file is runnable immediately.
"""

from __future__ import annotations

import asyncio
import os

from protolink import Agent, AgentCard, LocalTraceTelemetry, Task, create_llm


def build_agent() -> Agent:
    """Create a local runtime agent with optional LLM inference.

    The starter defaults to a tool-call path that runs without credentials.
    When OPENAI_API_KEY is present, it also wires an OpenAI-backed LLM and
    enables session conversation state.
    """
    llm = None
    if os.environ.get("OPENAI_API_KEY"):
        llm = create_llm(
            "openai",
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )

    agent = Agent(
        card=AgentCard(
            name="starter_agent",
            description="A starter Protolink agent with one local tool.",
            url="runtime://starter-agent",
        ),
        transport="runtime",
        llm=llm,
        state=["conversation"] if llm else None,
        telemetry=LocalTraceTelemetry(),
        verbosity=1,
    )

    @agent.tool(name="add", description="Add two integers")
    async def add(a: int, b: int) -> int:
        """Return the sum of two integers."""
        return a + b

    return agent


async def main() -> None:
    """Run the starter agent once and print the latest trace ID."""
    agent = build_agent()

    if agent.llm:
        response = await agent.invoke("Use the add tool to calculate 21 + 21.")
        print(response)
    else:
        task = Task.create_tool_call(tool_name="add", args={"a": 21, "b": 21})
        result = await agent.handle_task(task)
        print(result.get_last_part_content())

    if isinstance(agent.telemetry, LocalTraceTelemetry):
        print(agent.telemetry.recorder.replay()[-1]["trace_id"])


if __name__ == "__main__":
    asyncio.run(main())
'''

TOOL_AGENT_TEMPLATE = '''"""Tool-first Protolink agent starter.

Run:
    uv run python tool_agent.py
"""

from __future__ import annotations

import asyncio

from protolink import Agent, AgentCard, LocalTraceTelemetry, Task


agent = Agent(
    card=AgentCard(
        name="tool_agent",
        description="A local tool agent.",
        url="runtime://tool-agent",
    ),
    transport="runtime",
    telemetry=LocalTraceTelemetry(),
)


@agent.tool(name="multiply", description="Multiply two integers")
async def multiply(a: int, b: int) -> int:
    """Return the product of two integers."""
    return a * b


async def main() -> None:
    """Execute the local tool agent once and print the latest trace ID."""
    task = Task.create_tool_call(tool_name="multiply", args={"a": 6, "b": 7})
    result = await agent.handle_task(task)
    print(result.get_last_part_content())
    print(agent.telemetry.recorder.replay()[-1]["trace_id"])


if __name__ == "__main__":
    asyncio.run(main())
'''

TEMPLATES = {
    "basic": AGENT_TEMPLATE,
    "tool": TOOL_AGENT_TEMPLATE,
}

__all__ = ["AGENT_TEMPLATE", "TEMPLATES", "TOOL_AGENT_TEMPLATE"]
