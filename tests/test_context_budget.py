from typing import ClassVar

import pytest

from protolink import (
    BudgetExceededError,
    ContextManifest,
    LLMModelProfile,
    RunBudget,
    RunContext,
    create_llm,
)
from protolink.llms.context import build_context_manifest
from protolink.llms.history import ConversationHistory


class DummyTool:
    description = "Look up a value"
    input_schema: ClassVar[dict] = {"type": "object", "properties": {"query": {"type": "string"}}}
    capabilities = ("data.read",)


def test_context_manifest_splits_prompt_sections_and_round_trips():
    history = ConversationHistory("System instructions with tool affordances")
    history.add_user("older question")
    history.add_assistant("older answer")
    history.add_user("current question")
    context = RunContext(run_id="run_manifest", session_id="session_manifest", agent_chain=["tester"])

    manifest = build_context_manifest(
        history=history,
        query="current question",
        run_context=context,
        provider="mock",
        model="mock-gpt",
        profile=LLMModelProfile(context_window=4096),
        tools={"lookup": DummyTool()},
    )

    assert manifest.run_id == "run_manifest"
    assert manifest.session_id == "session_manifest"
    assert manifest.agent_name == "tester"
    assert manifest.context_window == 4096
    assert manifest.user_tokens > 0
    assert manifest.history_tokens > 0
    assert manifest.tool_prompt_tokens > 0
    assert manifest.total_estimated_tokens == (
        manifest.system_tokens + manifest.history_tokens + manifest.tool_prompt_tokens + manifest.user_tokens
    )

    restored = ContextManifest.from_dict(manifest.to_dict())
    assert restored == manifest


def test_model_profile_preserves_capability_metadata_from_dict():
    llm = create_llm(
        "mock",
        metrics_profile={
            "context_window": 8192,
            "input_cost_per_million": 1.0,
            "output_cost_per_million": 3.0,
            "supports_tools": True,
            "supports_streaming": True,
            "supports_json_schema": False,
            "tokenizer": "cl100k_base",
            "metadata": {"quality": "test"},
        },
    )

    assert llm.metrics_profile is not None
    assert llm.metrics_profile.context_window == 8192
    assert llm.metrics_profile.input_cost_per_million == 1.0
    assert llm.metrics_profile.output_cost_per_million == 3.0
    assert llm.metrics_profile.supports_tools is True
    assert llm.metrics_profile.supports_streaming is True
    assert llm.metrics_profile.supports_json_schema is False
    assert llm.metrics_profile.tokenizer == "cl100k_base"
    assert llm.metrics_profile.metadata == {"quality": "test"}


@pytest.mark.asyncio
async def test_run_budget_denies_llm_call_before_model_invocation():
    calls = 0
    events: list[dict] = []

    def response_callback(_history, _system_prompt):
        nonlocal calls
        calls += 1
        return {"type": "final", "content": "should not run"}

    llm = create_llm("mock", response_callback=response_callback)
    context = RunContext(run_id="run_budget", budget=RunBudget(max_llm_calls=0))

    async def capture(event):
        events.append(event)

    with pytest.raises(BudgetExceededError):
        await llm.infer(query="hello", tools={}, run_context=context, event_callback=capture)

    assert calls == 0
    assert [event["type"] for event in events] == ["llm_step", "context_prepared", "budget_exceeded"]
    decision = events[-1]["decision"]
    assert decision["effect"] == "deny"
    assert decision["limit_name"] == "max_llm_calls"
