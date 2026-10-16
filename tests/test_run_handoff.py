"""Cooperative slices preserve durable effects, history and hard stopping conditions."""

from __future__ import annotations

import asyncio
import json

import pytest

from protolink import (
    Agent,
    CapabilityPolicy,
    CheckpointMismatchError,
    RunBudget,
    RunContext,
    RunHandoff,
    RunInterrupted,
    RunManager,
    Task,
    TaskState,
    ToolRejectedError,
    UncertainExecutionError,
)
from protolink.llms import MockLLM
from protolink.tools import Tool


class RecordingLLM(MockLLM):
    def __init__(self, responses, calls):
        super().__init__(sequential_responses=list(responses))
        self.calls = calls

    def call(self, history):
        self.calls.append(history.messages)
        return super().call(history)


def write_action(value):
    return {"type": "tool_call", "tool": "write", "args": {"value": value}}


def make_agent(path, calls, effects, responses, *, slice_steps=1, **kwargs):
    def write(value: str) -> str:
        """Record one committed application effect."""
        effects.append(value)
        return value

    return Agent(
        name="worker",
        llm=RecordingLLM(responses, calls),
        tools=[Tool.from_callable(write, capabilities=["test.write"])],
        durability=path,
        yield_after_steps=slice_steps,
        verbosity=0,
        **kwargs,
    )


def run_id(task):
    return RunContext.from_task(task).run_id


@pytest.mark.asyncio
async def test_handoff_survives_restart_and_polling_without_repeating_committed_effects(tmp_path):
    path, calls, effects = tmp_path / "runs.db", [], []
    agent = make_agent(path, calls, effects, [write_action("first")])
    task = await agent.run_task(Task.create_infer("private assignment"))
    first = RunHandoff.from_task(task)
    assert task.state is TaskState.INPUT_REQUIRED and first is not None
    assert first.reason == "step_slice" and first.steps == 1
    assert first.usage.llm_calls == first.usage.steps == first.usage.tool_calls == 1
    assert len(first.completed_action_ids) == 1
    assert {artifact.action_id for artifact in task.artifacts if artifact.kind == "action_result"} == set(
        first.completed_action_ids
    )
    assert RunHandoff.from_dict(first.to_dict()) == first
    assert "private assignment" not in json.dumps(first.to_dict())
    request_id = task.metadata["interruption"]["request_id"]
    # Reading or submitting the pending Task cannot authorize another slice.
    assert RunHandoff.from_task(await agent.run_task(task)) == first
    assert task.metadata["interruption"]["request_id"] == request_id
    assert len(calls) == 1 and effects == ["first"]

    restarted = make_agent(path, calls, effects, [write_action("second"), "done"])
    paused = await restarted.resume_task(run_id(task))
    second = RunHandoff.from_task(paused)
    assert second is not None and second.steps == 2
    assert second.usage.llm_calls == second.usage.tool_calls == 2
    assert set(first.completed_action_ids) < set(second.completed_action_ids)
    assert paused.metadata["interruption"]["request_id"] != request_id
    assert "private assignment" in str(calls[1]) and "first" in str(calls[1])
    assert await restarted.resume(run_id(task)) == "done"
    assert await restarted.resume(run_id(task)) == "done"
    assert effects == ["first", "second"] and len(calls) == 3
    finished = restarted.durability.get(run_id(task))
    assert finished.data["usage"]["steps"] == finished.data["usage"]["llm_calls"] == 3
    assert finished.data["usage"]["tool_calls"] == 2
    finished_task = Task.from_dict(finished.data["task"])
    receipts = [artifact for artifact in finished_task.artifacts if artifact.kind == "action_result"]
    assert {artifact.action_id for artifact in receipts} == set(second.completed_action_ids)
    assert len(receipts) == 2


@pytest.mark.asyncio
async def test_public_stream_exposes_handoff_and_invoke_raises_interruption(tmp_path):
    calls, effects = [], []
    agent = make_agent(tmp_path / "stream.db", calls, effects, [write_action("saved"), "done"])
    handle = agent.start_run("work")
    events = [event async for event in handle.events()]
    result = await handle.result()
    assert result.status == "input-required"
    assert result.handoff == RunHandoff.from_task(result.task)
    assert result.handoff.usage.llm_calls == 1 and len(calls) == 1
    yielded = [event for event in events if event.payload.get("llm_event_type") == "run_yielded"]
    assert len(yielded) == 1
    assert yielded[0].payload["metadata"]["handoff"] == result.handoff.to_dict()
    assert not any(event.payload.get("llm_event_type") == "llm_final" for event in events)
    assert [event.payload["new_state"] for event in events if event.final and event.type == "task.status"] == [
        "input-required"
    ]
    assert await agent.resume(run_id(result.task)) == "done"
    other = make_agent(tmp_path / "invoke.db", [], [], [write_action("saved")])
    with pytest.raises(RunInterrupted) as raised:
        await other.invoke("work")
    assert raised.value.interruption.kind == "yield"
    assert RunHandoff.from_task(raised.value.task) is not None


