"""Delegated tool intent is checked before dispatch and corrected without replay."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx2
import pytest

from protolink import (
    Agent,
    AgentCard,
    AgentGroup,
    AgentSkill,
    Artifact,
    Part,
    RunBudget,
    RunContext,
    RunEvent,
    RunHandle,
    Task,
    ToolCorrectionLimitError,
    ToolRejectedError,
    create_llm,
)
from protolink.core.budget import BudgetEnforcer, BudgetExceededError
from protolink.llms import MockLLM
from protolink.llms.delegation import validate_delegation_request
from protolink.llms.server.ollama_client import OllamaLLM
from protolink.llms.tool_calling import AGENT_INFER_TOOL_NAME, AGENT_TOOL_CALL_TOOL_NAME


def delegate(agent="planner", action="tool_call", tool="tool_call", args=None):
    payload = {"tool": tool, "args": args or {}} if action == "tool_call" else {"prompt": "Generate docstrings."}
    return {"type": "agent_call", "agent": agent, "action": action, **payload}


def planner_card():
    return AgentCard(
        name="planner", description="Reason about code", url="runtime://planner", capabilities={"has_llm": True}
    )


def scripted_ollama(monkeypatch, mode, actions, streaming):
    """Use real JSON/native acquisition with deterministic model responses."""
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="test", tool_calling=mode)
    proposals, requests = iter(actions), []

    def respond(payload):
        requests.append(json.loads(json.dumps(payload)))
        proposal = next(proposals)
        if mode == "native" and proposal["type"] == "agent_call":
            if proposal["action"] == "infer":
                name, arguments = AGENT_INFER_TOOL_NAME, {"agent": proposal["agent"], "prompt": proposal["prompt"]}
            else:
                name, arguments = (
                    AGENT_TOOL_CALL_TOOL_NAME,
                    {"agent": proposal["agent"], "tool": proposal["tool"], "args_json": json.dumps(proposal["args"])},
                )
            message = {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}
        else:
            message = {"content": json.dumps(proposal)}
        return {"message": message}

    monkeypatch.setattr(llm, "_post_chat", respond)
    if streaming:
        client = httpx2.AsyncClient
        transport = httpx2.MockTransport(
            lambda request: httpx2.Response(200, content=json.dumps(respond(json.loads(request.content))) + "\n")
        )
        monkeypatch.setattr(httpx2, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    return llm, requests


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_code_assistant_recovers_exact_planner_request_without_repeating_read(monkeypatch, mode, streaming):
    calls = []

    def read_file(path: str) -> str:
        """Read a distinctive observation once."""
        calls.append(("read", path))
        return "utils-observation-E1"

    def write_file(path: str, content: str) -> str:
        """Record the accepted change once."""
        calls.append(("write", path))
        return "written"

    coder = Agent(name="coder", transport="runtime", tools=[read_file, write_file], verbosity=0)
    planner = Agent(
        name="planner", transport="runtime", llm=MockLLM(default_response="Generated docstrings."), verbosity=0
    )
    llm, requests = scripted_ollama(
        monkeypatch,
        mode,
        [
            delegate("coder", tool="read_file", args={"path": "utils.py"}),
            delegate(args={"task_description": "Add docstrings to utils.py"}),
            delegate("coder", tool="read_file", args={"path": "utils.py"}),
            delegate(action="infer"),
            delegate("coder", tool="write_file", args={"path": "utils.py", "content": "Generated docstrings."}),
            {"type": "final", "content": "Added docstrings."},
        ],
        streaming,
    )
    parent = Agent(name="orchestrator", transport="runtime", llm=llm, verbosity=0)
    parent.discover_agents = AsyncMock(return_value=[coder.card, planner.card])
    planner_requests = []
    original_run, original_stream = planner.run_task, planner.run_task_streaming

    async def record_run(task):
        planner_requests.append(task)
        return await original_run(task)

    async def record_stream(task):
        planner_requests.append(task)
        async for event in original_stream(task):
            yield event

    planner.run_task, planner.run_task_streaming = record_run, record_stream
    context = RunContext(budget=RunBudget(max_llm_calls=6, max_tool_calls=2, max_steps=6))
    async with AgentGroup([parent, coder, planner]):
        if streaming:
            handle = RunHandle.start(parent, Task.create_infer("Add docstrings", context=context))
            events = [event async for event in handle.events()]
            result = await handle.result()
            assert result.status == "completed", result.error
            rejected = next(event for event in events if event.payload.get("llm_event_type") == "agent_call_rejected")
            assert rejected.type == "action.rejected" and rejected.severity == "warning"
            assert rejected.payload["rejection"]["code"] == "unknown_delegated_tool"
            assert "nothing changed" in rejected.summary
            task = result.task
        else:
            task = await parent.run_task(Task.create_infer("Add docstrings", context=context))
            assert task.state.value == "completed"
    assert calls == [("read", "utils.py"), ("write", "utils.py")]
    assert len(planner_requests) == 1
    assert planner_requests[0].messages[0].parts[0].type == "infer"
    assert len(requests) == 6
    feedback = json.dumps(requests[2]["messages"])
    assert "utils-observation-E1" in feedback and "agent_rejection" in feedback
    assert "action='infer'" in feedback and "top-level prompt" in feedback
    assert sum(artifact.kind == "action_rejection" for artifact in task.artifacts) == 1
    assert all(("tools" in request) == (mode == "native") for request in requests)


@pytest.mark.parametrize("serialized", [False, True])
def test_advertised_argument_schema_is_validated_and_coerced(serialized):
    card = AgentCard(
        name="counter",
        description="Count",
        url="runtime://counter",
        skills=[AgentSkill(id="count", input_schema={"count": {"type": "integer", "required": True}})],
    )
    if serialized:
        card = card.to_dict()
    payload = delegate("counter", tool="count", args={"count": "4"})
    assert validate_delegation_request("counter", "tool_call", payload, [card])["args"] == {"count": 4}
    assert payload["args"] == {"count": "4"}
    with pytest.raises(ToolRejectedError) as raised:
        validate_delegation_request(
            "counter", "tool_call", delegate("counter", tool="count", args={"count": "bad"}), [card]
        )
    assert raised.value.code == "invalid_delegated_arguments"


@pytest.mark.parametrize("proposal", [delegate(), delegate("invented", action="infer")])
@pytest.mark.asyncio
async def test_catalog_rejections_are_bounded_and_never_call_the_callback(proposal):
    llm = MockLLM(sequential_responses=[proposal] * 4)
    callback = AsyncMock()
    with pytest.raises(ToolCorrectionLimitError) as raised:
        await llm.infer(query="Plan", tools={}, agent_cards=[planner_card()], agent_callback=callback)
    assert raised.value.attempts == 3
    assert llm._current_seq_idx == 3
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_and_delegated_rejections_share_the_allowance():
    llm = create_llm(
        "mock",
        max_tool_corrections=1,
        sequential_responses=[{"type": "tool_call", "tool": "missing", "args": {}}, delegate()],
    )
    callback = AsyncMock()
    with pytest.raises(ToolCorrectionLimitError) as raised:
        await llm.infer(query="Plan", tools={}, agent_cards=[planner_card()], agent_callback=callback)
    assert raised.value.attempts == 2 and raised.value.tool_name == "planner.tool_call"
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_correction_consumes_the_current_model_budget():
    llm = MockLLM(sequential_responses=[delegate(), "unused"])
    context = RunContext(budget=RunBudget(max_llm_calls=1))
    budget = BudgetEnforcer(context)
    callback = AsyncMock()
    with pytest.raises(BudgetExceededError):
        await llm.infer(
            query="Plan",
            tools={},
            agent_cards=[planner_card()],
            agent_callback=callback,
            run_context=context,
            budget_enforcer=budget,
        )
    assert budget.usage.llm_calls == 1 and budget.usage.tool_calls == 0
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_rechecks_the_target_card_before_sending():
    old = AgentCard(name="worker", description="Worker", url="runtime://worker", skills=[AgentSkill(id="removed")])
    current = AgentCard(name="worker", description="Worker", url="runtime://worker")
    parent = Agent(
        name="parent",
        llm=MockLLM(sequential_responses=[delegate("worker", tool="removed"), "No available tool."]),
        verbosity=0,
    )
    parent.discover_agents = AsyncMock(side_effect=lambda filter_by=None: [old] if filter_by is None else [current])
    parent.call_agent = AsyncMock(side_effect=AssertionError("must not dispatch"))
    assert await parent.invoke("Work") == "No available tool."
    parent.call_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_rechecks_changed_inference_support_before_sending():
    old = planner_card()
    current = AgentCard(
        name="planner",
        description="Now tools-only",
        url="runtime://planner",
        capabilities={"supports_inference": False},
    )
    parent = Agent(name="parent", llm=MockLLM(sequential_responses=[delegate(action="infer"), "Unavailable."]))
    parent.discover_agents = AsyncMock(side_effect=lambda filter_by=None: [old] if filter_by is None else [current])
    parent.call_agent = AsyncMock(side_effect=AssertionError("must not dispatch"))
    assert await parent.invoke("Work") == "Unavailable."
    parent.call_agent.assert_not_awaited()


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.asyncio
async def test_tools_only_inference_corrects_to_tool_before_dispatch(monkeypatch, mode, streaming, owned):
    calls = []

    def read_file(path: str) -> str:
        """Record only accepted execution."""
        calls.append(path)
        return "utils-content"

    child = Agent(name="coder", transport="runtime", tools=[read_file], verbosity=0)
    assert child.card.capabilities.supports_inference is False
    llm, requests = scripted_ollama(
        monkeypatch,
        mode,
        [
            delegate("coder", action="infer"),
            delegate("coder", tool="read_file", args={"path": "utils.py"}),
            {"type": "final", "content": "Read successfully."},
        ],
        streaming,
    )
    parent = Agent(name="parent", llm=llm, transport="runtime", subagents=[child] if owned else None, verbosity=0)
    if not owned:
        parent.discover_agents = AsyncMock(return_value=[child.card])
    task = Task.create_infer(
        "Read utils.py",
        context=RunContext(budget=RunBudget(max_llm_calls=3, max_tool_calls=1, max_steps=4 if owned else 3)),
    )
    async with AgentGroup([parent, child]):
        if streaming:
            handle = RunHandle.start(parent, task)
            events = [event async for event in handle.events()]
            result = await handle.result()
            assert result.status == "completed", result.error
            rejection = next(event for event in events if event.payload.get("llm_event_type") == "agent_call_rejected")
            assert rejection.payload["rejection"]["code"] == "unsupported_inference"
        else:
            await parent.run_task(task)
            assert task.state.value == "completed"
    assert task.get_output() == "Read successfully."
    assert calls == ["utils.py"]
    assert len(requests) == 3
    feedback = json.dumps(requests[1]["messages"])
    assert "unsupported_inference" in feedback and "read_file" in feedback
    assert "action='tool_call'" in feedback
    assert sum(artifact.kind == "action_rejection" for artifact in task.artifacts) == 1
    if owned:
        assert len(task.metadata["subagent_runs"]) == 1


@pytest.mark.parametrize("serialized", [False, True])
def test_declared_no_inference_overrides_a_positive_llm_hint(serialized):
    card = AgentCard(
        name="worker",
        description="Tool requests only",
        url="runtime://worker",
        capabilities={"has_llm": True, "supports_inference": False},
    )
    cards = [card.to_dict() if serialized else card]
    with pytest.raises(ToolRejectedError) as rejected:
        validate_delegation_request("worker", "infer", {"prompt": "Reason"}, cards)
    assert rejected.value.code == "unsupported_inference"
    with pytest.raises(ToolRejectedError) as rejected:
        validate_delegation_request("worker", "tool_call", {"tool": "invented", "args": {}}, cards)
    assert "action='infer'" not in rejected.value.suggestion


@pytest.mark.parametrize("failure", [ValueError("body failed"), ConnectionError("disconnected")])
@pytest.mark.asyncio
async def test_arbitrary_callback_exceptions_are_not_reclassified_as_rejections(failure):
    llm = MockLLM(sequential_responses=[delegate(action="infer"), "must not continue"])
    callback = AsyncMock(side_effect=failure)
    with pytest.raises(RuntimeError, match=r"Agent call.*failed"):
        await llm.infer(query="Plan", tools={}, agent_cards=[planner_card()], agent_callback=callback)
    callback.assert_awaited_once()
    assert llm._current_seq_idx == 1


@pytest.mark.asyncio
async def test_callback_without_catalog_and_custom_non_llm_inference_still_work():
    for support in (None, True):
        card = AgentCard(
            name="planner",
            description="Custom task handler",
            url="runtime://planner",
            capabilities={"supports_inference": support},
        )
        assert card.capabilities.has_llm is False
        llm = MockLLM(sequential_responses=[delegate(action="infer"), "done"])
        callback = AsyncMock(return_value="custom answer")
        assert (await llm.infer(query="Plan", tools={}, agent_cards=[card], agent_callback=callback)).content == "done"
        callback.assert_awaited_once()
    llm = MockLLM(sequential_responses=[delegate(action="infer"), "done"])
    callback = AsyncMock(return_value="custom answer")
    assert (await llm.infer(query="Plan", tools={}, agent_cards=None, agent_callback=callback)).content == "done"
    callback.assert_awaited_once()


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.asyncio
async def test_single_tool_rejection_can_be_corrected_after_child_dispatch(tmp_path, durable):
    calls = []

    def select(value: str) -> str:
        """Reject before changing anything."""
        calls.append(value)
        if value != "good":
            raise ToolRejectedError("Choose good.", code="invalid_selection")
        return "selected"

    child = Agent(name="worker", transport="runtime", tools=[select], verbosity=0)
    parent = Agent(
        name="parent",
        transport="runtime",
        llm=MockLLM(
            sequential_responses=[
                delegate("worker", tool="select", args={"value": "bad"}),
                delegate("worker", tool="select", args={"value": "good"}),
                "done",
            ]
        ),
        verbosity=0,
        subagents=[child] if durable else None,
        durability=tmp_path / "runs.db" if durable else None,
    )
    if not durable:
        parent.discover_agents = AsyncMock(return_value=[child.card])
    context = RunContext(budget=RunBudget(max_tool_calls=2))
    async with AgentGroup([parent, child]):
        assert await parent.invoke("Select", context=context) == "done"
    assert calls == ["bad", "good"]
    if durable:
        record = parent.durability.get(context.run_id)
        assert record.status == "completed"
        assert any(entry["state"] == "rejected" for entry in record.data["actions"].values())
        assert not any(entry["state"] in {"executing", "uncertain"} for entry in record.data["actions"].values())
        assert next(iter(record.data["loops"].values()))["tool_corrections"] == 1


@pytest.mark.parametrize("reason", ["untyped", "completed_effect", "wrong_call_id", "infer", "multiple_requests"])
def test_only_explicit_correlated_no_change_tool_tasks_are_recoverable(reason):
    task = Task.create_infer("reason") if reason == "infer" else Task.create_tool_call("select", {"value": "bad"})
    if reason == "multiple_requests":
        task.messages[0].parts.append(Part.tool_call(tool_name="write", args={}))
    ids = frozenset(item.id for item in task.messages)
    error = {"message": "Tool 'select' not found"} if reason == "untyped" else ToolRejectedError("Rejected.").to_dict()
    call_id = task.messages[0].parts[0].as_tool_call().call_id if reason != "infer" else "request"
    task.begin()
    task.add_artifact(
        Artifact(parts=[Part.tool_output(call_id="different" if reason == "wrong_call_id" else call_id, error=error)])
    )
    if reason == "completed_effect":
        task.metadata["run_events"] = [RunEvent(type="action.completed").to_dict()]
    task.fail("worker failed")
    with pytest.raises(RuntimeError, match="worker failed"):
        Agent._require_completed_delegation(task, "worker", request_item_ids=ids)


@pytest.mark.asyncio
async def test_rejected_agent_observation_has_portable_fallback():
    class BrokenObservationLLM(MockLLM):
        def _inject_agent_call(self, **kwargs):
            raise RuntimeError("history adapter failed")

    llm = BrokenObservationLLM(sequential_responses=[delegate(), "Handled rejection."])
    callback = AsyncMock()
    assert (
        await llm.infer(query="Plan", tools={}, agent_cards=[planner_card()], agent_callback=callback)
    ).content == "Handled rejection."
    assert "portable_fallback" in json.dumps(llm.history.messages)
    assert "unknown_delegated_tool" in json.dumps(llm.history.messages)
    callback.assert_not_awaited()
