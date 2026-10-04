"""Owned local delegation shares controls without sharing conversation history."""

from __future__ import annotations

import asyncio

import pytest

from protolink import Agent, CapabilityPolicy, RunBudget, RunInterrupted, SubagentLimits, Task, TaskState
from protolink.llms import MockLLM
from protolink.tools import Tool


def parent_for(child, **kwargs):
    return Agent(
        name="parent",
        subagents=[child],
        verbosity=0,
        llm=MockLLM(
            sequential_responses=[
                {"type": "agent_call", "agent": child.card.name, "action": "infer", "prompt": "child request"},
                "parent done",
            ]
        ),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_existing_agent_call_routes_locally_with_isolated_history_and_lineage():
    child = Agent(name="child", llm=MockLLM(default_response="child done"), verbosity=0)
    parent = parent_for(child)
    run = parent.start_run("parent private request")
    events = [event async for event in run.events()]
    task = (await run.result()).task
    assert task.state is TaskState.COMPLETED
    assert task.get_output() == "parent done"
    assert "parent private request" not in str(child.llm.history.messages)
    assert "child request" in str(child.llm.history.messages)
    assert task.metadata["subagent_runs"][0]["agent"] == "child"
    delegated = [event for event in events if event.agent_name == "child"]
    assert delegated
    assert all(event.metadata.get("parent_run_id") for event in delegated)
    assert not parent._subagent_runs


@pytest.mark.asyncio
async def test_child_cannot_weaken_parent_policy():
    calls = []

    def write() -> str:
        calls.append(1)
        return "written"

    child = Agent(
        name="child",
        llm=MockLLM(sequential_responses=[{"type": "tool_call", "tool": "write", "args": {}}, "done"]),
        tools=[Tool.from_callable(write, capabilities=["test.write"])],
        verbosity=0,
    )
    parent = parent_for(child, policy=CapabilityPolicy({"test.write": "deny"}))
    with pytest.raises(Exception, match="denied"):
        await parent.invoke("save")
    assert calls == []


@pytest.mark.asyncio
async def test_child_llm_calls_share_parent_budget():
    child = Agent(name="child", llm=MockLLM(default_response="done"), verbosity=0)
    parent = parent_for(child)
    with pytest.raises(Exception, match="max_llm_calls"):
        await parent.invoke("go", budget=RunBudget(max_llm_calls=1))
    assert child.llm._current_seq_idx == 0


@pytest.mark.asyncio
async def test_durable_child_question_resumes_parent_without_new_child(tmp_path):
    from protolink import RunContext
    from protolink.tools.builtins import ask_user_tool

    def make():
        child = Agent(
            name="child",
            tools=[ask_user_tool()],
            verbosity=0,
            llm=MockLLM(
                sequential_responses=[
                    {"type": "tool_call", "tool": "ask_user", "args": {"question": "Format?"}},
                    "child done",
                ]
            ),
        )
        return parent_for(child, durability=tmp_path / "runs.db")

    parent = make()
    with pytest.raises(RunInterrupted) as raised:
        await parent.invoke("go")
    pause = raised.value
    child_run = pause.task.metadata["subagent_runs"][0]["run_id"]
    assert pause.interruption.run_id == child_run
    restarted = make()
    assert await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, answer="CSV") == "parent done"
    record = restarted.durability.get(pause.run_id)
    assert record.data["subagent_count"] == 1
    assert record.data["usage"]["tool_calls"] == 1
    assert restarted.durability.get(child_run).status == "completed"
    assert RunContext.from_task(pause.task).run_id != child_run


@pytest.mark.asyncio
async def test_background_handles_are_owned_and_cancelled_when_parent_finishes():
    entered = asyncio.Event()
    release = asyncio.Event()
    child_entered = asyncio.Event()
    child_stopped = asyncio.Event()

    class WaitingParent(Agent):
        async def handle_task(self, task):
            task.begin()
            entered.set()
            await release.wait()
            return task.complete()

    class WaitingChild(Agent):
        async def handle_task(self, task):
            task.begin()
            child_entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_stopped.set()

    child = WaitingChild(name="child", verbosity=0)
    parent = WaitingParent(name="parent", subagents=[child], verbosity=0)
    run = parent.start_run("go")
    await entered.wait()
    handle = await run.spawn("child", "work")
    await child_entered.wait()
    release.set()
    await run.result()
    assert child_stopped.is_set()
    assert handle._worker.done()
    assert not parent._subagent_runs


