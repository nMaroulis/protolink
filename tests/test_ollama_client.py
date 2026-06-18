import json
from typing import ClassVar

import pytest

from protolink.llms.actions import ToolCallAction
from protolink.llms.history import ConversationHistory
from protolink.llms.server.ollama_client import OllamaLLM


class _FakeOllamaResponse:
    status = 200

    def read(self):
        return json.dumps({"message": {"content": '{"type":"final","content":"ok"}'}}).encode()


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
