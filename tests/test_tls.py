"""TLS configuration and secure transport integration coverage."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import pytest

from protolink import Agent, AgentCard, Task, TLSConfig, create_llm
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.security import TLSConfig as SecurityTLSConfig
from protolink.transport import GRPCTransport, HTTPTransport, SSEJSONRPCTransport, WebSocketTransport

_FIXTURES = Path(__file__).parent / "fixtures" / "tls"
_CERTFILE = _FIXTURES / "cert.pem"
_KEYFILE = _FIXTURES / "key.pem"


def _server_tls(*, require_client_cert: bool = False) -> TLSConfig:
    """Return test server credentials trusted by the bundled test CA."""
    return TLSConfig(
        certfile=_CERTFILE,
        keyfile=_KEYFILE,
        cafile=_CERTFILE,
        require_client_cert=require_client_cert,
    )


def _client_tls(*, with_identity: bool = False) -> TLSConfig:
    """Return test client trust, optionally with an mTLS identity."""
    if with_identity:
        return TLSConfig(certfile=_CERTFILE, keyfile=_KEYFILE, cafile=_CERTFILE)
    return TLSConfig(cafile=_CERTFILE)


def _card(name: str, url: str) -> AgentCard:
    """Create a minimal card for a secure transport test agent."""
    return AgentCard(name=name, description=f"{name} TLS test agent", url=url)


async def _exercise_request_response(url: str, server_transport: Any, client_transport: Any) -> None:
    """Exercise the common agent contract and close both transport roles."""
    agent = Agent(
        _card("secure-agent", url),
        transport=server_transport,
        llm=create_llm("mock", default_response="secure transport ok"),
        verbosity=0,
    )
    client = AgentClient(client_transport)

    assert agent.server is not None
    await agent.server.start()
    try:
        card = await client.get_agent_card(url)
        result = await client.send_task(url, Task.create_infer(prompt="hello over TLS"))
        assert card.name == "secure-agent"
        assert result.get_last_part_content() == "secure transport ok"
    finally:
        await client_transport.stop()
        await agent.server.stop()


def test_tls_config_is_a_top_level_public_api() -> None:
    """TLSConfig should be discoverable without reaching into transport internals."""
    assert TLSConfig is SecurityTLSConfig


def test_tls_config_validates_and_builds_ssl_contexts() -> None:
    """TLSConfig should reject partial identities and build verified contexts."""
    with pytest.raises(ValueError, match="provided together"):
        TLSConfig(certfile=_CERTFILE)
    with pytest.raises(ValueError, match="cafile is required"):
        TLSConfig(require_client_cert=True)

    config = _server_tls(require_client_cert=True)
    server_context = config.create_server_context()
    client_context = config.create_client_context()

    assert server_context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert server_context.verify_mode == ssl.CERT_REQUIRED
    assert client_context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert client_context.verify_mode == ssl.CERT_REQUIRED
    assert client_context.check_hostname is True


def test_tls_config_serializes_paths_without_certificate_material() -> None:
    """Declarative agent configuration should persist TLS file references only."""
    config = _server_tls()
    serialized = config.to_dict()
    restored = TLSConfig.from_dict(serialized)

    assert serialized["certfile"] == str(_CERTFILE)
    assert "BEGIN CERTIFICATE" not in str(serialized)
    assert restored == config


def test_tls_is_owned_and_serialized_by_the_transport() -> None:
    """Agent should preserve advanced TLS without promoting it to Agent state."""
    server_tls = _server_tls()
    transport = HTTPTransport("https://127.0.0.1:8443", tls=server_tls)
    agent = Agent(_card("factory-agent", transport.url), transport=transport, verbosity=0)
    client_tls = _client_tls()
    client = AgentClient("http", url="https://127.0.0.1:8444", tls=client_tls)
    registry = Registry("http", url="https://127.0.0.1:8445", tls=client_tls, verbosity=0)

    serialized = agent.to_dict()
    restored = Agent.from_dict(serialized)

    assert "tls" not in serialized
    assert serialized["transport"]["tls"] == server_tls.to_dict()
    assert agent.transport is transport
    assert getattr(client.transport, "tls", None) is client_tls
    assert getattr(registry.client.transport, "tls", None) is client_tls
    assert restored.transport is not None
    assert getattr(restored.transport, "tls", None) == server_tls


@pytest.mark.asyncio
async def test_https_transport_uses_tls(unused_tcp_port: int) -> None:
    """HTTP request/response calls should work over a verified HTTPS socket."""
    url = f"https://127.0.0.1:{unused_tcp_port}"
    await _exercise_request_response(
        url,
        HTTPTransport(url=url, tls=_server_tls(), log_level="critical", access_log=False),
        HTTPTransport(url="http://127.0.0.1:0", tls=_client_tls(), log_level="critical", access_log=False),
    )


@pytest.mark.asyncio
async def test_sse_jsonrpc_stream_uses_tls(unused_tcp_port: int) -> None:
    """SSE JSON-RPC streaming should inherit HTTP's verified TLS path."""
    url = f"https://127.0.0.1:{unused_tcp_port}"
    server_transport = SSEJSONRPCTransport(
        url=url,
        tls=_server_tls(),
        log_level="critical",
        access_log=False,
    )
    client_transport = SSEJSONRPCTransport(
        url="http://127.0.0.1:0",
        tls=_client_tls(),
        log_level="critical",
        access_log=False,
    )
    agent = Agent(
        _card("secure-sse-agent", url),
        transport=server_transport,
        llm=create_llm("mock", default_response="secure stream ok"),
        verbosity=0,
    )
    client = AgentClient(client_transport)

    assert agent.server is not None
    await agent.server.start()
    try:
        events = [event async for event in client.send_task_streaming(url, Task.create_infer(prompt="stream"))]
        final_event = events[-1].to_dict() if hasattr(events[-1], "to_dict") else events[-1]
        assert final_event["final"] is True
    finally:
        await client_transport.stop()
        await agent.server.stop()


@pytest.mark.asyncio
async def test_secure_websocket_transport_uses_tls(unused_tcp_port: int) -> None:
    """WebSocket calls should work over a verified WSS connection."""
    pytest.importorskip("websockets")
    url = f"wss://127.0.0.1:{unused_tcp_port}"
    await _exercise_request_response(
        url,
        WebSocketTransport(url=url, tls=_server_tls()),
        WebSocketTransport(url="ws://127.0.0.1:0", tls=_client_tls()),
    )


@pytest.mark.asyncio
async def test_secure_grpc_transport_supports_mutual_tls(unused_tcp_port: int) -> None:
    """gRPC should encrypt the channel and enforce client certificates with mTLS."""
    pytest.importorskip("grpc")
    url = f"grpcs://127.0.0.1:{unused_tcp_port}"
    await _exercise_request_response(
        url,
        GRPCTransport(url=url, tls=_server_tls(require_client_cert=True)),
        GRPCTransport(url="grpc://127.0.0.1:0", tls=_client_tls(with_identity=True)),
    )
