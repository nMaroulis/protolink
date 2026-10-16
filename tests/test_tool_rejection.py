"""Tool rejection is explicit, bounded, observable and safe to resume."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap

import httpx
import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    CancellationToken,
    CapabilityPolicy,
    CompletionCheck,
    CompletionValidator,
    Part,
    RunAction,
    RunBudget,
    RunContext,
    RunHandle,
    RunInterrupted,
    RunReport,
    Task,
    Tool,
    ToolCorrectionLimitError,
    ToolRejectedError,
    create_llm,
)
from protolink.core.budget import BudgetDecision, BudgetEnforcer, BudgetExceededError, BudgetPolicy
from protolink.llms import MockLLM
from protolink.llms.server.ollama_client import OllamaLLM
from protolink.storage.durable import UncertainExecutionError
from protolink.telemetry.local import LocalTraceTelemetry
from protolink.tools.prepared import PreparedTool


def action(name="plan_task", **args):
    return {"type": "tool_call", "tool": name, "args": args}


def rejection():
    return ToolRejectedError(
        "Unknown check selection.",
        code="invalid_check_selection",
        details={"valid_ids": ["lint", "tests"]},
        suggestion="Select lint or tests.",
    )


def test_rejection_feedback_is_detached_and_round_trips():
    details = {"valid_ids": ["lint"]}
    error = ToolRejectedError("Choose a valid check.", details=details)
    details["valid_ids"].append("private")
    feedback = error.to_dict()
    feedback["details"]["valid_ids"].append("changed")
    restored = ToolRejectedError.from_dict(error.to_dict())
    assert restored.details == {"valid_ids": ["lint"]}
    assert restored.to_dict()["changes_made"] is False
    with pytest.raises(ValueError, match="guarantee"):
        ToolRejectedError.from_dict({**error.to_dict(), "changes_made": True})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"message": ""},
        {"message": "x", "code": " "},
        {"message": "x", "suggestion": ""},
        {"message": "x", "details": {"number": float("nan")}},
    ],
)
def test_invalid_rejection_feedback_fails_visibly(kwargs):
    with pytest.raises(ValueError):
        ToolRejectedError(**kwargs)


@pytest.mark.parametrize("limit", [0, 1, 4])
def test_factory_configures_runtime_limit_without_generation_options(limit):
    llm = create_llm("mock", max_tool_corrections=limit)
    assert llm.max_tool_corrections == limit
    assert "max_tool_corrections" not in llm.model_params
    restored = Agent.from_dict(Agent(name="serialized", llm=llm, verbosity=0).to_dict())
    assert restored.llm.max_tool_corrections == limit


@pytest.mark.parametrize("value", [True, "2", -1, 1000])
def test_invalid_runtime_correction_limit(value):
    with pytest.raises((TypeError, ValueError)):
        create_llm("mock", max_tool_corrections=value)


def scripted_ollama(monkeypatch, mode, actions, streaming):
    """Keep real adapter parsing and history while replacing network delivery."""
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="test", tool_calling=mode)
    responses, requests = iter(actions), []

    def respond(payload):
        requests.append(json.loads(json.dumps(payload)))
        proposal = next(responses)
        if mode == "native" and proposal["type"] == "tool_call":
            message = {"tool_calls": [{"function": {"name": proposal["tool"], "arguments": proposal["args"]}}]}
        else:
            message = {"content": json.dumps(proposal)}
        return {"message": message, "prompt_eval_count": 12, "eval_count": 7}

    monkeypatch.setattr(llm, "_post_chat", respond)
    if streaming:
        client = httpx.AsyncClient
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=json.dumps(respond(json.loads(request.content))) + "\n")
        )
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    return llm, requests


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_rejection_returns_feedback_without_replaying_completed_tools(monkeypatch, mode, streaming):
    llm, requests = scripted_ollama(
        monkeypatch,
        mode,
        [
            action("lookup"),
            action(check_id="typo"),
            action(check_id="lint"),
            action("lookup"),
            {"type": "final", "content": "Planned lint using observation-E1."},
        ],
        streaming,
    )
    calls, changes = [], []

    def lookup() -> str:
        """Return an observation that subsequent requests must retain."""
        calls.append("lookup")
        return "observation-E1"

    def plan_task(check_id: str) -> str:
        """Validate the selection before recording the accepted plan."""
        calls.append(check_id)
        if check_id not in {"lint", "tests"}:
            raise rejection()
        changes.append(check_id)
        return f"Planned {check_id}."

    agent = Agent(name="planner", llm=llm, tools=[lookup, plan_task], verbosity=0)
    context = RunContext(budget=RunBudget(max_llm_calls=5, max_tool_calls=3, max_steps=5))
    if streaming:
        handle = RunHandle.start(agent, Task.create_infer("Plan a check.", context=context))
        events = [event async for event in handle.events()]
        result = await handle.result()
        assert result.status == "completed", result.error
        rejected = [event for event in events if event.type == "action.rejected"]
        assert len(rejected) == 1
        assert rejected[0].severity == "warning"
        assert "nothing changed" in rejected[0].summary
        assert rejected[0].payload["rejection"]["code"] == "invalid_check_selection"
        receipts = result.task.artifacts
    else:
        task = await agent.run_task(Task.create_infer("Plan a check.", context=context))
        assert task.state.value == "completed", task.metadata
        assert any(event.type == "action.rejected" for event in RunReport.from_task(task).events)
        receipts = task.artifacts
    assert calls == ["lookup", "typo", "lint"]
    assert changes == ["lint"]
    assert len(requests) == 5
    feedback = json.dumps(requests[2]["messages"])
    assert "valid_ids" in feedback and "Select lint or tests" in feedback
    assert "observation-E1" in feedback and "tool_rejection" in feedback
    assert sum(receipt.kind == "action_rejection" for receipt in receipts) == 1
    assert sum(receipt.kind == "action_result" for receipt in receipts) == 2
    assert all(("tools" in request) == (mode == "native") for request in requests)


@pytest.mark.parametrize("limit", [0, 2])
@pytest.mark.asyncio
async def test_identical_rejections_are_not_deduplicated_and_exhaust_the_limit(limit):
    calls, events = [], []

    async def plan_task(check_id: str) -> str:
        """Reject without touching application state."""
        calls.append(check_id)
        raise rejection()

    llm = MockLLM(sequential_responses=[action(check_id="typo")] * (limit + 2))
    llm.max_tool_corrections = limit

    async def capture(event):
        events.append(event)

    with pytest.raises(ToolCorrectionLimitError) as raised:
        await llm.infer(query="Plan", tools={"plan_task": Tool.from_callable(plan_task)}, event_callback=capture)
    assert len(calls) == limit + 1
    assert raised.value.attempts == limit + 1 and raised.value.limit == limit
    assert raised.value.last_error.code == "invalid_check_selection"
    assert "nothing changed" in str(raised.value)
    assert not any(event["type"] == "tool_result" for event in events)
    assert events[-1]["type"] == "tool_rejected" and events[-1]["recoverable"] is False


@pytest.mark.asyncio
async def test_schema_unknown_tool_and_body_rejections_share_one_allowance():
    calls = []

    def plan_task(check_id: int) -> str:
        """Reject a syntactically valid but semantically unsupported selection."""
        calls.append(check_id)
        raise rejection()

    llm = MockLLM(sequential_responses=[action("missing"), action(check_id="bad-type"), action(check_id=1), "unused"])
    with pytest.raises(ToolCorrectionLimitError) as raised:
        await llm.infer(query="Plan", tools={"plan_task": Tool.from_callable(plan_task)})
    assert raised.value.attempts == 3
    assert calls == [1]


@pytest.mark.parametrize("budget", [RunBudget(max_llm_calls=1), RunBudget(max_tool_calls=1), RunBudget(max_steps=1)])
@pytest.mark.asyncio
async def test_rejections_consume_existing_run_budgets(budget):
    calls = []

    def plan_task(check_id: str) -> str:
        """Reject a request before any change."""
        calls.append(check_id)
        raise rejection()

    llm = MockLLM(sequential_responses=[action(check_id="typo")] * 4)
    context = RunContext(budget=budget)
    enforcer = BudgetEnforcer(context)
    with pytest.raises(BudgetExceededError):
        await llm.infer(
            query="Plan",
            tools={"plan_task": Tool.from_callable(plan_task)},
            run_context=context,
            budget_enforcer=enforcer,
        )
    assert calls == ["typo"]
    assert enforcer.usage.tool_calls == 1


@pytest.mark.asyncio
async def test_ordinary_execution_exception_still_aborts():
    def plan_task() -> str:
        """Represent an execution failure whose effects may be uncertain."""
        raise ValueError("write failed")

    llm = MockLLM(sequential_responses=[action(), "must not continue"])
    with pytest.raises(RuntimeError, match="execution failed") as raised:
        await llm.infer(query="Plan", tools={"plan_task": Tool.from_callable(plan_task)})
    assert isinstance(raised.value.__cause__, ValueError)
    assert llm._current_seq_idx == 1


@pytest.mark.asyncio
async def test_streamed_run_retains_structured_correction_limit_failure():
    def plan_task() -> str:
        """Reject before changing the plan."""
        raise rejection()

    llm = create_llm("mock", max_tool_corrections=0, sequential_responses=[action()])
    handle = Agent(name="planner", llm=llm, tools=[plan_task], verbosity=0).start_run("Plan")
    events = [event async for event in handle.events()]
    result = await handle.result()
    assert result.status == "failed"
    blocker = result.error["blockers"][0]
    assert blocker["code"] == "tool_correction_limit"
    assert blocker["attempts"] == 1 and blocker["max_tool_corrections"] == 0
    assert blocker["rejection"]["changes_made"] is False
    assert any(event.type == "action.rejected" for event in events)
    assert any(event.type == "tool.correction.exhausted" for event in events)
    assert not any(event.type == "action.completed" for event in events)


@pytest.mark.asyncio
async def test_direct_tools_report_structured_rejection_without_retrying():
    calls = []

    def plan_task() -> str:
        """Reject without changing application state."""
        calls.append("called")
        raise rejection()

    tool = Tool.from_callable(plan_task)
    with pytest.raises(ToolRejectedError):
        await tool()
    agent = Agent(name="planner", tools=[tool], verbosity=0)
    task = Task.create_infer("unused")
    output = await agent.execute_tool(Part.tool_call(tool_name="plan_task", args={}, call_id="request"), task=task)
    assert output.as_tool_output().error["status"] == "rejected"
    assert output.as_tool_output().error["changes_made"] is False
    assert calls == ["called", "called"]
    report = RunReport.from_task(task)
    assert any(event.type == "action.rejected" for event in report.events)
    assert not any(event.type in {"action.completed", "action.failed"} for event in report.events)
    validation = await CompletionValidator([CompletionCheck("executed", lambda evidence: True)]).validate(task)
    assert validation[0].code == "execution_evidence_missing"


@pytest.mark.asyncio
async def test_durable_pause_retains_rejection_counter_and_receipt(tmp_path):
    calls = []

    def plan_task(check_id: str) -> str:
        """Reject without effects before the protected action can be prepared."""
        calls.append(check_id)
        raise rejection()

    def save_plan() -> str:
        """Represent an operation requiring approval."""
        return "saved"

    def make(responses):
        llm = MockLLM(sequential_responses=responses)
        llm.max_tool_corrections = 1
        return Agent(
            name="planner",
            llm=llm,
            tools=[plan_task, Tool.from_callable(save_plan, capabilities=["plan.save"])],
            policy=CapabilityPolicy({"plan.save": "require_approval"}),
            durability=tmp_path / "runs.db",
            verbosity=0,
        )

    agent = make([action(check_id="bad"), action("save_plan")])
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("Plan")
    pause = raised.value
    record = agent.durability.get(pause.run_id)
    assert (
        next(entry for entry in record.data["actions"].values() if entry["state"] == "rejected")["rejection"][
            "changes_made"
        ]
        is False
    )
    assert next(iter(record.data["loops"].values()))["tool_corrections"] == 1
    restarted = make([action(check_id="bad"), "must not continue"])
    with pytest.raises(Exception, match="Tool correction limit"):
        await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, approved=True)
    assert calls == ["bad", "bad"]
    finished = restarted.durability.get(pause.run_id)
    assert finished.data["usage"]["tool_calls"] == 3
    assert not any(entry["state"] in {"executing", "uncertain"} for entry in finished.data["actions"].values())


@pytest.mark.asyncio
async def test_crash_after_rejection_receipt_does_not_reinvoke_or_recharge_tool(tmp_path):
    """Kill the worker after commit but before adding the rejection to history."""
    database = tmp_path / "runs.db"
    attempts = tmp_path / "attempts.txt"
    source = textwrap.dedent('''
        import asyncio
        import os
        import sys
        from pathlib import Path
        from protolink import Agent, RunBudget, RunContext, ToolRejectedError
        from protolink.core.durable import DurableRun
        from protolink.llms import MockLLM

        def plan_task(check_id: str) -> str:
            """Reject an unsupported check before changing the plan."""
            with Path(sys.argv[2]).open("a") as audit:
                audit.write(check_id + "\\n")
            raise ToolRejectedError("Unsupported check.", code="invalid_check")

        original = DurableRun.reject_action
        def crash_after_receipt(self, error):
            original(self, error)
            os._exit(71)
        DurableRun.reject_action = crash_after_receipt
        llm = MockLLM(sequential_responses=[{"type": "tool_call", "tool": "plan_task", "args": {"check_id": "bad"}}])
        agent = Agent(name="planner", llm=llm, tools=[plan_task], durability=sys.argv[1], verbosity=0)
        context = RunContext(
            run_id="recover-rejection", budget=RunBudget(max_llm_calls=2, max_tool_calls=1, max_steps=2)
        )
        asyncio.run(agent.invoke("Plan", context=context))
    ''')
    stopped = subprocess.run(
        [sys.executable, "-c", source, str(database), str(attempts)], capture_output=True, text=True, timeout=20
    )
    assert stopped.returncode == 71, stopped.stderr

    def plan_task(check_id: str) -> str:
        """Reject an unsupported check before changing the plan."""
        with attempts.open("a") as audit:
            audit.write(check_id + "\n")
        raise ToolRejectedError("Unsupported check.", code="invalid_check")

    agent = Agent(
        name="planner",
        llm=MockLLM(sequential_responses=["Recovered without retry."]),
        tools=[plan_task],
        durability=database,
        verbosity=0,
    )
    assert await agent.resume("recover-rejection") == "Recovered without retry."
    assert attempts.read_text().splitlines() == ["bad"]
    record = agent.durability.get("recover-rejection")
    assert record.status == "completed"
    assert record.data["usage"]["tool_calls"] == 1
    assert record.data["usage"]["llm_calls"] == 2
    assert next(iter(record.data["loops"].values()))["tool_corrections"] == 1


@pytest.mark.asyncio
async def test_authorized_execution_hook_can_reject_without_calling_the_callable():
    calls = []

    def plan_task(check_id: str) -> str:
        """Fallback callable must not bypass the prepared execution hook."""
        calls.append(check_id)
        return "unexpected"

    class PreparedTool(Tool):
        async def execute_authorized(self, execution):
            assert execution.authorization.action.payload["arguments"] == {"check_id": "bad"}
            raise rejection()

    agent = Agent(
        name="planner",
        llm=MockLLM(sequential_responses=[action(check_id="bad"), "Rejected safely."]),
        tools=[PreparedTool.from_callable(plan_task)],
        verbosity=0,
    )
    assert await agent.invoke("Plan") == "Rejected safely."
    assert calls == []


@pytest.mark.asyncio
async def test_rejection_survives_a_broken_provider_observation_hook():
    class BrokenObservationLLM(MockLLM):
        def _inject_tool_call(self, **kwargs):
            raise RuntimeError("history hook failed")

    def plan_task() -> str:
        """Reject with correction data."""
        raise rejection()

    llm = BrokenObservationLLM(sequential_responses=[action(), "Stopped safely."])
    assert (
        await llm.infer(query="Plan", tools={"plan_task": Tool.from_callable(plan_task)})
    ).content == "Stopped safely."
    assert "portable_fallback" in json.dumps(llm.history.messages)
    assert "invalid_check_selection" in json.dumps(llm.history.messages)


@pytest.mark.asyncio
async def test_local_trace_closes_rejected_span_with_distinct_status():
    def plan_task(check_id: str) -> str:
        """Reject without effects."""
        raise rejection()

    telemetry = LocalTraceTelemetry()
    agent = Agent(
        name="planner",
        llm=MockLLM(sequential_responses=[action(check_id="bad"), "Stopped without changes."]),
        tools=[plan_task],
        telemetry=telemetry,
        verbosity=0,
    )
    assert await agent.invoke("Plan") == "Stopped without changes."
    trace = telemetry.recorder.replay()[-1]
    spans = [span for span in trace["spans"] if span["kind"] == "tool"]
    assert len(spans) == 1 and spans[0]["ended_at"] is not None
    assert spans[0]["status"] == "rejected" and spans[0]["error"] is None


@pytest.mark.asyncio
async def test_direct_task_trace_distinguishes_rejection_from_execution_error():
    def plan_task() -> str:
        """Reject before changing the plan."""
        raise rejection()

    telemetry = LocalTraceTelemetry()
    agent = Agent(name="planner", tools=[plan_task], telemetry=telemetry, verbosity=0)
    task = await agent.run_task(Task.create_tool_call("plan_task", {}))
    assert task.state.value == "failed"
    trace = telemetry.recorder.replay()[-1]
    tool_span = next(span for span in trace["spans"] if span["kind"] == "tool")
    assert tool_span["status"] == "rejected" and tool_span["error"] is None
    assert tool_span["ended_at"] is not None


def prepared_plan_tool(*, async_builder=False):
    preparations, executions = [], []

    def plan_task(check_id: str) -> str:
        """Prepare an allowed check before requesting permission to save it."""
        raise AssertionError("The signature callable must not execute")

    def prepare(arguments, context):
        preparations.append(arguments["check_id"])
        if arguments["check_id"] not in {"lint", "tests"}:
            raise rejection()
        return RunAction(kind="tool.call", name="plan_task", payload={"arguments": arguments})

    async def prepare_async(arguments, context):
        await asyncio.sleep(0)
        return prepare(arguments, context)

    async def execute(execution):
        execution.check()
        check_id = execution.authorization.action.payload["arguments"]["check_id"]
        executions.append(check_id)
        return f"Planned {check_id}."

    return (
        PreparedTool(
            plan_task,
            prepare=prepare_async if async_builder else prepare,
            execute=execute,
            capabilities=("plan.save",),
        ),
        preparations,
        executions,
    )


@pytest.mark.parametrize("async_builder", [False, True])
@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_preparation_rejection_corrects_before_approval_execution_and_tool_charge(
    monkeypatch, async_builder, mode, streaming
):
    llm, requests = scripted_ollama(
        monkeypatch,
        mode,
        [action(check_id="bad"), action(check_id="lint"), {"type": "final", "content": "Planned lint."}],
        streaming,
    )
    tool, preparations, executions = prepared_plan_tool(async_builder=async_builder)
    approvals = []

    async def approve(request, context):
        approvals.append(request.action.payload["arguments"])
        return True

    agent = Agent(
        name="planner",
        llm=llm,
        tools=[tool],
        policy=CapabilityPolicy({"plan.save": "require_approval"}),
        approval_handler=approve,
        verbosity=0,
    )
    context = RunContext(budget=RunBudget(max_llm_calls=3, max_tool_calls=1, max_steps=3))
    task = Task.create_infer("Plan", context=context)
    if streaming:
        handle = RunHandle.start(agent, task)
        events = [event async for event in handle.events()]
        result = await handle.result()
        assert result.status == "completed", result.error
        task = result.task
    else:
        task = await agent.run_task(task)
        events = RunReport.from_task(task).events
    assert task.state.value == "completed"
    assert preparations == ["bad", "lint"]
    assert executions == ["lint"]
    assert approvals == [{"check_id": "lint"}]
    assert len(requests) == 3
    assert "invalid_check_selection" in json.dumps(requests[1]["messages"])
    rejected = [event for event in events if event.type == "action.rejected"]
    assert len(rejected) == 1
    assert rejected[0].payload["metadata"]["phase"] == "preparation"
    assert rejected[0].action_id
    assert not any(
        event.action_id == rejected[0].action_id
        for event in events
        if event.type in {"action.requested", "action.started", "approval.required", "action.completed"}
    )
    receipt = next(artifact for artifact in task.artifacts if artifact.kind == "action_rejection")
    assert receipt.action_id == rejected[0].action_id
    assert receipt.parts[0].content["phase"] == "preparation"
    assert sum(artifact.kind == "action_result" for artifact in task.artifacts) == 1


@pytest.mark.parametrize("limit", [0, 1])
@pytest.mark.asyncio
async def test_preparation_rejections_exhaust_corrections_without_charging_tools(limit):
    tool, preparations, executions = prepared_plan_tool()
    llm = MockLLM(sequential_responses=[action(check_id="bad")] * 3)
    llm.max_tool_corrections = limit
    agent = Agent(name="planner", llm=llm, tools=[tool], verbosity=0)
    context = RunContext(budget=RunBudget(max_tool_calls=0))
    with pytest.raises(ToolCorrectionLimitError) as raised:
        await agent.run_task(Task.create_infer("Plan", context=context))
    assert raised.value.attempts == limit + 1
    assert preparations == ["bad"] * (limit + 1)
    assert executions == []
    assert llm._current_seq_idx == limit + 1


@pytest.mark.asyncio
async def test_durable_preparation_correction_resumes_approval_with_counter_and_budget_intact(tmp_path):
    executions = []

    def make(responses):
        tool, _, accepted = prepared_plan_tool()
        llm = MockLLM(sequential_responses=responses)
        llm.max_tool_corrections = 1
        agent = Agent(
            name="planner",
            llm=llm,
            tools=[tool],
            policy=CapabilityPolicy({"plan.save": "require_approval"}),
            durability=tmp_path / "runs.db",
            verbosity=0,
        )
        executions.append(accepted)
        return agent

    agent = make([action(check_id="bad"), action(check_id="lint")])
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("Plan", budget=RunBudget(max_tool_calls=1, max_llm_calls=3, max_steps=3))
    pause = raised.value
    record = agent.durability.get(pause.run_id)
    assert record.data["usage"]["tool_calls"] == 0
    assert record.data["usage"]["llm_calls"] == 2
    assert next(iter(record.data["loops"].values()))["tool_corrections"] == 1
    assert len(record.data["actions"]) == 1
    assert next(iter(record.data["actions"].values()))["state"] == "waiting"
    restarted = make([action(check_id="bad"), "must not continue"])
    with pytest.raises(ToolCorrectionLimitError):
        await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, approved=True)
    finished = restarted.durability.get(pause.run_id)
    assert executions == [[], ["lint"]]
    assert finished.data["usage"]["tool_calls"] == 1
    assert finished.data["usage"]["llm_calls"] == 3
    assert next(iter(finished.data["loops"].values()))["tool_corrections"] == 2
    assert not any(entry["state"] in {"executing", "uncertain"} for entry in finished.data["actions"].values())


@pytest.mark.parametrize("error_type", [ValueError, PermissionError, UncertainExecutionError])
@pytest.mark.asyncio
async def test_other_preparation_failures_are_not_correctable(error_type):
    tool, preparations, executions = prepared_plan_tool()

    def fail(arguments, context):
        raise error_type("Preparation stopped")

    tool.action_builder = fail
    llm = MockLLM(sequential_responses=[action(check_id="lint"), "must not continue"])
    agent = Agent(name="planner", llm=llm, tools=[tool], verbosity=0)
    task = Task.create_infer("Plan")
    with pytest.raises(RuntimeError) as raised:
        await agent.run_task(task)
    if error_type is UncertainExecutionError:
        assert isinstance(raised.value, UncertainExecutionError)
    else:
        assert isinstance(raised.value.__cause__, error_type)
    assert llm._current_seq_idx == 1
    assert preparations == executions == []
    assert not any(artifact.kind == "action_rejection" for artifact in task.artifacts)


@pytest.mark.asyncio
async def test_prepared_tool_policy_denial_remains_terminal():
    tool, preparations, executions = prepared_plan_tool()
    llm = MockLLM(sequential_responses=[action(check_id="lint"), "must not continue"])
    agent = Agent(name="planner", llm=llm, tools=[tool], policy=CapabilityPolicy({"plan.save": "deny"}), verbosity=0)
    with pytest.raises(ActionDeniedError):
        await agent.invoke("Plan")
    assert preparations == ["lint"]
    assert executions == []
    assert llm._current_seq_idx == 1


@pytest.mark.parametrize("boundary", ["cancellation", "context_cancellation", "budget"])
@pytest.mark.asyncio
async def test_preparation_rejection_cannot_override_an_active_stop(boundary):
    stopped = False

    class StoppingPolicy(BudgetPolicy):
        def evaluate(self, budget, usage):
            if stopped and boundary == "budget":
                return BudgetDecision(effect="deny", message="Hard budget stopped preparation", usage=usage)
            return super().evaluate(budget, usage)

    context = RunContext()
    enforcer = BudgetEnforcer(context, policy=StoppingPolicy())
    cancellation = CancellationToken()
    tool, _, executions = prepared_plan_tool()

    async def prepare(arguments, context):
        nonlocal stopped
        await asyncio.sleep(0)
        stopped = True
        if boundary == "cancellation":
            cancellation.cancel("Stop during preparation")
        elif boundary == "context_cancellation":
            context.canceled = True
            context.cancel_reason = "Stop during preparation"
        raise rejection()

    tool.action_builder = prepare
    agent = Agent(name="planner", tools=[tool], verbosity=0)

    async def authorize(runtime_action):
        authorization, _ = await agent._authorize_tool_action(tool, runtime_action.payload["arguments"], context)
        return authorization

    llm = MockLLM(sequential_responses=[action(check_id="bad"), "must not continue"])
    events = []

    async def capture(event):
        events.append(event)

    with pytest.raises(BudgetExceededError if boundary == "budget" else asyncio.CancelledError):
        await llm.infer(
            query="Plan",
            tools={tool.name: tool},
            action_authorizer=authorize,
            cancellation_token=cancellation,
            run_context=context,
            budget_enforcer=enforcer,
            event_callback=capture,
        )
    assert llm._current_seq_idx == 1
    assert enforcer.usage.llm_calls == 1
    assert enforcer.usage.tool_calls == 0
    assert executions == []
    assert not any(event["type"] in {"tool_rejected", "tool_start"} for event in events)
