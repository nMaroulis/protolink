"""Gated providers prove delivery before generation ends, without live models."""

import asyncio
import json
import threading
from contextlib import aclosing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

from protolink import Agent, RunHandle, Task
from protolink.llms._streaming import http_stream, threaded_stream
from protolink.llms.api.anthropic_client import AnthropicLLM
from protolink.llms.api.deepseek_client import DeepSeekLLM
from protolink.llms.api.gemini_client import GeminiLLM
from protolink.llms.api.hugging_face_client import HuggingFaceLLM
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.llms.local.llamacpp_client import LlamaCPPLocalLLM
from protolink.llms.server.llamacpp_client import LlamaCPPServerLLM
from protolink.llms.server.ollama_client import OllamaLLM
from protolink.llms.server.openai_compatible_client import LMStudioLLM, OpenAICompatibleLLM
from protolink.llms.server.vllm_client import VLLMLLM

HTTP_BACKENDS = [OllamaLLM, OpenAICompatibleLLM, LMStudioLLM, VLLMLLM, LlamaCPPServerLLM]
SDK_BACKENDS = [OpenAILLM, AnthropicLLM, DeepSeekLLM, GeminiLLM, HuggingFaceLLM, LlamaCPPLocalLLM]


def _frame(text, ollama):
    chunk = {"message": {"content": text}} if ollama else {"choices": [{"delta": {"content": text}}]}
    return (("" if ollama else "data: ") + json.dumps(chunk) + "\n\n").encode()


@contextmanager
def _server(native, ollama):
    """Serve one chunk, pause until the test releases it, then send completion."""
    release = threading.Event()
    timed_out = threading.Event()
    requests = []
    first, rest = ("Hel", "lo") if native else ('{"type":"final","content":"Hel', 'lo"}')

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, self.headers, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson" if ollama else "text/event-stream")
            self.end_headers()
            try:
                self.wfile.write(_frame(first, ollama))
                self.wfile.flush()
                if not release.wait(3):
                    timed_out.set()
                self.wfile.write(_frame(rest, ollama))
                self.wfile.write(b'{"done":true}\n' if ollama else b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/prefix", release, timed_out, requests, first
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()


async def _first_chunk(events):
    async for event in events:
        if event.payload.get("llm_event_type") == "llm_chunk":
            return event
    raise AssertionError("Run finished without a text chunk")


def _run(llm):
    agent = Agent(
        {
            "name": "streamer",
            "description": "Streaming regression",
            "url": "runtime://streamer",
            "capabilities": {"streaming": True},
        },
        llm=llm,
        verbosity=0,
    )
    return RunHandle.start(agent, Task.create_infer(prompt="Say hello"))


@pytest.mark.parametrize("backend", HTTP_BACKENDS)
@pytest.mark.parametrize("native", [False, True], ids=["json-action", "native-tools"])
@pytest.mark.asyncio
async def test_http_chunk_reaches_run_handle_before_source_is_released(monkeypatch, backend, native):
    monkeypatch.setattr(backend, "validate_connection", lambda self: True)
    with _server(native, backend is OllamaLLM) as (url, release, timed_out, requests, first):
        llm = backend(
            base_url=url,
            model="test",
            supports_tool_calling=native,
            headers={"Authorization": "Bearer test"},
            model_params={"max_tokens": 42},
        )
        handle = _run(llm)
        try:
            async with aclosing(handle.events()) as events:
                event = await asyncio.wait_for(_first_chunk(events), timeout=2)
                assert event.payload["content"] == first
                assert not release.is_set() and not timed_out.is_set()
                assert not handle.task.is_terminal
                release.set()
                remaining = [event async for event in events]
            result = await handle.result()
            assert result.status == "completed", result.error
            assert result.output == "Hello"
            finals = [event for event in remaining if event.payload.get("llm_event_type") == "llm_final"]
            assert len(finals) == 1 and finals[0].payload["content"] == "Hello"
            assert remaining[-1].type == "task.status" and remaining[-1].final
            path, headers, payload = requests[0]
            assert path == ("/prefix/api/chat" if backend is OllamaLLM else "/prefix/v1/chat/completions")
            assert headers["Authorization"] == "Bearer test"
            assert payload["stream"] is True
            if backend is OllamaLLM:
                assert payload["options"]["num_predict"] == 42
                assert ("format" in payload) is not native
        finally:
            release.set()
            await handle.cancel()
            await handle.result()


def _sdk_llm(backend, factory):
    """Use real adapter parsing with only the provider SDK replaced."""
    llm = backend.__new__(backend)
    LLM.__init__(llm, model="test", model_params={})
    llm._supports_tool_calling = True
    llm._GenerateContentConfig = lambda **kwargs: kwargs
    llm._client = SimpleNamespace(
        responses=SimpleNamespace(create=factory),
        messages=SimpleNamespace(stream=factory),
        chat=SimpleNamespace(completions=SimpleNamespace(create=factory)),
        models=SimpleNamespace(generate_content_stream=factory),
        chat_completion=factory,
        create_chat_completion=factory,
    )
    return llm


def _sdk_event(text, backend):
    if backend is OpenAILLM:
        return SimpleNamespace(type="response.output_text.delta", delta=text)
    if backend is AnthropicLLM:
        return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))
    if backend is GeminiLLM:
        return SimpleNamespace(text=text)
    if backend is LlamaCPPLocalLLM:
        return {"choices": [{"delta": {"content": text}}]}
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