@pytest.mark.asyncio
async def test_slices_can_exceed_ten_total_steps_without_resetting_cumulative_budget(tmp_path):
    calls, effects = [], []
    actions = [write_action(str(index)) for index in range(11)] + ["done"]
    agent = make_agent(tmp_path / "runs.db", calls, effects, actions, slice_steps=3)
    task = Task.create_infer("long bounded work")
    RunContext(budget=RunBudget(max_steps=12, max_llm_calls=12, max_tool_calls=11)).attach_to_task(task)
    task = await agent.run_task(task)
    yielded_steps = []
    while (handoff := RunHandoff.from_task(task)) is not None:
        yielded_steps.append(handoff.steps)
        assert handoff.usage.steps == handoff.usage.llm_calls == handoff.steps
        task = await agent.resume_task(run_id(task))
    assert yielded_steps == [3, 6, 9]
    assert task.state is TaskState.COMPLETED and task.get_output() == "done"
    assert effects == [str(index) for index in range(11)] and len(calls) == 12
    usage = agent.durability.get(run_id(task)).data["usage"]
    assert usage["steps"] == usage["llm_calls"] == 12 and usage["tool_calls"] == 11


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [RunBudget(max_steps=1), RunBudget(max_llm_calls=1)])
async def test_exhausted_hard_budget_stops_instead_of_yielding_or_calling_model_again(tmp_path, budget):
    calls, effects = [], []
    agent = make_agent(tmp_path / "runs.db", calls, effects, [write_action("saved"), "must not run"])
    result = await agent.start_run("work", budget=budget).result()
    assert result.status == "failed" and result.handoff is None
    assert effects == ["saved"] and len(calls) == 1


@pytest.mark.asyncio
async def test_explicit_resume_cannot_reset_an_existing_model_budget(tmp_path):
    calls, effects = [], []
    agent = make_agent(tmp_path / "runs.db", calls, effects, [write_action("first"), write_action("second"), "done"])
    task = Task.create_infer("work")
    RunContext(budget=RunBudget(max_llm_calls=2)).attach_to_task(task)
    task = await agent.run_task(task)
    assert RunHandoff.from_task(task).usage.llm_calls == 1
    with pytest.raises(Exception, match="max_llm_calls"):
        await agent.resume_task(run_id(task))
    assert effects == ["first", "second"] and len(calls) == 2
    record = agent.durability.get(run_id(task))
    assert record.data["usage"]["llm_calls"] == 2
    assert RunHandoff.from_task(Task.from_dict(record.data["task"])) is None


@pytest.mark.asyncio
async def test_default_ten_step_limit_does_not_restart_with_each_slice(tmp_path):
    calls, effects = [], []
    agent = make_agent(
        tmp_path / "runs.db", calls, effects, [write_action(str(index)) for index in range(11)], slice_steps=3
    )
    task = await agent.run_task(Task.create_infer("work"))
    for expected in (3, 6, 9):
        assert RunHandoff.from_task(task).steps == expected
        if expected < 9:
            task = await agent.resume_task(run_id(task))
    with pytest.raises(Exception, match="10"):
        await agent.resume_task(run_id(task))
    assert effects == [str(index) for index in range(10)] and len(calls) == 10


@pytest.mark.asyncio
async def test_sibling_child_handoffs_resume_only_through_root_and_have_distinct_requests(tmp_path):
    calls, effects = [], []

    def make(name):
        child = make_agent(None, calls, effects, [write_action(name), f"{name} done"])
        child.card.name = name
        return child

    left, right = make("left"), make("right")
    parent = Agent(
        name="parent",
        subagents=[left, right],
        durability=tmp_path / "runs.db",
        verbosity=0,
        llm=MockLLM(
            sequential_responses=[
                {"type": "agent_call", "agent": name, "action": "infer", "prompt": "work"} for name in ("left", "right")
            ]
            + ["parent done"]
        ),
    )
    task = await parent.run_task(Task.create_infer("coordinate"))
    root_id = run_id(task)
    first = RunHandoff.from_task(task)
    first_request = task.metadata["interruption"]["request_id"]
    assert first.run_id != root_id and first.usage.llm_calls == 2
    assert left.durability is None and right.durability is None
    second_task = await parent.resume_task(root_id)
    second = RunHandoff.from_task(second_task)
    assert second.run_id not in {root_id, first.run_id}
    assert second_task.metadata["interruption"]["request_id"] != first_request
    assert second.usage.llm_calls == 5
    final = await parent.resume_task(root_id)
    assert final.state is TaskState.COMPLETED and final.get_output() == "parent done"
    assert effects == ["left", "right"] and len(calls) == 4
    assert parent.durability.get(root_id).data["usage"]["llm_calls"] == 7
    assert len(final.metadata["subagent_runs"]) == 2


@pytest.mark.asyncio
async def test_yield_configuration_is_part_of_checkpoint_fingerprint(tmp_path):
    path, calls, effects = tmp_path / "runs.db", [], []
    agent = make_agent(path, calls, effects, [write_action("saved")])
    task = await agent.run_task(Task.create_infer("work"))
    changed = make_agent(path, calls, effects, ["must not run"], slice_steps=2)
    with pytest.raises(CheckpointMismatchError):
        await changed.resume_task(run_id(task))
    assert len(calls) == 1 and effects == ["saved"]


