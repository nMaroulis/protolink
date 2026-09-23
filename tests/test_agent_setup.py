"""Simple setup preserves the Agent's execution and transport contracts."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from protolink import ActionDeniedError, Agent, AgentCard, AgentGroup, RunContext, TLSConfig, Tool, create_llm
from protolink.client import AgentClient
from protolink.llms import MockLLM
from protolink.llms.factory import LLMFactory, LLMProvider
from protolink.transport import HTTPTransport, RuntimeTransport


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def test_local_defaults_need_no_transport_or_registry():
    logger = Mock()
    agent = Agent(name="Research / Zürich", logger=logger)
    assert agent.card.name == "Research / Zürich"
    assert agent.card.description == "Agent Research / Zürich"
    assert agent.card.url == "runtime://Research%20%2F%20Z%C3%BCrich"
    assert agent.card.transport == "runtime"
    assert agent.transport is agent.llm is agent.client is agent.server is None
    logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_constructor_tools_keep_validation_policy_and_skills():
    calls = []

    async def write(value: int) -> int:
        """Record a value."""
        calls.append(value)
        return value

    tool = Tool.from_callable(write, capabilities=["files.write"])
    agent = Agent(name="helper", tools=iter([add, tool]), llm="mock", verbosity=0)
    assert calls == []
    assert agent.tools["write"] is tool
    assert {skill.id for skill in agent.card.skills} == {"add", "write"}
    assert await agent.call_tool("add", a="2", b=3) == 5
    with pytest.raises(ActionDeniedError):
        await agent.call_tool_in_context("write", RunContext(permissions={"files.write": "deny"}), value=1)
    assert calls == []
    assert await agent.call_tool("write", value="4") == 4
    assert calls == [4]


def test_model_strings_and_objects_share_existing_execution():
    agent = Agent(name="helper", llm="mock:TestModel", tools=[add], verbosity=0)
    assert agent.llm.model == "TestModel"
    assert agent.card.capabilities.has_llm
    assert agent.sync.invoke("hello") == "Unprocessed generic mock response"
    assert agent.sync.call_tool("add", a=1, b=2) == 3
    llm = MockLLM(default_response="configured")
    agent.llm = llm
    assert agent.llm is llm
    assert agent.sync.invoke("hello") == "configured"
    with pytest.raises(ValueError, match="Unknown"):
        agent.llm = "missing-provider:model"
    assert agent.llm is llm
    agent.llm = "mock"
    assert isinstance(agent.llm, MockLLM)
    agent.llm = None
    assert not agent.card.capabilities.has_llm


@pytest.mark.parametrize(
    ("spec", "provider", "model"),
    [
        ("OLLAMA:qwen3:4b", "ollama", "qwen3:4b"),
        ("huggingface:Org/CaseSensitive", "huggingface", "Org/CaseSensitive"),
        ("llama.cpp-local:/models/My Model.gguf", "llama.cpp-local", "/models/My Model.gguf"),
        ("openai-compatible:Org/Model:latest", "openai-compatible", "Org/Model:latest"),
    ],
)
def test_factory_preserves_model_names(monkeypatch, spec, provider, model):
    monkeypatch.setitem(LLMFactory._clients, provider, MockLLM)
    assert create_llm(spec).model == model
    assert Agent(name="helper", llm=spec, verbosity=0).llm.model == model


@pytest.mark.parametrize("spec", ["", " ", ":model", "mock:", "mock:  ", 42])
def test_invalid_model_strings_fail_clearly(spec):
    with pytest.raises(ValueError, match="provider"):
        create_llm(spec)


def test_factory_still_accepts_enum_and_explicit_model():
    assert create_llm(LLMProvider.MOCK, model="explicit").model == "explicit"
    with pytest.raises(ValueError, match="not both"):
        create_llm("mock:inline", model="explicit")


@pytest.mark.parametrize("transport", ["http", "HTTP", "sse", "json-rpc", "sse-json-rpc", "websocket", "grpc"])
def test_network_alias_requires_url_before_creating_llm(monkeypatch, transport):
    factory = Mock(side_effect=AssertionError("must not initialize provider"))
    monkeypatch.setattr("protolink.llms.create_llm", factory)
    with pytest.raises(ValueError, match="url is required"):
        Agent(name="helper", transport=transport, llm="openai:any-model")
    factory.assert_not_called()


@pytest.mark.parametrize(
    ("transport", "url"),
    [
        ("http", "http://127.0.0.1:8001"),
        ("HTTP", "http://[::1]:8001"),
        ("sse", "http://127.0.0.1:8002"),
        ("json-rpc", "http://127.0.0.1:8003"),
        ("sse-json-rpc", "http://127.0.0.1:8004"),
        ("websocket", "ws://127.0.0.1:8005"),
        ("grpc", "grpc://127.0.0.1:8006"),
        ("runtime", "runtime://helper"),
    ],
)
def test_network_alias_uses_the_supplied_endpoint(transport, url):
    agent = Agent(name="helper", url=url, transport=transport, verbosity=0)
    assert agent.card.url == agent.transport.url == url
    assert agent.card.transport == agent.transport.transport_type


@pytest.mark.parametrize(
    ("transport", "url"),
    [
        ("http", ""),
        ("http", "localhost:8000"),
        ("http", "http://:8000"),
        ("http", "http://localhost"),
        ("http", "http://localhost:0"),
        ("http", "http://localhost:65536"),
        ("http", "http://localhost:invalid"),
        ("http", "http://local host:8000"),
        ("http", "http://user:password@localhost:8000"),
        ("http", "http://localhost:8000?query=1"),
        ("http", "http://localhost:8000#fragment"),
        ("http", "http://localhost:8000/prefix"),
        ("http", "runtime://helper"),
        ("websocket", "http://localhost:8000"),
        ("grpc", "http://localhost:8000"),
        ("http", "https://localhost:8000"),
        ("websocket", "wss://localhost:8000"),
        ("grpc", "grpcs://localhost:8000"),
    ],
)
def test_invalid_shorthand_endpoints_fail_before_provider(monkeypatch, transport, url):
    factory = Mock(side_effect=AssertionError("must not initialize provider"))
    monkeypatch.setattr("protolink.llms.create_llm", factory)
    with pytest.raises(ValueError):
        Agent(name="helper", transport=transport, url=url, llm="mock")
    factory.assert_not_called()


def test_configured_transport_supplies_url_and_allows_public_proxy_address():
    transport = HTTPTransport("http://127.0.0.1:8000")
    agent = Agent(name="helper", transport=transport, verbosity=0)
    assert agent.transport is transport
    assert agent.card.url == transport.url
    public = Agent(name="public", url="https://agents.example/helper", transport=transport, verbosity=0)
    assert public.card.url == "https://agents.example/helper"
    assert public.transport.url == "http://127.0.0.1:8000"
    with pytest.raises(ValueError, match="explicit bind port"):
        Agent(name="invalid", transport=HTTPTransport("http://localhost"))
    with pytest.raises(ValueError, match="must match"):
        Agent(name="invalid", url="runtime://public", transport=RuntimeTransport("runtime://private"))


def test_secure_binding_requires_server_identity():
    with pytest.raises(ValueError, match="certfile and keyfile"):
        Agent(name="helper", transport=HTTPTransport("https://localhost:8443", tls=TLSConfig()))
    tls = TLSConfig(certfile="certs/agent.pem", keyfile="certs/agent-key.pem")
    transport = HTTPTransport("https://localhost:8443", tls=tls)
    agent = Agent(name="helper", transport=transport, verbosity=0)
    assert agent.card.url == transport.url
    assert agent.transport.tls is tls


def test_later_transport_configuration_updates_only_automatic_identity():
    agent = Agent(name="helper", verbosity=0)
    with pytest.raises(ValueError, match="scheme"):
        agent.transport = "http"
    assert agent.transport is None
    assert agent.card.url == "runtime://helper"
    transport = HTTPTransport("http://127.0.0.1:8000")
    agent.transport = transport
    assert agent.card.url == transport.url
    with pytest.raises(ValueError, match="scheme"):
        agent.transport = "websocket"
    assert agent.transport is transport
    assert agent.card.url == transport.url
    agent.card.url = "https://public.example/helper"
    agent.transport = HTTPTransport("http://127.0.0.1:8001")
    assert agent.card.url == "https://public.example/helper"


def test_a2a_shorthand_supports_configured_http_and_deferred_setup():
    agent = Agent(name="helper", a2a=True, verbosity=0)
    agent.transport = HTTPTransport("http://127.0.0.1:8000")
    assert agent.card.url == "http://127.0.0.1:8000"
    assert agent.a2a
    with pytest.raises(ValueError, match="requires an HTTP transport"):
        agent.transport = RuntimeTransport("runtime://helper")
    assert agent.card.url == "http://127.0.0.1:8000"


def test_custom_transport_retains_its_own_url_contract():
    class QueueTransport(RuntimeTransport):
        transport_type = "queue"

        def validate_url(self):
            return self.url.startswith("queue:")

    transport = QueueTransport("queue:helper")
    assert Agent(name="helper", transport=transport, verbosity=0).card.url == "queue:helper"
    with pytest.raises(ValueError, match="invalid URL"):
        Agent(name="helper", transport=QueueTransport("invalid"))


@pytest.mark.parametrize("identity", [{"name": "new"}, {"description": "new"}, {"url": "runtime://new"}])
def test_explicit_card_cannot_be_combined_with_identity_shorthand(identity):
    card = AgentCard(name="existing", description="Existing", url="runtime://existing")
    with pytest.raises(ValueError, match="not both"):
        Agent(card, **identity)


@pytest.mark.parametrize("identity", [{}, {"name": ""}, {"name": " "}, {"name": "helper", "description": ""}])
def test_missing_or_empty_identity_fails(identity):
    with pytest.raises(ValueError):
        Agent(**identity)


def test_explicit_card_and_serialized_configuration_remain_supported():
    card = AgentCard(name="existing", description="Existing", url="http://localhost:8000")
    assert Agent(card, transport="runtime", verbosity=0).card is card
    assert Agent(card.to_dict(), verbosity=0).card.name == "existing"
    shorthand = Agent(name="helper", description="Helpful", transport="runtime", verbosity=0)
    restored = Agent.from_dict(shorthand.to_dict())
    assert restored.card.to_dict() == shorthand.card.to_dict()
    assert restored.transport.url == "runtime://helper"
    shorthand.llm = "mock:Custom"
    assert shorthand.to_dict()["llm"]["model"] == "Custom"


@pytest.mark.asyncio
async def test_runtime_mesh_with_generated_cards_and_constructor_tools():
    worker = Agent(name="setup-worker", transport="runtime", tools=[add], verbosity=0)
    caller = Agent(name="setup-caller", transport="runtime", verbosity=0)
    async with AgentGroup([worker, caller]):
        assert await caller.peer(worker.card).call_tool("add", a=2, b=3) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("a2a", [False, True])
async def test_http_shorthand_serves_a_reachable_agent(unused_tcp_port, a2a):
    agent = Agent(
        name="http-helper",
        transport="http",
        url=f"http://127.0.0.1:{unused_tcp_port}",
        tools=[add],
        llm="mock",
        a2a=a2a,
        verbosity=0,
    )
    client = AgentClient(HTTPTransport("http://127.0.0.1:0"), a2a=a2a)
    await agent.server.start()
    try:
        peer = client.peer(agent.card.url)
        assert await peer.invoke("hello") == "Unprocessed generic mock response"
        if not a2a:
            assert await peer.call_tool("add", a=2, b=3) == 5
    finally:
        await client.transport.stop()
        await agent.server.stop()


def test_provider_extras_keep_hosted_and_server_installs_small():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]
    extras = project["optional-dependencies"]
    for provider in LLMProvider:
        if provider is LLMProvider.MOCK:
            continue
        requirements = extras[provider.value.replace(".", "-")]
        assert len(requirements) == 1
        if provider is not LLMProvider.LLAMACPP_LOCAL:
            assert not any("llama-cpp-python" in requirement for requirement in requirements)
    assert extras["deepseek"] == extras["openai"]
    assert len(project["dependencies"]) == 1
