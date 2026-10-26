"""Concurrent synchronous HTTP providers own their connections per request."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from protolink import Agent, Task, TaskState
from protolink.llms.api.grok_client import GrokLLM
from protolink.llms.history import ConversationHistory
from protolink.llms.server.llamacpp_client import LlamaCPPServerLLM
from protolink.llms.server.ollama_client import OllamaLLM


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", [OllamaLLM, LlamaCPPServerLLM])
@pytest.mark.parametrize("native", [False, True])
async def test_persistent_http_provider_concurrent_calls_have_independent_connections(monkeypatch, backend, native):
    barrier = threading.Barrier(2)
    connections = []

    class Connection:
        def __init__(self, host, port, *, timeout):
            self.closed = False
            self.prompt = None
            self.owner = None
            connections.append(self)

        def request(self, *, method, url, body, headers):
            assert self.owner is None, "A live connection was shared across requests"
            self.owner = threading.get_ident()
            self.prompt = json.loads(body)["messages"][-1]["content"]
            barrier.wait(timeout=2)

        def getresponse(self):
            assert self.owner == threading.get_ident()
            message = {"content": json.dumps({"type": "final", "content": self.prompt})}
            payload = {"message": message} if backend is OllamaLLM else {"choices": [{"message": message}]}
            return SimpleNamespace(status=200, read=lambda: json.dumps(payload).encode())

        def close(self):
            assert self.owner == threading.get_ident()
            self.closed = True

    monkeypatch.setattr(backend, "validate_connection", lambda self: True)
    monkeypatch.setattr("http.client.HTTPConnection", Connection)
    model = backend(base_url="http://test", supports_tool_calling=native)
    agent = Agent(name="concurrent-provider", llm=model, max_sync_workers=2, verbosity=0)
    try:
        tasks = await asyncio.gather(*(agent.run_task(Task.create_infer(prompt)) for prompt in ("first", "second")))
        assert all(task.state is TaskState.COMPLETED for task in tasks)
        assert [task.get_output() for task in tasks] == ["first", "second"]
        assert len(connections) == 2
        assert all(connection.closed for connection in connections)
    finally:
        await agent._stop()


@pytest.mark.parametrize("backend", [OllamaLLM, LlamaCPPServerLLM])
def test_http_provider_closes_failed_https_request(monkeypatch, backend):
    connections = []

    class Connection:
        def __init__(self, host, port, *, timeout):
            self.closed = False
            connections.append(self)

        def request(self, **kwargs):
            raise OSError("request failed")

        def close(self):
            self.closed = True

    monkeypatch.setattr(backend, "validate_connection", lambda self: True)
    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    model = backend(base_url="https://test")
    with pytest.raises(OSError, match="request failed"):
        model.call(ConversationHistory())
    assert len(connections) == 1 and connections[0].closed


@pytest.mark.asyncio
async def test_grok_shared_httpx_client_supports_concurrent_worker_calls(monkeypatch):
    import httpx2

    barrier = threading.Barrier(2)

    def respond(request):
        barrier.wait(timeout=2)
        prompt = json.loads(request.content)["messages"][-1]["content"]
        return httpx2.Response(200, json={"choices": [{"message": {"content": prompt}}]})

    monkeypatch.setattr(GrokLLM, "validate_connection", lambda self: True)
    model = GrokLLM(api_key="test")
    model._client.close()
    model._client = httpx2.Client(transport=httpx2.MockTransport(respond))
    agent = Agent(name="grok-concurrent", llm=model, max_sync_workers=2, verbosity=0)
    try:
        tasks = await asyncio.gather(*(agent.run_task(Task.create_infer(prompt)) for prompt in ("first", "second")))
        assert all(task.state is TaskState.COMPLETED for task in tasks)
        assert [task.get_output() for task in tasks] == ["first", "second"]
    finally:
        await agent._stop()
        model._client.close()
        await model._async_client.aclose()