@pytest.mark.asyncio
async def test_repeated_action_memory_survives_restart_and_multiple_handoffs(tmp_path):
    path, calls, effects = tmp_path / "runs.db", [], []
    agent = make_agent(path, calls, effects, [write_action("saved")])
    task = await agent.run_task(Task.create_infer("work"))
    restarted = make_agent(path, calls, effects, [write_action("saved"), "done"])
    task = await restarted.resume_task(run_id(task))
    handoff = RunHandoff.from_task(task)
    assert handoff is not None and handoff.steps == 2
    assert handoff.usage.tool_calls == 1
    assert len(handoff.completed_action_ids) == 1
    assert effects == ["saved"] and len(calls) == 2
    assert await restarted.resume(run_id(task)) == "done"
    assert effects == ["saved"] and len(calls) == 3
    assert "already performed this action" in str(calls[-1])


@pytest.mark.asyncio
async def test_rejection_corrections_are_not_reset_by_work_slices(tmp_path):
    calls, effects = [], []

    def reject() -> str:
        raise ToolRejectedError("No change", code="invalid", suggestion="Choose another value")

    llm = RecordingLLM([write_action("saved"), {"type": "tool_call", "tool": "reject", "args": {}}], calls)
    llm.max_tool_corrections = 1
    agent = make_agent(tmp_path / "runs.db", calls, effects, [])
    agent.llm = llm
    agent.add_tool(reject)
    task = await agent.run_task(Task.create_infer("work"))
    task = await agent.resume_task(run_id(task))
    assert RunHandoff.from_task(task) is not None
    llm.sequential_responses.append({"type": "tool_call", "tool": "reject", "args": {}})
    with pytest.raises(Exception, match="Tool correction limit"):
        await agent.resume_task(run_id(task))
    assert effects == ["saved"] and len(calls) == 3
    state = next(iter(agent.durability.get(run_id(task)).data["loops"].values()))
    assert state["tool_corrections"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["deny", "uncertain", "cancel"])
async def test_failed_denied_uncertain_or_canceled_work_never_becomes_handoff(tmp_path, failure):
    calls, effects = [], []
    entered = asyncio.Event()

    async def write(value: str):
        effects.append(value)
        entered.set()
        if failure == "cancel":
            await asyncio.Event().wait()
        return object() if failure == "uncertain" else value

    agent = make_agent(
        tmp_path / "runs.db",
        calls,
        effects,
        [write_action("saved")],
        policy=CapabilityPolicy({"test.write": "deny"}) if failure == "deny" else None,
    )
    agent.tools["write"] = Tool.from_callable(write, capabilities=["test.write"])
    handle = agent.start_run("work")
    if failure == "cancel":
        await asyncio.wait_for(entered.wait(), 2)
        await handle.cancel("stop work")
    result = await handle.result()
    assert result.status == ("canceled" if failure == "cancel" else "failed")
    assert result.handoff is None
    assert len(calls) == 1
    assert effects == ([] if failure == "deny" else ["saved"])
    if failure == "uncertain":
        with pytest.raises(UncertainExecutionError):
            await agent.resume_task(handle.context.run_id)
        assert len(calls) == 1 and effects == ["saved"]


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "2"])
def test_invalid_slice_size_is_rejected_at_construction(value):
    with pytest.raises(ValueError, match="yield_after_steps"):
        Agent(name="invalid", yield_after_steps=value)


@pytest.mark.asyncio
async def test_non_durable_slice_fails_before_model_or_tool_effects():
    calls, effects = [], []
    agent = make_agent(None, calls, effects, [write_action("must not happen")])
    with pytest.raises(ValueError, match="durability"):
        await agent.invoke("work")
    assert calls == effects == []


@pytest.mark.asyncio
async def test_canceling_a_suspended_handoff_removes_continuation(tmp_path):
    agent = make_agent(tmp_path / "runs.db", [], [], [write_action("saved")])
    task = await agent.run_task(Task.create_infer("work"))
    RunManager(agent).cancel(run_id(task))
    canceled = Task.from_dict(agent.durability.get(run_id(task)).data["task"])
    assert canceled.state is TaskState.CANCELED and RunHandoff.from_task(canceled) is None
    with pytest.raises(Exception, match="canceled"):
        await agent.resume_task(run_id(task))


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED])
async def test_terminal_task_does_not_expose_stale_handoff_metadata(tmp_path, state):
    agent = make_agent(tmp_path / "runs.db", [], [], [write_action("saved")])
    task = await agent.run_task(Task.create_infer("work"))
    assert RunHandoff.from_task(task) is not None
    # Historical interruption metadata must not turn a terminal result into an
    # invitation to continue. Serialized clients can retain that history.
    snapshot = task.to_dict()
    snapshot["state"] = state.value
    terminal = Task.from_dict(snapshot)
    assert "interruption" in terminal.metadata
    assert RunHandoff.from_task(terminal) is None
