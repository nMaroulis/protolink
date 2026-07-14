"""Focused tests for the opt-in A2A boundary on the public Agent API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar, cast

import pytest

from protolink import Agent, AgentCard
from protolink.a2a.v1 import A2A_AGENT_CARD_PATH
from protolink.client.request_spec import ClientRequestSpec
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport.base import Transport
from protolink.transport.config import TransportCapabilities


class _CapturingClient:
    """Record whether Agent forwards its A2A configuration to AgentClient."""

    def __init__(
        self,
        transport: Transport,
        *,
        a2a: bool = False,
        a2a_allow_cross_origin: bool = False,
    ) -> None:
        self.transport = transport
        self.a2a = a2a
        self.a2a_allow_cross_origin = a2a_allow_cross_origin


class _CapturingTransport(Transport):
    transport_type: ClassVar[str] = "http"
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities(networked=True)

    def __init__(self, url: str = "http://agent.test") -> None:
        super().__init__()
        self._url = url
        self.endpoints: list[EndpointSpec] = []

    async def send(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        del request_spec, base_url, data, params
        return None

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        del agent_url, task
        if False:  # pragma: no cover - preserve async-iterator shape
            yield None

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        self.endpoints.extend(endpoints)

    async def start(self) -> None:
        self._transport_running = True

    async def stop(self) -> None:
        self._transport_running = False

    def validate_url(self) -> bool:
        return True

    @property
    def url(self) -> str:
        return self._url


class _NonHTTPTransport(_CapturingTransport):
    transport_type: ClassVar[str] = "runtime"


@pytest.fixture
def card() -> AgentCard:
    return AgentCard(name="opt-in-agent", description="A2A opt-in test", url="http://agent.test")


@pytest.fixture(autouse=True)
def capture_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("protolink.agents.mixins.AgentClient", _CapturingClient)


def _route_keys(transport: _CapturingTransport) -> set[tuple[str, str]]:
    return {(endpoint.method, endpoint.path) for endpoint in transport.endpoints}


def test_a2a_defaults_off_and_native_routes_remain_unchanged(card: AgentCard) -> None:
    transport = _CapturingTransport()
    agent = Agent(card, transport=transport, verbosity=0)

    assert agent.a2a is False
    assert agent.client is not None
    assert cast(Any, agent.client).a2a is False
    assert agent.server is not None

    agent.server._build_endpoints()
    routes = _route_keys(transport)

    assert ("POST", "/tasks/") in routes
    assert ("GET", "/.well-known/agent.json") in routes
    assert ("GET", A2A_AGENT_CARD_PATH) not in routes
    assert ("POST", "/") not in routes


def test_a2a_true_adds_standard_routes_without_removing_native_routes(card: AgentCard) -> None:
    transport = _CapturingTransport()
    agent = Agent(card, transport=transport, a2a=True, verbosity=0)

    assert agent.a2a is True
    assert agent.client is not None
    assert cast(Any, agent.client).a2a is True
    assert agent.server is not None

    agent.server._build_endpoints()
    routes = _route_keys(transport)

    assert ("POST", "/tasks/") in routes
    assert ("GET", "/.well-known/agent.json") in routes
    assert ("GET", A2A_AGENT_CARD_PATH) in routes
    assert ("POST", "/") in routes


def test_a2a_true_allows_deferred_http_transport_configuration(card: AgentCard) -> None:
    agent = Agent(card, a2a=True, verbosity=0)

    assert agent.a2a is True
    assert agent.transport is None

    transport = _CapturingTransport()
    agent.transport = transport

    assert agent.transport is transport
    assert agent.client is not None
    assert cast(Any, agent.client).a2a is True


def test_a2a_true_rejects_non_http_transport(card: AgentCard) -> None:
    with pytest.raises(ValueError, match="a2a=True requires an HTTP transport"):
        Agent(card, transport=_NonHTTPTransport(), a2a=True, verbosity=0)


def test_a2a_round_trips_through_dict_and_yaml(card: AgentCard) -> None:
    agent = Agent(
        card,
        transport=_CapturingTransport(),
        a2a=True,
        a2a_allow_cross_origin=True,
        verbosity=0,
    )

    serialized = agent.to_dict()
    restored_dict = Agent.from_dict(serialized, transport=_CapturingTransport())
    restored_yaml = Agent.from_yaml_string(agent.to_yaml_string(), transport=_CapturingTransport())

    assert serialized["a2a"] is True
    assert serialized["a2a_allow_cross_origin"] is True
    assert restored_dict.a2a is True
    assert restored_yaml.a2a is True
    assert cast(Any, restored_dict.client).a2a_allow_cross_origin is True
    assert cast(Any, restored_yaml.client).a2a_allow_cross_origin is True
