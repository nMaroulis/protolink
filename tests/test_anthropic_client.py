from copy import deepcopy
from types import SimpleNamespace
from typing import ClassVar, cast
from unittest.mock import MagicMock

import pytest

from protolink.llms.actions import ToolCallAction
from protolink.llms.api.anthropic_client import AnthropicLLM
from protolink.llms.history import ConversationHistory
from protolink.tools.base import BaseTool


class DummyTool:
    name = "search"
    description = "Search for information."
    input_schema: ClassVar[dict] = {"query": {"type": "string", "required": True}}
    output_schema: ClassVar[dict] = {"type": "string"}
    tags: ClassVar[list] = []


def _make_anthropic_llm() -> AnthropicLLM:
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-test"
    llm._model_params = {"max_tokens": 128}
    llm.history = ConversationHistory()
    llm.system_prompt = ""
    llm._client = MagicMock()
    return llm


def _tools() -> dict[str, BaseTool]:
    return {"search": cast(BaseTool, DummyTool())}


def test_anthropic_llm_native_tool_call_action():
    llm = _make_anthropic_llm()

    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "search"
    mock_block.input = {"query": "protolink"}
    mock_block.id = "toolu_123"
    mock_response.content = [mock_block]
    llm._client.messages.create.return_value = mock_response

    history = ConversationHistory()
    history.add_user("Find docs")

    result = llm.call_action(history, tools=_tools(), agent_callback_available=False)

    llm._client.messages.create.assert_called_once()
    kwargs = llm._client.messages.create.call_args.kwargs

    assert kwargs["tools"][0]["name"] == "search"
    assert kwargs["tools"][0]["input_schema"] == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "search"
    assert result.action.args == {"query": "protolink"}
    assert result.native is True
    assert result.metadata["tool_use_id"] == "toolu_123"


def test_anthropic_call_action_derives_system_prompt_from_passed_history():
    llm = _make_anthropic_llm()
    llm.system_prompt = "stale shared prompt"

    mock_response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="search",
                input={"query": "protolink"},
                id="toolu_history",
            )
        ]
    )
    llm._client.messages.create.return_value = mock_response

    history = ConversationHistory(system_prompt="task-local prompt")
    history.add_user("Find docs")
    history.add_system("Correct the previous invalid action.")
    history.add_assistant("I will search.")

    llm.call_action(history, tools=_tools(), agent_callback_available=False)

    kwargs = llm._client.messages.create.call_args.kwargs
    assert kwargs["system"] == "task-local prompt\n\nCorrect the previous invalid action."
    assert kwargs["messages"] == [
        {"role": "user", "content": "Find docs"},
        {"role": "assistant", "content": "I will search."},
    ]


def test_anthropic_call_action_rejects_parallel_tool_uses():
    llm = _make_anthropic_llm()
    llm._client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="search", input={"query": "one"}, id="toolu_1"),
            SimpleNamespace(type="tool_use", name="search", input={"query": "two"}, id="toolu_2"),
        ]
    )

    with pytest.raises(ValueError, match="multiple parallel tool calls"):
        llm.call_action(ConversationHistory(), tools=_tools(), agent_callback_available=False)


def test_anthropic_llm_parse_plain_text():
    llm = _make_anthropic_llm()

    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "Hello world text response"
    mock_response.content = [mock_block]

    parsed = llm._parse_output(mock_response)
    assert parsed == "Hello world text response"


class _FakeAnthropicStream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_anthropic_call_action_stream_collects_tool_use_json_deltas():
    llm = _make_anthropic_llm()
    llm._client.messages.stream.return_value = _FakeAnthropicStream(
        [
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", name="search", id="toolu_stream", input={}),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"query":'),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='"protolink"}'),
            ),
        ]
    )

    history = ConversationHistory()
    history.add_user("Find docs")
    result = await llm.call_action_stream(history, tools=_tools(), agent_callback_available=False)

    kwargs = llm._client.messages.stream.call_args.kwargs
    assert kwargs["tools"][0]["name"] == "search"
    assert isinstance(result.action, ToolCallAction)
    assert result.action.tool == "search"
    assert result.action.args == {"query": "protolink"}
    assert result.native is True
    assert result.metadata["tool_use_id"] == "toolu_stream"
    assert result.metadata["streaming"] is True


