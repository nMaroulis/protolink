from __future__ import annotations

import asyncio
import inspect
import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from protolink import (
    Agent,
    AgentCard,
    AgentInterface,
    RetryPolicy,
    TransportConfig,
    TransportConnectionError,
    TransportLimitError,
    TransportLimits,
    TransportTimeoutError,
)
from protolink.client import AgentClient, RegistryClient
from protolink.client.request_spec import ClientRequestSpec
from protolink.discovery import Registry
from protolink.server.endpoint_handler import EndpointSpec
from protolink.transport import RuntimeTransport, Transport, TransportRequestContext


class HarnessTransport(Transport):
    """Minimal transport used to exercise the shared production contract."""

    def __init__(self, config: TransportConfig | None = None) -> None:
        super().__init__(config=config)
        self._url = "runtime://harness"

    async def send(
        self,
        request_spec: ClientRequestSpec,
        base_url: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        del request_spec, base_url, data, params
        return None

    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        del endpoints

    async def start(self) -> None:
        self._transport_running = True

    async def stop(self) -> None:
        self._transport_running = False

    def validate_url(self) -> bool:
        return True

    @property
    def url(self) -> str:
        return self._url


def test_transport_config_validates_resource_bounds() -> None:
    with pytest.raises(ValueError, match="max_request_bytes"):
        TransportLimits(max_request_bytes=0)
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)


def test_transport_request_context_is_public() -> None:
    context = TransportRequestContext(request_id="request-1", idempotency_key="operation-1")

    assert context.next_attempt().attempt == 2


def test_transport_rejects_oversized_payloads() -> None:
    transport = HarnessTransport(TransportConfig(limits=TransportLimits(max_request_bytes=4)))

    with pytest.raises(TransportLimitError, match="configured maximum"):
        transport.check_payload_limit("too large", kind="request")


@pytest.mark.asyncio
async def test_retry_policy_only_retries_explicitly_idempotent_requests() -> None:
    transport = HarnessTransport(
        TransportConfig(
            retry=RetryPolicy(
                max_attempts=3,
                initial_backoff=0,
                max_backoff=0,
                jitter=0,
            )
        )
    )
    spec = ClientRequestSpec(name="read", path="/value", method="GET", idempotent=True)
    context = transport.new_request_context(spec)
    attempts: list[str] = []

    async def operation(attempt: Any) -> str:
        attempts.append(attempt.request_id)
        if len(attempts) == 1:
            raise TransportConnectionError("temporary", retryable=True)
        return "ok"

    async with transport.request_slot():
        assert await transport.run_with_retries(spec, context, operation) == "ok"

    assert attempts == [context.request_id, context.request_id]
    assert transport.metrics.retries == 1
    assert transport.metrics.requests_succeeded == 1
    assert transport.metrics.active_requests == 0


@pytest.mark.asyncio
async def test_runtime_transport_caches_idempotent_responses() -> None:
    server = RuntimeTransport("runtime://server")
    client = RuntimeTransport("runtime://client")
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"value": payload["value"]}

    server.setup_routes(
        [
            EndpointSpec(
                name="write",
                path="/value",
                method="POST",
                handler=handler,
                request_source="body",
            )
        ]
    )
    await server.start()
    spec = ClientRequestSpec(name="write", path="/value", method="POST", idempotent=True)
    payload = {"id": "same-operation", "value": 3}

    try:
        first = asyncio.create_task(client.send(spec, server.url, payload))
        await started.wait()
        duplicate = asyncio.create_task(client.send(spec, server.url, payload))
        await asyncio.sleep(0)
        release.set()
        assert await first == {"value": 3}
        assert await duplicate == {"value": 3}
        assert await client.send(spec, server.url, payload) == {"value": 3}
    finally:
        await server.stop()
        await client.stop()

    assert calls == 1


