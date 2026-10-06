import json
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest

from protolink.llms.actions import ToolCallAction
from protolink.llms.history import ConversationHistory
from protolink.llms.server.ollama_client import OllamaLLM


class _FakeOllamaResponse:
    status = 200

    def read(self):
        return json.dumps(
            {
                "message": {"content": '{"type":"final","content":"ok"}'},
                "prompt_eval_count": 80,
                "eval_count": 20,
                "total_duration": 70_000_000,
                "load_duration": 5_000_000,
                "prompt_eval_duration": 40_000_000,
                "eval_duration": 25_000_000,
            }
        ).encode()


class _FakeOllamaConnection:
    def __init__(self):
        self.body = None

    def request(self, *, method, url, body, headers):
        self.body = body

    def getresponse(self):
        return _FakeOllamaResponse()

    def close(self):
        return None


class DummyTool:
    name = "lookup"
    description = "Look up a value."
    input_schema: ClassVar[dict] = {"key": {"type": "string", "required": True}}
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


class _ScriptedOllamaConnection:
    """Keep wire requests and closes while returning scripted HTTP responses."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = 0

    def request(self, *, method, url, body, headers):
        self.requests.append(json.loads(body))

    def getresponse(self):
        status, payload = next(self.responses)
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(status=status, read=lambda: body.encode())

    def close(self):
        self.closed += 1


def test_ollama_default_call_uses_plain_json_mode(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="gemma")
    fake_connection = _FakeOllamaConnection()
    llm._client = fake_connection

    history = ConversationHistory()
    history.add_user("hello")

    assert llm.call(history) == '{"type":"final","content":"ok"}'
    payload = json.loads(fake_connection.body)
    assert payload["format"] == "json"


@pytest.mark.asyncio
async def test_ollama_default_json_action_preserves_provider_timing_metadata(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="gemma")
    fake_connection = _FakeOllamaConnection()
    llm._client = fake_connection
    events = []

    async def capture(event):
        events.append(event)

    result = await llm.infer(query="hello", tools={}, event_callback=capture)

    assert result.content == "ok"
    completed = next(event for event in events if event["type"] == "llm_call_completed")
    usage = completed["metrics"]["usage"]
    assert usage["estimated"] is False
    assert usage["input_tokens"] == 80
    assert usage["output_tokens"] == 20
    assert '"prompt_eval_duration": 40000000' in json.dumps(usage["details"], sort_keys=True)


@pytest.mark.asyncio
async def test_ollama_native_call_action_stream_is_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(
        base_url="http://localhost:11434",
        model="qwen",
        supports_tool_calling=True,
    )
    requests = []

    def respond(request):
        requests.append(request)
        chunk = {
            "message": {"tool_calls": [{"function": {"name": "lookup", "arguments": {"key": "alpha"}}}]},
            "done": True,
        }
        return httpx.Response(200, content=json.dumps(chunk) + "\n")

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs)
    )

    history = ConversationHistory()
    history.add_user("Find alpha")

    result = await llm.call_action_stream(history, tools={"lookup": DummyTool()})
    payload = json.loads(requests[0].content)

    assert "format" not in payload
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert result.metadata["streaming"] is True


def test_ollama_unavailable_default_json_falls_back_without_changing_actions(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="gemma4:12b-mlx")
    result_body = {
        "message": {"content": '{"type":"tool_call","tool":"lookup","args":{"key":"alpha"}}'},
        "prompt_eval_count": 20,
        "eval_count": 15,
    }
    connection = _ScriptedOllamaConnection(
        [(501, {"error": "structured output is unavailable"}), (200, result_body), (200, result_body)]
    )
    llm._client = connection
    history = ConversationHistory()
    history.add_user("Find alpha")
    original_options = dict(llm.model_params)

    for _ in range(2):
        result = llm.call_action(history, tools={"lookup": DummyTool()})
        assert isinstance(result.action, ToolCallAction)
        assert result.action.args == {"key": "alpha"}
        assert not result.native and not llm.supports_tool_calling
        assert result.metadata["usage"]["input_tokens"] == 20

    assert connection.requests[0]["format"] == "json"
    assert all("format" not in request and "tools" not in request for request in connection.requests[1:])
    assert all(request["options"] == original_options for request in connection.requests)
    assert llm.model_params == original_options
    assert connection.closed == 3


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("response_format", [None, "json", {"type": "object"}])
def test_ollama_explicit_request_controls_are_not_generation_options(monkeypatch, native, response_format):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    settings = {"format": response_format, "think": False, "keep_alive": "2m", "max_tokens": 42}
    llm = OllamaLLM(base_url="http://localhost:11434", model_params=settings, supports_tool_calling=native)
    connection = _ScriptedOllamaConnection([(200, {"message": {"content": '{"type":"final","content":"ok"}'}})])
    llm._client = connection

    llm.call_action(ConversationHistory(), tools={})

    request = connection.requests[0]
    assert request["think"] is False and request["keep_alive"] == "2m"
    assert request["options"]["num_predict"] == 42
    assert not {"format", "think", "keep_alive", "max_tokens"} & request["options"].keys()
    if response_format is None:
        assert "format" not in request
    else:
        assert request["format"] == response_format
    assert all(llm.model_params[key] == value for key, value in settings.items())


@pytest.mark.parametrize("response_format", ["json", {"type": "object"}])
def test_ollama_explicit_format_rejection_is_not_silently_downgraded(monkeypatch, response_format):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model_params={"format": response_format})
    connection = _ScriptedOllamaConnection([(501, {"error": "structured output is unavailable"})])
    llm._client = connection

    with pytest.raises(RuntimeError, match="structured output is unavailable"):
        llm.call(ConversationHistory())

    assert len(connection.requests) == connection.closed == 1


@pytest.mark.parametrize(
    "status,body",
    [
        (500, {"error": "structured output is unavailable"}),
        (501, {"error": "model operation is not implemented"}),
        (400, {"error": "model does not support tools"}),
        (501, "structured output is unavailable"),
    ],
)
def test_ollama_other_request_errors_do_not_trigger_format_fallback(monkeypatch, status, body):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434")
    connection = _ScriptedOllamaConnection([(status, body)])
    llm._client = connection

    with pytest.raises(RuntimeError):
        llm.call(ConversationHistory())

    assert len(connection.requests) == connection.closed == 1


def test_ollama_format_fallback_is_bounded_and_scoped_to_model(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="gemma4:12b-mlx")
    connection = _ScriptedOllamaConnection(
        [
            (501, {"error": "structured output is unavailable"}),
            (501, {"error": "structured output is unavailable"}),
            (200, {"message": {"content": "ok"}}),
        ]
    )
    llm._client = connection

    with pytest.raises(RuntimeError, match="structured output is unavailable"):
        llm.call(ConversationHistory())
    assert len(connection.requests) == 2
    llm.model = "gemma4:e4b"
    assert llm.call(ConversationHistory()) == "ok"
    assert connection.requests[-1]["format"] == "json"


@pytest.mark.asyncio
async def test_ollama_streaming_json_fallback_preserves_typed_actions_and_closes_requests(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="gemma4:12b-mlx", model_params={"think": False})
    requests, clients = [], []
    content = '{"type":"tool_call","tool":"lookup","args":{"key":"alpha"}}'

    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(501, json={"error": "structured output is unavailable"})
        return httpx.Response(200, content=json.dumps({"message": {"content": content}, "done": True}) + "\n")

    client_type = httpx.AsyncClient

    def client(**kwargs):
        instance = client_type(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    chunks = []

    async def capture(chunk):
        chunks.append(chunk)

    for _ in range(2):
        result = await llm.call_action_stream(
            ConversationHistory(), tools={"lookup": DummyTool()}, chunk_callback=capture
        )
        assert isinstance(result.action, ToolCallAction)
        assert result.action.args == {"key": "alpha"}
        assert not result.native

    assert chunks == [content, content]
    assert len(requests) == 3 and requests[0]["format"] == "json"
    assert all("format" not in request for request in requests[1:])
    assert all(request["think"] is False and "think" not in request["options"] for request in requests)
    assert all(instance.is_closed for instance in clients)


@pytest.mark.asyncio
async def test_ollama_format_error_inside_accepted_stream_is_not_retried(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434")
    requests, clients = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            content='{"message":{"content":"partial"}}\n{"error":"structured output is unavailable"}\n',
        )

    client_type = httpx.AsyncClient

    def client(**kwargs):
        instance = client_type(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    chunks = []
    with pytest.raises(RuntimeError, match="structured output is unavailable"):
        async for chunk in llm.call_stream(ConversationHistory()):
            chunks.append(chunk)

    assert chunks == ["partial"] and len(requests) == 1
    assert all(instance.is_closed for instance in clients)
