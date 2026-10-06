"""Exercise context boundaries and lifecycle extensions on real inference runs."""

import json

import pytest

from protolink import Agent, AgentHooks, ContextLimitError, ContextPolicy, RunInterrupted
from protolink.llms import MockLLM
from protolink.llms.context_policy import CONTEXT_OBSERVATION_KEY, _artifacts, context_artifact_tool
from protolink.llms.history import ConversationHistory
from protolink.tools import Tool, ask_user_tool


def test_context_prunes_whole_turns_and_preserves_native_correlation():
    history = ConversationHistory()
    history.add_system("Keep these instructions")
    history.add_user("old " * 2000)
    history.add_assistant("old answer")
    history.add_user("current")
    history.add_raw({"role": "assistant", "content": "call", "tool_calls": {"id": "native"}})
    history.add_tool("result", tool_name="lookup")
    result = ContextPolicy(max_tokens=1500, reserve_tokens=200, preserve_recent=1).prepare(history)
    assert result["removed_messages"] == 2
    assert history.messages[0]["content"] == "Keep these instructions"
    assert history.messages_raw()[-2].tool_calls == {"id": "native"}
    assert history.messages_raw()[-1].name == "lookup"


def test_context_clears_old_results_in_place_and_fails_without_mutating_protected_input():
    history = ConversationHistory()
    history.add_system("instructions")
    history.add_user("current")
    history.add_assistant("call", tool_calls={"id": "native"})
    history.add_tool("large result " * 2000, tool_name="lookup")
    history.messages_raw()[-1].metadata[CONTEXT_OBSERVATION_KEY] = {"tool": "lookup", "context_artifact": "ref"}
    history.add_tool("recent", tool_name="lookup")
    history.messages_raw()[-1].metadata[CONTEXT_OBSERVATION_KEY] = {"tool": "lookup"}
    result = ContextPolicy(max_tokens=1500, reserve_tokens=200, preserve_recent=1).prepare(history)
    assert result["cleared_observations"] == 1
    assert "ref" in history.messages[-2]["content"]
    assert history.messages_raw()[-2].name == "lookup"
    assert history.messages[-1]["content"] == "recent"
    original = history.messages
    with pytest.raises(ContextLimitError):
        ContextPolicy(max_tokens=201, reserve_tokens=200).prepare(history)
    assert history.messages == original


@pytest.mark.asyncio
async def test_artifact_paging_eviction_truncation_and_scope():
    policy = ContextPolicy(tool_result_max_chars=20, artifact_max_chars=100, max_artifacts=1)
    token = _artifacts.set({})
    tool = context_artifact_tool()
    try:
        first = policy.observation("a" * 200)
        assert first["artifact_truncated"]
        second = policy.observation("b" * 200)
        with pytest.raises(ValueError, match="unavailable"):
            await tool(artifact_id=first["context_artifact"])
        page = await tool(artifact_id=second["context_artifact"], offset=10, max_chars=15)
        assert page == {"text": "b" * 15, "next_offset": 25, "untrusted_content": True}
        with pytest.raises(ValueError):
            await tool(artifact_id=second["context_artifact"], offset=-1)
    finally:
        _artifacts.reset(token)
    with pytest.raises(ValueError, match="scope"):
        await tool(artifact_id=second["context_artifact"])


@pytest.mark.asyncio
async def test_hooks_transform_observations_and_final_without_altering_committed_receipts(tmp_path):
    seen = []

    def source() -> dict:
        return {"private": "value", "public": "ok"}

    def before(request):
        seen.append(("model", request.step))

    async def after(observation):
        seen.append(("tool", observation.name))
        observation.result.pop("private")

    def complete(response):
        response.content = "checked: " + response.content

    model = MockLLM(sequential_responses=[{"type": "tool_call", "tool": "source", "args": {}}, "done"])
    agent = Agent(
        name="hooks",
        llm=model,
        tools=[source],
        hooks=[AgentHooks(before, after, complete)],
        durability=tmp_path / "runs.db",
        verbosity=0,
    )
    assert await agent.invoke("go") == "checked: done"
    record = agent.durability.list()[0]
    assert next(iter(record.data["actions"].values()))["result"]["private"] == "value"
    history = next(iter(record.data["loops"].values()))["history"]
    assert not any('"private"' in message["content"] for message in history)
    assert json.loads(history[-1]["content"])["content"] == "checked: done"
    assert seen == [("model", 1), ("tool", "source"), ("model", 2)]