@pytest.mark.asyncio
async def test_anthropic_call_action_stream_rejects_parallel_tool_uses():
    llm = _make_anthropic_llm()
    llm._client.messages.stream.return_value = _FakeAnthropicStream(
        [
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", name="search", id="toolu_1", input={}),
            ),
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", name="search", id="toolu_2", input={}),
            ),
        ]
    )

    with pytest.raises(ValueError, match="multiple parallel tool calls"):
        await llm.call_action_stream(ConversationHistory(), tools=_tools(), agent_callback_available=False)


class _SamplingCompatibleMessages:
    """Use the SDK v1 keyword surface and reconstruct its merged JSON body."""

    def __init__(self):
        self.bodies = []

    def create(self, *, model, system, messages, max_tokens, stream, tools=None, extra_body=None):
        self.bodies.append(
            {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, **(extra_body or {})}
        )
        assert stream is False
        if tools:
            content = SimpleNamespace(type="tool_use", name="search", input={"query": "protolink"}, id="tool_1")
        else:
            content = SimpleNamespace(type="text", text="answer")
        return SimpleNamespace(content=[content])

    def stream(self, *, model, system, messages, max_tokens, tools=None, extra_body=None):
        self.bodies.append(
            {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, **(extra_body or {})}
        )
        if tools:
            events = [
                SimpleNamespace(
                    type="content_block_start",
                    content_block=SimpleNamespace(type="tool_use", name="search", input={}, id="tool_1"),
                ),
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="input_json_delta", partial_json='{"query":"protolink"}'),
                ),
            ]
        else:
            events = [
                SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="answer"))
            ]
        return _FakeAnthropicStream(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["call", "call_stream", "call_action", "call_action_stream"])
@pytest.mark.parametrize(
    ("model_params", "sampling_body"),
    [
        ({}, {}),
        (
            {
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 4,
                "extra_body": {"temperature": 0.4, "metadata": {"user_id": "offline"}},
            },
            {"temperature": 0.4, "top_p": 0.8, "top_k": 4},
        ),
        ({"temperature": 0.0, "extra_body": None}, {"temperature": 0.0}),
    ],
)
async def test_anthropic_requests_support_sdk_v1_sampling_parameters(method, model_params, sampling_body):
    llm = _make_anthropic_llm()
    llm._model_params = {**AnthropicLLM.DEFAULT_MODEL_PARAMS, **deepcopy(model_params)}
    original_params = deepcopy(llm._model_params)
    sdk_messages = _SamplingCompatibleMessages()
    llm._client = SimpleNamespace(messages=sdk_messages)
    history = ConversationHistory(system_prompt="task prompt")
    history.add_user("Find docs")

    if method == "call":
        assert llm.call(history) == "answer"
    elif method == "call_stream":
        assert [chunk async for chunk in llm.call_stream(history)] == ["answer"]
    elif method == "call_action":
        result = llm.call_action(history, tools=_tools())
        assert isinstance(result.action, ToolCallAction)
    else:
        result = await llm.call_action_stream(history, tools=_tools())
        assert isinstance(result.action, ToolCallAction)

    assert len(sdk_messages.bodies) == 1
    body = sdk_messages.bodies[0]
    assert {name: body[name] for name in ("temperature", "top_p", "top_k") if name in body} == sampling_body
    assert body["max_tokens"] == 1024
    assert body["system"] == "task prompt"
    if model_params.get("extra_body"):
        assert body["metadata"] == {"user_id": "offline"}
    assert llm._model_params == original_params
