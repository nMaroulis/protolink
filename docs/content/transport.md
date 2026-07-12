import ApiSurface from '@site/src/components/ApiSurface';

# Transport

Protolink implements a **pluggable transport layer** that decouples the agent's cognitive logic from the underlying communication protocol. This architectural pattern allows the same agent instance to effectively "exist" across multiple mediums, whether serving HTTP requests, holding a stateful WebSocket connection, or communicating over a fast in-memory channel, without changing a single line of business logic.

At its core, the Transport abstraction behaves as a **protocol adapter pattern**, normalizing disparate wire formats into standard `Task` and `Message` domain objects.

All transports implement a consistent interface:

- **Ingress bridge**: Maps transport-specific events (HTTP POST, WS frames) to the internal `handle_task` implementation.
- **Egress signaling**: Provides a generic `send` primitive to dispatch requests defined by `ClientRequestSpec` specifications.
- **Control plane**: Routes operations such as task cancellation independently from the active work they control.
- **Lifecycle management**: Handles the startup/shutdown sequence of underlying I/O reactors (e.g., `uvicorn` loops or connection pools).

## Relationship with Client Layer

The **Transport** layer is low-level and typically not used directly by application code. Instead, developers use the high-level **[Client](client.md)** layer (specifically `AgentClient`), which wraps a transport instance and provides convenient, typed methods like `send_task` and `send_message`.

## Supported Transports

All transports inherit from the base `Transport` class.

- **HTTPTransport**
    - Uses HTTP/HTTPS for synchronous request/response.
    - Used for both Agent-to-Agent and Agent-to-Registry communication.
    - Serves browser-facing HTML pages such as `GET /status` and, for LLM-backed agents, `GET /chat`.
    - Backed by ASGI frameworks:
        - `Starlette` + `httpx` + `uvicorn` (lightweight default backend).
        - `FastAPI` + `pydantic` + `uvicorn` (with optional request validation).
    - Great default choice for web‑based agents, simple deployments, and interoperable APIs.

- **WebSocketTransport**
    - Uses WebSocket for streaming requests and responses.
    - Built on top of libraries like `websockets` (and `httpx` for HTTP parts where applicable).
    - Multiplexes endpoint specs over JSON frames instead of mounting browser-visible `GET /status` or `GET /chat` routes.
    - Uses a dedicated control connection for cancellation so the request cannot wait behind the active task or stream.
    - Useful for real‑time, bidirectional communication or token‑level streaming.

- **SSEJSONRPCTransport**
    - Uses HTTP request/response for normal calls and Server-Sent Events for task streams.
    - Streams JSON-RPC-style envelopes from `POST /tasks/stream`.
    - Inherits HTTP page exposure, so status and chat pages are available from the same base URL.
    - Useful for CLIs, browser clients, dashboards, and other consumers that want streaming without a WebSocket connection.

- **GRPCTransport**
    - Uses `grpc.aio` for unary request/response calls and unary-stream task events.
    - Registers one generic Protolink gRPC service and routes requests by `ClientRequestSpec` method/path.
    - Carries compact JSON envelopes over gRPC byte messages, so no generated protobuf files are required.
    - Supports gRPC metadata for the same bearer/API-key authentication headers used by HTTP and WebSocket transports.
    - Registers standard gRPC health checking and server reflection when installed through `protolink[grpc]`.
    - Useful for service meshes, polyglot infrastructure, and teams that want gRPC deadlines and connection pooling while keeping Protolink's transport-neutral agent API.

- **RuntimeTransport**
    - Simple **in‑process, in‑memory transport**.
    - Allows multiple agents to communicate within the same Python process.
    - Registers endpoint specs in memory only; there are no browser pages or bound network ports.
    - Ideal for local development, test suites, and tightly‑coupled agent systems with zero network overhead.

## Choosing a Transport

Some rough guidelines:

- Use **RuntimeTransport** for local experiments, tests, or when all agents live in the same process.
- Use **HTTPTransport** when you want a simple, interoperable API surface (e.g. calling agents from other services or frontends) and for communicating with the Registry.
- Use **SSEJSONRPCTransport** when you want HTTP-compatible streaming over `text/event-stream` while keeping normal HTTP status and chat pages.
- Use **WebSocketTransport** when you need streaming and interactive sessions over a single WebSocket protocol surface.
- Use **GRPCTransport** when your deployment already standardizes on gRPC deadlines, metadata, and connection management.

The rest of this page dives into the API of each transport in more detail.

## Production configuration

Every transport accepts the same `TransportConfig`. Pass it at the high-level `Agent`, `AgentClient`, or `Registry` boundary; ProtoLink forwards it to the selected transport.

```python
from protolink import Agent, AgentCard, RetryPolicy, TransportConfig, TransportLimits

transport_config = TransportConfig(
    limits=TransportLimits(
        max_request_bytes=8 * 1024 * 1024,
        max_response_bytes=8 * 1024 * 1024,
        max_event_bytes=1024 * 1024,
        max_concurrent_requests=200,
        max_concurrent_streams=50,
    ),
    retry=RetryPolicy(max_attempts=3),
    keepalive_interval=20,
    keepalive_timeout=10,
    shutdown_timeout=10,
)

agent = Agent(
    card=AgentCard(
        name="worker",
        description="Production task worker",
        url="grpcs://worker.internal:9443",
    ),
    transport="grpc",
    transport_config=transport_config,
)
```

`max_attempts=1` is the default, so upgrading never enables retries implicitly. ProtoLink retries only request specifications explicitly marked idempotent, preserves one correlation ID across attempts, and sends an idempotency key so completed operations can be replayed without executing the handler again. Streams are not automatically retried because resuming a partial event sequence requires application-level checkpoints.

The same limits apply to RuntimeTransport, making local tests representative of deployed serialization boundaries. HTTP uses bounded client/server concurrency, WebSocket uses bounded frame queues and ping/pong keepalive, and gRPC applies message-size, keepalive, and concurrent-RPC options.

## Shared Transport API Reference

The shared production API is available from the top-level package for normal application code:

```python
from protolink import (
    RetryPolicy,
    TransportConfig,
    TransportConnectionError,
    TransportError,
    TransportLimitError,
    TransportLimits,
    TransportMetricsSnapshot,
    TransportProtocolError,
    TransportRemoteError,
    TransportTimeoutError,
)
```

Custom transport implementations can import the base contract and extension types from the transport package:

```python
from protolink.transport import (
    Transport,
    TransportCapabilities,
    TransportRequestContext,
)
```

### `TransportConfig`

`TransportConfig` is the single configuration object accepted by every built-in transport. It is immutable and safe to share between an `Agent`, its client, and a `Registry`.

```python
TransportConfig(
    limits: TransportLimits = TransportLimits(),
    retry: RetryPolicy = RetryPolicy(),
    keepalive_interval: float | None = 20.0,
    keepalive_timeout: float = 20.0,
    shutdown_timeout: float = 5.0,
    idempotency_ttl: float = 300.0,
    idempotency_cache_size: int = 1024,
    collect_metrics: bool = True,
)
```

