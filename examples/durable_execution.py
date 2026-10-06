"""Pause, exit and resume through three separate application invocations.

uv run python examples/durable_execution.py start --directory /tmp/protolink-demo
uv run python examples/durable_execution.py approve --directory /tmp/protolink-demo
uv run python examples/durable_execution.py answer --directory /tmp/protolink-demo --answer CSV

All files belong to this explicit demo directory. No API key or network is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from protolink import Agent, CapabilityPolicy, RunInterrupted
from protolink.llms import MockLLM
from protolink.tools import Tool, ask_user_tool


def make_agent(directory: Path) -> Agent:
    def save_note(text: str) -> str:
        """Save one note in the application's demo directory."""
        with (directory / "notes.txt").open("a", encoding="utf-8") as file:
            file.write(text + "\n")
        return "Note saved"

    def choose_action(history, _system_prompt):
        observations = {}
        for message in history.messages:
            try:
                content = json.loads(message.get("content", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(content, dict) and content.get("type") == "tool_result":
                observations[content["tool"]] = content["result"]
        if "save_note" not in observations:
            return {"type": "tool_call", "tool": "save_note", "args": {"text": "Hello from ProtoLink v0.8.0"}}
        if "ask_user" not in observations:
            return {"type": "tool_call", "tool": "ask_user", "args": {"question": "Which export format?"}}
        answer = observations["ask_user"]["answer"]
        return f"Note saved once. Export preference: {answer}."

    return Agent(
        name="assistant",
        llm=MockLLM(response_callback=choose_action),
        tools=[Tool.from_callable(save_note, capabilities=["notes.write"]), ask_user_tool()],
        policy=CapabilityPolicy({"notes.write": "require_approval"}),
        durability=directory / "runs.sqlite",
        execution_version="demo-1",
        verbosity=0,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["start", "approve", "answer"])
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--answer")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    pending_file = args.directory / "pending.json"
    agent = make_agent(args.directory)
    try:
        if args.phase == "start":
            result = await agent.invoke("Save a note, then ask my export preference.")
        else:
            pending = json.loads(pending_file.read_text(encoding="utf-8"))
            response = {"approved": True} if args.phase == "approve" else {"answer": args.answer}
            result = await agent.resume(
                pending["root_run_id"], request_id=pending["request_id"], fingerprint=pending["fingerprint"], **response
            )
        print(result)
        pending_file.unlink(missing_ok=True)
    except RunInterrupted as pause:
        pending = {**pause.interruption.to_dict(), "root_run_id": pause.run_id}
        pending_file.write_text(json.dumps(pending, indent=2), encoding="utf-8")
        print(f"Paused for {pause.interruption.kind}. The application can exit now.")
        print(json.dumps(pause.interruption.request, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Run the complete restart demonstration in a temporary application directory.
        with tempfile.TemporaryDirectory(prefix="protolink-durable-demo-") as demo_directory:
            for phase in ("start", "approve", "answer"):
                command = [sys.executable, __file__, phase, "--directory", demo_directory]
                if phase == "answer":
                    command += ["--answer", "CSV"]
                subprocess.run(command, check=True, timeout=15)
            assert (Path(demo_directory) / "notes.txt").read_text().count("Hello") == 1
    else:
        asyncio.run(main())
