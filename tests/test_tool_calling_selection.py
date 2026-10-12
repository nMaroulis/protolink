"""Automatic selection uses bounded metadata checks and preserves explicit policy."""

import copy
import json
from types import SimpleNamespace

import pytest

from protolink import Agent, CapabilityPolicy, RunInterrupted
from protolink.llms import create_llm
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.base import LLM
from protolink.llms.server.ollama_client import OllamaLLM
from protolink.llms.server.openai_compatible_client import OpenAICompatibleLLM
from protolink.tools import Tool


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    return OllamaLLM(base_url="https://example.invalid/prefix", model="exact:tag-mlx", tool_calling="auto")


@pytest.mark.parametrize(
    "capabilities, expected",
    [
        (["completion", "tools"], "native"),
        (["completion"], "json"),
        ([], "json"),
        (None, "json"),
        ("tools", "json"),
        ([1], "json"),
    ],
)
def test_ollama_discovery_uses_exact_model_authenticated_metadata(monkeypatch, ollama, capabilities, expected):
    requests = []
    closes = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "example.invalid" and timeout == 5

        def request(self, method, path, *, body, headers):
            requests.append((method, path, json.loads(body), headers))

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda: json.dumps({"capabilities": capabilities}).encode())

        def close(self):
            closes.append(True)

    monkeypatch.setattr("protolink.llms.server.ollama_client.http.client.HTTPSConnection", Connection)
    ollama.headers["Authorization"] = "Bearer test"
    assert ollama.resolve_tool_calling() == expected
    assert ollama.uses_native_action_prompt == (expected == "native")
    assert ollama.supports_native_action_stream == (expected == "native")
    assert len(requests) == len(closes) == 1
    assert requests[0][:3] == ("POST", "/prefix/api/show", {"model": "exact:tag-mlx"})
    assert requests[0][3]["Authorization"] == "Bearer test"


@pytest.mark.parametrize("mode, expected", [("native", "native"), ("json", "json")])
def test_explicit_overrides_do_not_discover(monkeypatch, ollama, mode, expected):
    ollama.tool_calling = mode
    monkeypatch.setattr(ollama, "discover_tool_calling", lambda: pytest.fail("Explicit modes must not discover"))
    assert ollama.resolve_tool_calling() == expected


@pytest.mark.parametrize("legacy", [False, True])
def test_omitted_option_preserves_existing_flag(monkeypatch, ollama, legacy):
    ollama.tool_calling = None
    ollama.supports_tool_calling = legacy
    monkeypatch.setattr(ollama, "discover_tool_calling", lambda: pytest.fail("Defaults must not discover"))
    assert ollama.uses_native_action_prompt is legacy


@pytest.mark.parametrize("change", ["model", "base_url", "parameters", "headers"])
def test_configuration_changes_invalidate_cached_evidence(monkeypatch, ollama, change):
    discovery = iter([True, False])
    monkeypatch.setattr(ollama, "discover_tool_calling", lambda: next(discovery))
    assert ollama.resolve_tool_calling() == "native"
    if change == "parameters":
        ollama.model_params["temperature"] = 0.2
    elif change == "headers":
        ollama.headers["Authorization"] = "Bearer changed"
    else:
        setattr(ollama, change, "changed")
    assert ollama.resolve_tool_calling() == "json"


def test_cache_expiry_refresh_and_active_scope(monkeypatch, ollama):
    now = [0.0]
    discoveries = []
    monkeypatch.setattr("protolink.llms.base.monotonic", lambda: now[0])

    def discover():
        discoveries.append(True)
        return len(discoveries) % 2 == 1

    monkeypatch.setattr(ollama, "discover_tool_calling", discover)
    assert ollama.resolve_tool_calling() == "native"
    now[0] = 301.0
    with ollama.use_tool_calling():
        assert ollama.resolve_tool_calling() == "json"
        ollama.refresh_capabilities()
        ollama.tool_calling = "native"
        assert ollama.resolve_tool_calling() == "json"
    ollama.tool_calling = "auto"
    assert ollama.resolve_tool_calling() == "native"
    assert len(discoveries) == 3


def test_failed_discovery_is_cached_conservatively(monkeypatch, ollama):
    calls = []

    def unavailable():
        calls.append(True)
        raise ConnectionError("Unavailable")

    monkeypatch.setattr(ollama, "discover_tool_calling", unavailable)
    assert ollama.resolve_tool_calling() == ollama.resolve_tool_calling() == "json"
    assert len(calls) == 1


