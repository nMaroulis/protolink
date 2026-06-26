"""Protolink 0.6.3 request-spec LLM history compaction.

History compaction is application/runtime control, not a model-visible tool.
The simple ``recent`` and ``tokens`` strategies mutate history with code only.
The ``summary`` strategy makes one isolated summarization call with a separate
prompt, outside the normal agent inference loop.

Run it with:

    python examples/v063_history_compaction.py
"""

from __future__ import annotations

import asyncio
import json

from protolink import Agent, AgentCard, HistoryCompactionRequest, create_llm
from protolink.client import AgentClient
from protolink.llms.history import ConversationHistory
from protolink.llms.mock_client import MockLLM
from protolink.transport import RuntimeTransport


class SummaryMockLLM(MockLLM):
    """Mock LLM that returns raw compaction JSON for the isolated summary call."""

    def __init__(self) -> None:
        """Initialize the mock and keep the summary prompts for inspection."""
        super().__init__(default_response="unused")
        self.summary_prompts: list[ConversationHistory] = []

    def call(self, history: ConversationHistory) -> str:
        """Return the exact JSON shape expected by the summary compactor."""
        self.summary_prompts.append(history)
        return json.dumps({"summary": "The user chose Athens; deployment is still pending."})


def seed_history(llm, *, turns: int = 5) -> None:
    """Populate an LLM with enough messages for visible compaction."""
    llm.history.reset_to_system("System: preserve policy and safety constraints.")
    for index in range(turns):
        llm.history.add_user(f"user message {index}: details " + ("context " * 8))
        llm.history.add_assistant(f"assistant message {index}: response " + ("answer " * 8))


async def direct_compaction_examples() -> None:
    """Show the direct LLM facade for all three compaction strategies."""
    recent_llm = create_llm("mock", default_response="unused")
    seed_history(recent_llm)
    recent = recent_llm.compact_history("recent", max_messages=4)
    print("Recent compaction:", recent.to_dict())

    token_llm = create_llm("mock", default_response="unused")
    seed_history(token_llm)
    tokens = token_llm.compact_history("tokens", max_tokens=90, preserve_recent=2)
    print("Token compaction:", tokens.to_dict())

    summary_llm = SummaryMockLLM()
    seed_history(summary_llm)
    summary = summary_llm.compact_history("summary", preserve_recent=2, summary_max_tokens=80)
    print("Summary compaction:", summary.to_dict())
    print("Summary used isolated prompt:", len(summary_llm.summary_prompts) == 1)


async def client_request_spec_example() -> None:
    """Compact a remote agent through the AgentClient request spec endpoint."""
    url = "runtime://v063-history-compactor"
    llm = create_llm("mock", default_response="unused")
    seed_history(llm, turns=4)
    agent = Agent(
        AgentCard(name="history_compactor", description="Compacts history on request", url=url),
        transport=RuntimeTransport(url=url),
        llm=llm,
        verbosity=0,
    )
    client = AgentClient(RuntimeTransport(url="runtime://v063-history-client"))
    assert agent.server is not None
    await agent.server.start()

    try:
        report = await client.compact_history(
            url,
            strategy="recent",
            max_messages=3,
            metadata={"requested_by": "example"},
        )
    finally:
        await agent.server.stop()

    direct_request = await agent.compact_history(HistoryCompactionRequest(strategy="recent", max_messages=3))
    print("Client endpoint after messages:", report.after_messages)
    print("Direct request changed:", direct_request.changed)
    print("Compaction tool exposed to prompt:", "protolink_compact_history" in llm.system_prompt)


async def main() -> None:
    """Run direct and client/server compaction examples."""
    await direct_compaction_examples()
    await client_request_spec_example()


if __name__ == "__main__":
    asyncio.run(main())
