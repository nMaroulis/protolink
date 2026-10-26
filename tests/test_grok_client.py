import json
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest

from protolink.llms.actions import FinalAction, ToolCallAction
from protolink.llms.api.grok_client import GrokLLM
from protolink.llms.history import ConversationHistory
from protolink.llms.tool_calling import AGENT_INFER_TOOL_NAME, AGENT_TOOL_CALL_TOOL_NAME


class DummyTool:
    name = "lookup"
    description = "Look up a value."
    input_schema: ClassVar[dict] = {"key": {"type": "string", "required": True}}
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


class _FakeAsyncResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self.lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx2.Request("POST", "https://api.x.ai/v1/chat/completions")
            response = httpx2.Response(self.status_code, request=request)
            raise httpx2.HTTPStatusError("HTTP error", request=request, response=response)

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FakeAsyncStreamContext:
    def __init__(self, response: _FakeAsyncResponse):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_grok_llm(*, supports_tool_calling: bool = True, api_key: str = "xai-test-key") -> GrokLLM:
    llm = GrokLLM.__new__(GrokLLM)
    llm.model = "grok-4-latest"
    llm.base_url = "https://api.x.ai/v1"
    llm._api_key = api_key
    llm._model_params = {"temperature": 1.0}
    llm.history = ConversationHistory()
    llm.system_prompt = ""
    llm._supports_tool_calling = supports_tool_calling
    llm._client = MagicMock()
    llm._async_client = MagicMock()
    return llm


def test_grok_call_returns_expected_text():
    llm = _make_grok_llm()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello from Grok!",
                }
            }
        ]
    }
    llm._client.post.return_value = mock_response

    history = ConversationHistory()
    history.add_system("You are a helpful assistant.")
    history.add_user("Say hello.")

    result = llm.call(history)

    assert result == "Hello from Grok!"
    mock_response.raise_for_status.assert_called_once()
    llm._client.post.assert_called_once_with(
        "https://api.x.ai/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer xai-test-key",
        },
        json={
            "model": "grok-4-latest",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say hello."},
            ],
            "stream": False,
            "temperature": 1.0,
        },
    )


def test_grok_call_action_builds_tool_call_action():
    llm = _make_grok_llm()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_grok_1",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"key": "alpha"}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    llm._client.post.return_value = mock_response

    history = ConversationHistory()
    history.add_user("Find alpha")
    result = llm.call_action(
        history,
        tools={"lookup": DummyTool()},
        agent_callback_available=False,
    )

    mock_response.raise_for_status.assert_called_once()
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert result.native is True
    assert result.metadata["provider"] == "grok"


def test_grok_call_action_builds_final_action_when_no_tool_call():
    llm = _make_grok_llm()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Here is the final answer.",
                    "tool_calls": None,
                }
            }
        ]
    }
    llm._client.post.return_value = mock_response

    history = ConversationHistory()
    history.add_user("Answer question")
    result = llm.call_action(history, tools={"lookup": DummyTool()})

    assert isinstance(result.action, FinalAction)
    assert result.action.content == "Here is the final answer."
    assert result.native is True
    assert result.metadata["provider"] == "grok"


def test_grok_call_action_raises_on_empty_content_and_no_tool_calls():
    llm = _make_grok_llm()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "   ",
                    "tool_calls": [],
                }
            }
        ]
    }
    llm._client.post.return_value = mock_response

    history = ConversationHistory()
    history.add_user("Empty response")

    with pytest.raises(ValueError, match="Grok response did not contain content or tool_calls"):
        llm.call_action(history, tools={"lookup": DummyTool()})


@pytest.mark.asyncio
async def test_grok_call_stream_yields_expected_chunks():
    llm = _make_grok_llm()

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        "",  # Empty line
        'data: {"choices": [{"delta": {"content": " "}}]}',
        "data: invalid json payload",  # Malformed JSON should be skipped
        'data: {"choices": [{"delta": {"content": "from Grok!"}}]}',
        "data: [DONE]",
        'data: {"choices": [{"delta": {"content": "should not be reached"}}]}',
    ]
    fake_response = _FakeAsyncResponse(sse_lines)
    llm._async_client.stream.return_value = _FakeAsyncStreamContext(fake_response)

    history = ConversationHistory()
    history.add_user("Stream test")

    chunks = [chunk async for chunk in llm.call_stream(history)]

    assert chunks == ["Hello", " ", "from Grok!"]
    llm._async_client.stream.assert_called_once_with(
        "POST",
        "https://api.x.ai/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer xai-test-key",
        },
        json={
            "model": "grok-4-latest",
            "messages": [{"role": "user", "content": "Stream test"}],
            "stream": True,
            "temperature": 1.0,
        },
    )