@pytest.mark.asyncio
async def test_websocket_does_not_cache_failed_idempotent_responses() -> None:
    pytest.importorskip("websockets")
    from protolink.transport import WebSocketTransport

    calls = 0

    async def handler(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return {"value": payload["value"]}

    transport = WebSocketTransport("ws://127.0.0.1:9000")
    transport.setup_routes(
        [EndpointSpec(name="write", path="/value", method="POST", handler=handler, request_source="body")]
    )
    frames = iter(
        [
            json.dumps(
                {
                    "id": "request-1",
                    "idempotency_key": "same-operation",
                    "method": "POST",
                    "path": "/value",
                    "data": {"value": 3},
                }
            ),
            json.dumps(
                {
                    "id": "request-2",
                    "idempotency_key": "same-operation",
                    "method": "POST",
                    "path": "/value",
                    "data": {"value": 3},
                }
            ),
        ]
    )

    class FakeWebSocket:
        def __init__(self) -> None:
            self.responses: list[str] = []

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            try:
                return next(frames)
            except StopIteration:
                raise StopAsyncIteration from None

        async def send(self, response: str) -> None:
            self.responses.append(response)

    websocket = FakeWebSocket()
    await transport._handle_connection(websocket)
    responses = [json.loads(response) for response in websocket.responses]

    assert responses[0]["ok"] is False
    assert responses[1] == {"id": "request-2", "ok": True, "result": {"value": 3}}
    assert calls == 2


@pytest.mark.asyncio
async def test_grpc_does_not_cache_failed_idempotent_responses() -> None:
    pytest.importorskip("grpc")
    from protolink.transport import GRPCTransport

    calls = 0

    async def handler(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return {"value": payload["value"]}

    transport = GRPCTransport("grpc://127.0.0.1:9000")
    transport.setup_routes(
        [EndpointSpec(name="write", path="/value", method="POST", handler=handler, request_source="body")]
    )
    context = SimpleNamespace(invocation_metadata=lambda: ())
    first = await transport._handle_unary(
        {
            "id": "request-1",
            "idempotency_key": "same-operation",
            "method": "POST",
            "path": "/value",
            "data": {"value": 3},
        },
        context,
    )
    second = await transport._handle_unary(
        {
            "id": "request-2",
            "idempotency_key": "same-operation",
            "method": "POST",
            "path": "/value",
            "data": {"value": 3},
        },
        context,
    )

    assert first["ok"] is False
    assert second == {"id": "request-2", "ok": True, "result": {"value": 3}}
    assert calls == 2


@pytest.mark.asyncio
async def test_websocket_timeout_discards_the_pooled_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("websockets")
    from protolink.transport import WebSocketTransport

    transport = WebSocketTransport("ws://127.0.0.1:9000", timeout=0.01)
    connection = SimpleNamespace(
        send=AsyncMock(),
        recv=AsyncMock(side_effect=TimeoutError),
        close=AsyncMock(),
    )

    async def ensure_connection(base_url: str, loop_key: str, *, request_id: str | None = None) -> Any:
        del base_url, request_id
        transport._client_conns[loop_key] = connection
        return connection

    monkeypatch.setattr(transport, "_ensure_client_connection", ensure_connection)
    spec = ClientRequestSpec(name="read", path="/value", method="GET")

    with pytest.raises(TransportTimeoutError):
        await transport.send(spec, "ws://127.0.0.1:9001")

    assert transport._client_conns == {}
    connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_websocket_request_discards_the_pooled_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("websockets")
    from protolink.transport import WebSocketTransport

    transport = WebSocketTransport("ws://127.0.0.1:9000")
    sent = asyncio.Event()
    never_respond = asyncio.Event()

    async def send(raw: str) -> None:
        del raw
        sent.set()

    async def recv() -> str:
        await never_respond.wait()
        raise AssertionError("unreachable")

    connection = SimpleNamespace(send=send, recv=recv, close=AsyncMock())

    async def ensure_connection(base_url: str, loop_key: str, *, request_id: str | None = None) -> Any:
        del base_url, request_id
        transport._client_conns[loop_key] = connection
        return connection

    monkeypatch.setattr(transport, "_ensure_client_connection", ensure_connection)
    spec = ClientRequestSpec(name="read", path="/value", method="GET")
    request = asyncio.create_task(transport.send(spec, "ws://127.0.0.1:9001"))
    await sent.wait()
    request.cancel()

    with pytest.raises(asyncio.CancelledError):
        await request

    assert transport._client_conns == {}
    connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_abandoned_websocket_stream_discards_the_pooled_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("websockets")
    from protolink.transport import WebSocketTransport

    transport = WebSocketTransport("ws://127.0.0.1:9000")

    class FakeConnection:
        def __init__(self) -> None:
            self.request: dict[str, Any] | None = None
            self.close = AsyncMock()

        async def send(self, raw: str) -> None:
            self.request = json.loads(raw)

        async def recv(self) -> str:
            assert self.request is not None
            return json.dumps(
                {
                    "id": self.request["id"],
                    "ok": True,
                    "result": {"type": "task_progress", "final": False},
                    "final": False,
                }
            )

    connection = FakeConnection()

    async def ensure_connection(base_url: str, loop_key: str, *, request_id: str | None = None) -> Any:
        del base_url, request_id
        transport._client_conns[loop_key] = connection
        return connection

    monkeypatch.setattr(transport, "_ensure_client_connection", ensure_connection)
    stream = transport.subscribe("ws://127.0.0.1:9001", {"id": "task-1"})

    assert await anext(stream) == {"type": "task_progress", "final": False}
    await stream.aclose()

    assert transport._client_conns == {}
    connection.close.assert_awaited_once()


def test_agent_card_round_trips_additional_interfaces() -> None:
    card = AgentCard(
        name="worker",
        description="Does work",
        url="https://worker.example",
        interfaces=[AgentInterface(url="grpcs://worker.example:443", transport="grpc")],
    )

    restored = AgentCard.from_dict(card.to_dict())

    assert restored.url == card.url
    assert restored.transport == "http"
    assert restored.interfaces == card.interfaces


def test_agent_round_trip_restores_registry_authentication() -> None:
    from protolink.security import APIKeyAuth
    from protolink.transport import HTTPTransport

    authenticator = APIKeyAuth(valid_keys={"secret": "client"})
    registry_transport = HTTPTransport(
        "https://registry.example",
        authenticator=authenticator,
        credentials="secret",
    )
    agent = Agent(
        AgentCard(name="worker", description="Does work", url="https://worker.example"),
        transport=HTTPTransport("https://worker.example"),
        registry=RegistryClient(registry_transport),
        authenticator=authenticator,
        credentials="secret",
        verbosity=0,
    )

    restored = Agent.from_dict(agent.to_dict())

    assert restored.registry_client is not None
    restored_transport = restored.registry_client.transport
    assert isinstance(restored_transport.authenticator, APIKeyAuth)
    assert restored_transport.credentials == "secret"


def test_client_uses_configured_transport_instance() -> None:
    config = TransportConfig(retry=RetryPolicy(max_attempts=2))
    transport = RuntimeTransport("runtime://client", config=config)
    client = AgentClient(transport)

    assert client.transport is transport
    assert client.transport.config is config


def test_agent_and_registry_transports_own_independent_config() -> None:
    agent_config = TransportConfig(retry=RetryPolicy(max_attempts=2))
    registry_config = TransportConfig(
        limits=TransportLimits(max_concurrent_requests=25),
    )
    agent_transport = RuntimeTransport("runtime://configured-agent", config=agent_config)
    registry_transport = RuntimeTransport("runtime://configured-registry", config=registry_config)
    agent = Agent(
        card=AgentCard(
            name="configured-agent",
            description="Exercises transport configuration propagation",
            url="runtime://configured-agent",
        ),
        transport=agent_transport,
        registry=RegistryClient(registry_transport),
    )
    standalone_registry_transport = RuntimeTransport(
        "runtime://standalone-configured-registry",
        config=registry_config,
    )
    registry = Registry(transport=standalone_registry_transport)
    restored = Agent.from_dict(agent.to_dict())

    assert agent.transport is agent_transport
    assert agent.transport.config is agent_config
    assert agent.registry_client is not None
    assert agent.registry_client.transport is registry_transport
    assert agent.registry_client.transport.config is registry_config
    assert registry.client.transport is standalone_registry_transport
    assert registry.client.transport.config is registry_config
    assert restored.transport is not None
    assert restored.transport.config == agent_config
    assert restored.registry_client is not None
    assert restored.registry_client.transport.config == registry_config


def test_agent_string_transport_uses_simple_defaults() -> None:
    agent = Agent(
        card=AgentCard(
            name="simple-agent",
            description="Exercises the zero-configuration path",
            url="runtime://simple-agent",
        ),
        transport="runtime",
    )

    assert agent.transport is not None
    assert agent.transport.config == TransportConfig()


def test_agent_constructor_keeps_advanced_settings_on_transport() -> None:
    parameters = inspect.signature(Agent).parameters

    assert "tls" not in parameters
    assert "transport_config" not in parameters


def test_client_and_registry_constructors_keep_advanced_settings_on_transport() -> None:
    client_parameters = inspect.signature(AgentClient).parameters
    registry_parameters = inspect.signature(Registry).parameters

    assert "tls" not in client_parameters
    assert "transport_config" not in client_parameters
    assert "tls" not in registry_parameters
    assert "transport_config" not in registry_parameters


@pytest.mark.asyncio
async def test_health_and_lifecycle_are_idempotent() -> None:
    transport = HarnessTransport()

    await transport.start()
    await transport.start()
    assert transport.health()["ready"] is True
    assert transport.health()["metrics"]["requests_started"] == 0

    await transport.stop()
    await transport.stop()
    assert transport.health()["ready"] is False


@pytest.mark.asyncio
async def test_pooled_resources_close_on_their_owning_event_loop() -> None:
    transport = HarnessTransport()
    owner_loop = asyncio.new_event_loop()
    owner_ready = threading.Event()
    closed_on: list[int] = []

    def run_owner_loop() -> None:
        asyncio.set_event_loop(owner_loop)
        owner_ready.set()
        owner_loop.run_forever()
        owner_loop.close()

    owner_thread = threading.Thread(target=run_owner_loop)
    owner_thread.start()
    owner_ready.wait(timeout=2)

    async def register_resource() -> None:
        async def close_resource() -> None:
            closed_on.append(threading.get_ident())

        transport.register_loop_resource("background", close_resource)

    try:
        asyncio.run_coroutine_threadsafe(register_resource(), owner_loop).result(timeout=2)
        await transport.close_loop_resources()
        assert closed_on == [owner_thread.ident]
    finally:
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        owner_thread.join(timeout=2)


@pytest.mark.parametrize("backend", ["starlette", "fastapi"])
@pytest.mark.asyncio
async def test_http_health_probe_does_not_require_application_auth(unused_tcp_port: int, backend: str) -> None:
    httpx = pytest.importorskip("httpx")
    from protolink.security import BearerTokenAuth
    from protolink.transport import HTTPTransport

    transport = HTTPTransport(
        f"http://127.0.0.1:{unused_tcp_port}",
        authenticator=BearerTokenAuth(secret="health-test-secret"),
        backend=backend,
        log_level="critical",
        access_log=False,
    )
    transport.setup_routes(
        [
            EndpointSpec(
                name="health",
                path="/healthz",
                method="GET",
                handler=transport.health,
                request_source="none",
            )
        ]
    )

    await transport.start()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{unused_tcp_port}/healthz")
        assert response.status_code == 200
        assert response.json()["ready"] is True
        assert transport.metrics.requests_started == 1
        assert transport.metrics.requests_succeeded == 1
        assert transport.metrics.active_requests == 0
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_grpc_registers_standard_health_service(unused_tcp_port: int) -> None:
    grpc = pytest.importorskip("grpc")
    health_pb2 = pytest.importorskip("grpc_health.v1.health_pb2")
    health_pb2_grpc = pytest.importorskip("grpc_health.v1.health_pb2_grpc")
    reflection_pb2 = pytest.importorskip("grpc_reflection.v1alpha.reflection_pb2")
    reflection_pb2_grpc = pytest.importorskip("grpc_reflection.v1alpha.reflection_pb2_grpc")
    from protolink.transport import GRPCTransport

    transport = GRPCTransport(f"grpc://127.0.0.1:{unused_tcp_port}")
    await transport.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{unused_tcp_port}")
    try:
        stub = health_pb2_grpc.HealthStub(channel)
        response = await stub.Check(health_pb2.HealthCheckRequest(service=transport._SERVICE_NAME))
        assert response.status == health_pb2.HealthCheckResponse.SERVING

        async def reflection_requests():
            yield reflection_pb2.ServerReflectionRequest(list_services="")

        reflection_stub = reflection_pb2_grpc.ServerReflectionStub(channel)
        responses = reflection_stub.ServerReflectionInfo(reflection_requests())
        reflection_response = await anext(responses.__aiter__())
        service_names = {service.name for service in reflection_response.list_services_response.service}
        assert transport._SERVICE_NAME in service_names
        assert "grpc.health.v1.Health" in service_names
    finally:
        await channel.close()
        await transport.stop()
