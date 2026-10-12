"""Run the real Ollama action adapter against scripted responses, entirely offline.

Run with ``python examples/action_correction.py`` from an installed checkout.
The example performs one tool, receives an invalid tool-call wrapper, then
corrects the next response without repeating the tool. It demonstrates both
portable JSON actions and automatic native-tool selection. Scripted responses
verify the runtime contract; they do not measure a real model's reliability.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from protolink import Agent
from protolink.llms import ToolCallingMode
from protolink.llms.server.ollama_client import OllamaLLM


class ScriptedOllama(OllamaLLM):
    """Replace model HTTP responses while retaining adapter and runtime logic."""

    def validate_connection(self) -> bool:
        """This offline adapter has no server to validate."""
        return True

    def discover_tool_calling(self) -> bool:
        """Supply the capability a real server would advertise through metadata."""
        return True

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a tool request, malformed proposal, then a corrected answer."""
        step = len([message for message in payload["messages"] if message["role"] == "assistant"])
        correction_present = any(
            "not a dispatchable ProtoLink action" in str(message["content"]) for message in payload["messages"]
        )
        if correction_present:
            content = json.dumps({"type": "final", "content": "The saved observation is result-E1."})
        elif step:
            content = json.dumps({"tool_call": {"name": "lookup", "arguments": {"key": "docs"}}})
        elif "tools" in payload:
            return {"message": {"tool_calls": [{"function": {"name": "lookup", "arguments": {"key": "docs"}}}]}}
        else:
            content = json.dumps({"type": "tool_call", "tool": "lookup", "args": {"key": "docs"}})
        return {"message": {"content": content}}


async def run_example(mode: ToolCallingMode) -> None:
    """Check one protocol without sharing tool state between runs."""
    calls: list[str] = []

    def lookup(key: str) -> str:
        """Return an observation that subsequent model steps can reuse."""
        calls.append(key)
        return "result-E1"

    llm = ScriptedOllama(base_url="http://localhost:11434", model="scripted", tool_calling=mode)
    agent = Agent(name="helper", llm=llm, tools=[lookup], verbosity=0)
    answer = await agent.invoke("Look up docs, then explain the result.")
    assert calls == ["docs"], f"A completed tool was repeated: {calls}"
    print(f"{mode} -> {llm.resolve_tool_calling()}: {answer} (tool executions: {len(calls)})")


async def main() -> None:
    """Recover in both protocols while checking the completed tool ran once."""
    await run_example("json")
    await run_example("auto")


if __name__ == "__main__":
    asyncio.run(main())