def test_grok_call_raises_on_http_error():
    llm = _make_grok_llm()

    mock_response = MagicMock()
    request = httpx2.Request("POST", "https://api.x.ai/v1/chat/completions")
    response = httpx2.Response(401, request=request)
    mock_response.raise_for_status.side_effect = httpx2.HTTPStatusError(
        "Unauthorized", request=request, response=response
    )
    llm._client.post.return_value = mock_response

    history = ConversationHistory()
    history.add_user("Test error")

    with pytest.raises(httpx2.HTTPStatusError, match="Unauthorized"):
        llm.call(history)


@pytest.mark.asyncio
async def test_grok_call_stream_raises_on_http_error():
    llm = _make_grok_llm()

    fake_response = _FakeAsyncResponse([], status_code=500)
    llm._async_client.stream.return_value = _FakeAsyncStreamContext(fake_response)

    history = ConversationHistory()
    history.add_user("Test stream error")

    with pytest.raises(httpx2.HTTPStatusError, match="HTTP error"):
        async for _ in llm.call_stream(history):
            pass


def test_grok_call_action_respects_agent_tool_exclusion():
    llm = _make_grok_llm()

    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "Done", "tool_calls": None}}]}
    llm._client.post.return_value = mock_response

    history = ConversationHistory()
    history.add_user("Tool exclusion test")

    # When agent_callback_available is False
    llm.call_action(
        history,
        tools={"lookup": DummyTool()},
        agent_callback_available=False,
    )
    kwargs = llm._client.post.call_args.kwargs
    payload = kwargs["json"]
    tool_names = {t["function"]["name"] for t in payload["tools"]}
    assert tool_names == {"lookup"}
    assert AGENT_INFER_TOOL_NAME not in tool_names
    assert AGENT_TOOL_CALL_TOOL_NAME not in tool_names

    # When agent_callback_available is True and agent_cards are provided
    llm.call_action(
        history,
        tools={"lookup": DummyTool()},
        agent_callback_available=True,
        agent_cards=[{"name": "worker_agent"}],
    )
    payload_with_agents = llm._client.post.call_args.kwargs["json"]
    tool_names = {t["function"]["name"] for t in payload_with_agents["tools"]}
    assert "lookup" in tool_names
    assert AGENT_INFER_TOOL_NAME in tool_names
    assert AGENT_TOOL_CALL_TOOL_NAME in tool_names


@pytest.mark.asyncio
async def test_grok_call_action_stream_collects_tool_call_deltas():
    llm = _make_grok_llm()

    delta1 = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_stream_1",
                            "function": {"name": "lookup", "arguments": '{"key":'},
                        }
                    ]
                }
            }
        ]
    }
    delta2 = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {"arguments": '"alpha"}'},
                        }
                    ]
                }
            }
        ]
    }
    sse_lines = [
        f"data: {json.dumps(delta1)}",
        f"data: {json.dumps(delta2)}",
        "data: [DONE]",
    ]
    fake_response = _FakeAsyncResponse(sse_lines)
    llm._async_client.stream.return_value = _FakeAsyncStreamContext(fake_response)

    history = ConversationHistory()
    history.add_user("Find alpha streamed")
    result = await llm.call_action_stream(
        history,
        tools={"lookup": DummyTool()},
        agent_callback_available=False,
    )

    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert result.native is True
    assert result.metadata["streaming"] is True
    assert result.metadata["provider"] == "grok"


@pytest.mark.asyncio
async def test_grok_call_action_stream_text_deltas_with_callback():
    llm = _make_grok_llm()

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " world!"}}]}',
        "data: [DONE]",
    ]
    fake_response = _FakeAsyncResponse(sse_lines)
    llm._async_client.stream.return_value = _FakeAsyncStreamContext(fake_response)

    callback = AsyncMock()
    history = ConversationHistory()
    history.add_user("Stream text")

    result = await llm.call_action_stream(
        history,
        tools={"lookup": DummyTool()},
        chunk_callback=callback,
    )

    assert isinstance(result.action, FinalAction)
    assert result.action.content == "Hello world!"
    assert result.native is True
    assert callback.await_count == 2
    callback.assert_any_await("Hello")
    callback.assert_any_await(" world!")


def test_grok_validate_connection():
    llm = _make_grok_llm()

    # Success case
    mock_response = MagicMock()
    llm._client.get.return_value = mock_response
    assert llm.validate_connection() is True
    llm._client.get.assert_called_once_with(
        "https://api.x.ai/v1/models",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer xai-test-key",
        },
    )

    # Failure case
    llm._client.get.side_effect = httpx2.ConnectError("Connection refused")
    assert llm.validate_connection() is False


def test_grok_tool_calling_properties():
    llm_with_tools = _make_grok_llm(supports_tool_calling=True)
    assert llm_with_tools.uses_native_action_prompt is True
    assert llm_with_tools.supports_native_action_stream is True

    llm_without_tools = _make_grok_llm(supports_tool_calling=False)
    assert llm_without_tools.uses_native_action_prompt is False
    assert llm_without_tools.supports_native_action_stream is False