| Field | Default | Applied behavior |
|-------|---------|------------------|
| `limits` | `TransportLimits()` | Payload and per-event-loop concurrency bounds. |
| `retry` | `RetryPolicy()` | Bounded retry policy. The default performs one attempt only. |
| `keepalive_interval` | `20.0` seconds | WebSocket ping interval, HTTP keep-alive expiry, and gRPC keepalive interval. Set `None` to disable periodic WebSocket/HTTP keepalive; gRPC receives a zero interval. |
| `keepalive_timeout` | `20.0` seconds | WebSocket pong timeout, Uvicorn keep-alive timeout, and gRPC keepalive timeout. |
| `shutdown_timeout` | `5.0` seconds | Maximum wait for each loop-owned client connection or channel to close. Also used as WebSocket close timeout. |
| `idempotency_ttl` | `300.0` seconds | How long a completed idempotent result remains replayable. |
| `idempotency_cache_size` | `1024` | Maximum completed results retained by each transport instance. Oldest results are evicted first. |
| `collect_metrics` | `True` | Enables the dependency-free in-process metric recorder. When false, snapshots remain available but stay at zero. |

All timing and cache values must be positive, except `keepalive_interval`, which may be `None`. Invalid configurations raise `ValueError` during construction.

`TransportConfig.to_dict()` returns JSON-safe nested dictionaries. `TransportConfig.from_dict(data)` restores `TransportLimits`, `RetryPolicy`, and the retryable-method `frozenset`. `Agent.to_dict()`, YAML serialization, and `Agent.from_dict()` preserve this configuration under the serialized transport block.

### `TransportLimits`

```python
TransportLimits(
    max_request_bytes: int = 16 * 1024 * 1024,
    max_response_bytes: int = 16 * 1024 * 1024,
    max_event_bytes: int = 4 * 1024 * 1024,
    max_concurrent_requests: int = 100,
    max_concurrent_streams: int = 100,
)
```

| Field | Default | Meaning |
|-------|---------|---------|
| `max_request_bytes` | `16 MiB` | Maximum serialized request envelope or body. |
| `max_response_bytes` | `16 MiB` | Maximum serialized unary response. |
| `max_event_bytes` | `4 MiB` | Maximum serialized event yielded by a stream. |
| `max_concurrent_requests` | `100` | Per-event-loop unary request capacity. Additional work waits for a slot instead of spawning without a bound. |
| `max_concurrent_streams` | `100` | Per-event-loop active stream capacity. Additional streams wait for a slot. |

Payload sizes are calculated after ProtoLink recursively normalizes domain objects through its normal serializer. A payload over its byte bound raises `TransportLimitError` before it is sent or yielded. Every limit must be greater than zero. `to_dict()` returns all five integer fields.

Protocol-specific mapping:

| Transport | Request/response limits | Concurrency/backpressure |
|-----------|-------------------------|--------------------------|
| HTTP | Checked before outbound send and before server response; `httpx` pools use the request limit. | Uvicorn `limit_concurrency` plus per-loop client request slots. |
| SSE JSON-RPC | HTTP request limits plus `max_event_bytes` for every SSE result. | HTTP concurrency plus a bounded active-stream semaphore. |
| WebSocket | `websockets` frame size plus explicit request, response, and event checks. | Bounded frame queues, unary handler slots, and active-stream slots. |
| gRPC | Mapped to `grpc.max_send_message_length` and `grpc.max_receive_message_length`, with explicit envelope checks. | `maximum_concurrent_rpcs` defaults to `max_concurrent_requests`; streams also use active-stream slots. |
| Runtime | Applies the same serialized-size checks despite not opening a socket. | Both caller and target transports enforce per-loop request and stream slots. |

### `RetryPolicy`

```python
RetryPolicy(
    max_attempts: int = 1,
    initial_backoff: float = 0.1,
    max_backoff: float = 2.0,
    jitter: float = 0.1,
    retryable_methods: frozenset[str] = frozenset({"DELETE", "GET", "POST", "PUT"}),
)
```

| Field | Meaning |
|-------|---------|
| `max_attempts` | Total attempts, including the initial request. `1` disables retries. |
| `initial_backoff` | Base delay before the first retry. |
| `max_backoff` | Upper bound for exponential backoff. Must be at least `initial_backoff`. |
| `jitter` | Maximum random delay added to each retry. Set `0` for deterministic tests. |
| `retryable_methods` | HTTP-style methods eligible for retry after the request spec also declares idempotency. |

A request is retried only when all three conditions are true:

1. `ClientRequestSpec.idempotent` is `True`.
2. The request method appears in `retryable_methods`.
3. The raised `TransportError` has `retryable=True`.

The delay before retry number `n` is `min(initial_backoff * 2**(n - 1), max_backoff) + uniform(0, jitter)`. The same request ID and idempotency key are retained across every attempt; only `TransportRequestContext.attempt` increases. Streams are never automatically retried because replaying a partial event sequence requires an application checkpoint.

Built-in task submission, agent-card retrieval, cancellation, state description, registry discovery, registry heartbeat, and registry unregister requests declare idempotency. Mutating state compaction/reset operations and streaming requests do not.

### Correlation and idempotency

`TransportRequestContext` is an immutable request-scoped value:

```python
TransportRequestContext(
    request_id: str,
    idempotency_key: str | None = None,
    attempt: int = 1,
)
```

`next_attempt()` returns a new context with the same IDs and `attempt + 1`. `Transport.new_request_context()` generates the initial context. For idempotent payloads it derives the operation key from `id`, `task_id`, or `agent_url` when available; otherwise it uses the generated request ID.

| Transport | Correlation ID | Idempotency key |
|-----------|----------------|-----------------|
| HTTP / SSE | `X-Protolink-Request-ID` header | `Idempotency-Key` header |
| WebSocket | Envelope `id` | Envelope `idempotency_key` |
| gRPC | Envelope `id` and `x-protolink-request-id` metadata | Envelope `idempotency_key` and `idempotency-key` metadata |
| Runtime | In-process `TransportRequestContext` | In-process namespaced operation key |

Server-side keys are namespaced by method and path. The first request owns the operation; concurrent duplicates await its result, and later duplicates replay the completed result until the TTL expires. This cache is process-local. Use a durable application-level idempotency store as well when operations must remain deduplicated across restarts or multiple server replicas.

### `TransportCapabilities`

Every transport declares immutable class-level capabilities. Applications normally inspect `transport.capabilities`; custom transports set the class attribute.

```python
TransportCapabilities(
    networked: bool = True,
    streaming: bool = False,
    tls: bool = False,
    bidirectional: bool = False,
    persistent_connections: bool = False,
)
```

