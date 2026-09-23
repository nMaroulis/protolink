"""Exercise the real supported SDK without sending telemetry over the network."""

import asyncio
import json
import uuid

import pytest

from protolink import Part, Task
from protolink.telemetry import LangfuseTelemetry

langfuse = pytest.importorskip("langfuse")


@pytest.fixture
def telemetry_factory(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    clients = []

    def create():
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        # SDK 4.0 has no public exporter constructor argument. Replace only
        # its network exporter, retaining real observation/processor behavior.
        monkeypatch.setattr("langfuse._client.span_processor.OTLPSpanExporter", lambda **kwargs: exporter)

        def client_factory(**kwargs):
            client = langfuse.Langfuse(
                **kwargs,
                tracer_provider=provider,
            )
            clients.append(client)
            return client

        monkeypatch.setattr(
            "protolink.telemetry.langfuse_telemetry.require_langfuse", lambda: (langfuse, client_factory)
        )
        telemetry = LangfuseTelemetry(
            public_key=f"pk-lf-test-{uuid.uuid4()}", secret_key="sk-lf-test", host="http://127.0.0.1:9"
        )
        return telemetry, exporter

    yield create
    for client in clients:
        client.shutdown()


@pytest.mark.asyncio
async def test_real_sdk_exports_task_generation_and_tool_results(telemetry_factory):
    telemetry, exporter = telemetry_factory()
    task = Task.create_infer(prompt="Hello")

    await telemetry.on_task_start(task, "assistant")
    await telemetry.on_llm_start("Hello", model="test-model", metadata={"tokens": 3})
    await telemetry.on_llm_end(Part("text", "answer"))
    await telemetry.on_tool_start("success", {"value": 1})
    await telemetry.on_tool_end("success", {"value": 2})
    await telemetry.on_tool_start("failure", {})
    await telemetry.on_tool_end("failure", None, error="unavailable")
    await telemetry.on_task_end(task, task, "assistant")

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"Task: assistant", "LLM Call", "Tool: success", "Tool: failure"}
    root = spans["Task: assistant"]
    assert f"{root.context.trace_id:032x}" == langfuse.Langfuse.create_trace_id(seed=task.id)
    for name in ("LLM Call", "Tool: success", "Tool: failure"):
        assert spans[name].parent.span_id == root.context.span_id
        assert spans[name].context.trace_id == root.context.trace_id
    assert spans["LLM Call"].attributes["langfuse.observation.type"] == "generation"
    assert "answer" in spans["LLM Call"].attributes["langfuse.observation.output"]
    assert json.loads(spans["Tool: success"].attributes["langfuse.observation.output"]) == {"value": 2}
    assert spans["Tool: failure"].attributes["langfuse.observation.level"] == "ERROR"
    assert spans["Tool: failure"].attributes["langfuse.observation.status_message"] == "unavailable"
    assert not telemetry._tasks.get()


@pytest.mark.asyncio
async def test_nested_tasks_restore_parent_generation(telemetry_factory):
    telemetry, exporter = telemetry_factory()
    parent = Task.create_infer(prompt="parent")
    child = Task.create_infer(prompt="child")
    await telemetry.on_task_start(parent, "parent")
    await telemetry.on_llm_start("parent generation")
    await telemetry.on_task_start(child, "child")
    await telemetry.on_llm_start("child generation")
    await telemetry.on_llm_end(Part("text", "child output"))
    await telemetry.on_task_end(child, child, "child")
    await telemetry.on_llm_end(Part("text", "parent output"))
    await telemetry.on_task_end(parent, parent, "parent")

    spans = exporter.get_finished_spans()
    assert len(spans) == 4
    for task, output in ((parent, "parent output"), (child, "child output")):
        trace_id = int(langfuse.Langfuse.create_trace_id(seed=task.id), 16)
        generation = next(s for s in spans if s.name == "LLM Call" and s.context.trace_id == trace_id)
        assert output in generation.attributes["langfuse.observation.output"]


@pytest.mark.asyncio
async def test_concurrent_tasks_and_tracker_instances_do_not_share_state(telemetry_factory):
    first, first_exporter = telemetry_factory()
    second, second_exporter = telemetry_factory()

    async def run(name):
        task = Task.create_infer(prompt=name)
        await first.on_task_start(task, name)
        await second.on_task_start(task, name)
        await first.on_llm_start(name)
        await second.on_llm_start(name)
        await asyncio.sleep(0)
        await first.on_llm_end(Part("text", name))
        await second.on_llm_end(Part("text", name))
        await second.on_task_end(task, task, name)
        await first.on_task_end(task, task, name)

    await asyncio.gather(run("one"), run("two"))
    for exporter in (first_exporter, second_exporter):
        spans = exporter.get_finished_spans()
        assert len(spans) == 4
        roots = {s.context.trace_id: s for s in spans if s.name.startswith("Task:")}
        for generation in (s for s in spans if s.name == "LLM Call"):
            root = roots[generation.context.trace_id]
            assert generation.parent.span_id == root.context.span_id
            assert root.name.removeprefix("Task: ") in generation.attributes["langfuse.observation.output"]


@pytest.mark.asyncio
async def test_sdk_failure_does_not_leak_into_the_parent_task(telemetry_factory, monkeypatch):
    telemetry, exporter = telemetry_factory()
    parent = Task.create_infer(prompt="parent")
    child = Task.create_infer(prompt="child")
    await telemetry.on_task_start(parent, "parent")

    def fail(**kwargs):
        raise RuntimeError("SDK unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(telemetry.langfuse, "start_observation", fail)
        await telemetry.on_task_start(child, "child")
    await telemetry.on_tool_start("must-not-attach-to-parent", {})
    await telemetry.on_tool_end("must-not-attach-to-parent", "ignored")
    await telemetry.on_task_end(child, child, "child")
    await telemetry.on_tool_start("parent-tool", {})
    await telemetry.on_tool_end("parent-tool", "done")
    await telemetry.on_task_end(parent, parent, "parent")
    assert {s.name for s in exporter.get_finished_spans()} == {"Task: parent", "Tool: parent-tool"}


@pytest.mark.asyncio
async def test_failed_output_update_still_ends_observation(telemetry_factory, monkeypatch):
    telemetry, exporter = telemetry_factory()
    task = Task.create_infer(prompt="hello")
    await telemetry.on_task_start(task, "assistant")
    await telemetry.on_llm_start("hello")

    def fail(**kwargs):
        raise RuntimeError("cannot serialize output")

    monkeypatch.setattr(telemetry._current().generation, "update", fail)
    await telemetry.on_llm_end(Part("text", "answer"))
    await telemetry.on_task_end(task, task, "assistant")
    assert {s.name for s in exporter.get_finished_spans()} == {"Task: assistant", "LLM Call"}
