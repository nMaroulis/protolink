"""Private request dependencies and lazy per-task provider selection."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass

import pytest

from protolink import Agent, AgentGroup, Message, Part, RunContext, Task, TaskState, create_llm
from protolink.client import AgentClient
from protolink.core.request_context import current_request_context, request_context
from protolink.llms import MockLLM
from protolink.transport import RuntimeTransport


def _output(task: Task) -> str:
    return str(task.artifacts[-1].parts[0].content)


def test_private_mapping_is_copied_read_only_nested_and_never_serialized():
    service = object()
    values = {"service": service, "credential": "private-secret"}
    with request_context(values, inherit=("service",)) as context:
        values["credential"] = "changed"
        assert context["credential"] == "private-secret"
        assert context["service"] is service
        with pytest.raises(TypeError):
            context["other"] = 1
        with request_context({"inner": True}):
            assert dict(current_request_context()) == {"inner": True}
        assert current_request_context() is context
        task = Task.create_infer("hello")
        RunContext.ensure_task_context(task)
        assert "private-secret" not in json.dumps(task.to_dict())
        assert "service" not in json.dumps(task.to_dict())
    assert dict(current_request_context()) == {}


@pytest.mark.parametrize(
    "values,inherit,error",
    [(None, (), TypeError), ({1: "a"}, (), TypeError), ({}, "x", TypeError), ({}, ("missing",), ValueError)],
)
def test_private_mapping_validation(values, inherit, error):
    with pytest.raises(error), request_context(values, inherit=inherit):
        pass


@pytest.mark.asyncio
async def test_factory_is_lazy_once_per_task_and_never_validates_a_provider():
    factories: list[str] = []

    class LazyModel(MockLLM):
        def validate_connection(self):
            raise AssertionError("Construction and factory binding must not contact a provider")

    def factory():
        factories.append(current_request_context()["choice"])
        return LazyModel(model=factories[-1], default_response=factories[-1])

    def ping() -> str:
        return "pong"

    agent = Agent(name="lazy", llm_factory=factory, tools=[ping], verbosity=0)
    assert agent.llm is None
    assert agent.card.capabilities.supports_inference is True
    assert factories == []
    await agent.run_task(Task.create_tool_call("ping"))
    assert factories == []
    task = Task.create(Message(role="user", parts=[Part.infer(prompt="first"), Part.infer(prompt="second")]))
    with request_context({"choice": "version-1"}):
        await agent.run_task(task)
    assert task.state is TaskState.COMPLETED
    assert factories == ["version-1"]
    assert agent.llm is None
    with request_context({"choice": "version-2"}):
        result = await agent.run_task(Task.create_infer("later"))
    assert "version-2" in _output(result)
    assert factories == ["version-1", "version-2"]


@pytest.mark.asyncio
async def test_concurrent_queued_runs_keep_snapshot_and_factory_and_tool_context_private():
    entered = asyncio.Event()
    release = asyncio.Event()
    seen: list[tuple[str, str, bool]] = []

    @dataclass(frozen=True)
    class Settings:
        model: str

    async def factory():
        private = current_request_context()
        settings = private["settings"]
        if settings.model == "old":
            entered.set()
            await release.wait()

        def respond(_history, _prompt):
            # The synchronous provider executes in a worker with copied context.
            seen.append(
                (
                    settings.model,
                    current_request_context()["credential"],
                    threading.current_thread() is threading.main_thread(),
                )
            )
            return {"type": "final", "content": settings.model}

        return create_llm("mock", model=settings.model, response_callback=respond)

    agent = Agent(name="concurrent", llm_factory=factory, verbosity=0)
    values = {"settings": Settings("old"), "credential": "first-secret"}
    with request_context(values):
        old = agent.start_run("first")
    await entered.wait()
    values.update(settings=Settings("new"), credential="second-secret")
    with request_context(values):
        new = agent.start_run("second")
    second = await new.result()
    release.set()
    first = await old.result()
    assert "old" in first.output
    assert "new" in second.output
    assert {
        event.payload["metadata"].get("model") for event in first.report.events if event.type == "llm.call.started"
    } == {"old"}
    assert {
        event.payload["metadata"].get("model") for event in second.report.events if event.type == "llm.call.started"
    } == {"new"}
    assert sorted(seen) == [("new", "second-secret", False), ("old", "first-secret", False)]
    assert "first-secret" not in json.dumps(first.task.to_dict())
    assert "second-secret" not in json.dumps(second.task.to_dict())
    assert agent.llm is None
    assert not current_request_context()


@pytest.mark.asyncio
async def test_explicit_local_delegation_inherits_only_selected_dependencies():
    seen: list[dict] = []

    def inspect_context() -> str:
        seen.append(dict(current_request_context()))
        return "inspected"

    child = Agent(name="child", tools=[inspect_context], verbosity=0)
    parent = Agent(
        name="parent",
        subagents=[child],
        llm=create_llm(
            "mock",
            sequential_responses=[
                {
                    "type": "agent_call",
                    "agent": "child",
                    "action": "tool_call",
                    "payload": {"tool": "inspect_context", "args": {}},
                },
                {"type": "final", "content": "done"},
            ],
        ),
        verbosity=0,
    )
    service = object()
    with request_context({"service": service, "credential": "only-parent"}, inherit=("service",)):
        await parent.run_task(Task.create_infer("inspect"))
        assert current_request_context()["credential"] == "only-parent"
    assert seen == [{"service": service}]


@pytest.mark.asyncio
async def test_runtime_transport_clears_private_context_for_unary_and_streaming():
    seen: list[dict] = []

    def inspect_context() -> str:
        seen.append(dict(current_request_context()))
        return "done"

    worker = Agent(name="transport-child", transport="runtime", tools=[inspect_context], verbosity=0)
    client = AgentClient(RuntimeTransport("runtime://private-test-client"))
    async with AgentGroup([worker], client=client) as group:
        with request_context({"credential": "never-over-transport"}, inherit=("credential",)):
            await group.client.send_task(worker.card.url, Task.create_tool_call("inspect_context"))
            async for _event in group.client.send_task_streaming(
                worker.card.url, Task.create_tool_call("inspect_context")
            ):
                assert current_request_context()["credential"] == "never-over-transport"
    assert seen == [{}, {}]


@pytest.mark.asyncio
async def test_factory_model_configuration_is_private_and_requires_reconnection():
    agent = None

    def respond(_history, _prompt):
        serialized = agent.to_dict()
        assert "llm" not in serialized
        assert serialized["llm_factory"] == {"reconnect_required": True}
        assert "provider-secret" not in json.dumps(serialized)
        return {"type": "final", "content": "done"}

    def factory():
        return create_llm("mock", model_params={"api_key": "provider-secret"}, response_callback=respond)

    agent = Agent(name="factory-private", llm_factory=factory, verbosity=0)
    await agent.run_task(Task.create_infer("hello"))
    config = agent.to_dict()
    with pytest.raises(ValueError, match="Reconnect model factories"):
        Agent.from_dict(config)
    restored = Agent.from_dict(config, llm_factory=factory, verbosity=0)
    assert restored.llm is None
    assert restored.llm_factory is factory


@pytest.mark.asyncio
async def test_factory_preserves_provider_native_actions_and_persistent_session_history():
    from protolink.llms.actions import FinalAction, LLMActionResult

    users: list[list[str]] = []

    class NativeModel(MockLLM):
        _native_tool_calling_available = True
        _native_tool_calling_default = True

        def call_action(self, history, *, tools, **kwargs):
            assert self.resolve_tool_calling() == "native"
            users.append([str(message.content) for message in history.messages_raw() if message.role.value == "user"])
            return LLMActionResult(FinalAction(type="final", content=self.model), raw_response="native", native=True)

    async def factory():
        return NativeModel(model=current_request_context()["model"])

    agent = Agent(name="native-factory", llm_factory=factory, state=["conversation"], verbosity=0)
    for prompt, model in [("first question", "one"), ("second question", "two")]:
        task = Task.create_infer(prompt, session_id="shared")
        with request_context({"model": model}):
            await agent.run_task(task)
        assert model in _output(task)
    assert users == [["first question"], ["first question", "second question"]]


@pytest.mark.asyncio
async def test_factory_spec_and_invalid_return_values():
    agent = Agent(name="factory-string", llm_factory=lambda: "mock:lazy-model", verbosity=0)
    result = await agent.run_task(Task.create_infer("hello"))
    assert result.state is TaskState.COMPLETED
    invalid = Agent(name="invalid-factory", llm_factory=lambda: object(), verbosity=0)
    with pytest.raises(TypeError, match="must return an LLM"):
        await invalid.run_task(Task.create_infer("hello"))
    with pytest.raises(ValueError, match="either llm or llm_factory"):
        Agent(name="both", llm="mock", llm_factory=lambda: "mock", verbosity=0)


@pytest.mark.asyncio
async def test_slow_sync_provider_does_not_block_another_request_or_publish_late_answer():
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def respond(_history, _prompt):
        choice = current_request_context()["choice"]
        if choice == "slow":
            entered.set()
            try:
                assert release.wait(timeout=5)
            finally:
                finished.set()
        return {"type": "final", "content": choice}

    agent = Agent(
        name="blocking-provider",
        llm_factory=lambda: create_llm("mock", response_callback=respond),
        max_sync_workers=2,
        verbosity=0,
    )
    with request_context({"choice": "slow"}):
        slow = agent.start_run("slow request")
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        with request_context({"choice": "fast"}):
            fast = agent.start_run("fast request")
        assert (await asyncio.wait_for(fast.result(), 1)).output == "fast"
        await asyncio.wait_for(slow.cancel(), 1)
        canceled = await slow.result()
        assert canceled.status == "canceled"
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert canceled.task.state is TaskState.CANCELED
    assert canceled.output is None
    assert not any(event.payload.get("llm_event_type") == "llm_final" for event in slow.report.events)


@pytest.mark.asyncio
async def test_factory_works_with_ask_and_chat_without_startup_resolution():
    from protolink.rag import Knowledge, SearchHit

    resolutions = []

    def search(query: str, k: int = 5) -> list[SearchHit]:
        return [SearchHit(text="Relevant source", source="test")]

    def factory():
        choice = current_request_context()["choice"]
        resolutions.append(choice)
        return create_llm("mock", default_response=choice)

    agent = Agent(
        name="factory-chat",
        transport="runtime",
        llm_factory=factory,
        knowledge=Knowledge.from_callable(search),
        verbosity=0,
    )
    assert resolutions == []
    assert "Chat not available" not in agent.get_chat()
    async with AgentGroup([agent]):
        assert ("POST", "/chat") in agent.transport._endpoints
        assert resolutions == []
        with request_context({"choice": "request model"}):
            answer = await agent.ask("question")
            chat = await agent.handle_chat_message({"message": "hello"})
    assert answer.text == "request model"
    assert chat == {"response": "request model"}
    assert resolutions == ["request model", "request model"]


@pytest.mark.asyncio
async def test_direct_stream_and_a2a_text_resolve_factory_once_each():
    resolutions = []

    def factory():
        resolutions.append(True)
        return create_llm("mock", default_response="resolved")

    agent = Agent(name="factory-entrypoints", llm_factory=factory, verbosity=0)
    stream = [event async for event in agent.call_llm_stream(Part.infer(prompt="direct"))]
    assert len(resolutions) == 1
    assert any(isinstance(event, dict) and "__protolink_part__" in event for event in stream)
    for streaming in (False, True):
        task = Task.create(Message(role="user", parts=[Part.text("A2A request")]))
        task.metadata["a2a_inbound"] = True
        if streaming:
            _ = [event async for event in agent.run_task_streaming(task)]
        else:
            await agent.run_task(task)
        assert task.state is TaskState.COMPLETED
        assert "resolved" in _output(task)
    assert len(resolutions) == 3


@pytest.mark.asyncio
async def test_runtime_receiving_application_can_resolve_its_own_private_dependencies():
    seen = []

    def inspect_context() -> str:
        seen.append(dict(current_request_context()))
        return "done"

    class ReceivingAgent(Agent):
        async def handle_task_streaming(self, task):
            # Stand-in for receiving application middleware: one binding must
            # survive several streamed events without leaking to its caller.
            assert not current_request_context()
            with request_context({"receiver": "local service"}):
                async for event in super().handle_task_streaming(task):
                    yield event

    worker = ReceivingAgent(name="receiving-context", transport="runtime", tools=[inspect_context], verbosity=0)
    client = AgentClient(RuntimeTransport("runtime://receiving-context-client"))
    async with AgentGroup([worker]):
        with request_context({"caller": "private credential"}):
            async for _event in client.send_task_streaming(worker.card.url, Task.create_tool_call("inspect_context")):
                assert dict(current_request_context()) == {"caller": "private credential"}
    assert seen == [{"receiver": "local service"}]
