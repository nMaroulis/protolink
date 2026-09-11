"""Acceptance is based on execution and resource versions, with bounded attempts."""

import asyncio

import pytest

from protolink import (
    Agent,
    AgentCard,
    CompletionCheck,
    CompletionValidator,
    Graph,
    Message,
    Pipeline,
    ResourceRevision,
    RunBudget,
    RunContext,
    RunEvent,
    RunReport,
    Task,
)
from protolink.core.budget import BudgetExceededError
from protolink.flows import Flow
from protolink.flows.limits import WorkflowLimitError


@pytest.mark.asyncio
async def test_approval_is_not_execution_and_stale_verification_fails():
    task = Task.create_infer(prompt="test")
    report = RunReport.from_events([RunEvent(type="action.approved", action_id="a")])
    validator = CompletionValidator([CompletionCheck("done", lambda evidence: True, action_ids=("a",))])
    (result,) = await validator.validate(task, report=report)
    assert result.status == "blocked" and result.code == "execution_evidence_missing"
    report = RunReport.from_events(
        [
            RunEvent(
                type="action.completed",
                action_id="a",
                payload={
                    "action": {"name": "operation"},
                    "result": {"exit_code": 0},
                },
            )
        ]
    )
    current = ResourceRevision("file", "v1")

    async def accepted(evidence):
        assert evidence.outcomes[0].result["exit_code"] == 0
        return True

    validator = CompletionValidator(
        [
            CompletionCheck(
                "done",
                accepted,
                action_ids=("a",),
                revisions=(current,),
                read_revision=lambda _: current,
            )
        ]
    )
    (passed,) = await validator.validate(task, report=report)
    assert passed.passed and passed.is_current([current])
    current = ResourceRevision("file", "v2")
    (stale,) = await validator.validate(task, report=report)
    assert stale.status == "stale" and not passed.is_current([current])
    saved = RunReport.from_dict(RunReport.from_task(task).to_dict())
    assert saved.validations[-1]["status"] == "stale"


@pytest.mark.asyncio
async def test_resource_change_during_async_predicate_invalidates_evidence():
    current = ResourceRevision("file", "v1")

    async def predicate(evidence):
        nonlocal current
        await asyncio.sleep(0)
        current = ResourceRevision("file", "v2")
        return True

    validator = CompletionValidator(
        [
            CompletionCheck(
                "fresh",
                predicate,
                require_execution=False,
                revisions=(current,),
                read_revision=lambda _: current,
            )
        ]
    )
    (result,) = await validator.validate(Task.create_infer(prompt="check"))
    assert result.status == "stale"


class Count(Flow):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def execute(self, task):
        self.calls += 1
        return task


@pytest.mark.asyncio
async def test_graph_iteration_and_specific_repair_visit_limits():
    attempt = Count()
    graph = Graph(max_iterations=8, max_node_visits={"repair": 2})
    graph.add_node("repair", attempt).add_edge("repair", "repair").set_entry_point("repair")
    task = Task.create(Message.user("begin"))
    with pytest.raises(WorkflowLimitError) as caught:
        await graph.execute(task)
    assert attempt.calls == 2
    assert caught.value.node == "repair" and caught.value.limit == 2
    assert task.metadata["blockers"][-1]["code"] == "workflow_limit"
    assert RunReport.from_task(task).events[-1].type == "workflow.blocked"
    graph = Graph(max_iterations=1)
    graph.add_node("loop", Count()).add_edge("loop", "loop").set_entry_point("loop")
    with pytest.raises(WorkflowLimitError):
        await graph.execute(Task.create_infer(prompt="begin"))


@pytest.mark.asyncio
async def test_pipeline_and_nested_workflows_share_native_step_budget():
    count = Count()
    pipeline = Pipeline([count, count], max_steps=1)
    with pytest.raises(WorkflowLimitError):
        await pipeline.execute(Task.create_infer(prompt="begin"))
    assert count.calls == 1
    count = Count()
    pipeline = Pipeline([Pipeline([count, count]), count])
    task = Task.create_infer(prompt="begin")
    RunContext(budget=RunBudget(max_steps=2)).attach_to_task(task)
    with pytest.raises(BudgetExceededError):
        await pipeline.execute(task)
    assert count.calls == 1


@pytest.mark.asyncio
async def test_workflow_runtime_budget_and_precancellation():
    entered = []

    class Wait(Flow):
        async def execute(self, task):
            entered.append(True)
            await asyncio.Event().wait()
            return task

    task = Task.create_infer(prompt="begin")
    RunContext(budget=RunBudget(max_runtime_seconds=0.02)).attach_to_task(task)
    with pytest.raises(TimeoutError):
        await Pipeline([Wait()]).execute(task)
    assert task.metadata["blockers"][-1]["code"] == "budget_exceeded"
    task = Task.create_infer(prompt="begin")
    RunContext(canceled=True).attach_to_task(task)
    with pytest.raises(asyncio.CancelledError):
        await Pipeline([Wait()]).execute(task)
    assert len(entered) == 1


@pytest.mark.asyncio
async def test_pipeline_continues_with_real_agents_and_never_retries_denial():
    a = Agent(AgentCard(name="one", description="test", url="runtime://one"), verbosity=0)
    b = Agent(AgentCard(name="two", description="test", url="runtime://two"), verbosity=0)
    from protolink import ActionDeniedError, CapabilityPolicy, create_llm

    a.llm = create_llm("mock", default_response="one")
    b.llm = create_llm("mock", default_response="two")
    result = await Pipeline([a, b]).execute(Task.create_infer(prompt="begin"))
    assert result.get_last_part_content() == "two"
    effects = []

    @a.tool(capabilities=["write"])
    def write() -> str:
        effects.append(1)
        return "done"

    a.action_authorizer.policy = CapabilityPolicy({"write": "deny"})
    graph = Graph(max_node_visits=3)
    graph.add_node("attempt", a).add_edge("attempt", "attempt").set_entry_point("attempt")
    with pytest.raises(ActionDeniedError):
        await graph.execute(Task.create_tool_call(tool_name="write", args={}))
    assert effects == []


@pytest.mark.asyncio
async def test_enclosing_agent_remains_cancelable_after_a_completed_flow_node():
    started = asyncio.Event()
    a = Agent(AgentCard(name="node", description="test", url="runtime://node"), verbosity=0)

    @a.tool
    def first() -> str:
        return "first result"

    class Wait(Flow):
        async def execute(self, task):
            started.set()
            await asyncio.Event().wait()
            return task

    class Parent(Agent):
        async def handle_task(self, task):
            return await Pipeline([a, Wait()]).execute(task)

    parent = Parent(AgentCard(name="parent", description="test", url="runtime://parent"), verbosity=0)
    task = Task.create_tool_call(tool_name="first", args={})
    request = asyncio.create_task(parent.run_task(task))
    await started.wait()
    assert task.state.value == "working"
    await parent.cancel_task(task.id)
    result = await request
    assert result.id == task.id and result.state.value == "canceled"
    assert any(event.type == "action.completed" for event in RunReport.from_task(result).events)