@pytest.mark.asyncio
async def test_hook_tool_filter_is_enforced_and_cannot_replace_executables():
    calls = []

    def forbidden() -> str:
        calls.append(True)
        return "effect"

    def filter_tools(request):
        request.tools.clear()

    agent = Agent(
        name="filter",
        tools=[forbidden],
        hooks=[filter_tools],
        verbosity=0,
        llm=MockLLM(sequential_responses=[{"type": "tool_call", "tool": "forbidden", "args": {}}, "done"]),
    )
    assert await agent.invoke("go") == "done"
    assert calls == []

    def replace_tool(request):
        request.tools["forbidden"] = Tool.from_callable(lambda: "replacement", name="forbidden")

    agent = Agent(name="replace", tools=[forbidden], hooks=[replace_tool], llm=MockLLM(), verbosity=0)
    with pytest.raises(Exception, match="introduce or replace"):
        await agent.invoke("go")
    assert calls == []


@pytest.mark.asyncio
async def test_hook_failure_stops_completion_and_non_none_returns_are_errors():
    def invalid(response):
        raise ValueError("output rejected")

    agent = Agent(
        name="fail", llm=MockLLM(default_response="done"), hooks=[AgentHooks(before_complete=invalid)], verbosity=0
    )
    with pytest.raises(Exception, match="output rejected"):
        await agent.invoke("go")
    bad = Agent(name="bad", llm=MockLLM(), hooks=[lambda request: True], verbosity=0)
    with pytest.raises(Exception, match="must return None"):
        await bad.invoke("go")


@pytest.mark.asyncio
async def test_hook_prompt_edits_survive_filtered_prompt_regeneration():
    def prepare(request):
        request.history.set_system("Custom compiled instructions")
        request.tools.clear()

    def respond(history, prompt):
        return history.messages[0]["content"]

    agent = Agent(
        name="prompt", tools=[lambda: "unused"], hooks=[prepare], llm=MockLLM(response_callback=respond), verbosity=0
    )
    assert await agent.invoke("go") == "Custom compiled instructions"


@pytest.mark.asyncio
async def test_ephemeral_observations_are_not_retained_as_context_artifacts(tmp_path):
    def evidence() -> str:
        return "private knowledge " * 1000

    tool = Tool.from_callable(evidence)
    tool._protolink_ephemeral_result = True
    agent = Agent(
        name="ephemeral",
        tools=[tool],
        context_policy=ContextPolicy(tool_result_max_chars=40),
        durability=tmp_path / "runs.db",
        verbosity=0,
        llm=MockLLM(sequential_responses=[{"type": "tool_call", "tool": "evidence", "args": {}}, "done"]),
    )
    assert await agent.invoke("go") == "done"
    assert agent.durability.list()[0].data["context_artifacts"] == {}


def test_context_and_callbacks_serialization_requires_explicit_reconnection():
    hook = AgentHooks(before_model=lambda request: None)
    agent = Agent(name="restore", llm=MockLLM(), context_policy="auto", hooks=[hook], verbosity=0)
    config = agent.to_dict()
    with pytest.raises(ValueError, match="callbacks"):
        Agent.from_dict(config, llm=MockLLM())
    restored = Agent.from_dict(config, llm=MockLLM(), hooks=[hook])
    assert restored.context_policy == agent.context_policy
    assert restored.tools["read_context_artifact"].func is not None


@pytest.mark.asyncio
async def test_offloaded_artifact_survives_question_and_agent_restart(tmp_path):
    def source() -> str:
        return "evidence " * 1000

    def make(responses):
        return Agent(
            name="artifacts",
            llm=MockLLM(sequential_responses=responses),
            tools=[source, ask_user_tool()],
            context_policy=ContextPolicy(tool_result_max_chars=40),
            durability=tmp_path / "runs.db",
            verbosity=0,
        )

    first = make(
        [
            {"type": "tool_call", "tool": "source", "args": {}},
            {"type": "tool_call", "tool": "ask_user", "args": {"question": "Continue?"}},
        ]
    )
    with pytest.raises(RunInterrupted) as raised:
        await first.invoke("go")
    pause = raised.value
    record = first.durability.get(pause.run_id)
    key = next(iter(record.data["context_artifacts"]))
    restarted = make(
        [
            {
                "type": "tool_call",
                "tool": "read_context_artifact",
                "args": {"artifact_id": key, "offset": 0, "max_chars": 20},
            },
            "done",
        ]
    )
    assert await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, answer="yes") == "done"
    assert "evidence" in restarted.durability.get(pause.run_id).data["context_artifacts"][key]