@pytest.mark.parametrize("backend", SDK_BACKENDS)
@pytest.mark.parametrize("direct", [False, True], ids=["run-handle", "call-stream"])
@pytest.mark.asyncio
async def test_sdk_reads_allow_incremental_consumption(backend, direct):
    release = threading.Event()
    closed = threading.Event()
    worker_ids = []
    callback_thread = threading.get_ident()
    is_json = backend is HuggingFaceLLM and not direct
    first, rest = ('{"type":"final","content":"Hel', 'lo"}') if is_json else ("Hel", "lo")

    def source(*args, **kwargs):
        worker_ids.append(threading.get_ident())
        try:
            yield _sdk_event(first, backend)
            worker_ids.append(threading.get_ident())
            assert release.wait(3), "Consumer could not run while SDK blocked"
            yield _sdk_event(rest, backend)
        finally:
            worker_ids.append(threading.get_ident())
            closed.set()

    llm = _sdk_llm(backend, source)
    handle = None
    try:
        if direct:
            async with aclosing(llm.call_stream(ConversationHistory())) as stream:
                assert await asyncio.wait_for(anext(stream), 2) == first
                assert not release.is_set()
                release.set()
                assert "".join([chunk async for chunk in stream]) == rest
        else:
            handle = _run(llm)
            async with aclosing(handle.events()) as events:
                assert (await asyncio.wait_for(_first_chunk(events), 2)).payload["content"] == first
                assert not release.is_set() and not handle.task.is_terminal
                release.set()
                _ = [event async for event in events]
            result = await handle.result()
            assert result.status == "completed", result.error
            assert result.output == "Hello"
        assert closed.is_set()
        assert len(set(worker_ids)) == 1 and worker_ids[0] != callback_thread
    finally:
        release.set()
        if handle is not None:
            await handle.cancel()
            await handle.result()


class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, parts, *, pause=False):
        self.parts = parts
        self.pause = pause
        self.closed = False
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for part in self.parts:
            yield part
        if self.pause:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def _mock_http(monkeypatch, source, status=200):
    client_type = httpx.AsyncClient
    clients = []

    def client(**kwargs):
        instance = client_type(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, stream=source)), **kwargs
        )
        clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return clients


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("failure", ["cancel", "callback"])
@pytest.mark.asyncio
async def test_ollama_closes_response_on_cancellation_or_callback_error(monkeypatch, native, failure):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    source = _ByteStream([_frame("first", ollama=True)], pause=True)
    clients = _mock_http(monkeypatch, source)
    llm = OllamaLLM(base_url="http://test", supports_tool_calling=native)

    async def callback(chunk):
        if failure == "callback":
            raise ValueError("consumer failed")

    task = asyncio.create_task(llm.call_action_stream(ConversationHistory(), tools={}, chunk_callback=callback))
    if failure == "cancel":
        await asyncio.wait_for(source.waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ValueError, match="consumer failed"):
            await task
    assert source.closed and all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    "parts,status,error",
    [
        ([b'{"error":"model failed"}\n'], 200, "model failed"),
        ([b"not json\n"], 200, "invalid streaming JSON"),
        ([b"[]\n"], 200, "invalid streaming payload"),
        ([b"overloaded"], 503, "503: overloaded"),
    ],
)
@pytest.mark.asyncio
async def test_http_stream_errors_close_resources(monkeypatch, parts, status, error):
    source = _ByteStream(parts)
    clients = _mock_http(monkeypatch, source, status)
    with pytest.raises(RuntimeError, match=error):
        async with http_stream("http://test", {}, headers={}, timeout=1, provider="test") as stream:
            _ = [chunk async for chunk in stream]
    assert source.closed and all(client.is_closed for client in clients)


@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.asyncio
async def test_fragmented_unicode_and_completion_marker_do_not_wait_for_eof(monkeypatch, sse):
    frame = (("data:" if sse else "") + '{"message":{"content":"café"}}\n\n').encode()
    marker = b"data: [DONE]\n\n" if sse else b'{"done":true}\n'
    source = _ByteStream([bytes([byte]) for byte in frame + marker], pause=True)
    _mock_http(monkeypatch, source)
    async with http_stream("http://test", {}, headers={}, timeout=1, provider="test") as stream:
        async with asyncio.timeout(1):
            chunks = [chunk async for chunk in stream]
    assert chunks[0]["message"]["content"] == "café"
    assert source.closed and not source.waiting.is_set()


