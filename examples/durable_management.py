"""Manage a stopped question through a reusable application factory.

Run ``python examples/durable_management.py`` from the repository root to create
a pending request. Then inspect it with ``protolink run pending --durability
managed-runs.sqlite --json`` or open ``protolink dashboard --factory
examples.durable_management:application``. The factory reconstructs the same
tools/model contract; the model callback derives its next action from history.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from protolink import Agent, RunInterrupted, RunManager
from protolink.llms import MockLLM
from protolink.tools import ask_user_tool


def application(path: str | Path = "managed-runs.sqlite") -> Agent:
    """Reconnect the application's private checkpoint file and executable tools."""

    def respond(history, prompt):
        if any(message["content"].startswith('{"type": "tool_result"') for message in history.messages):
            return "The requested format is recorded."
        return {"type": "tool_call", "tool": "ask_user", "args": {"question": "Which export format?"}}

    return Agent(
        name="managed-example",
        llm=MockLLM(response_callback=respond),
        tools=[ask_user_tool()],
        durability=path,
        verbosity=0,
    )


async def main(path: str | Path = "managed-runs.sqlite") -> None:
    """Save a question and print the IDs used by the CLI or authenticated UI."""
    agent = application(path)
    try:
        await agent.invoke("Choose an export format")
    except RunInterrupted as pause:
        print(RunManager(agent).inspect(pause.run_id))
        print("Continue this request in the dashboard, or use run resume with its request ID and answer.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durability", default="managed-runs.sqlite", help="Demo checkpoint file")
    asyncio.run(main(parser.parse_args().durability))
