"""A shared local model cannot evaluate two mutable contexts concurrently."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from protolink.llms.history import ConversationHistory
from protolink.llms.local.llamacpp_client import LlamaCPPLocalLLM


def local_model(monkeypatch, tmp_path, complete):
    from protolink.llms.local import llamacpp_client

    path = tmp_path / "model.gguf"
    path.touch()
    monkeypatch.setattr(
        llamacpp_client,
        "require_llama_cpp",
        lambda: SimpleNamespace(Llama=lambda **kwargs: SimpleNamespace(create_chat_completion=complete)),
    )
    return LlamaCPPLocalLLM(model=str(path), tool_calling="native")


async def wait_for_event(event):
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_shared_local_unary_calls_are_serialized(monkeypatch, tmp_path, native):
    entered, release = threading.Event(), threading.Event()
    count = 0

    def complete(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            assert release.wait(3)
        return {"choices": [{"message": {"content": "done"}}]}

    llm = local_model(monkeypatch, tmp_path, complete)
    history = ConversationHistory("test")
    call = (lambda: llm.call_action(history, tools={})) if native else (lambda: llm.call(history))
    first = asyncio.create_task(asyncio.to_thread(call))
    second = None
    try:
        await wait_for_event(entered)
        second = asyncio.create_task(asyncio.to_thread(call))
        await asyncio.sleep(0.02)
        assert count == 1 and not second.done()
    finally:
        release.set()
        await first
        if second is not None:
            await second
    assert count == 2


@pytest.mark.asyncio
async def test_canceled_local_stream_keeps_model_lock_until_read_and_cleanup_finish(monkeypatch, tmp_path):
    blocked, release, cleaned = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def chunks():
        try:
            yield {"choices": [{"delta": {"content": "first"}}]}
            blocked.set()
            assert release.wait(3)
        finally:
            cleaned.set()

    def complete(*, stream, **kwargs):
        calls.append(stream)
        return chunks() if stream else {"choices": [{"message": {"content": "done"}}]}

    llm = local_model(monkeypatch, tmp_path, complete)
    history = ConversationHistory("test")
    stream = llm.call_stream(history)
    assert await anext(stream) == "first"
    pending = asyncio.create_task(anext(stream))
    unary = None
    try:
        await wait_for_event(blocked)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        unary = asyncio.create_task(asyncio.to_thread(llm.call, history))
        await asyncio.sleep(0.02)
        assert calls == [True] and not cleaned.is_set()
    finally:
        release.set()
        if unary is not None:
            assert await asyncio.wait_for(unary, 2) == "done"
        await stream.aclose()
    assert cleaned.is_set() and calls == [True, False]