| Transport | Networked | Streaming | TLS | Bidirectional | Persistent connections |
|-----------|-----------|-----------|-----|---------------|------------------------|
| `HTTPTransport` | Yes | No | Yes | No | Yes |
| `SSEJSONRPCTransport` | Yes | Yes | Yes | No | Yes |
| `WebSocketTransport` | Yes | Yes | Yes | Yes | Yes |
| `GRPCTransport` | Yes | Yes | Yes | No | Yes |
| `RuntimeTransport` | No | Yes | No | No | No |

`supports_streaming` remains available as the compatibility flag used by `AgentClient` and `AgentServer`; it matches `capabilities.streaming` on all built-in transports.

### `Transport` base class

Application code usually receives a transport from `Agent.transport` or `AgentClient.transport`. The stable inspection surface is:

| Member | Type | Purpose |
|--------|------|---------|
| `transport_type` | `ClassVar[str]` | Factory/card identifier such as `"http"`, `"grpc"`, or `"runtime"`. |
| `supports_streaming` | `ClassVar[bool]` | Compatibility flag used to decide whether `/tasks/stream` is registered. |
| `capabilities` | `ClassVar[TransportCapabilities]` | Declarative transport behavior. |
| `config` | `TransportConfig` | Effective shared configuration for this instance. |
| `url` | `str` | Canonical bind/identity URL. |
| `metrics` | `TransportMetricsSnapshot` | Immutable snapshot taken at property access time. |
| `is_running` | `bool` | Whether this instance currently owns a running server endpoint. |
| `health()` | `dict[str, Any]` | JSON-compatible readiness, capability, and metric payload. |
| `validate_url()` | `bool` | Whether the configured URL uses a scheme accepted by the transport. |
| `start()` / `stop()` | `Awaitable[None]` | Idempotent server and pooled-resource lifecycle. |
| `send(...)` | `Awaitable[Any]` | Low-level unary request primitive used by clients. |
| `subscribe(agent_url, task)` | `AsyncIterator[Any]` | Low-level streaming primitive; unsupported transports raise `NotImplementedError`. |

#### Custom transport contract

A custom transport subclasses `Transport`, calls `super().__init__(config=config)`, declares its class capabilities, and implements `send`, `setup_routes`, `start`, `stop`, `validate_url`, and `url`. Streaming transports also override `subscribe`.

The base class exposes reusable extension hooks so custom transports can preserve the built-in operational contract:

| Method | Intended use |
|--------|--------------|
| `new_request_context(request_spec, data=None)` | Generate stable correlation and optional idempotency metadata. |
| `payload_size(payload)` | Return the normalized UTF-8 JSON size estimate. |
| `check_payload_limit(payload, kind, url=None)` | Enforce `kind="request"`, `"response"`, or `"event"`; returns measured bytes. |
| `request_slot()` | Async context manager for bounded outbound unary work. Pair it with `run_with_retries()`. |
| `inbound_request_slot()` | Async context manager for bounded inbound unary work and full outcome metrics. |
| `stream_slot()` | Async context manager for bounded streams and stream outcome metrics. |
| `run_with_retries(request_spec, context, operation)` | Execute an async operation under retry eligibility, backoff, and request metrics. |
| `register_loop_resource(key, closer)` | Record an async client/channel closer with the event loop that owns it. |
| `discard_loop_resource(key)` | Remove a resource that was already invalidated or closed. |
| `close_loop_resources()` | Close all registered resources on their owning loops under `shutdown_timeout`. |
| `acquire_idempotent_response(key)` | Claim an operation or await/replay an existing result. Returns `(owns_operation, result)`. |
| `complete_idempotent_response(key, response)` | Publish and cache a successful or protocol-level response. |
| `abort_idempotent_response(key, error)` | Release waiting duplicates when execution fails before a response exists. |

These hooks are an extension API for transport authors. Normal agent applications should configure the transport and call `AgentClient`, not manually coordinate slots or idempotency ownership.

#### Internal instance state

The base constructor creates the following private variables. They explain lifecycle behavior but are not a public mutation surface:

| Variable | Role |
|----------|------|
| `_metrics` | Thread-safe mutable recorder behind the immutable `metrics` property. |
| `_request_semaphores` | Per-event-loop unary request semaphores. Separate loops never share asyncio primitives. |
| `_stream_semaphores` | Per-event-loop active-stream semaphores. |
| `_resource_lock` | Thread lock protecting loop-owned resource registration. |
| `_loop_resources` | Resource key to `(owner_loop, async_closer)` mapping used during cross-loop shutdown. |
| `_idempotency_lock` | Thread lock protecting completed and in-flight operation state. |
| `_idempotency_cache` | TTL-bound, oldest-first completed response cache. |
| `_idempotency_inflight` | Shared futures used so concurrent duplicate requests await one owner. |
| `_transport_running` | Base lifecycle flag used by `is_running` and health reporting. |

Do not replace or mutate these collections from application code. A custom transport should use the public helper methods above.

### `TransportMetricsSnapshot`

`transport.metrics` returns a new immutable snapshot. Reading it does not reset counters.

| Field | Type | Meaning |
|-------|------|---------|
| `requests_started` | `int` | Unary request executions admitted by this instance. |
| `requests_succeeded` | `int` | Unary executions completed successfully. |
| `requests_failed` | `int` | Unary executions ending with an exception or terminal transport failure. |
| `retries` | `int` | Additional attempts started by `RetryPolicy`. |
| `streams_started` | `int` | Streams admitted by this instance. |
| `streams_completed` | `int` | Streams that exited normally. |
| `streams_failed` | `int` | Streams that exited with an exception or cancellation. |
| `active_requests` | `int` | Current unary request gauge. |
| `active_streams` | `int` | Current stream gauge. |
| `bytes_sent` | `int` | Estimated normalized payload bytes attempted by outbound operations. Retries add bytes again. |
| `bytes_received` | `int` | Estimated normalized result bytes accepted by outbound operations. |
| `total_latency_ms` | `float` | Cumulative unary latency, not an average or histogram. |

`snapshot.to_dict()` produces the exact JSON-compatible mapping embedded in health responses. Metrics are process-local operational counters, not a replacement for durable telemetry. Set `collect_metrics=False` when another layer owns all measurement.

### Transport errors

All transport exceptions inherit from `TransportError` and expose the same diagnostic attributes:

```python
TransportError(
    message: str,
    *,
    url: str | None = None,
    request_id: str | None = None,
    retryable: bool = False,
    status_code: int | str | None = None,
)
```

| Error | Compatibility base | Raised for |
|-------|--------------------|------------|
| `TransportConnectionError` | `ConnectionError` | Connection establishment, retention, or peer availability failure. |
| `TransportTimeoutError` | `TimeoutError` | Request or stream deadline expiry. |
| `TransportProtocolError` | `RuntimeError` | Invalid JSON/envelope shape, mismatched request ID, or incompatible wire response. |
| `TransportRemoteError` | `RuntimeError` | A reachable peer returns an HTTP/gRPC status or protocol error result. |
| `TransportLimitError` | `ValueError` | Serialized request, response, or event exceeds its configured byte limit. |

