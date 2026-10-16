"""Offline contract tests using the optional provider SDKs' real HTTP parsers."""

import builtins
import importlib
import json
import socket
from contextlib import ExitStack
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

from protolink.llms import _deps
from protolink.llms.actions import FinalAction, ToolCallAction
from protolink.llms.api.anthropic_client import AnthropicLLM
from protolink.llms.api.deepseek_client import DeepSeekLLM
from protolink.llms.api.gemini_client import GeminiLLM
from protolink.llms.api.hugging_face_client import HuggingFaceLLM
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.history import ConversationHistory


class LookupTool:
    name = "lookup"
    description = "Look up a value."
    input_schema: ClassVar[dict] = {"key": {"type": "string", "required": True}}
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


TOOLS = {"lookup": LookupTool()}
HISTORY = ConversationHistory(system_prompt="Follow the task instructions.")
HISTORY.add_user("Find alpha.")
ANSWER = "Offline answer."
ARGS = '{"key":"alpha"}'


class ProviderEndpoint:
    def __init__(self, provider, http):
        self.provider = provider
        self.http = http
        self.requests = []
        self.mode = "text"

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request, body))
        assert request.method == "POST"
        if self.mode == "http_error":
            return self.http.Response(
                400, json={"error": {"message": "Invalid provider request", "type": "invalid_request_error"}}
            )
        if self.provider == "openai":
            payload, events = self.openai()
        elif self.provider == "anthropic":
            payload, events = self.anthropic()
        elif self.provider in {"deepseek", "huggingface"}:
            payload, events = self.chat()
        else:
            payload, events = self.gemini()
        if body.get("stream") or ":streamGenerateContent" in request.url.path:
            data = "".join(
                (f"event: {event['type']}\n" if "type" in event else "") + f"data: {json.dumps(event)}\n\n"
                for event in events
            )
            return self.http.Response(200, headers={"content-type": "text/event-stream"}, content=data)
        return self.http.Response(200, json=payload)

    def openai(self):
        output = [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": ANSWER, "annotations": []}],
            }
        ]
        events = [
            {
                "type": "response.output_text.delta",
                "delta": ANSWER,
                "sequence_number": 0,
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_1",
                "logprobs": [],
            }
        ]
        if self.mode in {"tool", "parallel", "alternatives"}:
            output = []
            events = []
            for index in range(2 if self.mode == "parallel" else 1):
                item = {
                    "type": "function_call",
                    "id": f"fc_{index}",
                    "call_id": f"call_{index}",
                    "name": "lookup",
                    "arguments": ARGS,
                    "status": "completed",
                }
                output.append(item)
                events += [
                    {
                        "type": "response.output_item.added",
                        "output_index": index,
                        "sequence_number": index * 4,
                        "item": {**item, "arguments": ""},
                    },
                    {
                        "type": "response.function_call_arguments.delta",
                        "output_index": index,
                        "sequence_number": index * 4 + 1,
                        "item_id": item["id"],
                        "delta": ARGS[:7],
                    },
                    {
                        "type": "response.function_call_arguments.delta",
                        "output_index": index,
                        "sequence_number": index * 4 + 2,
                        "item_id": item["id"],
                        "delta": ARGS[7:],
                    },
                    {
                        "type": "response.output_item.done",
                        "output_index": index,
                        "sequence_number": index * 4 + 3,
                        "item": item,
                    },
                ]
        response = {
            "id": "resp_1",
            "object": "response",
            "created_at": 1,
            "model": "offline",
            "status": "completed",
            "output": output,
            "error": None,
            "incomplete_details": None,
            "parallel_tool_calls": False,
            "tools": [],
            "tool_choice": "auto",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
        if self.mode == "stream_error":
            events.append(
                {
                    "type": "error",
                    "code": "server_error",
                    "message": "Generation failed",
                    "param": None,
                    "sequence_number": 1,
                }
            )
        elif self.mode == "stream_failed":
            events.append(
                {
                    "type": "response.failed",
                    "sequence_number": 1,
                    "response": {
                        **response,
                        "status": "failed",
                        "error": {"code": "server_error", "message": "Generation failed"},
                    },
                }
            )
        elif self.mode == "stream_incomplete":
            events.append(
                {
                    "type": "response.incomplete",
                    "sequence_number": 1,
                    "response": {
                        **response,
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    },
                }
            )
        elif self.mode == "response_failed":
            response.update(status="failed", error={"code": "server_error", "message": "Generation failed"})
        elif self.mode == "response_incomplete":
            response.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        return response, events

    def anthropic(self):
        content = {"type": "text", "text": ANSWER}
        delta = {"type": "text_delta", "text": ANSWER}
        if self.mode in {"tool", "parallel"}:
            content = {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"key": "alpha"}}
            delta = {"type": "input_json_delta", "partial_json": ARGS}
        response = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "offline",
            "content": [content],
            "stop_reason": "tool_use" if self.mode == "tool" else "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
        events = [
            {"type": "message_start", "message": {**response, "content": [], "stop_reason": None}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {**content, "input": {}} if self.mode == "tool" else {**content, "text": ""},
            },
            {"type": "content_block_delta", "index": 0, "delta": delta},
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": response["stop_reason"], "stop_sequence": None},
                "usage": {"output_tokens": 2},
            },
            {"type": "message_stop"},
        ]
        return response, events

    def chat(self):
        answer = json.dumps({"type": "final", "content": ANSWER}) if self.mode == "json" else ANSWER
        message = {"role": "assistant", "content": answer}
        deltas = [{"content": answer}]
        if self.mode in {"tool", "parallel"}:
            tool_calls = [
                {"id": f"call_{i}", "type": "function", "function": {"name": "lookup", "arguments": ARGS}}
                for i in range(2 if self.mode == "parallel" else 1)
            ]
            message.update(content=None, tool_calls=tool_calls)
            deltas = []
            for index, tool in enumerate(tool_calls):
                deltas += [
                    {"tool_calls": [{**tool, "index": index, "function": {"name": "lookup", "arguments": ARGS[:7]}}]},
                    {"tool_calls": [{"index": index, "function": {"arguments": ARGS[7:]}}]},
                ]
        response = {
            "id": "chat_1",
            "object": "chat.completion",
            "created": 1,
            "model": "offline",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
        events = [
            {
                "id": "chat_1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "offline",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            for delta in deltas
        ]
        return response, events

    def gemini(self):
        parts = [{"text": ANSWER}]
        if self.mode in {"tool", "parallel", "alternatives"}:
            parts = [
                {"functionCall": {"name": "lookup", "args": {"key": "alpha"}}}
                for _ in range(2 if self.mode == "parallel" else 1)
            ]
        response = {
            "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2, "totalTokenCount": 3},
        }
        if self.mode == "alternatives":
            response["candidates"].append(
                {
                    "index": 1,
                    "content": {"role": "model", "parts": [{"functionCall": {"name": "alternative_tool", "args": {}}}]},
                    "finishReason": "STOP",
                }
            )
        return response, [response]


@pytest.fixture(autouse=True)
def forbid_provider_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Provider compatibility tests must never open network connections")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)


@pytest.fixture(params=["openai", "anthropic", "deepseek", "gemini", "huggingface"])
def provider_sdk(request, monkeypatch):
    provider = request.param
    modules = {
        "openai": "openai",
        "anthropic": "anthropic",
        "deepseek": "openai",
        "gemini": "google.genai",
        "huggingface": "huggingface_hub",
    }
    sdk = pytest.importorskip(modules[provider])
    if provider == "huggingface":
        http = pytest.importorskip("httpx2" if int(sdk.__version__.split(".")[0]) >= 2 else "httpx")
    elif provider == "gemini":
        import httpx as http
    else:
        package = "httpx" if sdk.__version__.split(".")[0] in {"0", "2"} else "httpx2"
        http = pytest.importorskip(package)
    endpoint = ProviderEndpoint(provider, http)
    client = http.Client(transport=http.MockTransport(endpoint))
    adapter = {
        "openai": OpenAILLM,
        "anthropic": AnthropicLLM,
        "deepseek": DeepSeekLLM,
        "gemini": GeminiLLM,
        "huggingface": HuggingFaceLLM,
    }[provider]
    monkeypatch.setattr(adapter, "validate_connection", lambda self: True)
    kwargs = {"api_key": "hf_offline_test", "model": "offline", "base_url": "http://provider.invalid"}
    sdk_class = (
        sdk.Client
        if provider == "gemini"
        else sdk.Anthropic
        if provider == "anthropic"
        else sdk.OpenAI
        if provider in {"openai", "deepseek"}
        else None
    )
    if sdk_class is not None:
        original_init = sdk_class.__init__

        def init(self, **options):
            if provider == "gemini":
                http_options = {**(options.pop("http_options", None) or {}), "httpx_client": client}
                original_init(self, **options, http_options=http_options)
            else:
                original_init(self, **options, http_client=client, max_retries=0)

        monkeypatch.setattr(sdk_class, "__init__", init)
    else:
        http_utils = importlib.import_module("huggingface_hub.utils._http")
        previous_factory = http_utils._GLOBAL_CLIENT_FACTORY
        sdk.set_client_factory(lambda: client)
        kwargs = {"api_key": "hf_offline_test", "model": "http://provider.invalid/v1"}
    with ExitStack() as stack:
        stack.callback(client.close)
        if provider == "huggingface":
            stack.callback(sdk.set_client_factory, previous_factory)
            stack.callback(sdk.close_session)
        llm = adapter(**kwargs)
        if provider != "huggingface":
            stack.callback(llm._client.close)
        yield SimpleNamespace(name=provider, sdk=sdk, llm=llm, endpoint=endpoint)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["call", "call_stream", "call_action", "call_action_stream"])
async def test_real_sdk_text_requests_and_responses(provider_sdk, method):
    provider = provider_sdk
    callback = AsyncMock()
    if provider.name == "huggingface" and method.startswith("call_action"):
        provider.endpoint.mode = "json"
    if method == "call":
        assert provider.llm.call(HISTORY) == ANSWER
    elif method == "call_stream":
        assert "".join([chunk async for chunk in provider.llm.call_stream(HISTORY)]) == ANSWER
    elif method == "call_action":
        result = provider.llm.call_action(HISTORY, tools=TOOLS)
        assert isinstance(result.action, FinalAction)
        assert result.action.content == ANSWER
    else:
        result = await provider.llm.call_action_stream(HISTORY, tools=TOOLS, chunk_callback=callback)
        assert isinstance(result.action, FinalAction)
        assert result.action.content == ANSWER
        callback.assert_awaited_once_with(
            json.dumps({"type": "final", "content": ANSWER}) if provider.name == "huggingface" else ANSWER
        )
    assert len(provider.endpoint.requests) == 1
    request, body = provider.endpoint.requests[0]
    assert request.url.host == "provider.invalid"
    if provider.name == "anthropic":
        assert body["system"] == "Follow the task instructions."
        assert body["messages"] == [{"role": "user", "content": "Find alpha."}]
        assert not {"temperature", "top_p", "top_k"}.intersection(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_sdk", ["openai", "anthropic", "deepseek", "gemini"], indirect=True)
@pytest.mark.parametrize("stream", [False, True])
async def test_real_sdk_native_tool_requests_and_responses(provider_sdk, stream):
    provider = provider_sdk
    provider.endpoint.mode = "tool"
    callback = AsyncMock()
    if stream:
        result = await provider.llm.call_action_stream(HISTORY, tools=TOOLS, chunk_callback=callback)
        callback.assert_not_awaited()
    else:
        result = provider.llm.call_action(HISTORY, tools=TOOLS)
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}
    assert len(provider.endpoint.requests) == 1
    if not stream:
        assert result.metadata["usage"]["input_tokens"] == 1
        assert result.metadata["usage"]["output_tokens"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_sdk", ["gemini"], indirect=True)
@pytest.mark.parametrize("stream", [False, True])
async def test_real_gemini_alternative_candidates_are_not_parallel_calls(provider_sdk, stream):
    provider_sdk.endpoint.mode = "alternatives"
    if stream:
        result = await provider_sdk.llm.call_action_stream(HISTORY, tools=TOOLS)
    else:
        result = provider_sdk.llm.call_action(HISTORY, tools=TOOLS)
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "lookup"
    assert result.action.args == {"key": "alpha"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["call", "call_stream", "call_action", "call_action_stream"])
async def test_real_sdk_http_errors_reach_callers(provider_sdk, method):
    provider = provider_sdk
    provider.endpoint.mode = "http_error"
    if provider.name == "gemini":
        from google.genai.errors import ClientError

        expected = ClientError
    elif provider.name == "huggingface":
        from huggingface_hub.errors import HfHubHTTPError

        expected = HfHubHTTPError
    else:
        expected = provider.sdk.BadRequestError
    with pytest.raises(expected):
        if method == "call":
            provider.llm.call(HISTORY)
        elif method == "call_stream":
            _ = [chunk async for chunk in provider.llm.call_stream(HISTORY)]
        elif method == "call_action":
            provider.llm.call_action(HISTORY, tools=TOOLS)
        else:
            await provider.llm.call_action_stream(HISTORY, tools=TOOLS)
    assert len(provider.endpoint.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_sdk", ["openai", "deepseek", "gemini"], indirect=True)
@pytest.mark.parametrize("stream", [False, True])
async def test_real_sdk_parallel_tool_calls_are_not_silently_discarded(provider_sdk, stream):
    provider = provider_sdk
    provider.endpoint.mode = "parallel"
    with pytest.raises(ValueError, match=r"[Mm]ultiple parallel tool calls"):
        if stream:
            await provider.llm.call_action_stream(HISTORY, tools=TOOLS)
        else:
            provider.llm.call_action(HISTORY, tools=TOOLS)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_sdk", ["openai"], indirect=True)
@pytest.mark.parametrize("mode", ["stream_error", "stream_failed", "stream_incomplete"])
@pytest.mark.parametrize("action", [False, True])
async def test_real_openai_stream_failures_do_not_return_partial_success(provider_sdk, mode, action):
    provider = provider_sdk
    provider.endpoint.mode = mode
    with pytest.raises(RuntimeError, match="max_output_tokens" if mode == "stream_incomplete" else "Generation failed"):
        if action:
            await provider.llm.call_action_stream(HISTORY, tools=TOOLS)
        else:
            _ = [chunk async for chunk in provider.llm.call_stream(HISTORY)]


@pytest.mark.parametrize("provider_sdk", ["openai"], indirect=True)
@pytest.mark.parametrize("mode", ["response_failed", "response_incomplete"])
@pytest.mark.parametrize("action", [False, True])
def test_real_openai_failed_responses_do_not_return_partial_success(provider_sdk, mode, action):
    provider_sdk.endpoint.mode = mode
    with pytest.raises(RuntimeError, match="max_output_tokens" if mode.endswith("incomplete") else "Generation failed"):
        if action:
            provider_sdk.llm.call_action(HISTORY, tools=TOOLS)
        else:
            provider_sdk.llm.call(HISTORY)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_sdk", ["anthropic"], indirect=True)
@pytest.mark.parametrize("method", ["call", "call_stream", "call_action", "call_action_stream"])
@pytest.mark.parametrize("extra_body", [None, {"temperature": 0.4, "metadata": {"user_id": "offline"}}])
async def test_real_anthropic_preserves_explicit_sampling_and_body_precedence(provider_sdk, method, extra_body):
    llm = provider_sdk.llm
    llm._model_params.update(temperature=0.0, top_p=0.8, top_k=4, extra_body=extra_body)
    original = json.loads(json.dumps(llm._model_params))
    if method == "call":
        llm.call(HISTORY)
    elif method == "call_stream":
        _ = [chunk async for chunk in llm.call_stream(HISTORY)]
    elif method == "call_action":
        llm.call_action(HISTORY, tools=TOOLS)
    else:
        await llm.call_action_stream(HISTORY, tools=TOOLS)
    body = provider_sdk.endpoint.requests[0][1]
    assert body["temperature"] == (0.4 if extra_body else 0.0)
    assert body["top_p"] == 0.8
    assert body["top_k"] == 4
    if extra_body:
        assert body["metadata"] == {"user_id": "offline"}
    assert llm._model_params == original


@pytest.mark.parametrize(
    ("loader", "package", "extra"),
    [
        (_deps.require_openai, "openai", "openai"),
        (_deps.require_anthropic, "anthropic", "anthropic"),
        (_deps.require_gemini, "google.genai", "gemini"),
        (_deps.require_hugging_face, "huggingface_hub", "huggingface"),
    ],
)
def test_missing_provider_sdk_explains_optional_extra(monkeypatch, loader, package, extra):
    original_import = builtins.__import__

    def import_without_provider(name, *args, **kwargs):
        if name == package or name.startswith(package + "."):
            raise ModuleNotFoundError(f"No module named {package!r}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_provider)
    with pytest.raises(ImportError, match=rf"protolink\[{extra}\]"):
        loader()
