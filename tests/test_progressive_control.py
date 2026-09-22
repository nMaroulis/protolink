"""Convenience paths retain execution, validation, ownership, and failure boundaries."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    AgentGroup,
    BudgetExceededError,
    CompletionCheck,
    Pipeline,
    RepeatUntil,
    RunBudget,
    RunContext,
    RunReport,
    SQLiteRunStore,
    Step,
    StructuredResponseError,
    Task,
    TaskExecutionError,
    TaskState,
    Tool,
    ToolStep,
    create_knowledge,
    create_llm,
)
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.flows.limits import WorkflowLimitError


def make_agent(name="simple", **options):
    return Agent(
        AgentCard(name=name, description="Convenience test", url=f"runtime://{name}", capabilities={"streaming": True}),
        verbosity=0,
        **options,
    )


class Answer(BaseModel):
    count: int


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["invoke", "ask"])
async def test_run_controls_reach_handler_without_mutating_context(method):
    class Capture(Agent):
        async def handle_task(self, task):
            context = RunContext.from_task(task)
            assert context.session_id == "override"
            assert context.budget.max_llm_calls == 1
            assert context.permissions == {"files.write": "deny"}
            context.permissions["files.write"] = "allow"
            return task.complete("ok")

    agent = Capture(
        AgentCard(name="capture", description="Capture", url="runtime://capture"),
        llm=create_llm("mock"),
        knowledge=create_knowledge(),
        verbosity=0,
    )
    context = RunContext(session_id="original", permissions={"files.write": "deny"}, budget=RunBudget(max_llm_calls=9))
    await getattr(agent, method)("hi", session_id="override", budget=RunBudget(max_llm_calls=1), context=context)
    assert context.session_id == "original"
    assert context.budget.max_llm_calls == 9
    assert context.permissions == {"files.write": "deny"}


@pytest.mark.asyncio
async def test_invoke_budget_and_permissions_prevent_execution():
    llm = create_llm("mock", sequential_responses=[{"type": "tool_call", "tool": "write", "args": {}}])
    agent = make_agent(llm=llm)
    writes = []

    @agent.tool(capabilities=["files.write"])
    def write() -> str:
        writes.append(1)
        return "done"

    with pytest.raises(BudgetExceededError):
        await agent.invoke("write", budget=RunBudget(max_llm_calls=0))
    with pytest.raises(ActionDeniedError):
        await agent.invoke("write", context=RunContext(permissions={"files.write": "deny"}))
    assert writes == []


@pytest.mark.asyncio
async def test_start_run_chunks_share_one_execution_and_persist(tmp_path):
    store = SQLiteRunStore(tmp_path / "runs.db")
    calls = []

    def respond(history, prompt):
        calls.append(1)
        return "hello"

    agent = make_agent(llm=create_llm("mock", response_callback=respond), run_store=store)
    handle = agent.start_run("hi", context=RunContext(session_id="stream"), budget=RunBudget(max_llm_calls=1))
    first = [chunk async for chunk in handle.chunks()]
    second = [chunk async for chunk in handle.chunks()]
    result = await handle.result()
    assert first == second and first
    assert json.loads("".join(first))["content"] == "hello"
    assert calls == [1]
    assert result.output == "hello" and result.status == "completed"
    assert result.report.context.session_id == "stream"
    assert store.get_report(result.report.context.run_id) is not None
    assert store.get_task(result.task.id) is not None


@pytest.mark.asyncio
async def test_start_run_accepts_tool_task_and_cancels():
    started = asyncio.Event()
    agent = make_agent()

    @agent.tool
    async def wait() -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    task = Task.create_tool_call(tool_name="wait")
    RunContext(session_id="keep").attach_to_task(task)
    handle = agent.start_run(task)
    await asyncio.wait_for(started.wait(), 1)
    await handle.cancel("stop")
    result = await asyncio.wait_for(handle.result(), 1)
    assert result.status == "canceled"
    assert result.report.context.session_id == "keep"
    assert not agent.active_task_ids


def test_bulk_tools_keep_schema_policy_and_falsey_results():
    agent = make_agent()

    def add(a: int, b: int) -> int:
        return a + b

    agent.add_tools([add, Tool.from_callable(lambda: False, name="no", capabilities=["answer.read"])])
    assert agent.sync.call_tool("add", a="1", b=-1) == 0
    assert agent.sync.call_tool("no") is False
    assert agent.tools["no"].capabilities == ("answer.read",)
    assert {skill.id for skill in agent.card.skills} == {"add", "no"}


@pytest.mark.asyncio
async def test_peer_local_and_client_facades_use_normal_remote_lifecycle():
    worker = make_agent("peer-worker", transport="runtime", llm=create_llm("mock", default_response="hello"))
    caller = make_agent("peer-caller", transport="runtime")

    @worker.tool
    def echo(method: str) -> str:
        return method

    async with AgentGroup([worker, caller]):
        peer = caller.peer(worker.card)
        assert await peer.invoke("hi") == "hello"
        assert await peer.call_tool("echo", method="GET") == "GET"
        client_peer = AgentClient("runtime").peer(worker.card.url)
        assert await client_peer.call_tool("echo", method="POST") == "POST"
        with pytest.raises(TaskExecutionError):
            await peer.call_tool("missing")
        task = Task.create_tool_call(tool_name="missing")
        assert (await peer.run_task(task)).state is TaskState.FAILED
        worker.llm = create_llm("mock", default_response='{"count": 2}')
        assert (await peer.invoke_typed("count", Answer)).count == 2


@pytest.mark.asyncio
async def test_peer_resolves_names_unambiguously_and_keeps_protocol():
    card = AgentCard(name="worker", description="worker", url="runtime://worker")
    registry = SimpleNamespace(discover=AsyncMock(return_value=[card]))
    client = AgentClient("runtime")

    async def reply(url, task, *, protocol):
        assert url == card.url and protocol == "protolink"
        assert RunContext.from_task(task).session_id == "peer-session"
        return task.complete("ok")

    client.send_task = AsyncMock(side_effect=reply)
    peer = client.peer("worker", registry=registry, protocol="protolink")
    assert await peer.invoke("hi", session_id="peer-session") == "ok"
    for cards in ([], [card, card]):
        registry.discover.return_value = cards
        with pytest.raises(ValueError, match="Expected one peer"):
            await peer.invoke("hi")
    assert client.send_task.await_count == 1


@pytest.mark.asyncio
async def test_peer_name_lookup_with_owned_runtime_registry():
    worker = make_agent("registered-worker", transport="runtime", llm=create_llm("mock", default_response="found"))
    caller = make_agent("registered-caller", transport="runtime")
    registry = Registry(url="runtime://convenience-registry", transport="runtime")
    async with AgentGroup([worker, caller], registry=registry, own_registry=True):
        assert await caller.peer("registered-worker").invoke("hello") == "found"


def test_sync_peer_can_infer_validate_and_call_tools():
    worker = make_agent("sync-peer-worker", transport="runtime", llm=create_llm("mock", default_response='{"count":0}'))
    worker.add_tools([Tool.from_callable(lambda method: method, name="echo")])
    worker.start(background=True)
    try:
        peer = AgentClient("runtime").peer(worker.card)
        assert peer.sync.call_tool("echo", method="GET") == "GET"
        assert peer.sync.invoke("hello") == '{"count":0}'
        assert peer.sync.invoke_typed("count", Answer).count == 0
    finally:
        worker.stop()


def test_flow_sync_invoke_and_callable_steps_preserve_falsey_output():
    def answer(task):
        from protolink import Artifact, Part

        task.add_artifact(Artifact(parts=[Part.json({})]))
        return task

    assert Pipeline([Step(answer)]).sync.invoke("hello") == {}


@pytest.mark.asyncio
async def test_repeat_until_checks_fresh_receipts_and_retains_report():
    agent = make_agent()
    values = iter([2, 7])
    agent.add_tools([Tool.from_callable(lambda: next(values), name="measure")])
    seen = []

    def accept(evidence):
        seen.append([outcome.result for outcome in evidence.outcomes])
        return evidence.outcomes[-1].result >= 5

    flow = RepeatUntil(ToolStep(agent, "measure"), CompletionCheck("minimum", accept), max_attempts=3)
    task = await flow.execute(Task.create_infer(prompt="measure"))
    assert seen == [[2], [7]]
    assert task.get_last_part_content().result == 7
    assert [v["status"] for v in RunReport.from_task(task).validations] == ["failed", "passed"]


@pytest.mark.asyncio
async def test_repeat_until_enforces_shared_budget_and_attempt_limit():
    calls = []
    agent = make_agent()
    agent.add_tools([Tool.from_callable(lambda: calls.append(1) or 0, name="measure")])
    flow = RepeatUntil(ToolStep(agent, "measure"), CompletionCheck("never", lambda e: False), max_attempts=2)
    task = Task.create_infer(prompt="measure")
    with pytest.raises(WorkflowLimitError):
        await flow.execute(task)
    assert calls == [1, 1]
    assert task.state is TaskState.FAILED
    assert len(RunReport.from_task(task).validations) == 2
    calls.clear()
    with pytest.raises(BudgetExceededError):
        await flow.invoke("measure", budget=RunBudget(max_tool_calls=1))
    assert calls == [1]


@pytest.mark.asyncio
async def test_tool_step_dynamic_arguments_and_failed_step_never_repeat():
    agent = make_agent()

    @agent.tool
    def length(text: str) -> int:
        return len(text)

    step = ToolStep(agent, "length", args=lambda task: {"text": task.get_last_part_content()["prompt"]})
    assert (await step.invoke("abc")).result == 3
    called = []

    async def fail(task):
        called.append(1)
        return task.fail("no")

    flow = RepeatUntil(Step(fail), CompletionCheck("unused", lambda e: True), max_attempts=3)
    with pytest.raises(TaskExecutionError):
        await flow.invoke("hi")
    assert called == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [TaskState.FAILED, TaskState.CANCELED, TaskState.INPUT_REQUIRED])
async def test_acceptance_loop_stops_before_checks_on_unsuccessful_task(state):
    calls = []

    def stop(task):
        calls.append("step")
        return task.update_state(state)

    def check(evidence):
        calls.append("check")
        return False

    loop = RepeatUntil(Step(stop), CompletionCheck("unused", check, require_execution=False), max_attempts=3)
    result = await loop.execute(Task.create_infer(prompt="work"))
    assert result.state is state
    assert calls == ["step"]


@pytest.mark.asyncio
async def test_typed_response_repair_is_explicit_and_budgeted():
    agent = make_agent(
        llm=create_llm(
            "mock",
            sequential_responses=[
                {"type": "final", "content": "invalid"},
                {"type": "final", "content": '{"count": 3}'},
            ],
        )
    )
    answer = await agent.invoke_typed("count", Answer, max_attempts=2, budget=RunBudget(max_llm_calls=2))
    assert answer == Answer(count=3)
    agent.llm = create_llm("mock", default_response="invalid")
    with pytest.raises(BudgetExceededError):
        await agent.invoke_typed("count", Answer, max_attempts=3, budget=RunBudget(max_llm_calls=1))
    with pytest.raises(StructuredResponseError) as raised:
        await agent.invoke_typed("count", Answer)
    assert raised.value.attempts == 1
    assert raised.value.validation_error is not None
    assert raised.value.task.get_last_part_content() == "invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", [TaskState.FAILED, TaskState.CANCELED, TaskState.INPUT_REQUIRED, TaskState.SUBMITTED, TaskState.WORKING]
)
async def test_typed_response_does_not_retry_execution_failures_or_incomplete_tasks(state):
    calls = []

    class Failing(Agent):
        async def handle_task(self, task):
            calls.append(1)
            if state is not TaskState.SUBMITTED:
                task.begin()
            return task.update_state(state)

    agent = Failing(AgentCard(name="fail", description="fail", url="runtime://fail"), verbosity=0)
    with pytest.raises((TaskExecutionError, StructuredResponseError)):
        await agent.invoke_typed("count", Answer, max_attempts=3)
    assert calls == [1]


@pytest.mark.asyncio
async def test_typed_repair_keeps_original_schema_and_request_in_stateless_agent():
    prompts = []

    def respond(history, system_prompt):
        prompt = history.messages[-1]["content"]
        prompts.append(prompt)
        if len(prompts) == 1:
            return "not JSON"
        assert "Count the red items" in prompt
        assert '"count"' in prompt
        assert "not JSON" in prompt
        assert "Validation errors" in prompt
        return '{"count": 4}'

    agent = make_agent(llm=create_llm("mock", response_callback=respond))
    assert (await agent.invoke_typed("Count the red items", Answer, max_attempts=2)).count == 4
    assert len(prompts) == 2


@pytest.mark.asyncio
async def test_typed_response_does_not_accept_unchanged_input_as_null():
    class Empty(Agent):
        async def handle_task(self, task):
            return task.begin().update_state(TaskState.COMPLETED)

    agent = Empty(AgentCard(name="empty", description="empty", url="runtime://empty"), verbosity=0)
    with pytest.raises(StructuredResponseError):
        await agent.invoke_typed("Return nothing", type(None))


def test_typed_sync_accepts_fenced_json():
    agent = make_agent(llm=create_llm("mock", default_response='```json\n{"count": 0}\n```'))
    assert agent.sync.invoke_typed("count", Answer).count == 0


@pytest.mark.asyncio
async def test_new_sync_methods_reject_active_loop_before_creating_coroutines(recwarn):
    agent = make_agent()
    flow = Pipeline([])
    peer = AgentClient("runtime").peer("runtime://worker")
    for call in (
        lambda: agent.sync.invoke_typed("hi", Answer),
        lambda: agent.sync.add_mcp(command="python"),
        lambda: flow.sync.invoke("hi"),
        lambda: peer.sync.call_tool("echo", method="GET"),
    ):
        with pytest.raises(RuntimeError, match="active event loop"):
            call()
    assert not [warning for warning in recwarn if "was never awaited" in str(warning.message)]


@pytest.mark.asyncio
async def test_mcp_async_discovery_selection_and_prefix_keep_remote_names(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.types import CallToolResult, ListToolsResult, TextContent
    from mcp.types import Tool as MCPTool

    from protolink.tools.adapters import MCPToolAdapter, mcp_adapter

    adapter = MCPToolAdapter(command="unused")
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(
            return_value=ListToolsResult(
                tools=[
                    MCPTool(
                        name="echo",
                        description="echo",
                        inputSchema={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    ),
                ]
            )
        ),
        call_tool=AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="ok")])),
    )

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield session

    @asynccontextmanager
    async def stdio(*args, **kwargs):
        yield None, None

    monkeypatch.setattr(mcp_adapter, "stdio_client", stdio)
    monkeypatch.setattr(mcp_adapter, "ClientSession", connection)
    agent = make_agent()
    tools = await agent.add_mcp(adapter, include=["echo"], prefix="remote_")
    assert [tool.name for tool in tools] == ["remote_echo"]
    await agent.call_tool("remote_echo", text="hi")
    assert session.call_tool.call_args.args[0] == "echo"
    assert session.list_tools.await_count == 1
    with pytest.raises(ValueError, match="conflict"):
        await agent.add_mcp(adapter, prefix="remote_")
    with pytest.raises(ValueError, match="Unknown MCP tools"):
        await agent.add_mcp(adapter, include=["missing"])
    with pytest.raises(ValueError, match="not both"):
        await agent.add_mcp(adapter, command="python")
    assert list(agent.tools) == ["remote_echo"]
