"""Worker declarations reuse native delegation rather than callable wrappers."""

import asyncio
import copy
import json

import pytest

from protolink import Agent, CapabilityPolicy, RunBudget, RunContext, RunInterrupted, Task, Tool
from protolink.core.durable import configuration_fingerprint
from protolink.core.task import TaskState
from protolink.llms import MockLLM
from protolink.llms.actions import FinalAction, LLMActionResult, ToolCallAction, action_to_json
from protolink.llms.tool_calling import (
    anthropic_tools,
    chat_completion_tools,
    gemini_function_declarations,
    openai_responses_tools,
)
from protolink.tools.builtins import ask_user_tool


def make_parent(child, *, name="ask_worker", tool=None, **kwargs):
    alias = {
        "type": "tool_call",
        "tool": name,
        "args": {"task": "Research alpha"} if tool is None else {"value": "3"},
    }
    parent = Agent(
        name="parent",
        subagents=[child],
        verbosity=0,
        llm=MockLLM(sequential_responses=[alias, "parent done"]),
        **kwargs,
    )
    parent.add_worker_tool(child.card.name, name=name, tool=tool)
    return parent


def test_registration_is_explicit_and_does_not_replace_tools():
    def occupied():
        return None

    worker = Agent(name="researcher", llm="mock", verbosity=0)
    parent = Agent(name="parent", subagents=[worker], tools=[occupied], verbosity=0)
    original = dict(parent.tools)
    with pytest.raises(ValueError, match="exact name"):
        parent.add_worker_tool("Researcher")
    with pytest.raises(ValueError, match="no registered tool"):
        parent.add_worker_tool("researcher", tool="missing")
    with pytest.raises(ValueError, match="conflicts"):
        parent.add_worker_tool("researcher", name="occupied")
    with pytest.raises(ValueError):
        parent.add_worker_tool("researcher", name="protolink_delegate_agent")
    assert parent.tools == original
    facade = parent.add_worker_tool("researcher")
    assert facade.name == "researcher"
    assert set(facade.input_schema["properties"]) == {"task"}
    assert facade.input_schema["required"] == ["task"]
    assert parent.card.skills[-1].id == "researcher"


def test_tool_facade_copies_declared_schema_without_exposing_route_arguments():
    def lookup(value: int) -> int:
        return value + 1

    child = Agent(name="researcher", tools=[lookup], verbosity=0)
    parent = Agent(name="parent", subagents=[child], verbosity=0)
    facade = parent.add_worker_tool("researcher", tool="lookup")
    assert facade.name == "researcher_lookup"
    assert facade.input_schema == child.tools["lookup"].input_schema
    assert facade.input_schema is not child.tools["lookup"].input_schema
    assert facade.output_schema == child.tools["lookup"].output_schema
    assert "agent" not in facade.input_schema["properties"]
    parameters = openai_responses_tools(parent.tools, include_agent_tools=False)[0]["parameters"]
    assert set(parameters["properties"]) == {"value"}
    assert anthropic_tools(parent.tools, include_agent_tools=False)[0]["input_schema"] == parameters
    assert chat_completion_tools(parent.tools, include_agent_tools=False)[0]["function"]["parameters"] == parameters
    assert gemini_function_declarations(parent.tools, include_agent_tools=False)[0] == {
        "name": "researcher_lookup",
        "description": facade.description,
        "parameters_json_schema": parameters,
    }
    assert facade.to_action({"value": "3"}).model_dump(exclude_none=True) == {
        "type": "agent_call",
        "agent": "researcher",
        "action": "tool_call",
        "tool": "lookup",
        "args": {"value": 3},
    }


def test_facade_never_retargets_a_removed_or_replaced_local_worker():
    child = Agent(name="researcher", llm="mock", verbosity=0)
    parent = make_parent(child)
    facade = parent.tools["ask_worker"]
    parent.subagents["researcher"] = Agent(name="researcher", llm="mock", verbosity=0)
    with pytest.raises(ValueError, match="originally registered"):
        facade.to_action({"task": "go"})


