"""Automatic provider metadata checks never block asynchronous inference."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from protolink import Agent, current_request_context, request_context
from protolink.llms import MockLLM


@pytest.mark.parametrize("entrypoint", ["agent", "llm"])
@pytest.mark.asyncio
async def test_blocking_discovery_allows_other_requests_and_prompt_cancellation(entrypoint):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    discovery_threads = []
    model_calls = []

    class DiscoveringModel(MockLLM):
        _native_tool_calling_available = True

        def discover_tool_calling(self):
            discovery_threads.append(threading.get_ident())
            entered.set()
            try:
                assert release.wait(3)
                return True
            finally:
                finished.set()

    slow_model = DiscoveringModel(
        tool_calling="auto", response_callback=lambda *_args: model_calls.append(True) or "late"
    )
    fast_model = MockLLM(default_response="fast")
    agent = Agent(name="discovery", llm_factory=lambda: current_request_context()["model"], verbosity=0)

    async def run(model):
        if entrypoint == "llm":
            return await model.infer(query="request", tools={})
        with request_context({"model": model}):
            return await agent.invoke("request")

    task = asyncio.create_task(run(slow_model))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert not finished.is_set()
        assert len(discovery_threads) == 1
        assert discovery_threads[0] != threading.get_ident()
        fast_result = await asyncio.wait_for(run(fast_model), 1)
        assert (fast_result.content if entrypoint == "llm" else fast_result) == "fast"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert model_calls == []
        assert slow_model._active_tool_calling.get() is None
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        await asyncio.gather(task, return_exceptions=True)
    assert model_calls == []


@pytest.mark.parametrize("saved", ["native", "json", "invalid"])
@pytest.mark.asyncio
async def test_saved_durable_mode_skips_discovery(monkeypatch, saved):
    class DiscoveringModel(MockLLM):
        _native_tool_calling_available = True

        def discover_tool_calling(self):
            pytest.fail("A saved durable mode must not contact the provider")

    model = DiscoveringModel(tool_calling="auto")
    durable = SimpleNamespace(data={"tool_calling_mode": saved})
    monkeypatch.setattr("protolink.core.durable.current_durable_run", lambda: durable)
    if saved == "invalid":
        with pytest.raises(ValueError, match="invalid tool-calling mode"):
            async with model._use_tool_calling():
                pass
    else:
        async with model._use_tool_calling():
            assert model.resolve_tool_calling() == saved
    assert model._tool_calling_capability_cache is None
    assert model._active_tool_calling.get() is None


@pytest.mark.asyncio
async def test_active_mode_skips_discovery_and_remains_bound():
    class DiscoveringModel(MockLLM):
        _native_tool_calling_available = True

        def discover_tool_calling(self):
            pytest.fail("An active mode must not contact the provider")

    model = DiscoveringModel(tool_calling="auto")
    token = model._active_tool_calling.set("native")
    try:
        async with model._use_tool_calling():
            assert model.resolve_tool_calling() == "native"
        assert model._active_tool_calling.get() == "native"
    finally:
        model._active_tool_calling.reset(token)
