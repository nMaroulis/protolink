"""Run a dependency-free Agent that chooses when to search local knowledge.

The in-memory knowledge base, lexical embedder, runtime transport, and MockLLM all ship with ProtoLink. The scripted
model still follows the real inference loop: it calls the automatically registered ``search_handbook`` tool, reads the
tool result, and then answers with the returned citation label.

Run it from the repository root:

    python examples/rag_agent.py
"""

from __future__ import annotations

import json
from typing import Any

from protolink import Agent, AgentCard, Document, create_knowledge, create_llm


def handbook_response(history: Any, _system_prompt: str) -> dict[str, Any]:
    """Search once, then build the final answer from the actual tool result."""
    for message in reversed(history.messages):
        if message.get("role") != "system":
            continue
        try:
            payload = json.loads(str(message.get("content", "")))
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "tool_result" or payload.get("tool") != "search_handbook":
            continue

        hits = payload.get("result", {}).get("hits", [])
        if not hits:
            return {
                "type": "final",
                "content": "I could not find that policy in the employee handbook.",
            }
        best_hit = hits[0]
        return {
            "type": "final",
            "content": f"{best_hit['text']} {best_hit['citation']}",
        }

    return {
        "type": "tool_call",
        "tool": "search_handbook",
        "args": {
            "query": "expense receipt submission deadline",
            "k": 2,
        },
    }


knowledge = create_knowledge(
    "memory",
    name="handbook",
    description="the employee handbook and internal company policies",
    sources=[
        Document(
            text="Employees must submit expense receipts within 30 days of purchase.",
            source="expense-policy.md",
            metadata={"department": "finance"},
        ),
        Document(
            text="New employees receive their building badge during first-day onboarding.",
            source="onboarding.md",
            metadata={"department": "people"},
        ),
    ],
)

agent = Agent(
    card=AgentCard(
        name="handbook-assistant",
        description="Answers questions using the employee handbook",
        url="runtime://handbook-assistant",
    ),
    transport="runtime",
    llm=create_llm("mock", response_callback=handbook_response),
    knowledge=knowledge,
    retrieval="auto",
    verbosity=0,
)


if __name__ == "__main__":
    answer = agent.sync.invoke("When must I submit an expense receipt?")
    print(answer)
