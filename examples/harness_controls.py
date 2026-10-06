"""Run context, hook, routing and evaluation examples without external services.

From a checkout with ProtoLink installed: python examples/harness_controls.py.
Mock adapters script execution; these assertions demonstrate the runtime contract,
not real-model quality. Docker remains optional and is documented separately.
"""

from __future__ import annotations

import asyncio

from protolink import (
    Agent,
    AgentHooks,
    ContextPolicy,
    EchoAgent,
    EvaluationCase,
    FinalResponse,
    RoutedLLM,
    compare_evaluations,
    evaluate,
)
from protolink.llms import MockLLM


class UnavailableModel(MockLLM):
    """Simulate a transient request failure so fallback is observable offline."""

    def call(self, history) -> str:
        raise ConnectionError("Scripted provider outage")


def validate_answer(response: FinalResponse) -> None:
    """Reject empty output before it becomes a completed Agent response."""
    if not isinstance(response.content, str) or not response.content.strip():
        raise ValueError("Expected a nonempty text answer")


async def demonstrate_context() -> None:
    """Retrieve a page from an offloaded observation using the normal tool protocol."""

    def evidence() -> str:
        """Return a deliberately large piece of application evidence."""
        return "Evidence: the integration checks passed.\n" * 100

    def scripted_response(history, prompt):
        for message in reversed(history.messages):
            if message["role"] != "system" or not message["content"].startswith('{"type": "tool_result"'):
                continue
            import json

            observation = json.loads(message["content"])
            if observation["tool"] == "read_context_artifact":
                return "Read the evidence from the scoped artifact."
            return {
                "type": "tool_call",
                "tool": "read_context_artifact",
                "args": {
                    "artifact_id": observation["result"]["context_artifact"],
                    "max_chars": 80,
                },
            }
        return {"type": "tool_call", "tool": "evidence", "args": {}}

    agent = Agent(
        name="context-example",
        llm=MockLLM(response_callback=scripted_response),
        tools=[evidence],
        context_policy=ContextPolicy(tool_result_max_chars=80),
        hooks=[AgentHooks(before_complete=validate_answer)],
        verbosity=0,
    )
    assert await agent.invoke("Inspect the evidence") == "Read the evidence from the scoped artifact."
    print("Context: oversized observation stored and read by scoped retrieval.")


async def main() -> None:
    """Exercise the simple configuration entry points and inspect their outcomes."""
    await demonstrate_context()
    router = RoutedLLM(
        {"primary": UnavailableModel(), "backup": MockLLM(default_response="Fallback succeeded")},
        fallbacks=["backup"],
    )
    agent = Agent(name="routing-example", llm=router, hooks=[AgentHooks(before_complete=validate_answer)], verbosity=0)
    assert await agent.invoke("Hello") == "Fallback succeeded"
    print("Routing: transient model request switched to the configured backup.")
    cases = [EvaluationCase("greeting", "hello", "hello"), EvaluationCase("farewell", "bye", "bye")]
    baseline = await evaluate(lambda: EchoAgent(verbosity=0), cases, repetitions=2, concurrency=2)
    candidate = await evaluate(lambda: EchoAgent(verbosity=0), cases)
    assert baseline.passed and compare_evaluations(baseline, candidate)["passed"]
    print("Evaluation:", candidate.to_dict()["scores"])


if __name__ == "__main__":
    asyncio.run(main())