`retryable` describes the failure category only; the request spec and method must still permit retries. `status_code` is an HTTP integer or protocol-native string such as a gRPC status name. `request_id` lets logs and traces correlate the exception with request headers or envelopes.

```python
try:
    result = await client.send_task(agent_url, task)
except TransportError as exc:
    logger.error(
        "transport failed",
        extra={
            "url": exc.url,
            "request_id": exc.request_id,
            "retryable": exc.retryable,
            "status_code": exc.status_code,
        },
    )
```

### Health and readiness

`transport.health()` returns this transport-neutral shape:

```json
{
  "status": "ready",
  "ready": true,
  "transport": "grpc",
  "url": "grpc://127.0.0.1:9001",
  "capabilities": {
    "networked": true,
    "streaming": true,
    "tls": true,
    "bidirectional": false,
    "persistent_connections": true
  },
  "metrics": {
    "requests_started": 12,
    "requests_succeeded": 12,
    "requests_failed": 0,
    "retries": 1,
    "streams_started": 2,
    "streams_completed": 2,
    "streams_failed": 0,
    "active_requests": 0,
    "active_streams": 0,
    "bytes_sent": 4096,
    "bytes_received": 8192,
    "total_latency_ms": 184.5
  }
}
```

Agents and registries expose the same payload at `GET /healthz` and `GET /readyz`. These probe endpoints do not require application authentication. `ready` becomes true after the transport server starts and false after it stops.

gRPC additionally exposes `grpc.health.v1.Health` and service discovery through reflection when the packages installed by `protolink[grpc]` are present. Direct `GRPCTransport` construction accepts `enable_health=False` and `enable_reflection=False` to disable either service.