def test_live_facade_cannot_be_registered_on_another_parent():
    child = Agent(name="researcher", llm="mock", verbosity=0)
    parent = make_parent(child)
    other = Agent(name="other", subagents=[Agent(name="researcher", llm="mock", verbosity=0)], verbosity=0)
    with pytest.raises(ValueError, match="another parent"):
        other.add_tool(parent.tools["ask_worker"])
    assert "ask_worker" not in other.tools


@pytest.mark.parametrize("arguments", [{"task": " "}, {"task": "go", "agent": "other"}, {"prompt": "go"}])
def test_inference_facade_rejects_empty_tasks_and_route_override_arguments(arguments):
    child = Agent(name="researcher", llm="mock", verbosity=0)
    parent = make_parent(child)
    with pytest.raises(ValueError):
        parent.tools["ask_worker"].to_action(arguments)


@pytest.mark.asyncio
async def test_json_facade_becomes_one_canonical_agent_action():
    child = Agent(name="researcher", llm=MockLLM(default_response="research result"), verbosity=0)
    parent = make_parent(child)
    run = parent.start_run("go")
    result = await run.result()
    assert result.output == "parent done"
    child_contexts = result.task.metadata["subagent_runs"]
    assert len(child_contexts) == 1
    assert child_contexts[0]["agent"] == "researcher"
    requested = [
        event for event in result.report.events if event.type == "action.requested" and event.agent_name == "parent"
    ]
    assert requested[0].payload["action"]["kind"] == "agent.call"
    assert requested[0].payload["action"]["name"] == "researcher"
    assert not any(
        isinstance(event.payload.get("action"), dict) and event.payload["action"].get("name") == "ask_worker"
        for event in result.report.events
    )
    observations = [
        json.loads(message["content"])
        for message in parent.llm.history.messages
        if message["role"] == "system" and message["content"].startswith('{"type": "tool_result"')
    ]
    assert observations[-1] == {"type": "tool_result", "tool": "ask_worker", "result": "research result"}


class NativeFacadeLLM(MockLLM):
    _native_tool_calling_available = True
    _native_tool_calling_default = True

    def call_action(self, history, **kwargs):
        if not any(
            '"tool": "ask_worker"' in message["content"] for message in history.messages if message["role"] == "system"
        ):
            action = ToolCallAction(tool="ask_worker", args=getattr(self, "facade_args", {"task": "Research alpha"}))
            return LLMActionResult(
                action, action_to_json(action), native=True, metadata={"provider": "native", "call_id": "call_123"}
            )
        action = FinalAction(content="native done")
        return LLMActionResult(action, action_to_json(action), native=True)

    async def call_action_stream(self, history, **kwargs):
        return self.call_action(history, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_native_facade_keeps_original_function_name(streaming):
    child = Agent(name="researcher", llm="mock", verbosity=0)
    parent = make_parent(child)
    parent.llm = NativeFacadeLLM()
    events = []
    task = Task.create_infer("go")
    if streaming:
        run = parent.start_run(task)
        async for event in run.events():
            events.append(event)
        assert (await run.result()).output == "native done"
    else:
        assert await parent.invoke("go") == "native done"
    assert any('"tool": "ask_worker"' in message["content"] for message in parent.llm.history.messages)


@pytest.mark.asyncio
async def test_native_facade_checkpoint_preserves_provider_identity_and_canonical_route(tmp_path):
    def make():
        child = Agent(name="researcher", llm="mock", verbosity=0)
        parent = make_parent(
            child,
            durability=tmp_path / "runs.db",
            policy=CapabilityPolicy({"agent.delegate": "require_approval"}),
        )
        parent.llm = NativeFacadeLLM()
        return parent

    parent = make()
    with pytest.raises(RunInterrupted) as raised:
        await parent.invoke("go")
    pause = raised.value
    pending = parent.durability.get(pause.run_id).data["loops"]["part:0"]["pending"]
    assert pending["action"] == {
        "type": "agent_call",
        "agent": "researcher",
        "action": "infer",
        "prompt": "Research alpha",
    }
    assert pending["native"] is True
    assert pending["metadata"] == {
        "provider": "native",
        "call_id": "call_123",
        "worker_tool": {"name": "ask_worker", "args": {"task": "Research alpha"}},
    }
    restarted = make()
    assert (
        await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, approved=True) == "native done"
    )
    assert restarted.durability.get(pause.run_id).data["subagent_count"] == 1
    assert any('"tool": "ask_worker"' in message["content"] for message in restarted.llm.history.messages)