@pytest.mark.asyncio
async def test_threaded_stream_cancellation_closes_after_in_progress_read_returns():
    reading = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    def source():
        try:
            yield "first"
            reading.set()
            assert release.wait(3)
            yield "second"
        finally:
            closed.set()

    async def consume():
        async with threaded_stream(source) as stream:
            _ = [chunk async for chunk in stream]

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(reading.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert not closed.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(closed.wait, 2)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.asyncio
async def test_run_handle_cancel_closes_ollama_stream_before_source_finishes(monkeypatch, native):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    source = _ByteStream([_frame("first", ollama=True)], pause=True)
    clients = _mock_http(monkeypatch, source)
    handle = _run(OllamaLLM(base_url="http://test", supports_tool_calling=native))
    try:
        async with aclosing(handle.events()) as events:
            await asyncio.wait_for(_first_chunk(events), 1)
            await asyncio.wait_for(handle.cancel(), 1)
            result = await asyncio.wait_for(handle.result(), 1)
            remaining = [event async for event in events]
        assert result.status == "canceled"
        assert not any(event.payload.get("llm_event_type") == "llm_final" for event in remaining)
        assert source.closed and all(client.is_closed for client in clients)
    finally:
        await handle.cancel()
        await handle.result()


@pytest.mark.parametrize("backend", HTTP_BACKENDS)
@pytest.mark.asyncio
async def test_http_direct_stream_explicit_close_releases_connection(monkeypatch, backend):
    monkeypatch.setattr(backend, "validate_connection", lambda self: True)
    source = _ByteStream([_frame("first", backend is OllamaLLM)], pause=True)
    clients = _mock_http(monkeypatch, source)
    llm = backend(base_url="http://test", model="test")
    async with aclosing(llm.call_stream(ConversationHistory())) as stream:
        assert await anext(stream) == "first"
    assert source.closed and all(client.is_closed for client in clients)


@pytest.mark.parametrize("backend", HTTP_BACKENDS)
@pytest.mark.asyncio
async def test_native_http_tool_assembly_retains_text_and_split_arguments(monkeypatch, backend):
    from protolink.llms.actions import ToolCallAction

    monkeypatch.setattr(backend, "validate_connection", lambda self: True)
    ollama = backend is OllamaLLM
    if ollama:
        parts = [
            _frame("Checking", ollama=True),
            json.dumps(
                {
                    "message": {"tool_calls": [{"function": {"name": "lookup", "arguments": {"key": "alpha"}}}]},
                    "done": True,
                }
            ).encode()
            + b"\n",
        ]
    else:
        parts = [_frame("Checking", ollama=False)]
        for function in [{"name": "lookup", "arguments": '{"key":'}, {"arguments": '"alpha"}'}]:
            chunk = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": function}]}}]}
            parts.append(("data: " + json.dumps(chunk) + "\n\n").encode())
        parts.append(b"data: [DONE]\n\n")
    source = _ByteStream(parts)
    _mock_http(monkeypatch, source)
    llm = backend(base_url="http://test", model="test", supports_tool_calling=True)
    chunks = []

    async def capture(chunk):
        chunks.append(chunk)

    result = await llm.call_action_stream(ConversationHistory(), tools={}, chunk_callback=capture)
    assert chunks == ["Checking"]
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup" and result.action.args == {"key": "alpha"}
    assert result.native and source.closed


@pytest.mark.parametrize("phase", ["open", "read", "callback"])
@pytest.mark.asyncio
async def test_sdk_failure_propagates_and_closes_stream_on_its_worker(phase):
    closed = threading.Event()
    loop_thread = threading.get_ident()
    threads = []

    def source():
        try:
            yield "first"
            if phase == "read":
                raise ValueError("read failed")
        finally:
            threads.append(threading.get_ident())
            closed.set()

    def factory():
        threads.append(threading.get_ident())
        if phase == "open":
            raise ValueError("open failed")
        return source()

    with pytest.raises(ValueError, match=f"{phase} failed"):
        async with threaded_stream(factory) as stream:
            async for _ in stream:
                assert threading.get_ident() == loop_thread
                if phase == "callback":
                    raise ValueError("callback failed")
    assert len(set(threads)) == 1 and threads[0] != loop_thread
    assert closed.is_set() is (phase != "open")


@pytest.mark.parametrize("backend", [DeepSeekLLM, LlamaCPPLocalLLM, GeminiLLM])
@pytest.mark.asyncio
async def test_direct_sdk_stream_skips_usage_and_empty_text(backend):
    empty = (
        SimpleNamespace(text=None)
        if backend is GeminiLLM
        else ({"choices": []} if backend is LlamaCPPLocalLLM else SimpleNamespace(choices=[]))
    )
    llm = _sdk_llm(backend, lambda **kwargs: iter([empty, _sdk_event("Hello", backend), empty]))
    assert [text async for text in llm.call_stream(ConversationHistory())] == ["Hello"]
