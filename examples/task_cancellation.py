"""Cancel a running Protolink task without committing its side effect.

This provider-free example starts a task containing a long-running async tool,
waits until the tool is active, and cancels it from another coroutine. It shows
the three observable cancellation results:

1. The tool coroutine is interrupted at an ``await`` point.
2. The stream ends with one final ``canceled`` task status event.
3. ``Task`` and ``RunContext`` preserve the cancellation reason.

Cancellation is cooperative and best-effort. Async work can normally stop at an
await point; synchronous functions and already-issued external operations need
their own cancellation strategy when stronger guarantees are required.
"""

from __future__ import annotations

import asyncio
from typing import Any

from protolink import Agent, AgentCard, InMemoryEventSink, RunContext, Task


async def main() -> None:
    """Run and cancel one streamed task."""
    started = asyncio.Event()
    committed: list[str] = []

    agent = Agent(
        AgentCard(
            name="cancellation_agent",
            description="Demonstrates live task cancellation",
            url="runtime://cancellation-agent",
            capabilities={"streaming": True},
        ),
        verbosity=0,
    )

    @agent.tool(name="delayed_update", description="Commit an update after several steps")
    async def delayed_update(value: str) -> str:
        """Simulate interruptible work with a side effect only at the end."""
        started.set()
        for step in range(1, 11):
            print(f"  working step {step}/10")
            await asyncio.sleep(0.1)

        # Cancellation occurs before this line, so the update is never committed.
        committed.append(value)
        return value

    task = Task.create_tool_call(
        tool_name="delayed_update",
        args={"value": "important update"},
    )
    RunContext(
        run_id="run_cancellation_example",
        session_id="session_cancellation_example",
        metadata={"source": "example"},
    ).attach_to_task(task)

    sink = InMemoryEventSink()

    async def consume_events() -> None:
        async for task_event in agent.handle_task_streaming(task):
            run_event = await sink.emit_task_event(
                task_event,
                context=RunContext.from_task(task),
            )
            print(f"event: {run_event.type:<16} {run_event.summary}")

    running = asyncio.create_task(consume_events())
    await started.wait()
    await asyncio.sleep(0.25)

    print("\nRequesting cancellation...")
    canceled_task = await agent.cancel_task(
        task.id,
        reason="Stopped by the example user",
    )
    await running

    context = RunContext.from_task(canceled_task)
    final_event: dict[str, Any] = sink.to_list()[-1]

    print("\nFinal state")
    print(f"  task: {canceled_task.state.value}")
    print(f"  reason: {context.cancel_reason}")
    print(f"  final event: {final_event['summary']}")
    print(f"  committed values: {committed}")

    assert canceled_task.state.value == "canceled"
    assert context.canceled is True
    assert committed == []


if __name__ == "__main__":
    asyncio.run(main())