def test_unknown_compatible_server_stays_json(monkeypatch):
    monkeypatch.setattr(OpenAICompatibleLLM, "validate_connection", lambda self: True)
    llm = OpenAICompatibleLLM(tool_calling="auto")
    assert llm.resolve_tool_calling() == "json"
    llm.tool_calling = "native"
    assert llm.resolve_tool_calling() == "native"


@pytest.mark.asyncio
async def test_direct_tool_invocation_does_not_discover_model_capabilities(monkeypatch, ollama):
    monkeypatch.setattr(ollama, "discover_tool_calling", lambda: pytest.fail("Tool-only tasks must not discover"))

    def lookup(key: str) -> str:
        """Return a value without involving a language model."""
        return key

    agent = Agent(name="direct-tool", llm=ollama, tools=[lookup], verbosity=0)
    result = await agent.invoke("", part_type="tool_call", tool_name="lookup", tool_args={"key": "docs"})
    assert result.result == "docs"


def test_hosted_adapter_uses_its_declared_native_contract():
    llm = OpenAILLM.__new__(OpenAILLM)
    LLM.__init__(llm, model="test", model_params={}, tool_calling="auto")
    assert llm.resolve_tool_calling() == "native"
    llm.tool_calling = "json"
    assert not llm.uses_native_action_prompt


def test_factory_consumes_runtime_option_and_preserves_serialization():
    llm = create_llm("mock", tool_calling="json")
    assert llm.tool_calling == "json" and "tool_calling" not in llm.model_params
    agent = Agent(name="selection", llm=llm)
    serialized = agent.to_dict()
    assert serialized["llm"]["tool_calling"] == "json"
    restored = Agent.from_dict(serialized)
    assert restored.llm.tool_calling == "json"


@pytest.mark.parametrize("mode", ["bogus", True, 1, {}, []])
def test_invalid_modes_fail_clearly(mode):
    with pytest.raises(ValueError, match="tool_calling must be"):
        create_llm("mock", tool_calling=mode)


def test_native_override_requires_an_implemented_adapter():
    with pytest.raises(ValueError, match="does not implement native"):
        create_llm("mock", tool_calling="native")


def test_copy_does_not_inherit_a_live_mode_or_discovery_cache(monkeypatch, ollama):
    monkeypatch.setattr(ollama, "discover_tool_calling", lambda: True)
    ollama._tool_calling_capability_cache = ("old", 1000, True)
    with ollama.use_tool_calling():
        copied = copy.deepcopy(ollama)
    assert copied._active_tool_calling.get() is None
    assert copied._tool_calling_capability_cache is None


@pytest.mark.asyncio
async def test_durable_auto_selection_survives_resume_without_rediscovery(monkeypatch, tmp_path):
    monkeypatch.setattr(OllamaLLM, "validate_connection", lambda self: True)
    calls = []

    def make(*, restarted=False):
        llm = OllamaLLM(base_url="http://localhost:11434", model="test", tool_calling="auto")

        def discover():
            assert not restarted, "Resumption must retain the checkpoint's native mode"
            return True

        def response(payload):
            assert "tools" in payload
            if not restarted:
                return {"message": {"tool_calls": [{"function": {"name": "lookup", "arguments": {"key": "docs"}}}]}}
            corrected = "not a dispatchable ProtoLink action" in json.dumps(payload["messages"])
            content = '{"type":"final","content":"done"}' if corrected else '{"tool_call":{"name":"lookup"}}'
            return {"message": {"content": content}}

        def lookup(key: str) -> str:
            """Return a completed observation for durable reuse."""
            calls.append(key)
            return "observation-E1"

        monkeypatch.setattr(llm, "discover_tool_calling", discover)
        monkeypatch.setattr(llm, "_post_chat", response)
        return Agent(
            name="durable-selection",
            llm=llm,
            tools=[Tool.from_callable(lookup, capabilities=["docs.read"])],
            policy=CapabilityPolicy({"docs.read": "require_approval"}),
            durability=tmp_path / "selection.db",
            verbosity=0,
        )

    first = make()
    with pytest.raises(RunInterrupted) as caught:
        await first.invoke("Find docs")
    interruption = caught.value
    assert first.durability.get(interruption.run_id).data["tool_calling_mode"] == "native"
    assert not calls
    resumed = make(restarted=True)
    result = await resumed.resume(
        interruption.run_id,
        request_id=interruption.interruption.request_id,
        approved=True,
    )
    assert result == "done"
    assert calls == ["docs"]
    completed = resumed.durability.get(interruption.run_id)
    assert completed.data["usage"]["llm_calls"] == 3
    assert completed.data["usage"]["tool_calls"] == 1