@pytest.mark.asyncio
async def test_parent_delegation_policy_cannot_be_bypassed_by_tool_facade():
    child = Agent(name="researcher", llm=MockLLM(default_response="child"), verbosity=0)
    parent = make_parent(child, policy=CapabilityPolicy({"agent.delegate": "deny"}))
    with pytest.raises(Exception, match="denied"):
        await parent.invoke("go")
    assert child.llm._current_seq_idx == 0


@pytest.mark.asyncio
async def test_native_facade_child_rejection_uses_original_function_observation():
    from protolink import ToolRejectedError

    def lookup(value: int) -> int:
        raise ToolRejectedError("Choose another item", code="unavailable")

    child = Agent(name="researcher", tools=[lookup], verbosity=0)
    parent = make_parent(child, tool="lookup")
    parent.llm = NativeFacadeLLM()
    parent.llm.facade_args = {"value": 3}
    assert await parent.invoke("go") == "native done"
    observations = [
        json.loads(message["content"])
        for message in parent.llm.history.messages
        if message["role"] == "system" and message["content"].startswith('{"type": "tool_result"')
    ]
    assert observations[-1]["tool"] == "ask_worker"
    assert observations[-1]["result"]["type"] == "agent_rejection"
    assert observations[-1]["result"]["code"] == "unavailable"
    assert observations[-1]["result"]["changes_made"] is False


@pytest.mark.asyncio
async def test_call_tool_inside_active_task_cannot_detach_a_worker():
    child = Agent(name="researcher", llm="mock", verbosity=0)
    parent = make_parent(child)

    async def nested_call():
        return await parent.call_tool("ask_worker", task="go")

    parent.add_tool(nested_call)
    task = await parent.run_task(Task.create_tool_call("nested_call", {}))
    assert task.state is TaskState.FAILED
    assert "standalone parent task" in str(task.metadata["error"])
    assert not task.metadata.get("subagent_runs")


@pytest.mark.asyncio
async def test_worker_inference_uses_shared_model_budget():
    child = Agent(name="researcher", llm=MockLLM(sequential_responses=["child"]), verbosity=0)
    parent = make_parent(child)
    with pytest.raises(Exception, match="max_llm_calls"):
        await parent.invoke("go", budget=RunBudget(max_llm_calls=1))
    assert child.llm._current_seq_idx == 0


@pytest.mark.asyncio
async def test_explicit_tool_facade_charges_only_actual_child_tool():
    calls = []

    def lookup(value: int) -> int:
        calls.append(value)
        return value + 1

    child = Agent(name="researcher", tools=[lookup], verbosity=0)
    parent = make_parent(child, tool="lookup")
    task = Task.create_tool_call("ask_worker", {"value": "3"})
    RunContext(budget=RunBudget(max_tool_calls=1)).attach_to_task(task)
    result = await parent.run_task(task)
    assert result.get_output() == 4
    assert calls == [3]
    assert len(result.metadata["subagent_runs"]) == 1
    assert await parent.call_tool("ask_worker", value=5) == 6
    with pytest.raises(ValueError, match="native parent task"):
        await parent.call_tool_in_context("ask_worker", RunContext(), value=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_native_child_tool_facade_observation_matches_public_schema(streaming):
    def lookup(value: int) -> int:
        return value + 1

    child = Agent(name="researcher", tools=[lookup], verbosity=0)
    parent = make_parent(child, tool="lookup")
    parent.llm = NativeFacadeLLM()
    parent.llm.facade_args = {"value": "3"}
    if streaming:
        assert (await parent.start_run("go").result()).output == "native done"
    else:
        assert await parent.invoke("go") == "native done"
    observations = [
        json.loads(message["content"])
        for message in parent.llm.history.messages
        if message["role"] == "system" and message["content"].startswith('{"type": "tool_result"')
    ]
    assert observations[-1] == {"type": "tool_result", "tool": "ask_worker", "result": 4}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, False, 0, "", {"result": "nested", "call_id": "user", "error": None}])