@pytest.mark.asyncio
async def test_child_count_depth_and_queued_cancellation():
    from protolink import RunContext, SubagentLimitError
    from protolink.agents.subagents import subagent_scope
    from protolink.core.budget import BudgetEnforcer

    started = asyncio.Event()

    class Wait(Agent):
        async def handle_task(self, task):
            started.set()
            await asyncio.Event().wait()

    child = Wait(name="child", verbosity=0)
    parent = parent_for(child, subagent_limits=SubagentLimits(max_children=2, max_concurrency=1))
    task = Task.create_infer("go")
    RunContext.ensure_task_context(task, agent_name="parent")
    async with subagent_scope(parent, task, BudgetEnforcer(RunContext.from_task(task))) as supervisor:
        first = await supervisor.spawn("child", "first")
        await started.wait()
        second = await supervisor.spawn("child", "queued")
        with pytest.raises(SubagentLimitError, match="count"):
            await supervisor.spawn("child", "third")
        await second.cancel()
        assert second._worker.cancelled()
    assert first._worker.done()


def test_optional_background_tools_and_configuration_roundtrip(tmp_path):
    child = Agent(name="child", verbosity=0)
    parent = parent_for(child, subagent_limits=SubagentLimits(background=True))
    assert {"spawn_subagent", "wait_subagent", "cancel_subagent"} <= parent.tools.keys()
    config = parent.to_dict()
    with pytest.raises(ValueError, match="Reconnect"):
        Agent.from_dict(config)
    restored = Agent.from_dict(config, subagents=[child])
    assert restored.subagent_limits.background
    assert len(restored.tools) == 3
    agent = Agent(name="d", durability=tmp_path / "runs.db", execution_version="3", verbosity=0)
    restored = Agent.from_dict(agent.to_dict())
    assert restored.durability.path == str(tmp_path / "runs.db")
    assert restored.execution_version == "3"
    with pytest.raises(ValueError, match="background"):
        Agent(
            name="invalid",
            subagents=[child],
            subagent_limits=SubagentLimits(background=True),
            durability=tmp_path / "d",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("depth,concurrency,success", [(1, 3, False), (2, 1, False), (2, 2, True)])
async def test_nested_children_obey_depth_and_concurrency_without_deadlock(depth, concurrency, success):
    grandchild = Agent(name="grandchild", llm=MockLLM(default_response="evidence"), verbosity=0)
    child = parent_for(grandchild)
    child.card.name = "child"
    parent = parent_for(child, subagent_limits=SubagentLimits(max_depth=depth, max_concurrency=concurrency))
    if success:
        assert await asyncio.wait_for(parent.invoke("go"), timeout=2) == "parent done"
    else:
        with pytest.raises(Exception, match=r"depth|slot"):
            await asyncio.wait_for(parent.invoke("go"), timeout=2)
    assert not parent._subagent_runs
    assert not child._subagent_runs


@pytest.mark.asyncio
async def test_durable_child_requires_checkpointed_parent(tmp_path):
    child = Agent(name="child", llm=MockLLM(), durability=tmp_path / "runs.db", verbosity=0)
    with pytest.raises(Exception, match="durable parent"):
        await parent_for(child).invoke("go")


@pytest.mark.asyncio
async def test_child_commits_never_outrun_root_budget_or_child_reservations(tmp_path):
    from protolink import RunContext, SQLiteDurableStore
    from protolink.tools import ask_user_tool

    class CheckingStore(SQLiteDurableStore):
        checked = 0

        def save(self, run_id, token, status, data):
            context = RunContext.from_task(Task.from_dict(data["task"]))
            if context.parent_run_id is not None:
                root = self.get(context.parent_run_id)
                for counter in ("llm_calls", "tool_calls", "steps"):
                    assert root.data["usage"][counter] >= data["usage"][counter]
                self.checked += 1
            elif any(entry.get("child_task") for entry in data["actions"].values()):
                assert data.get("subagent_count", 0) >= 1
            super().save(run_id, token, status, data)

    store = CheckingStore(tmp_path / "runs.db")
    child = Agent(
        name="child",
        tools=[ask_user_tool()],
        verbosity=0,
        llm=MockLLM(
            sequential_responses=[
                {"type": "tool_call", "tool": "ask_user", "args": {"question": "Format?"}},
                "done",
            ]
        ),
    )
    parent = parent_for(child, durability=store)
    with pytest.raises(RunInterrupted) as raised:
        await parent.invoke("go")
    pause = raised.value
    assert await parent.resume(pause.run_id, request_id=pause.interruption.request_id, answer="CSV") == "parent done"
    assert store.checked > 5
