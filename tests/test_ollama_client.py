import json
from typing import ClassVar

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


class _FakeOllamaStreamResponse:
    status = 200

    def __iter__(self):
        yield json.dumps(
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "lookup", "arguments": {"key": "alpha"}}},
                    ]
                }
            }
        ).encode()

    def read(self):
        return b""


class _FakeOllamaStreamConnection:
    def __init__(self):
        self.body = None

    def request(self, *args, **kwargs):
        self.body = args[2] if len(args) >= 3 else kwargs["body"]

    def getresponse(self):
        return _FakeOllamaStreamResponse()

    def close(self):
        return None


class DummyTool:
    name = "lookup"
    description = "Look up a value."
    input_schema: ClassVar[dict] = {"key": {"type": "string", "required": True}}
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


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
    fake_connection = _FakeOllamaStreamConnection()
    llm._client = fake_connection

    history = ConversationHistory()
    history.add_user("Find alpha")

    result = await llm.call_action_stream(history, tools={"lookup": DummyTool()})
    payload = json.loads(fake_connection.body)

    assert "format" not in payload
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert result.metadata["streaming"] is True
