"""Malformed model proposals cannot bypass correction or replay observations."""

import json
from types import SimpleNamespace

import httpx2
import pytest

from protolink import Agent, RunBudget, RunContext, RunHandle, Task
from protolink.core.budget import BudgetEnforcer, BudgetExceededError
from protolink.llms.actions import FinalAction
from protolink.llms.api.anthropic_client import AnthropicLLM
from protolink.llms.api.deepseek_client import DeepSeekLLM
from protolink.llms.api.gemini_client import GeminiLLM
from protolink.llms.api.grok_client import GrokLLM
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.errors import InferParseError
from protolink.llms.local.llamacpp_client import LlamaCPPLocalLLM
from protolink.llms.parsing import ActionParseError, normalize_native_text, parse_infer_response
from protolink.llms.server.llamacpp_client import LlamaCPPServerLLM
from protolink.llms.server.ollama_client import OllamaLLM
from protolink.llms.server.openai_compatible_client import OpenAICompatibleLLM

WRAPPER = {"tool_call": {"name": "explorer", "arguments": {"query": "docs"}}}
WRAPPER_TEXT = json.dumps(WRAPPER)
BACKENDS = [
    OllamaLLM,
    OpenAICompatibleLLM,
    LlamaCPPServerLLM,
    LlamaCPPLocalLLM,
    OpenAILLM,
    AnthropicLLM,
    GeminiLLM,
    DeepSeekLLM,
    GrokLLM,
]


def _normalize(backend, text):
    """Exercise real synchronous adapters without initializing provider SDKs."""
    llm = backend.__new__(backend)
    if backend is OpenAILLM:
        response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message", role="assistant", content=[SimpleNamespace(type="output_text", text=text)]
                )
            ]
        )
        return llm._action_from_response(response)
    if backend is AnthropicLLM:
        return llm._action_from_response(SimpleNamespace(content=[SimpleNamespace(type="text", text=text)]))
    if backend is GeminiLLM:
        return llm._action_from_response(SimpleNamespace(text=text))
    if backend is DeepSeekLLM:
        return llm._action_from_chat_response(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
        )
    payload = {"message": {"content": text}} if backend is OllamaLLM else {"choices": [{"message": {"content": text}}]}
    return llm._action_from_chat_result(payload)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("text", [WRAPPER_TEXT, '{"type":"tool_call","args":{}}'])
def test_native_adapters_propagate_recognizable_bad_actions(backend, text):
    with pytest.raises(ActionParseError) as caught:
        _normalize(backend, text)
    assert caught.value.raw_response == text


@pytest.mark.parametrize("wrapper", ["tool_call", "tool_calls", "function_call", "function_calls", "agent_call"])
def test_wrappers_are_not_repaired_into_final_answers(wrapper):
    payload = {wrapper: WRAPPER["tool_call"]}
    with pytest.raises(ActionParseError):
        parse_infer_response(json.dumps(payload))


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize(
    "text",
    [
        "A plain answer.",
        'Example only:\n```json\n{"tool_call":{"name":"explorer"}}\n```',
        '```python\nrequest = {"tool_call": {"name": "explorer"}}\n```',
        '{"statement":"Answer","evidence_ids":["E1"]}',
        '{"example":{"tool_call":{"name":"explorer"}}}',
        '[{"name":"A"},{"name":"B"}]',
        '{"type":"object","properties":{"name":{"type":"string"}}}',
        '{"type":"article","content":"Application data"}',
    ],
)
def test_native_adapters_preserve_answers_and_code_examples(backend, text):
    result = _normalize(backend, text)
    assert isinstance(result.action, FinalAction)
    assert result.action.content == text


@pytest.mark.parametrize("parse", [parse_infer_response, lambda raw: normalize_native_text(raw).action])
def test_explicit_final_content_can_contain_an_action_example(parse):
    action = parse(json.dumps({"type": "final", "content": WRAPPER}))
    assert isinstance(action, FinalAction)
    assert json.loads(action.content) == WRAPPER


@pytest.mark.parametrize(
    "text",
    [
        "```json\n" + WRAPPER_TEXT + "\n```",
        "<think>Choose a tool.</think>\n" + WRAPPER_TEXT,
        '{"tool_call":',
        '{"type":"tool_call",',
        '{"type":"tool_call","tool":"explorer","args":{}}\nExtra text',
    ],
)
def test_native_standalone_bad_actions_are_not_plain_text(text):
    with pytest.raises(ActionParseError):
        normalize_native_text(text)


