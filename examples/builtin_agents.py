"""Exercise the specialist presets offline using actual tool results.

Run: python examples/builtin_agents.py

The scripted models select tools and format their returned evidence. Web data
comes from fixtures; the database and workspace live in a temporary directory.
Replace the models and provider tools to connect the same presets to your app.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from protolink import DatabaseAgent, Document, EchoAgent, ExplorerAgent, KnowledgeAgent, ResearchAgent
from protolink.llms import MockLLM
from protolink.tools import SQLiteDatabase, Tool


def model_for(tool: str, arguments: dict[str, Any], render: Callable[[Any], str]) -> MockLLM:
    """Select one tool, then format its real result through the inference loop."""

    def respond(history, _system_prompt):
        for message in reversed(history.messages):
            if message.get("role") != "system":
                continue
            try:
                payload = json.loads(str(message.get("content", "")))
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "tool_result" and payload.get("tool") == tool:
                return {"type": "final", "content": render(payload["result"])}
        return {"type": "tool_call", "tool": tool, "args": arguments}

    return MockLLM(response_callback=respond)


async def main() -> None:
    echo = EchoAgent(verbosity=0)
    assert await echo.invoke("  Hello\n") == "  Hello\n"
    print("Echo: exact input preserved")

    def fixture_search(query: str) -> dict[str, Any]:
        """Return one offline source; production tools may use any provider."""
        return {
            "query": query,
            "results": [
                {"title": "ProtoLink fixture", "url": "https://example.com/guide", "snippet": "Tools are reusable."}
            ],
            "untrusted_content": True,
        }

    def fixture_fetch(url: str) -> dict[str, Any]:
        """Return bounded fixture text without contacting the URL."""
        return {"url": url, "text": "Tools are reusable across ordinary agents and presets.", "untrusted_content": True}

    source = "https://example.com/guide"
    researcher = ResearchAgent(
        search_tool=Tool.from_callable(fixture_search, name="web_search", capabilities=["network.read"]),
        fetch_tool=Tool.from_callable(fixture_fetch, name="fetch_url", capabilities=["network.read"]),
        llm=model_for("fetch_url", {"url": source}, lambda result: f"{result['text']} [{result['url']}]"),
        verbosity=0,
    )
    found = await researcher.call_tool("web_search", query="Reusable tools")
    assert found["results"][0]["url"] == source
    print("Research:", await researcher.invoke("Read the selected source and cite it."))

    expert = KnowledgeAgent(
        sources=[Document(text="Checkpoint recovery resumes committed actions safely.", source="recovery.md")],
        llm=model_for(
            "search_knowledge",
            {"query": "checkpoint recovery"},
            lambda result: (
                f"{result['hits'][0]['text']} {result['hits'][0]['citation']}"
                if result["hits"]
                else "Insufficient evidence."
            ),
        ),
        verbosity=0,
    )
    print("Knowledge:", await expert.invoke("What does checkpoint recovery do?"))

    with TemporaryDirectory(prefix="protolink-presets-") as directory:
        workspace = Path(directory).resolve()
        database_path = workspace / "sales.sqlite"
        with sqlite3.connect(database_path) as connection:
            connection.execute("CREATE TABLE sales(region TEXT, revenue INTEGER)")
            connection.executemany("INSERT INTO sales VALUES (?, ?)", [("EU", 10), ("EU", 20), ("US", 5)])
        analyst = DatabaseAgent(
            database=SQLiteDatabase(database_path),
            llm=model_for(
                "query_database",
                {"sql": "SELECT SUM(revenue) FROM sales WHERE region = ?", "parameters": ["EU"]},
                lambda result: f"EU revenue = {result['rows'][0][0]} (bounded read-only SQL)",
            ),
            verbosity=0,
        )
        assert "sales" in str(await analyst.call_tool("database_schema"))
        print("Database:", await analyst.invoke("Total EU revenue?"))

        note = workspace / "README.txt"
        note.write_text("The runtime uses explicit tools and capability policies.", encoding="utf-8")
        explorer = ExplorerAgent(
            roots=[workspace],
            llm=model_for("read_file", {"path": str(note)}, lambda result: f"{result['content']} [{result['path']}]"),
            verbosity=0,
        )
        print("Explorer:", await explorer.invoke(f"Read {note} and cite the path."))


if __name__ == "__main__":
    asyncio.run(main())