async def test_durable_direct_child_tool_facade_returns_raw_falsey_or_structured_results(tmp_path, value):
    calls = []

    def lookup():
        calls.append(1)
        return value

    def make():
        child = Agent(name="researcher", tools=[Tool.from_callable(lookup, capabilities=["test.lookup"])], verbosity=0)
        return make_parent(
            child,
            tool="lookup",
            durability=tmp_path / "runs.db",
            policy=CapabilityPolicy({"test.lookup": "require_approval"}),
        )

    parent = make()
    with pytest.raises(RunInterrupted) as raised:
        await parent.call_tool("ask_worker")
    pause = raised.value
    restarted = make()
    result = await restarted.resume_task(pause.run_id, request_id=pause.interruption.request_id, approved=True)
    assert result.get_output() == value
    assert calls == [1]
    assert restarted.durability.get(pause.run_id).data["usage"]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_direct_facade_inherits_parent_policy_at_child_dispatch():
    calls = []

    def write(value: int) -> int:
        calls.append(value)
        return value

    child = Agent(name="researcher", tools=[Tool.from_callable(write, capabilities=["files.write"])], verbosity=0)
    parent = make_parent(child, tool="write", policy=CapabilityPolicy({"files.write": "deny"}))
    with pytest.raises(Exception, match="denied"):
        await parent.call_tool("ask_worker", value=1)
    assert calls == []


@pytest.mark.asyncio
async def test_direct_facade_cancellation_stops_owned_child():
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def wait(value: int) -> int:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        return value

    child = Agent(name="researcher", tools=[wait], verbosity=0)
    parent = make_parent(child, tool="wait")
    task = Task.create_tool_call("ask_worker", {"value": 1})
    running = asyncio.create_task(parent.run_task(task))
    await asyncio.wait_for(entered.wait(), 2)
    await parent.cancel_task(task.id)
    result = await running
    assert result.state is TaskState.CANCELED
    assert stopped.is_set()
    assert not parent._subagent_runs


@pytest.mark.asyncio
async def test_direct_durable_worker_facade_resumes_one_child_without_double_charging(tmp_path):
    def make():
        child = Agent(
            name="researcher",
            tools=[ask_user_tool()],
            verbosity=0,
            llm=MockLLM(
                sequential_responses=[
                    {"type": "tool_call", "tool": "ask_user", "args": {"question": "Format?"}},
                    "child done",
                ]
            ),
        )
        return make_parent(child, durability=tmp_path / "runs.db")

    parent = make()
    with pytest.raises(RunInterrupted) as raised:
        await parent.call_tool("ask_worker", task="Research alpha")
    pause = raised.value
    saved = parent.durability.get(pause.run_id)
    assert saved.data["usage"]["tool_calls"] == 1
    assert saved.data["subagent_count"] == 1
    restarted = make()
    assert await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, answer="CSV") == "child done"
    saved = restarted.durability.get(pause.run_id)
    assert saved.data["usage"]["tool_calls"] == 1
    assert saved.data["subagent_count"] == 1


def test_worker_facade_serialization_requires_explicit_reconnection():
    child = Agent(name="researcher", llm="mock", verbosity=0)
    parent = make_parent(child)
    config = parent.to_dict()
    serialized = config["tools"][0]
    assert serialized["type"] == "worker"
    assert serialized["worker_binding"] == {"agent": "researcher", "action": "infer"}
    assert "func_path" not in serialized
    with pytest.raises(ValueError, match="Reconnect local subagents"):
        Agent.from_dict(config)
    restored = Agent.from_dict(config, subagents=[child])
    assert restored.tools["ask_worker"].binding == parent.tools["ask_worker"].binding
    tampered = copy.deepcopy(config)
    tampered["tools"][0]["input_schema"]["properties"]["task"]["type"] = "number"
    with pytest.raises(ValueError, match="schema differs"):
        Agent.from_dict(tampered, subagents=[child])


def test_worker_binding_changes_durable_configuration_fingerprint():
    workers = [Agent(name=name, llm="mock", verbosity=0) for name in ["first", "second"]]
    parents = [Agent(name="parent", subagents=workers, llm="mock", verbosity=0) for _ in workers]
    for parent, child in zip(parents, workers, strict=True):
        parent.add_worker_tool(child.card.name, name="ask", description="Same public description")
    assert configuration_fingerprint(parents[0]) != configuration_fingerprint(parents[1])
