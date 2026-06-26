"""Protolink 0.6.3 context manifests, model profiles, and run budgets.

This provider-free example shows the runtime data an application can inspect
before a model call:

1. ``ContextManifest`` estimates the prompt surface about to enter the model.
2. ``LLMModelProfile`` carries descriptive model metadata for budgeting UIs.
3. ``RunBudget`` is enforced before the mock model is invoked.

Run it with:

    python examples/v063_context_budget.py
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from protolink import (
    BudgetExceededError,
    LLMModelProfile,
    RunBudget,
    RunContext,
    create_llm,
)


class LookupTool:
    """Tiny tool descriptor used only to make tool prompt tokens visible."""

    description = "Look up one value from a local catalog."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    capabilities = ("catalog.read",)


async def main() -> None:
    """Run one budgeted call, then show a hard budget denial."""
    events: list[dict] = []

    async def capture(event: dict) -> None:
        """Collect raw LLM events emitted during inference."""
        events.append(event)

    llm = create_llm(
        "mock",
        default_response="The context manifest and budget were accepted.",
        metrics_profile=LLMModelProfile(
            context_window=4096,
            supports_tools=True,
            supports_streaming=False,
            supports_json_schema=True,
            tokenizer="estimated",
            metadata={"tier": "local-demo"},
        ),
    )
    llm.history.reset_to_system("Answer concisely and cite local context.")
    llm.history.add_user("Earlier: remember that the workspace is read-only.")
    llm.history.add_assistant("Noted: read-only workspace.")

    context = RunContext(
        run_id="run_v063_context_budget",
        session_id="session_v063_context_budget",
        agent_chain=["budget-demo"],
        budget=RunBudget(max_steps=3, max_llm_calls=1, max_input_tokens=4096),
    )

    response = await llm.infer(
        query="Summarize the runtime context controls.",
        tools={"lookup": LookupTool()},
        run_context=context,
        event_callback=capture,
    )

    manifest = next(event["manifest"] for event in events if event["type"] == "context_prepared")
    print("Model response:", response.content)
    print("Manifest total tokens:", manifest["total_estimated_tokens"])
    print("Tool prompt tokens:", manifest["tool_prompt_tokens"])
    print("Profile supports tools:", llm.metrics_profile.supports_tools)
    print("Budget events:", [event["type"] for event in events if event["type"].startswith("budget_")])

    denied_events: list[dict] = []
    denied_model_calls = 0

    async def capture_denied(event: dict) -> None:
        """Collect events from the denied run."""
        denied_events.append(event)

    def should_not_run(_history, _system_prompt):
        """Prove the hard budget stops execution before the provider call."""
        nonlocal denied_model_calls
        denied_model_calls += 1
        return "This response should never be generated."

    denied_llm = create_llm("mock", response_callback=should_not_run)
    try:
        await denied_llm.infer(
            query="This call is blocked by max_llm_calls=0.",
            tools={},
            run_context=RunContext(
                run_id="run_v063_context_budget_denied",
                budget=RunBudget(max_llm_calls=0),
            ),
            event_callback=capture_denied,
        )
    except BudgetExceededError as exc:
        print("Denied budget limit:", exc.decision.limit_name)
        print("Provider calls after denial:", denied_model_calls)
        print("Denied events:", [event["type"] for event in denied_events])


if __name__ == "__main__":
    asyncio.run(main())
