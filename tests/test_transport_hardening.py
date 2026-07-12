from __future__ import annotations

import asyncio
import threading
from typing import Any

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
)
from protolink.client import AgentClient
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
    transport = HarnessTransport(
        TransportConfig(limits=TransportLimits(max_request_bytes=4))
    )

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


def test_high_level_client_propagates_transport_config() -> None:
    config = TransportConfig(retry=RetryPolicy(max_attempts=2))
    client = AgentClient(
        transport="runtime",
        url="runtime://client",
        transport_config=config,
    )

    assert client.transport.config is config


def test_agent_and_registry_factories_propagate_transport_config() -> None:
    config = TransportConfig(retry=RetryPolicy(max_attempts=2))
    agent = Agent(
        card=AgentCard(
            name="configured-agent",
            description="Exercises transport configuration propagation",
            url="runtime://configured-agent",
        ),
        transport="runtime",
        registry="runtime",
        registry_url="runtime://configured-registry",
        transport_config=config,
    )
    registry = Registry(
        transport="runtime",
        url="runtime://configured-registry",
        transport_config=config,
    )

    assert agent.transport is not None
    assert agent.transport.config is config
    assert agent.registry_client is not None
    assert agent.registry_client.transport.config is config
    assert registry.client.transport.config is config


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


@pytest.mark.asyncio
async def test_http_health_probe_does_not_require_application_auth(unused_tcp_port: int) -> None:
    httpx = pytest.importorskip("httpx")
    from protolink.security import BearerTokenAuth
    from protolink.transport import HTTPTransport

    transport = HTTPTransport(
        f"http://127.0.0.1:{unused_tcp_port}",
        authenticator=BearerTokenAuth(secret="health-test-secret"),
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