See [`examples/transport_production.py`](https://github.com/nMaroulis/protolink/blob/main/examples/transport_production.py) for a provider-free configuration example.

## TLS and mutual TLS

TLS is transport security: it encrypts traffic and verifies certificates before ProtoLink sends any task data. It is separate from application authentication. Use `TLSConfig` for HTTPS, secure WebSockets, and secure gRPC; use an `Authenticator` for bearer tokens, API keys, Basic auth, or OAuth. Production services commonly use both.

The high-level API accepts the same configuration everywhere:

```python
from protolink import Agent, AgentCard, TLSConfig

tls = TLSConfig(
    certfile="certs/agent.pem",
    keyfile="certs/agent-key.pem",
    cafile="certs/ca.pem",
)

agent = Agent(
    card=AgentCard(
        name="secure-agent",
        description="Agent served over HTTPS",
        url="https://agent.internal:8443",
    ),
    transport="http",
    tls=tls,
)
```

The URL scheme activates encryption. The transport name does not change:

| Transport | Plain URL | TLS URL |
|-----------|-----------|---------|
| HTTP and SSE JSON-RPC | `http://` | `https://` |
| WebSocket | `ws://` | `wss://` |
| gRPC | `grpc://` | `grpcs://` |
| Runtime | `runtime://` | Not applicable; no network socket |

`certfile` and `keyfile` form the local certificate identity. A secure server URL requires both. `cafile` supplies trusted certificate authorities; outbound clients use the operating system trust store when it is omitted. Hostname verification is enabled by default and should remain enabled in production.

| `TLSConfig` field | Default | Purpose |
|-------------------|---------|---------|
| `certfile` | `None` | PEM certificate chain presented by this server or mTLS client. |
| `keyfile` | `None` | PEM private key matching `certfile`; the two fields must be supplied together. |
| `cafile` | System roots for clients | PEM CA bundle used to verify remote servers and inbound mTLS clients. |
| `require_client_cert` | `False` | Require a trusted certificate from every inbound client. Requires `cafile`. |
| `check_hostname` | `True` | Verify outbound certificate hostnames. Disabling this does not disable CA verification. |

For a client that only calls a secure service, certificate trust is enough:

```python
from protolink import TLSConfig
from protolink.client import AgentClient

client = AgentClient(
    transport="grpc",
    url="grpc://127.0.0.1:0",
    tls=TLSConfig(cafile="certs/ca.pem"),
)
result = client.sync.send_task("grpcs://worker.internal:9443", task)
```

Enable mutual TLS by requiring a trusted client certificate on the server. The calling workload must then provide its own certificate and key:

```python
server_tls = TLSConfig(
    certfile="certs/server.pem",
    keyfile="certs/server-key.pem",
    cafile="certs/ca.pem",
    require_client_cert=True,
)

client_tls = TLSConfig(
    certfile="certs/client.pem",
    keyfile="certs/client-key.pem",
    cafile="certs/ca.pem",
)
```

`Agent`, `AgentClient`, and `Registry` accept `tls=` when they create a transport by name. Directly constructed `HTTPTransport`, `SSEJSONRPCTransport`, `WebSocketTransport`, and `GRPCTransport` instances accept the same argument. Certificate paths are serialized by `Agent.to_dict()` and `to_yaml()`; private-key contents are never embedded.

:::note[TLS termination]

Native TLS is useful for direct service exposure and end-to-end mTLS. It is also valid to terminate TLS at a trusted ingress, reverse proxy, load balancer, or service mesh and use an insecure ProtoLink URL only on the protected internal hop. Do not advertise an insecure URL outside that boundary. Restart the transport and recreate client connections after rotating certificate files so new SSL contexts and gRPC credentials are loaded.

:::

<ApiSurface
  eyebrow="Transport module"
  title="Transport Layer"
  path="protolink.transport"
  description="The protocol adapter layer that lets the same agent runtime communicate over HTTP, SSE JSON-RPC, WebSocket, gRPC, or an in-process runtime channel."
  pills={[
    "HTTP",
    "SSE JSON-RPC",
    "WebSocket",
    "gRPC",
    "TLS / mTLS",
    "RuntimeTransport",
    "Control-plane routes",
  ]}
  cards={[
    {
      title: "Request response",
      text: "Submit tasks, discover agents, fetch cards, and call registry endpoints over simple JSON HTTP.",
      code: "HTTPTransport",
    },
    {
      title: "Streaming",
      text: "Emit task status, LLM chunks, tool events, artifacts, and final completion updates over SSE, WebSocket, gRPC, or runtime streams.",
      code: "subscribe()",
    },
    {
      title: "Local runtime",
      text: "Exercise real agent boundaries inside one process with no network server.",
      code: "RuntimeTransport",
    },
    {
      title: "Backends",
      text: "Bind endpoint specs through ASGI backends or the generic gRPC service without changing agent behavior.",
      code: "EndpointSpec",
    },
  ]}
/>

## Transport Conformance Expectations

Agent-facing transports should preserve the same logical contract even when their wire formats differ:

- `AgentClient.send_task()` submits a serialized `Task` and receives a parsed `Task`.
- `AgentClient.get_agent_card()` returns the same public `AgentCard` exposed by the server.
- Streaming transports emit task events until the final task status update closes the stream. An LLM sub-event may carry `final=True` for the model step without closing the whole task stream.
- Control-plane routes such as `POST /tasks/cancel` and registry heartbeats must not depend on the active request/stream connection.
- Request parsers may be synchronous or asynchronous; transports must normalize both.

The repository includes `tests/test_transport_conformance.py` to keep Runtime, HTTP, WebSocket, and gRPC behavior aligned. Add new transports to that suite before treating them as production-ready.

---

## Browser and Endpoint Exposure

`AgentServer` and `RegistryServer` declare transport-neutral `EndpointSpec` objects. Each transport decides how those specs become reachable.

### Agent endpoints

| Endpoint | Purpose | Transport exposure |
|----------|---------|---------------------------------|
| `POST /tasks/` | Submit a task to the agent. | No, JSON API |
| `POST /tasks/cancel` | Cancel an active task. | No, JSON API |
| `POST /llm/history/compact` | Compact LLM history through the control plane. | No, JSON API |
| `POST /state/describe` | Inspect enabled state stores. | No, JSON API |
| `POST /state/reset` | Reset enabled state stores. | No, JSON API |
| `POST /state/compact` | Compact persisted conversation state. | No, JSON API |
| `GET /.well-known/agent.json` | Return the public `AgentCard`. | Yes, JSON document |
| `GET /status` | Render the agent status page. | Yes, HTML page |
| `GET /healthz` | Return transport liveness and metrics. | Yes, JSON document |
| `GET /readyz` | Return transport readiness and metrics. | Yes, JSON document |
| `GET /chat` | Render the self-contained chat UI or a fallback page. | Yes, HTML page |
| `POST /chat` | Send a chat message to `Agent.invoke()`. Registered only when the agent has an LLM. | No, JSON API used by the page |
| `POST /tasks/stream` | Stream task events. Registered only when the transport advertises streaming support. | SSE, WebSocket, gRPC, or runtime stream depending on transport |

### Registry endpoints

| Endpoint | Purpose | Transport exposure |
|----------|---------|---------------------------------|
| `POST /agents/` | Register an `AgentCard`. | No, JSON API |
| `DELETE /agents/` | Unregister an agent URL. | No, JSON API |
| `POST /agents/heartbeat` | Refresh agent liveness metadata. | No, JSON API |
| `GET /agents/` | Discover registered agents. | Yes, JSON document |
| `GET /status` | Render the registry status page. | Yes, HTML page |
| `GET /healthz` | Return transport liveness and metrics. | Yes, JSON document |
| `GET /readyz` | Return transport readiness and metrics. | Yes, JSON document |

### Transport mapping

| Transport | How endpoint specs are exposed |
|-----------|--------------------------------|
| `HTTPTransport` | Starlette/FastAPI mounts physical HTTP routes. Browser pages are available at `<base-url>/status` and `<base-url>/chat`. |
| `SSEJSONRPCTransport` | Same HTTP routes as `HTTPTransport`, plus `POST /tasks/stream` as `text/event-stream`. The aliases `"sse"`, `"json-rpc"`, and `"sse-json-rpc"` all use this transport. |
| `WebSocketTransport` | Endpoint specs are cached in memory and selected by JSON frames containing `id`, `method`, and `path`. A plain browser `GET /status` is not served. |
| `GRPCTransport` | Endpoint specs are cached in memory and selected by JSON envelopes sent to the generic `Invoke` or `Stream` gRPC methods. A plain browser `GET /status` is not served. |
| `RuntimeTransport` | Endpoint specs are cached in the process-local transport registry and called directly through `AgentClient`. No socket or browser surface is created. |

The browser pages themselves are not separate servers. Agent status and registry status are rendered by `protolink.utils.renderers.status`; agent chat is rendered by `protolink.utils.renderers.chat`.

---

## HTTPTransport

`HTTPTransport` is the main network transport for communication in Protolink. It handles both Agent-to-Agent JSON HTTP APIs and Registry operations.

### Overview

- **Client side**
  - Uses `httpx.AsyncClient` to send JSON requests to other agents or registries.
  - Implements the generic `send` method to dispatch requests defined by `ClientRequestSpec`.

- **Server side**
  - Uses an ASGI app (Starlette or FastAPI) to expose endpoints like:
    - `POST /tasks/` - submit a `Task` to the agent.
    - `POST /tasks/cancel` - request best-effort cancellation of an active task ID.
    - `GET /.well-known/agent.json` - agent metadata.
    - `GET /status` - agent or registry status HTML.
    - `GET /chat` - agent chat UI HTML when served by an agent.
    - Registry endpoints (if acting as a registry).
  - Uses a backend implementation of `BackendInterface` to manage the ASGI app and `uvicorn` server.

### Backend Architecture

`HTTPTransport` separates the network transport logic from the underlying server implementation using the `BackendInterface`.

```python
class BackendInterface(ABC):
    @abstractmethod
    def setup_routes(self, endpoints: list[EndpointSpec]) -> None: ...
    @abstractmethod
    async def start(self, url: str, tls: TLSConfig | None = None) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
```

This interface is implemented by two backends located in `protolink/transport/backends/`:

1.  **StarletteBackend** (`starlette.py`):
    - Default lightweight implementation using standard Starlette.
    - Minimal overhead, no extra validation.
    
2.  **FastAPIBackend** (`fastapi.py`):
    - Uses FastAPI to provide schema validation.
    - When `validate_schema=True` is passed to the transport, incoming requests are checked against Pydantic models before processing.


Backend and validation are selected via the `HTTPTransport` constructor:

```python
from protolink.transport import HTTPTransport

# Starlette backend (default)
transport = HTTPTransport(url="http://localhost:8000")

# Explicit Starlette backend
transport = HTTPTransport(url="http://localhost:8000", backend="starlette")

# FastAPI backend without schema validation
transport = HTTPTransport(url="http://localhost:8000", backend="fastapi", validate_schema=False)

# FastAPI backend with full schema validation
transport = HTTPTransport(url="http://localhost:8000", backend="fastapi", validate_schema=True)
```

### Wire Format

`HTTPTransport` sends and receives JSON payloads that match the core models' `to_dict()` methods. A typical `Task` request body looks like this:

:::note[Recursive JSON normalization]

Starlette and FastAPI normalize transport results recursively before JSON encoding. Nested Protolink dataclasses such as `ToolOutput`, objects exposing `to_dict()` or `model_dump()`, mappings, and collections are converted into JSON-compatible values even when they appear inside event content or metadata. WebSocket responses use the same normalization path.

:::
```json
{
  "id": "8c1e93b3-9f72-4a37-8c4c-3d2d8a9c4f7c",
  "state": "submitted",
  "messages": [
    {
      "id": "f0e4c2f7-5d3b-4b0a-b6e0-6a7f2d9c1b2a",
      "role": "user",
      "parts": [
        {"type": "text", "content": "Hi Bob, how are you?"}
      ],
      "timestamp": "2025-01-01T12:00:00Z"
    }
  ],
  "artifacts": [],
  "metadata": {},
  "created_at": "2025-01-01T12:00:00Z"
}
```

The tables below document each object type.

#### Task

| Field        | Type             | Description                                   |
|------------- |------------------|-----------------------------------------------|
| `id`         | `str`            | Unique task identifier.                       |
| `state`      | `str`            | Serialized `TaskState`, such as `"submitted"`, `"working"`, `"input-required"`, `"completed"`, `"failed"`, or `"canceled"`. |
| `messages`   | `list[Message]`  | Conversation history for this task.           |
| `artifacts`  | `list[Artifact]` | Outputs produced by the task.                 |
| `metadata`   | `dict[str, Any]` | Arbitrary metadata attached to the task, including optional `state_history`. |
| `created_at` | `str`            | ISO‑8601 timestamp (UTC).                     |

`completed`, `failed`, and `canceled` are terminal states. Default agents move incoming tasks to `working` before execution and then finish them as `completed`, `input-required`, or `failed` depending on the produced outputs.

`POST /tasks/cancel` accepts an A2A-style task-ID payload such as `{"id": "task-id", "metadata": {"reason": "Stopped by user"}}`. The response is the updated serialized `Task`. The endpoint controls active execution only; it is not a durable task lookup API.

`POST /llm/history/compact` accepts a control-plane history-compaction payload such as `{"strategy": "tokens", "max_tokens": 8000, "preserve_recent": 6, "session_id": "customer-42"}`. The response is a serialized `HistoryCompactionResult`. This endpoint does not create a `Task` and does not expose compaction as a model tool.

#### Message

```json
{
  "id": "f0e4c2f7-5d3b-4b0a-b6e0-6a7f2d9c1b2a",
  "role": "user",
  "parts": [
    {"type": "text", "content": "Hi Bob, how are you?"}
  ],
  "timestamp": "2025-01-01T12:00:00Z"
}
```

| Field       | Type                                | Description                |
|------------ |-------------------------------------|----------------------------|
| `id`        | `str`                               | Unique message identifier. |
| `role`      | `"user" ⎪ "agent" ⎪ "assistant" ⎪ "system"` | Sender role.               |
| `parts`     | `list[Part]`                        | Content payloads.          |
| `timestamp` | `str`                               | ISO‑8601 timestamp.        |

#### Part

```json
{"type": "text", "content": "Hi Bob, how are you?"}
```

| Field    | Type  | Description                       |
|--------- |-------|-----------------------------------|
| `type`   | `str` | Content type (e.g. `"text"`).     |
| `content`| `Any` | The actual content payload.       |

#### Artifact

```json
{
  "id": "a1b2c3",
  "parts": [
    {"type": "text", "content": "final report"}
  ],
  "metadata": {"kind": "report"},
  "timestamp": "2025-01-01T12:00:00Z"
}
```

| Field         | Type             | Description                 |
|-------------- |------------------|-----------------------------| 
| `id` | `str`            | Unique artifact identifier. |
| `parts`       | `list[Part]`     | Artifact content.           |
| `metadata`    | `dict[str, Any]` | Artifact metadata.          |
| `timestamp`   | `str`            | ISO‑8601 timestamp.         |
| `kind`        | `str`            | Application-defined category (e.g. `"result"`, `"preview"`, `"diagnostic"`). |
| `name`        | `str ⎪ null`    | Optional display or resource name. |
| `uri`         | `str ⎪ null`    | Optional URI identifying the represented resource. |
| `media_type`  | `str ⎪ null`    | Optional MIME type describing the artifact as a whole. |
| `action_id`   | `str ⎪ null`    | Optional ID of the `RunAction` that produced this artifact. |

### Typical Usage

#### Exposing an agent over HTTP

```python
from protolink.agents import Agent
from protolink.models import AgentCard, Task, Message
from protolink.transport import HTTPTransport


class EchoAgent(Agent):
    def __init__(self, port: int) -> None:
        url = f"http://127.0.0.1:{port}"
        card = AgentCard(
            name="echo", 
            description="Echoes back the last user message", 
            url=url,
        )
        transport = HTTPTransport(url=url)
        super().__init__(card, transport=transport)

    async def handle_task(self, task: Task) -> Task:
        last_msg = task.messages[-1]
        reply = Message.agent(f"echo: {last_msg.parts[0].content}")
        return Task(id=task.id, messages=task.messages + [reply])
```

Then run the agent and call it from another agent or client using `call_agent` or `send_message_to`.

#### Calling a remote agent

```python
from protolink.agents import Agent
from protolink.models import AgentCard, Task, Message
from protolink.transport import HTTPTransport


# Agent that calls other agents
class CallerAgent(Agent):
    def __init__(self, target_url: str) -> None:
        url = "http://localhost:8021"
        card = AgentCard(name="caller", description="Calls other agents", url=url)
        transport = HTTPTransport(url=url)
        super().__init__(card, transport=transport)
        self.target_url = target_url

    async def handle_task(self, task: Task) -> Task:
        # Forward the task to another agent
        result = await self.call_agent(self.target_url, task)
        return result


async def call_remote(url: str) -> None:
    hello = Task.create(Message.user("Hello over HTTP!"))
    result = await caller_agent.call_agent(url, hello)
    print("Response:", result.messages[-1].parts[0].content)
```

### HTTPTransport API Reference

The most important public methods on `HTTPTransport` are summarized below.

#### Constructor & lifecycle

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | `url: str`, `timeout: float = 360.0`, `authenticator: Authenticator ⎪ None = None`, `backend: Literal["starlette", "fastapi"] = "starlette"`, `validate_schema: bool = False`, `credentials: str ⎪ None = None`, `tls: TLSConfig ⎪ None = None`, `config: TransportConfig ⎪ None = None`, `log_level: str = "info"`, `access_log: bool = True` | `None` | Configure URL, timeout, authentication, TLS, shared production behavior, backend, validation, and Uvicorn logging. |
| `start` | `self` | `Awaitable[None]` | Start the selected backend and create the internal `httpx.AsyncClient`. `AgentServer` or `RegistryServer` registers endpoint specs before transport startup. |
| `stop` | `self` | `Awaitable[None]` | Stop the backend server and close the internal HTTP client. Safe to call multiple times. |

#### Properties

| Name | Type | Access | Description |
| ---- | ---- | ------ | ----------- |
| `url` | `str` | Read-only | The base URL configured for this transport. |
| `timeout` | `float` | Read/Write | The request timeout (in seconds) for outgoing requests. This can be changed at runtime to easily adjust timeouts for subsequent requests without restarting the transport. |
| `config` | `TransportConfig` | Read-only reference | Effective limits, retry, keepalive, shutdown, idempotency, and metric settings. |
| `capabilities` | `TransportCapabilities` | Class-level | Networked, TLS-capable, persistent, unary-only capability declaration. |
| `metrics` | `TransportMetricsSnapshot` | Read-only snapshot | Current request, retry, byte, stream, and latency counters. |
| `is_running` | `bool` | Read-only | Whether the ASGI server is running. |

#### Sending & receiving

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `setup_routes` | `endpoints: list[EndpointSpec]` | `None` | Mount transport-neutral server endpoint specs onto the selected Starlette or FastAPI backend. Called by `AgentServer` and `RegistryServer`. |
| `send` | `request_spec: ClientRequestSpec`, `base_url: str`, `data: Any = None`, `params: dict ⎪ None = None` | `Awaitable[Any]` | Send a generic request to the agent. This is the low-level primitive used by `AgentClient`. |

#### Auth & utilities

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `authenticate` | `credentials: str` | `Awaitable[None]` | Use the configured `Authenticator` to obtain an auth context (for example, exchanging an API key for a bearer token). The resulting context is automatically injected into outgoing HTTP headers. |
| `validate_url` | `-` | `bool` | Return `True` when the configured URL uses `http://` or `https://`. |
| `health` | `-` | `dict[str, Any]` | Return readiness, capabilities, URL, and metric snapshot. |

---

## RuntimeTransport

`RuntimeTransport` is an in-process, in-memory transport that enables agents to communicate directly without network overhead. Perfect for testing, local multi-agent setups, and rapid prototyping.

### Overview

Unlike network transports (HTTP, WebSocket), RuntimeTransport avoids actual TCP I/O. However, it perfectly mirrors the behavioral boundaries of `HTTPTransport` ensuring seamless interchangeability:

- **Strict URL Routing** - each agent transport is initialized explicitly with a unique URL (e.g., `runtime://agent-name`).
- **Global In-Memory Registry** - transports discover each other seamlessly through an automatic shared class-level global registry.
- **Serialization Isolation** - message models natively pass through Pydantic dict boundaries, maintaining process and state safety equivalently to HTTP wire framing.
- **Supports streaming** - agents can use generic `EndpointSpec` routing for real-time task streams.
- **Supports cancellation** - the same `/tasks/cancel` endpoint dispatches in-process without opening a local socket.

### Usage

```python
import asyncio
from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import RuntimeTransport


class TranslatorAgent(Agent):
    """Custom agent that translates messages."""

    async def handle_task(self, task: Task) -> Task:
        user_message = task.get_last_part_content()
        return task.complete(f"Translated: {user_message}")


async def main() -> None:
    # Initialize separate transports explicitly matching endpoint design
    assistant = Agent(
        card=AgentCard(
            name="assistant",
            description="A helpful assistant",
            url="runtime://assistant",
        ),
        transport=RuntimeTransport(url="runtime://assistant"),
    )

    translator = TranslatorAgent(
        card=AgentCard(
            name="translator",
            description="Translates messages",
            url="runtime://translator",
        ),
        transport=RuntimeTransport(url="runtime://translator"),
    )

    # Boot the transports to securely bind to the global memory registry
    assistant.start(background=True)
    translator.start(background=True)

    # Directly dispatch task payloads towards the unique URL identifiers
    task = Task.create(Message.user("Hello!"))
    response = await assistant.call_agent("runtime://translator", task)
    print(response.get_last_part_content())  # "Translated: Hello!"
```

### API Reference

#### Constructor & Lifecycle

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `url: str`, `config: TransportConfig ⎪ None = None` | `None` | Create an isolated in-memory transport with the same limits, retries, idempotency, and metrics contract as network transports. |
| `start` | `self` | `Awaitable[None]` | Register the allocated `url` actively directly on the class-level registry cache. |
| `stop` | `self` | `Awaitable[None]` | Detach registry allocations cleaning up in-memory routing bindings. |

#### Properties

| Name | Type | Access | Description |
| ---- | ---- | ------ | ----------- |
| `url` | `str` | Read-only | The unique runtime URL allocated to this transport. |
| `is_running` | `bool` | Read-only | Whether the transport is currently registered in the global in-memory registry. |
| `config` | `TransportConfig` | Read-only reference | Effective shared production configuration. |
| `capabilities` | `TransportCapabilities` | Class-level | In-process, streaming, non-networked capability declaration. |
| `metrics` | `TransportMetricsSnapshot` | Read-only snapshot | Current request, stream, retry, byte, and latency counters. |

#### Sending

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `send` | `request_spec`, `base_url`, `data`, `params` | `Awaitable[Any]` | Route a request via explicit parsed endpoint pathways toward registered peers. Internally utilized by `AgentClient`. |
| `subscribe` | `base_url: str`, `task: Task` | `AsyncIterator[dict]` | Connect securely subscribing mapped events from peer endpoint definitions natively generating iterative tokens. |

### Key Differences from HTTPTransport

| Aspect | HTTPTransport | RuntimeTransport |
|--------|---------------|------------------|
| Network | HTTP over TCP | Direct In-memory (Global Registry) |
| URL prefix requirements | HTTP(s) Protocol | `runtime://` Prefix format |
| Transport Instantiation | Multi-Process/Network | Process Local Instances |
| Serialization Engine | Full JSON Decoding via HTTP body | Native dict structures via Pydantic serialization bridging |
| Use case | Distributed production topologies | Test composition, high-efficiency decoupled orchestration |

---

## WebSocketTransport

`WebSocketTransport` (when available) provides streaming, bidirectional communication between agents or between agents and external clients.

Use it when:

- You need token‑level or chunk‑level streaming.
- You want long‑lived interactive sessions (chat UIs, dashboards, tools that stream output).

### WebSocketTransport API

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | `url: str`, `timeout: float = 360.0`, `authenticator: Authenticator ⎪ None = None`, `credentials: str ⎪ None = None`, `tls: TLSConfig ⎪ None = None`, `config: TransportConfig ⎪ None = None` | `None` | Configure URL, timeout, authentication, credentials, TLS, frame/concurrency limits, ping/pong keepalive, retry, shutdown, idempotency, and metrics. |
| `send` | `request_spec`, `base_url`, `data=None`, `params=None` | `Awaitable[Any]` | Send one correlated JSON envelope over a loop-local persistent connection. Control-channel specs use a separate cached connection. |
| `subscribe` | `agent_url: str`, `task: Any` | `AsyncIterator[Any]` | Send a `Task` to `/tasks/stream` and receive task event payloads over a single WebSocket connection. |
| `setup_routes` | `endpoints: list[EndpointSpec]` | `None` | Cache endpoint specs for the server-side frame router. |
| `start` / `stop` | `self` | `Awaitable[None]` | Start or stop the WebSocket server. |
| `validate_url` | `-` | `bool` | Accept `ws://` and `wss://` URLs. |
| `health` | `-` | `dict[str, Any]` | Return shared readiness, capability, and metric data. |

#### Properties

| Name | Type | Access | Description |
| ---- | ---- | ------ | ----------- |
| `url` | `str` | Read-only | The base URL configured for this transport. |
| `timeout` | `float` | Read/Write | The timeout (in seconds) for WebSocket receive operations. This can be changed at runtime to adjust response wait times for subsequent requests. |
| `config` | `TransportConfig` | Read-only reference | Effective limits, retry, ping/pong, shutdown, idempotency, and metric settings. |
| `capabilities` | `TransportCapabilities` | Class-level | Networked, streaming, TLS-capable, bidirectional, persistent capability declaration. |
| `metrics` | `TransportMetricsSnapshot` | Read-only snapshot | Current unary and stream counters, bytes, retries, and latency. |

---

## GRPCTransport

`GRPCTransport` exposes Protolink agents through a generic `grpc.aio` service. It supports the same high-level `AgentClient` calls as the other transports:

- `send_task()` and `get_agent_card()` use the unary `Invoke` method.
- `send_task_streaming()` uses the unary-stream `Stream` method.
- Control-plane calls such as cancellation, state operations, and history compaction use the same request-spec envelopes as other transports.

Install the optional dependency with:

```bash
pip install "protolink[grpc]"
```

### Client Usage

```python
from protolink import Agent, AgentCard, Task, create_llm
from protolink.client import AgentClient

agent_url = "grpc://127.0.0.1:8010"
agent = Agent(
    AgentCard(name="grpc-agent", description="Served over gRPC", url=agent_url),
    transport="grpc",
    llm=create_llm("mock", default_response="hello from grpc"),
)
agent.start(register=False, background=True)

client = AgentClient(transport="grpc", url="grpc://127.0.0.1:0")
result = client.sync.send_task(agent_url, Task.create_infer(prompt="Say hello"))
print(result.get_last_part_content())

agent.stop()
```

See [`examples/grpc_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/grpc_agent.py) for a complete request/response and streaming round trip.

### Wire Format

The gRPC service name is `protolink.transport.v1.ProtolinkTransport`. It exposes two methods:

| Method | Shape | Purpose |
|--------|-------|---------|
| `Invoke` | unary -> unary | Agent cards, task submission, registry calls, and control-plane operations. |
| `Stream` | unary -> stream | Task event streams for `POST /tasks/stream`. |

Each gRPC message is a JSON envelope carried as UTF-8 bytes:

```json
{
  "id": "request-id",
  "method": "POST",
  "path": "/tasks/",
  "data": {"id": "task-id", "messages": []},
  "params": {}
}
```

Responses follow the same envelope family used by WebSocket and SSE JSON-RPC:

```json
{"id":"request-id","ok":true,"result":{"state":"completed"},"final":true}
```

Authentication uses gRPC metadata keys compatible with the HTTP headers Protolink already builds: `authorization` and `x-api-key`.

### API

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | `url: str`, `timeout: float = 360.0`, `authenticator: Authenticator ⎪ None = None`, `credentials: str ⎪ None = None`, `channel_options = None`, `server_options = None`, `compression = None`, `maximum_concurrent_rpcs: int ⎪ None = None`, `graceful_shutdown_timeout: float = 3.0`, `tls: TLSConfig ⎪ None = None`, `config: TransportConfig ⎪ None = None`, `enable_health: bool = True`, `enable_reflection: bool = True` | `None` | Configure deadlines, auth, TLS/mTLS, shared limits/retries/keepalive, grpcio overrides, compression, shutdown grace, standard health, and reflection. Explicit gRPC options override values derived from `config`. |
| `send` | `request_spec`, `base_url`, `data`, `params` | `Awaitable[Any]` | Send a unary request to the peer's `Invoke` method and parse the response through the request spec. |
| `subscribe` | `agent_url: str`, `task: Any` | `AsyncIterator[Any]` | Send a task to `Stream` and yield each task event result until the stream is final. |
| `setup_routes` | `endpoints: list[EndpointSpec]` | `None` | Cache transport-neutral endpoint specs for the generic gRPC router. |
| `start` / `stop` | `self` | `Awaitable[None]` | Start or stop the `grpc.aio` server and loop-local client channels. |
| `validate_url` | `-` | `bool` | Accept `grpc://` and `grpcs://` URLs. |
| `url` / `timeout` | `str` / `float` | URL read-only; timeout read/write | Inspect the server identity URL or adjust future call deadlines. |
| `config` / `capabilities` / `metrics` | Shared types | Read-only | Inspect effective production settings, declared behavior, and operational counters. |
| `health` | `-` | `dict[str, Any]` | Return ProtoLink health data; standard gRPC health is exposed separately when enabled. |

---

## SSEJSONRPCTransport

`SSEJSONRPCTransport` provides streaming task execution over regular HTTP. It inherits the request/response behavior of `HTTPTransport` and adds a `subscribe()` method for consuming `POST /tasks/stream` as `text/event-stream`.

Use it when:

- You want live task progress in a CLI or browser without managing WebSocket state.
- You need streaming over infrastructure that already supports HTTP.
- You want a structured envelope with request ids, `ok` status, `result` payloads, and final markers.

### Client Usage

```python
from protolink.client import AgentClient
from protolink.models import Task

client = AgentClient(transport="sse", url="http://localhost:8000")
task = Task.create_infer(prompt="Explain Protolink streaming")

async for event in client.send_task_streaming("http://localhost:8010", task):
    print(event)
```

The aliases `"sse"`, `"json-rpc"`, and `"sse-json-rpc"` all resolve to `SSEJSONRPCTransport`.

### Wire Format

Each SSE frame contains one JSON payload:

```text
data: {"jsonrpc":"2.0","id":"...","ok":true,"result":{"type":"task_llm_stream"},"final":false}
```

The stream ends when `final` is `true`. If an error occurs, the envelope uses `ok: false` and includes an `error` object.

Event results are normalized recursively before the SSE frame is encoded. For example, a `TaskLLMStreamEvent` carrying a delegated tool result inside `metadata` sends the structured `ToolOutput` fields (`call_id`, `result`, and `error`) as JSON rather than failing the stream when it encounters the Python dataclass. The same guarantee applies to WebSocket stream payloads.

### API

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | Same as `HTTPTransport`, including `config: TransportConfig ⎪ None = None` | `None` | Configure the inherited HTTP unary path and SSE streaming production behavior. |
| `subscribe` | `agent_url: str`, `task: Any` | `AsyncIterator[Any]` | POST a task to `/tasks/stream`, parse SSE JSON-RPC envelopes, and yield each `result` payload. |
| `send` | `request_spec`, `base_url`, `data`, `params` | `Awaitable[Any]` | Inherited from `HTTPTransport` for normal request/response calls. |
| `config` / `capabilities` / `metrics` | Shared types | Read-only | Inspect effective settings, streaming/TLS capabilities, and unary/stream counters. |
