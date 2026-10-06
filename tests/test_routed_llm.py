"""Request fallback remains bounded and never repeats an already executed tool."""

import pytest

from protolink import Agent, BudgetExceededError, RoutedLLM, RunBudget, RunInterrupted, Task
from protolink.llms import MockLLM


class Unavailable(MockLLM):
    def call(self, history):
        raise ConnectionError("provider unavailable")


class PartialStream(MockLLM):
    async def call_stream(self, history):
        yield '{"type":"final","content":"partial'
        raise ConnectionError("stream disconnected")


@pytest.mark.asyncio
async def test_fallback_is_charged_and_tool_is_executed_once():
    calls = []

    def effect() -> str:
        calls.append(True)
        return "ok"

    router = RoutedLLM(
        {
            "primary": Unavailable(),
            "backup": MockLLM(sequential_responses=[{"type": "tool_call", "tool": "effect", "args": {}}, "done"]),
        },
        fallbacks=["backup"],
    )
    agent = Agent(name="route", llm=router, tools=[effect], verbosity=0)
    task = Task.create_infer("go", budget=RunBudget(max_llm_calls=4, max_tool_calls=1))
    result = await agent.start_run(task).result()
    assert result.output == "done"
    assert calls == [True]
    responses = [
        event
        for event in result.report.events
        if event.type == "llm.stream" and event.payload.get("llm_event_type") == "llm_response"
    ]
    assert responses[-1].payload["metadata"]["metadata"]["routing"]["key"] == "backup"


@pytest.mark.asyncio
async def test_budget_stops_fallback_before_request():
    reached = []

    class Backup(MockLLM):
        def call(self, history):
            reached.append(True)
            return super().call(history)

    agent = Agent(
        name="limited", llm=RoutedLLM({"primary": Unavailable(), "backup": Backup()}, fallbacks=["backup"]), verbosity=0
    )
    with pytest.raises(BudgetExceededError):
        await agent.run_task(Task.create_infer("go", budget=RunBudget(max_llm_calls=1)))
    assert reached == []


@pytest.mark.asyncio
async def test_partial_stream_prevents_fallback():
    backup = MockLLM(sequential_responses=["backup"])
    agent = Agent(
        name="partial", llm=RoutedLLM({"primary": PartialStream(), "backup": backup}, fallbacks=["backup"]), verbosity=0
    )
    handle = agent.start_run("go")
    chunks = [chunk async for chunk in handle.chunks()]
    result = await handle.result()
    assert "partial" in "".join(chunks)
    assert result.status == "failed"
    assert backup._current_seq_idx == 0


@pytest.mark.asyncio
async def test_selector_changes_model_between_steps_without_changing_protocol():
    calls = []

    def lookup() -> str:
        calls.append(True)
        return "evidence"

    router = RoutedLLM(
        {
            "fast": MockLLM(default_response={"type": "tool_call", "tool": "lookup", "args": {}}),
            "reason": MockLLM(default_response="done"),
        },
        selector=lambda history: (
            "reason" if any(m["content"].startswith('{"type": "tool_result"') for m in history.messages) else "fast"
        ),
    )
    assert await Agent(name="select", llm=router, tools=[lookup], verbosity=0).invoke("go") == "done"
    assert calls == [True]
    config = Agent(name="saved", llm=router, verbosity=0).to_dict()
    with pytest.raises(ValueError, match="Reconnect routing"):
        Agent.from_dict(config)


@pytest.mark.asyncio
async def test_authentication_errors_do_not_fall_back():
    class Unauthorized(MockLLM):
        def call(self, history):
            error = RuntimeError("invalid credentials")
            error.status_code = 401
            raise error

    agent = Agent(
        name="auth", llm=RoutedLLM({"primary": Unauthorized(), "backup": MockLLM()}, fallbacks=["backup"]), verbosity=0
    )
    with pytest.raises(Exception, match="invalid credentials"):
        await agent.invoke("go")


@pytest.mark.asyncio
async def test_durable_routing_preserves_request_budget_across_restart(tmp_path):
    from protolink.tools import ask_user_tool

    def response(history, prompt):
        if any(message["content"].startswith('{"type": "tool_result"') for message in history.messages):
            return "done"
        return {"type": "tool_call", "tool": "ask_user", "args": {"question": "Continue?"}}

    def make():
        return Agent(
            name="durable-router",
            tools=[ask_user_tool()],
            durability=tmp_path / "runs.db",
            verbosity=0,
            llm=RoutedLLM(
                {"primary": Unavailable(), "backup": MockLLM(response_callback=response)}, fallbacks=["backup"]
            ),
        )

    with pytest.raises(RunInterrupted) as raised:
        await make().invoke("go", budget=RunBudget(max_llm_calls=4, max_tool_calls=1))
    pause = raised.value
    restarted = make()
    assert await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, answer="yes") == "done"
    usage = restarted.durability.get(pause.run_id).data["usage"]
    assert usage["llm_calls"] == 4 and usage["tool_calls"] == 1