def _scripted_ollama(monkeypatch, mode, texts, *, streaming=False):
    """Script actual Ollama acquisition in either protocol and transport mode."""
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    llm = OllamaLLM(base_url="http://localhost:11434", model="test", tool_calling=mode)
    responses = iter(texts)
    requests = []

    def response(payload):
        requests.append(json.loads(json.dumps(payload)))
        text = next(responses)
        if mode == "native" and text == "TOOL":
            return {"message": {"tool_calls": [{"function": {"name": "explorer", "arguments": {"query": "docs"}}}]}}
        content = '{"type":"tool_call","tool":"explorer","args":{"query":"docs"}}' if text == "TOOL" else text
        return {"message": {"content": content}, "prompt_eval_count": 12, "eval_count": 7}

    monkeypatch.setattr(llm, "_post_chat", response)
    if streaming:
        client_type = httpx2.AsyncClient
        transport = httpx2.MockTransport(
            lambda request: httpx2.Response(200, content=json.dumps(response(json.loads(request.content))) + "\n")
        )
        monkeypatch.setattr(httpx2, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs))
    return llm, requests


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_correction_preserves_results_and_does_not_replay_tools(monkeypatch, mode, streaming):
    llm, requests = _scripted_ollama(
        monkeypatch,
        mode,
        [
            "TOOL",
            WRAPPER_TEXT,
            "TOOL",
            '{"type":"final","content":"Done."}',
        ],
        streaming=streaming,
    )
    calls = []

    def explorer(query: str) -> str:
        """Return a distinctive observation and record actual execution."""
        calls.append(query)
        return "completed-observation-E1"

    agent = Agent(name="boundary", llm=llm, tools=[explorer], verbosity=0)
    context = RunContext(run_id="same-run", budget=RunBudget(max_llm_calls=4, max_tool_calls=1, max_steps=4))
    if streaming:
        handle = RunHandle.start(agent, Task.create_infer("Find docs.", context=context))
        events = [event async for event in handle.events()]
        result = await handle.result()
        assert result.status == "completed", result.error
        assert result.output == "Done."
        assert sum(event.payload.get("llm_event_type") == "llm_parse_error" for event in events) == 1
    else:
        assert await agent.invoke("Find docs.", context=context) == "Done."
    assert calls == ["docs"]
    assert len(requests) == 4
    assert "completed-observation-E1" in json.dumps(requests[2]["messages"])
    assert "not a dispatchable ProtoLink action" in json.dumps(requests[2]["messages"])
    assert all(("tools" in request) == (mode == "native") for request in requests)


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.asyncio
async def test_correction_spends_the_current_call_budget(monkeypatch, mode):
    llm, requests = _scripted_ollama(monkeypatch, mode, [WRAPPER_TEXT, '{"type":"final","content":"unused"}'])
    context = RunContext(run_id="budget", budget=RunBudget(max_llm_calls=1))
    enforcer = BudgetEnforcer(context)
    with pytest.raises(BudgetExceededError):
        await llm.infer(query="Find docs", tools={}, run_context=context, budget_enforcer=enforcer)
    assert len(requests) == 1
    assert enforcer.usage.llm_calls == 1


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_invalid_response_output_tokens_spend_the_current_budget(monkeypatch, mode, streaming):
    llm, requests = _scripted_ollama(monkeypatch, mode, [WRAPPER_TEXT], streaming=streaming)
    context = RunContext(run_id="token-budget", budget=RunBudget(max_output_tokens=1))
    with pytest.raises(BudgetExceededError):
        await llm.infer(query="Find docs", tools={}, streaming=streaming, run_context=context)
    assert len(requests) == 1


@pytest.mark.parametrize("mode", ["json", "native"])
@pytest.mark.asyncio
async def test_wrapper_correction_uses_existing_parse_limit(monkeypatch, mode):
    llm, requests = _scripted_ollama(monkeypatch, mode, [WRAPPER_TEXT] * 3)
    with pytest.raises(InferParseError) as caught:
        await llm.infer(query="Find docs", tools={})
    assert len(requests) == 3
    assert caught.value.attempts == 3
    assert caught.value.raw_response == WRAPPER_TEXT
