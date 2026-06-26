"""Protolink 0.6.3 state inspection and control endpoints.

This example uses ``RuntimeTransport`` so it behaves like a remote client/server
flow without opening a network port. The client describes, compacts, and resets
one persistent conversation session through typed request specs.

Run it with:

    python examples/v063_state_control.py
"""

from __future__ import annotations

import asyncio

from protolink import Agent, AgentCard, RunContext, Task, create_llm
from protolink.client import AgentClient
from protolink.transport import RuntimeTransport


async def ask(agent: Agent, session_id: str, prompt: str) -> None:
    """Send one task into a persistent conversation session."""
    task = Task.create_infer(prompt=prompt)
    RunContext(session_id=session_id).attach_to_task(task)
    await agent.handle_task(task)


async def main() -> None:
    """Describe, compact, and reset state through AgentClient specs."""
    url = "runtime://v063-state-agent"
    session_id = "session_v063_state"
    agent = Agent(
        AgentCard(name="state_agent", description="State control demo", url=url),
        transport=RuntimeTransport(url=url),
        llm=create_llm("mock", default_response="stored in conversation state"),
        state=["conversation"],
        verbosity=0,
    )
    client = AgentClient(RuntimeTransport(url="runtime://v063-state-client"))
    assert agent.server is not None
    await agent.server.start()

    try:
        for index in range(5):
            await ask(agent, session_id, f"Remember repository fact {index}.")

        described = await client.describe_state(url, session_id=session_id, include_data=False)
        compacted = await client.compact_state(
            url,
            session_id=session_id,
            strategy="recent",
            max_messages=4,
        )
        after_compact = await client.describe_state(url, session_id=session_id)
        reset = await client.reset_state(url, session_id=session_id)
        after_reset = await client.describe_state(url, session_id=session_id)
    finally:
        await agent.server.stop()

    print("Describe operation:", described.operation)
    print("Messages before compact:", described.stores[0].message_count)
    print("Compacted stores:", compacted.compacted)
    print("Messages after compact:", after_compact.stores[0].message_count)
    print("Reset stores:", reset.cleared)
    print("Session exists after reset:", after_reset.stores[0].exists)


if __name__ == "__main__":
    asyncio.run(main())
