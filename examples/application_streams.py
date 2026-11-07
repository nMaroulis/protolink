"""A small embedded app with private dependencies, approvals and reconnectable streams.

Run ``python examples/application_streams.py`` offline; replace ``model_for``
for real models. The app owns rendering, authentication and domain data.
"""

import asyncio
from tempfile import TemporaryDirectory
from types import MappingProxyType

from protolink import (
    Agent,
    AgentGroup,
    ApprovalBroker,
    ApprovalDecision,
    ApprovalScope,
    CapabilityPolicy,
    GroupLimits,
    RunContext,
    SQLiteRunStore,
    Task,
    create_llm,
    current_request_context,
    request_context,
)


def model_for():
    """Resolve one request's frozen model choice only when inference starts."""
    return create_llm(
        "mock",
        model=current_request_context()["model"],
        sequential_responses=[
            {"type": "tool_call", "tool": "read_price", "args": {"symbol": "BTC"}},
            "BTC is **$123** in this offline example.\n",
        ],
    )


async def approve(broker, scope):
    """Simulate an authenticated application's approval adapter."""
    async for record in broker.events(scope):
        if record.status == "pending":
            # A real app displays the prepared action and waits for its user.
            broker.resolve(
                ApprovalDecision(approved=True, request_id=record.request.request_id),
                scope=scope,
                fingerprint=record.fingerprint,
            )
            return


async def show_answer(handle):
    """Apply provisional updates; only completed confirms success."""
    answer = ""
    async for update in handle.answer_events():
        answer = answer + update.content if update.type == "delta" else update.content
        print(update.type, repr(answer))


async def main():
    """Own the group's lifecycle and persist its authoritative final report."""
    with TemporaryDirectory() as directory:
        store = SQLiteRunStore(f"{directory}/runs.sqlite")
        broker = ApprovalBroker(timeout_seconds=10)
        agent = Agent(
            name="dashboard",
            llm_factory=model_for,
            run_store=store,
            verbosity=0,
            policy=CapabilityPolicy({"prices.read": "require_approval"}),
            approval_handler=broker,
        )

        @agent.tool(capabilities=["prices.read"])
        def read_price(symbol: str) -> float:
            """Read one symbol from the request's application data source."""
            return current_request_context()["prices"][symbol]

        async with AgentGroup([agent], limits=GroupLimits(max_concurrent_runs=2, max_queued_runs=8)) as group:
            task = Task.create_infer(prompt="Read BTC's example price.")
            RunContext(session_id="conversation-1").attach_to_task(task)
            with request_context({"model": "offline", "prices": MappingProxyType({"BTC": 123.0})}):
                handle = group.run(agent, task, request_id="message-1")
            scope = ApprovalScope(frozenset({handle.context.run_id}))
            stream = handle.presentation_events()
            first = await anext(stream)
            await stream.aclose()  # Closing a subscriber leaves the run active.
            reconnected = group.get_run(handle.context.run_id)
            ui = asyncio.create_task(approve(broker, scope))
            answers = asyncio.create_task(show_answer(reconnected))
            async for update in reconnected.presentation_events(after=first.sequence):
                print(update.sequence, update.summary, update.name or "")
            await asyncio.gather(answers, ui)
            result = await handle.result()
            assert result.status == "completed" and store.get_report(handle.context.run_id) is not None
            print(result.status, result.output)


if __name__ == "__main__":
    asyncio.run(main())
