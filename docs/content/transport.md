import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Transport

Protolink implements a **pluggable transport layer** that decouples the agent's cognitive logic from the underlying communication protocol. This architectural pattern allows the same agent instance to effectively "exist" across multiple mediums, whether serving HTTP requests, holding a stateful WebSocket connection, or communicating over a fast in-memory channel, without changing a single line of business logic.

At its core, the Transport abstraction behaves as a **protocol adapter pattern**, normalizing disparate wire formats into standard `Task` and `Message` domain objects.

A2A supplies the shared agent model; a Transport moves it. ProtoLink's transports carry the same A2A-derived task and message objects, but they are not all canonical A2A bindings. `Agent(..., transport="http", a2a=True)` enables ProtoLink's A2A 1.0 JSON-RPC boundary; Runtime, WebSocket, SSE JSON-RPC, and gRPC remain ProtoLink-native transports.

All transports implement a consistent interface:

- **Ingress bridge**: Maps transport-specific events (HTTP POST, WS frames) to the internal `handle_task` implementation.
- **Egress signaling**: Provides a generic `send` primitive to dispatch requests defined by `ClientRequestSpec` specifications.
- **Control plane**: Routes operations such as task cancellation independently from the active work they control.
- **Lifecycle management**: Handles the startup/shutdown sequence of underlying I/O reactors (e.g., `uvicorn` loops or connection pools).

## Relationship with Client Layer

The **Transport** layer is low-level and typically not used directly by application code. Instead, developers use the high-level **[Client](client.md)** layer (specifically `AgentClient`), which wraps a transport instance and provides convenient, typed methods like `send_task` and `send_message`.

## Supported Transports

All transports inherit from the base `Transport` class.

<div className="provider-strip-label">[ http ]   [ runtime ]   [ websockets ]   [ sse json-rpc ]   [ grpc ]</div>

<div className="provider-strip">
  <img src="https://uxwing.com/wp-content/themes/uxwing/download/web-app-development/http-icon.png" width="55" className="hover-icon" />
  <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/0/0e/Python_Windows_bytecode_icon_2016.svg/960px-Python_Windows_bytecode_icon_2016.svg.png?_=20220830131150" width="55" className="hover-icon" />
  <img src="https://assets.streamlinehq.com/image/private/w_300,h_300,ar_1/f_auto/v1/icons/5/websocket-w02xh571b3sxzooa60n1.png/websocket-16wzrfp0ko22h8s0km8xcb.png?_a=DATAiZAAZAA0" width="55" className="hover-icon" />
  <img src="https://cdn.iconscout.com/icon/free/png-256/free-json-icon-svg-download-png-226010.png?f=webp&w=128" width="55" className="hover-icon" />
  <img src="https://img-resize-cdn.joshmartin.ch/2550x0%2Ccbc4c56136fef320860b8e74c818ea95624c7bb8f63d85330b1b243a02a08914/https://joshmartin.ch/app/uploads/2024/04/pluginicon.png" width="55" className="hover-icon" />
</div>

- **HTTPTransport**
    - Uses HTTP/HTTPS for synchronous request/response.
    - Used for both Agent-to-Agent and Agent-to-Registry communication.
    - When serving an Agent with `a2a=True`, also mounts the standard A2A Agent Card and A2A 1.0 JSON-RPC endpoints.
    - Serves browser-facing HTML pages such as `GET /status` and, for LLM-backed agents, `GET /chat`.
    - Backed by ASGI frameworks:
        - `Starlette` + `httpx` + `uvicorn` (lightweight default backend).
        - `FastAPI` + `pydantic` + `uvicorn` (with optional request validation).
    - Great default choice for web‑based agents, simple deployments, and interoperable APIs.

- **WebSocketTransport**
    - Uses WebSocket for streaming requests and responses.
    - Built on top of the `websockets` library.
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

Choose the transport for the boundary around the agent; the `Agent`, `Task`, and client APIs stay the same.

| Transport | Use it when | Expected transport overhead | Streaming | Built-in surface and utilities | Main trade-off |
| --- | --- | --- | --- | --- | --- |
| [Runtime](#runtimetransport) (`"runtime"`) | All agents run in one Python process. It is the natural choice for tests, notebooks, local meshes, embedded agents, and deterministic flows. | **Lowest.** There is no socket or network round trip, although ProtoLink still enforces serialization and payload limits. | Yes | In-process routing plus Python-level `health()` and `metrics`. No listening port, browser pages, dashboard probe, TLS, or external A2A endpoint. | It cannot cross a process or host boundary and provides no network isolation. |
| [HTTP](#httptransport) (`"http"`) | You want the default network service, broad client compatibility, browser-facing utilities, or the optional **A2A 1.0** wire boundary. | **Network baseline.** Pooled keep-alive connections make it a strong default for unary calls, but a caller receives the result only after the response is complete. | No live `subscribe()` stream | ProtoLink-native task and control APIs; `/status`, `/healthz`, `/readyz`, LLM-backed `/chat`, dashboard actions, ordinary HTTP tooling, proxies, and TLS. `a2a=True` adds the standard Agent Card, JSON-RPC routes, and outbound translation. | Use SSE, WebSocket, or gRPC when callers need incremental task events. A2A currently remains unary. |
| [SSE JSON-RPC](#ssejsonrpctransport) (`"sse"`; aliases `"json-rpc"`, `"sse-json-rpc"`) | A browser, CLI, or dashboard needs one-way live progress while you keep an HTTP deployment model. | **HTTP-like for unary calls; progressive for streams.** One long-lived response delivers the first event before task completion and avoids polling, with text framing per event. | Yes, server to client | The native HTTP routes, status/health/chat pages, and dashboard actions, plus `POST /tasks/stream` as `text/event-stream`. The A2A 1.0 adapter is **not** mounted on this transport today. | The event channel is one-way, and proxies must permit long-lived SSE responses instead of buffering or timing them out. |
| [WebSocket](#websockettransport) (`"websocket"`) | You need a long-lived interactive connection, frequent messages, or bidirectional task and token streaming. | **Low per frame after connection setup.** A connection can be reused for many JSON frames, while persistent connections and per-channel serialization still consume resources. | Yes, bidirectional | ProtoLink-native task and control operations over JSON frames, WSS/TLS, and a dedicated control connection so cancellation does not wait behind an active stream. | There are no plain HTTP status/chat pages, dashboard probes, or A2A endpoints; reconnect and load-balancer handling is more involved. |
| [gRPC](#grpctransport) (`"grpc"`) | Internal services or service meshes already use gRPC deadlines, metadata, pooled channels, health checks, and reflection. | **Low for repeated RPCs and streams.** It uses persistent HTTP/2 channels and compact framing, but ProtoLink carries JSON byte envelopes rather than generated protobuf messages, so measure your workload. | Yes, server streaming | Generic `Invoke` and `Stream` methods, metadata authentication, TLS, deadlines, compression options, standard gRPC health, and reflection. | It requires the gRPC extra, has no browser/dashboard or A2A pages, and is less convenient for direct browser clients. |

The performance column compares **transport overhead**, not total agent response time, and is architectural guidance rather than benchmark data. Model inference, tool execution, payload size, network distance, TLS, and concurrency usually matter more than the protocol alone. Use the [built-in transport metrics](#transportmetricssnapshot) to compare representative workloads in your own deployment.

`RuntimeTransport` is available with the base package. Install `protolink[http]` for HTTP, SSE JSON-RPC, and WebSocket, or `protolink[grpc]` for gRPC. String aliases are enough for the normal path, for example `Agent(card=card, transport="sse")`; construct the concrete class only when you need explicit TLS, limits, retries, or protocol-specific settings.

The rest of this page dives into the API of each transport in more detail.

## How a request moves through a transport

For everyday use, a transport is simply the part of ProtoLink that moves a task from one process to another. The Agent decides **what** work should happen; the transport decides **how** the request and response cross the boundary safely.

One normal unary request follows this path:

1. `AgentClient` selects a `ClientRequestSpec`, which describes the operation without depending on HTTP, WebSocket, gRPC, or another protocol.
2. The transport creates a request context containing a correlation ID and, for safe repeatable operations, an idempotency key.
3. ProtoLink serializes the payload and checks its configured byte limit.
4. The request waits for a concurrency slot. This applies backpressure when the process is already busy instead of starting unlimited work.
5. The concrete transport sends the request using headers, metadata, or an envelope appropriate for its protocol.
6. If the connection fails, ProtoLink retries only when the operation, method, and error all say that retrying is safe.
7. The receiving transport deduplicates idempotent requests, executes the endpoint handler, checks the response size, and returns the result.
8. Metrics and health state are updated around the operation so applications can inspect what happened.

Streaming requests use the same ideas, but hold a stream slot and check every event independently. ProtoLink does not automatically restart a failed stream because it cannot know which events the consumer already processed.

The shared APIs exist to solve four practical production problems:

| Problem | ProtoLink feature | Why it matters |
|---------|-------------------|----------------|
| A large payload or traffic spike exhausts memory | `TransportLimits` and request/stream slots | Work is bounded before one busy peer destabilizes the whole process. |
| A temporary network failure interrupts a safe operation | `RetryPolicy` plus `ClientRequestSpec.idempotent` | Safe operations can recover without blindly repeating state changes. |
| A retry arrives after the server already completed the first attempt | Correlation IDs and idempotency keys | The duplicate receives the original result instead of executing the handler twice. |
| Operators cannot tell whether a service is ready or failing | Typed errors, metrics, and health endpoints | Failures become inspectable and automation can make informed decisions. |

## Production configuration

Every transport accepts the same `TransportConfig`. Configure it on the concrete transport passed to `Agent`, `AgentClient`, or `Registry`. This keeps operational behavior consistent when an application changes protocols: an 8 MiB request limit means the same thing over HTTP, gRPC, WebSocket, or the in-process runtime.

Most applications can start without creating this object. The defaults bound resources, collect local metrics, and keep retries disabled. Add an explicit configuration when deployment requirements differ from those defaults, such as a known maximum task size, a service concurrency budget, or a retry policy approved for your workload.

```python
from protolink import Agent, AgentCard, RetryPolicy, TransportConfig, TransportLimits
from protolink.transport import GRPCTransport

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

card = AgentCard(
    name="worker",
    description="Production task worker",
    url="grpcs://worker.internal:9443",
)
transport = GRPCTransport(url=card.url, config=transport_config)
agent = Agent(card=card, transport=transport)
```

`max_attempts=1` is the default, so upgrading never enables retries implicitly. ProtoLink retries only request specifications explicitly marked idempotent, preserves one correlation ID across attempts, and sends an idempotency key so completed operations can be replayed without executing the handler again. Streams are not automatically retried because resuming a partial event sequence requires application-level checkpoints.

The same limits apply to RuntimeTransport, making local tests representative of deployed serialization boundaries. HTTP uses bounded client/server concurrency, WebSocket uses bounded frame queues and ping/pong keepalive, and gRPC applies message-size, keepalive, and concurrent-RPC options.

:::tip[Start simple, configure explicitly]

Use string aliases while prototyping: `Agent(card=card, transport="grpc")`, `AgentClient("grpc", url=...)`, or `Registry("grpc", url=...)`. When deployment needs advanced settings, construct `GRPCTransport(url=..., config=transport_config)` and pass that object to the facade. The same rule applies everywhere.

:::

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

### get_transport

<ApiReference
  kind="function"
  path="protolink.transport.get_transport"
  signature={`get_transport(
    transport: str,
    **kwargs: Any,
) -> Transport`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/factory.py#L21"
>

Constructs a built-in transport by its case-insensitive alias and imports optional protocol modules lazily.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="get_transport parameters">
    <ApiField name="transport" type="str" required>
      One of `"http"`, `"runtime"`, `"websocket"`, `"grpc"`, `"sse"`, `"json-rpc"`, or `"sse-json-rpc"`.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Constructor values such as `url`, `config`, `tls`, or `credentials`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="get_transport return value">
    <ApiField name="transport_instance" type="Transport">
      A concrete transport instance for the selected alias.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="get_transport errors">
    <ApiField name="ValueError">
      Raised when the alias is unknown.
    </ApiField>
    <ApiField name="ImportError">
      Raised when the selected optional transport dependency is not installed.
    </ApiField>
    <ApiField name="constructor error">
      Validation and setup errors raised by the concrete transport are propagated.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Keyword filtering">
  The factory inspects the selected constructor and silently drops keyword arguments it does not declare, unless that constructor accepts `**kwargs`. Construct the concrete class directly when detecting a misspelled or unsupported option is important.
</ApiCallout>

</ApiReference>

### TransportConfig

<ApiReference
  kind="dataclass"
  path="protolink.TransportConfig"
  signature={`TransportConfig(
    limits: TransportLimits = TransportLimits(),
    retry: RetryPolicy = RetryPolicy(),
    keepalive_interval: float | None = 20.0,
    keepalive_timeout: float = 20.0,
    shutdown_timeout: float = 5.0,
    idempotency_ttl: float = 300.0,
    idempotency_cache_size: int = 1024,
    collect_metrics: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/config.py#L109"
>

`TransportConfig` is the immutable operational policy accepted by every built-in transport. Share one instance when an Agent, client, and Registry should use the same limits and retry behavior; construct a new instance to change policy.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TransportConfig parameters">
    <ApiField name="limits" type="TransportLimits" defaultValue="TransportLimits()">
      Bounds serialized request, response, and event sizes and the number of active unary requests and streams. Concurrency semaphores are maintained per event loop.
    </ApiField>
    <ApiField name="retry" type="RetryPolicy" defaultValue="RetryPolicy()">
      Controls bounded retries. The default policy performs exactly one attempt, so creating a transport never enables retries implicitly.
    </ApiField>
    <ApiField name="keepalive_interval" type="float | None" defaultValue="20.0">
      Seconds between WebSocket pings, the HTTP keep-alive expiry, and the gRPC keepalive interval. `None` disables the periodic HTTP/WebSocket setting and maps to a zero gRPC interval.
    </ApiField>
    <ApiField name="keepalive_timeout" type="float" defaultValue="20.0">
      Seconds allowed for WebSocket pong handling, Uvicorn idle keep-alive, and gRPC keepalive acknowledgement.
    </ApiField>
    <ApiField name="shutdown_timeout" type="float" defaultValue="5.0">
      Maximum wait for each loop-owned connection or channel closer. WebSocket also uses it as the connection close timeout. This is not a request deadline.
    </ApiField>
    <ApiField name="idempotency_ttl" type="float" defaultValue="300.0">
      Seconds a completed idempotent response remains eligible for replay in this process.
    </ApiField>
    <ApiField name="idempotency_cache_size" type="int" defaultValue="1024">
      Maximum completed responses retained by one transport instance. Expired entries are pruned and the oldest remaining entries are evicted first.
    </ApiField>
    <ApiField name="collect_metrics" type="bool" defaultValue="True">
      Enables dependency-free in-process counters. When disabled, `metrics` still returns a snapshot whose counters remain zero.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Methods">
  <ApiFields ariaLabel="TransportConfig methods">
    <ApiField name="to_dict()" type="dict[str, Any]">
      Returns a JSON-safe nested mapping.
    </ApiField>
    <ApiField name="from_dict(data)" type="TransportConfig">
      Reconstructs nested `TransportLimits` and `RetryPolicy` values and restores `retryable_methods` as a `frozenset`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="TransportConfig errors">
    <ApiField name="ValueError">
      Raised when a timeout, TTL, or cache size is not positive, or when `keepalive_interval` is neither `None` nor positive.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Serialization">
  `Agent.to_dict()`, YAML serialization, and `Agent.from_dict()` preserve this configuration inside the serialized transport block. Certificate and transport-specific constructor settings are handled separately.
</ApiCallout>

</ApiReference>

### TransportLimits

<ApiReference
  kind="dataclass"
  path="protolink.TransportLimits"
  signature={`TransportLimits(
    max_request_bytes: int = 16777216,
    max_response_bytes: int = 16777216,
    max_event_bytes: int = 4194304,
    max_concurrent_requests: int = 100,
    max_concurrent_streams: int = 100,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/config.py#L32"
>

Limits protect the process from accidental overload; they are not authorization rules. Byte limits reject one oversized normalized JSON payload, while concurrency limits make excess work wait asynchronously instead of spawning without a bound.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TransportLimits parameters">
    <ApiField name="max_request_bytes" type="int" defaultValue="16777216">
      Maximum serialized request envelope or body: 16 MiB by default.
    </ApiField>
    <ApiField name="max_response_bytes" type="int" defaultValue="16777216">
      Maximum serialized unary response: 16 MiB by default.
    </ApiField>
    <ApiField name="max_event_bytes" type="int" defaultValue="4194304">
      Maximum serialized event yielded by a stream: 4 MiB by default.
    </ApiField>
    <ApiField name="max_concurrent_requests" type="int" defaultValue="100">
      Unary request capacity per event loop. Additional work waits for a slot.
    </ApiField>
    <ApiField name="max_concurrent_streams" type="int" defaultValue="100">
      Active stream capacity per event loop. Additional streams wait for a slot.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="TransportLimits serialization">
    <ApiField name="to_dict()" type="dict[str, int]">
      Returns all five limits as integers.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="TransportLimits errors">
    <ApiField name="ValueError">
      Raised when any limit is zero or negative.
    </ApiField>
    <ApiField name="TransportLimitError">
      Raised later by a transport when a normalized request, response, or event exceeds the corresponding byte limit.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

Choose byte limits from the largest valid serialized task your application expects, with headroom for envelope metadata. Choose concurrency limits from measured CPU, memory, downstream-service, and model-provider capacity. Higher values increase parallelism and peak resource use; they do not make an individual request faster.

Protocol-specific mapping:

| Transport | Request/response limits | Concurrency/backpressure |
|-----------|-------------------------|--------------------------|
| HTTP | Checked before outbound send and before server response; `httpx` pools use the request limit. | Uvicorn `limit_concurrency` plus per-loop client request slots. |
| SSE JSON-RPC | HTTP request limits plus `max_event_bytes` for every SSE result. | HTTP concurrency plus a bounded active-stream semaphore. |
| WebSocket | `websockets` frame size plus explicit request, response, and event checks. | Bounded frame queues, unary handler slots, and active-stream slots. |
| gRPC | Mapped to `grpc.max_send_message_length` and `grpc.max_receive_message_length`, with explicit envelope checks. | `maximum_concurrent_rpcs` defaults to `max_concurrent_requests`; streams also use active-stream slots. |
| Runtime | Applies the caller transport's serialized request, response, and event checks despite not opening a socket. | Unary calls use the caller's outbound slot and the target's inbound slot. Live streams use the caller's stream slot; the target handler is not wrapped in a second stream slot. |

### RetryPolicy

<ApiReference
  kind="dataclass"
  path="protolink.RetryPolicy"
  signature={`RetryPolicy(
    max_attempts: int = 1,
    initial_backoff: float = 0.1,
    max_backoff: float = 2.0,
    jitter: float = 0.1,
    retryable_methods: frozenset[str] = frozenset({"DELETE", "GET", "POST", "PUT"}),
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/config.py#L67"
>

`RetryPolicy` controls how often a safe request may be attempted. ProtoLink separately requires the `ClientRequestSpec` to declare the operation idempotent, preventing a retry policy from blindly repeating mutations.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RetryPolicy parameters">
    <ApiField name="max_attempts" type="int" defaultValue="1">
      Total attempts, including the initial call. `3` means one initial call plus at most two retries; `1` disables retries.
    </ApiField>
    <ApiField name="initial_backoff" type="float" defaultValue="0.1">
      Base delay in seconds before the first retry.
    </ApiField>
    <ApiField name="max_backoff" type="float" defaultValue="2.0">
      Upper bound in seconds for exponential backoff. It must be at least `initial_backoff`.
    </ApiField>
    <ApiField name="jitter" type="float" defaultValue="0.1">
      Maximum random delay added to each retry. Use `0` for deterministic timing in tests.
    </ApiField>
    <ApiField name="retryable_methods" type="frozenset[str]" defaultValue={'frozenset({"DELETE", "GET", "POST", "PUT"})'}>
      HTTP-style methods eligible for retry after the request spec also declares idempotency. ProtoLink uppercases the request method before membership testing, so custom policy values should normally be uppercase.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="RetryPolicy serialization">
    <ApiField name="to_dict()" type="dict[str, Any]">
      Returns JSON-safe values and serializes `retryable_methods` as a sorted list.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RetryPolicy errors">
    <ApiField name="ValueError">
      Raised when `max_attempts` is below one, a timing value is negative, or `max_backoff` is lower than `initial_backoff`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Retry formula">
  Before retry number `n`, ProtoLink sleeps for `min(initial_backoff * 2**(n - 1), max_backoff) + uniform(0, jitter)`.
</ApiCallout>

</ApiReference>

A request is retried only when all three conditions are true:

1. `ClientRequestSpec.idempotent` is `True`.
2. The request method appears in `retryable_methods`.
3. The raised `TransportError` has `retryable=True`.

The same request ID and idempotency key are retained across every attempt; only `TransportRequestContext.attempt` increases. Streams are never automatically retried because replaying a partial event sequence requires an application checkpoint.

Built-in task submission, agent-card retrieval, cancellation, state description, registry discovery, registry heartbeat, and registry unregister requests declare idempotency. Mutating state compaction/reset operations and streaming requests do not.

The transport retries only typed `TransportError` failures marked `retryable=True`. Application exceptions and protocol errors that indicate invalid data are returned immediately because waiting and trying the same invalid operation again cannot repair them.

### Correlation and idempotency

Correlation and idempotency solve related but different problems:

- A **request ID** answers “which logical request produced this log, metric, or error?” It stays the same across retry attempts so operators can follow the whole operation.
- An **idempotency key** answers “has this logical operation already executed?” The server uses it to suppress duplicate execution and replay the completed result.

Consider a task that completes on the server, but the response connection breaks before the client receives it. The client cannot tell whether execution happened, so it retries. The repeated request keeps the same idempotency key; the server returns the stored result rather than running the task a second time. The request ID keeps both attempts connected in diagnostics.

#### TransportRequestContext

<ApiReference
  kind="dataclass"
  path="protolink.transport.TransportRequestContext"
  signature={`TransportRequestContext(
    request_id: str,
    idempotency_key: str | None = None,
    attempt: int = 1,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/base.py#L39"
>

Immutable metadata for one logical unary request. A retry creates a new context with a higher attempt number while preserving the identifiers needed for tracing and duplicate suppression.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TransportRequestContext parameters">
    <ApiField name="request_id" type="str" required>
      Correlation identifier carried in headers, metadata, or protocol envelopes and retained across every attempt.
    </ApiField>
    <ApiField name="idempotency_key" type="str | None" defaultValue="None">
      Stable operation key sent only when the request specification is idempotent.
    </ApiField>
    <ApiField name="attempt" type="int" defaultValue="1">
      One-based attempt number.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Methods">
  <ApiFields ariaLabel="TransportRequestContext methods">
    <ApiField name="next_attempt()" type="TransportRequestContext">
      Returns a new context with the same request and idempotency IDs and `attempt + 1`.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

`Transport.new_request_context()` generates the initial context. For idempotent payloads it derives the operation key from `id`, `task_id`, or `agent_url` when available; otherwise it uses the generated request ID.

| Transport | Correlation ID | Idempotency key |
|-----------|----------------|-----------------|
| HTTP / SSE | `X-Protolink-Request-ID` header | `Idempotency-Key` header |
| WebSocket | Envelope `id` | Envelope `idempotency_key` |
| gRPC | Envelope `id` and `x-protolink-request-id` metadata | Envelope `idempotency_key` and `idempotency-key` metadata |
| Runtime | In-process `TransportRequestContext` | In-process namespaced operation key |

Server-side keys are namespaced by method and path. The first request owns the operation; concurrent duplicates await its result, and later duplicates replay the completed result until the TTL expires. Failed or cancelled operations are released rather than cached, so a later request can try the operation again. This cache is process-local. Use a durable application-level idempotency store as well when operations must remain deduplicated across restarts or multiple server replicas.

The TTL and cache size are memory bounds, not correctness guarantees. Once an entry expires or is evicted, the transport no longer remembers the operation. Deployments requiring long-lived exactly-once business effects should enforce a durable unique operation key in their storage layer as well.

### TransportCapabilities

<ApiReference
  kind="dataclass"
  path="protolink.transport.TransportCapabilities"
  signature={`TransportCapabilities(
    networked: bool = True,
    streaming: bool = False,
    tls: bool = False,
    bidirectional: bool = False,
    persistent_connections: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/config.py#L10"
>

Immutable class-level feature flags used by generic code instead of concrete-class checks. They describe what an implementation supports, not whether its server is currently healthy.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TransportCapabilities parameters">
    <ApiField name="networked" type="bool" defaultValue="True">
      Whether calls cross a network boundary rather than the process-local Runtime registry.
    </ApiField>
    <ApiField name="streaming" type="bool" defaultValue="False">
      Whether the transport implements `subscribe()` and can expose `/tasks/stream`.
    </ApiField>
    <ApiField name="tls" type="bool" defaultValue="False">
      Whether the transport can own a native TLS-protected socket or client connection.
    </ApiField>
    <ApiField name="bidirectional" type="bool" defaultValue="False">
      Whether one persistent connection supports traffic in both directions.
    </ApiField>
    <ApiField name="persistent_connections" type="bool" defaultValue="False">
      Whether client-side connections or channels are pooled and reused.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Inspection">
  Applications normally read `transport.capabilities`; custom implementations replace the class attribute. The compatibility flag `supports_streaming` matches `capabilities.streaming` on every built-in transport.
</ApiCallout>

</ApiReference>

| Transport | Networked | Streaming | TLS | Bidirectional | Persistent connections |
|-----------|-----------|-----------|-----|---------------|------------------------|
| `HTTPTransport` | Yes | No | Yes | No | Yes |
| `SSEJSONRPCTransport` | Yes | Yes | Yes | No | Yes |
| `WebSocketTransport` | Yes | Yes | Yes | Yes | Yes |
| `GRPCTransport` | Yes | Yes | Yes | No | Yes |
| `RuntimeTransport` | No | Yes | No | No | No |

### Transport

<ApiReference
  kind="abstract class"
  path="protolink.transport.Transport"
  signature={`Transport(
    *,
    config: TransportConfig | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/base.py#L61"
>

The base class centralizes limits, retry decisions, metrics, correlation, duplicate suppression, and loop-aware cleanup while concrete subclasses own their wire protocol. Most applications use `AgentClient` instead of calling its low-level methods.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Transport constructor parameters">
    <ApiField name="config" type="TransportConfig | None" defaultValue="None">
      Shared operational configuration. `None` constructs a fresh default `TransportConfig`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="Transport attributes">
    <ApiField name="transport_type" type="ClassVar[str]">
      Factory and serialized-card identifier such as `"http"`, `"grpc"`, or `"runtime"`.
    </ApiField>
    <ApiField name="supports_streaming" type="ClassVar[bool]">
      Compatibility flag used by `AgentClient` and `AgentServer`.
    </ApiField>
    <ApiField name="capabilities" type="ClassVar[TransportCapabilities]">
      Declarative feature set for the concrete implementation.
    </ApiField>
    <ApiField name="config" type="TransportConfig">
      Effective immutable configuration.
    </ApiField>
    <ApiField name="url" type="str">
      Abstract read-only canonical bind or identity URL.
    </ApiField>
    <ApiField name="metrics" type="TransportMetricsSnapshot">
      A new immutable snapshot captured on each property access.
    </ApiField>
    <ApiField name="is_running" type="bool">
      Base lifecycle flag used by health reporting.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Abstract lifecycle">
  <ApiFields ariaLabel="Transport abstract lifecycle">
    <ApiField name="setup_routes(endpoints)" type="None">
      Binds transport-neutral `EndpointSpec` values to the server-side router.
    </ApiField>
    <ApiField name="start()" type="Awaitable[None]">
      Starts the server and marks the instance ready. Built-in implementations are safe to call again while already running.
    </ApiField>
    <ApiField name="stop()" type="Awaitable[None]">
      Stops the server and closes loop-owned resources. Built-in implementations tolerate repeated shutdown.
    </ApiField>
    <ApiField name="validate_url()" type="bool">
      Reports whether this instance's configured URL uses a supported scheme.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Transport.send

<ApiReference
  kind="async method"
  path="Transport.send"
  signature={`await transport.send(
    request_spec: ClientRequestSpec,
    base_url: str,
    data: Any = None,
    params: dict[str, Any] | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/base.py#L92"
>

Low-level unary primitive implemented by each transport and used by `AgentClient`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Transport send parameters">
    <ApiField name="request_spec" type="ClientRequestSpec" required>
      Declares the method, path, request and response parsers, channel, and idempotency eligibility.
    </ApiField>
    <ApiField name="base_url" type="str" required>
      Destination agent or Registry URL.
    </ApiField>
    <ApiField name="data" type="Any" defaultValue="None">
      Optional request payload. Domain objects are normalized before size checks and wire encoding.
    </ApiField>
    <ApiField name="params" type="dict[str, Any] | None" defaultValue="None">
      Optional query-style parameters carried by the selected protocol.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Transport send return value">
    <ApiField name="result" type="Any">
      The response produced by `request_spec.response_parser`; the concrete type depends on the operation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Transport send errors">
    <ApiField name="TransportError">
      Concrete transports raise typed connection, timeout, protocol, remote, and limit subclasses. Only eligible retryable failures enter the retry loop.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Transport.subscribe

<ApiReference
  kind="async iterator method"
  path="Transport.subscribe"
  signature={`transport.subscribe(
    agent_url: str,
    task: Any,
) -> AsyncIterator[Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/base.py#L108"
>

Low-level task-event stream. HTTP's base implementation does not support it; Runtime, SSE JSON-RPC, WebSocket, and gRPC override it.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Transport subscribe parameters">
    <ApiField name="agent_url" type="str" required>
      Destination agent URL.
    </ApiField>
    <ApiField name="task" type="Any" required>
      Task payload submitted to the streaming endpoint.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="Transport subscribe yielded values">
    <ApiField name="event" type="Any">
      One parsed task event at a time. Concrete transports stop after the final event.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Transport subscribe errors">
    <ApiField name="NotImplementedError">
      Raised by the base implementation and by transports without streaming support.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Retry behavior">
  ProtoLink does not automatically retry or resume streams. Even when a stream failure is categorized as retryable, the exception is returned to the consumer because the transport cannot know which events were already processed.
</ApiCallout>

</ApiReference>

#### Transport.health

<ApiReference
  kind="method"
  path="Transport.health"
  signature={`transport.health() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/base.py#L163"
>

Returns a JSON-compatible point-in-time view of lifecycle state, identity, declared capabilities, and local transport metrics.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Transport health return value">
    <ApiField name="health" type="dict[str, Any]">
      Contains `status`, `ready`, `transport`, `url`, `capabilities`, and `metrics`. `status` is `"ready"` while running and `"stopped"` otherwise.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Custom transport contract

A custom transport subclasses `Transport`, calls `super().__init__(config=config)`, declares its class capabilities, and implements `send`, `setup_routes`, `start`, `stop`, `validate_url`, and `url`. Streaming transports also override `subscribe`.

The split is intentional: the custom class implements the wire protocol, while the inherited helpers preserve the same safety contract as built-in transports. A typical outbound implementation creates a request context, checks the request size, enters `request_slot()`, and calls `run_with_retries()` around the actual protocol operation. An inbound implementation enters `inbound_request_slot()`, claims any idempotency key, invokes the endpoint, checks the response, and then completes or aborts the idempotent result.

The base class exposes reusable extension hooks so custom transports can preserve the built-in operational contract:

<ApiSection title="Correlation, payloads, and retries">
  <ApiFields ariaLabel="Transport reliability extension methods">
    <ApiField name="new_request_context(request_spec, data=None)" type="TransportRequestContext">
      Generates a correlation ID and, for idempotent specifications, a stable operation key derived from `id`, `task_id`, `agent_url`, or the generated request ID.
    </ApiField>
    <ApiField name="payload_size(payload)" type="int">
      Returns the UTF-8 byte length after ProtoLink's recursive JSON normalization.
    </ApiField>
    <ApiField name="check_payload_limit(payload, *, kind, url=None)" type="int">
      Measures and enforces the configured `"request"`, `"response"`, or `"event"` limit, returning the measured byte count or raising `TransportLimitError`.
    </ApiField>
    <ApiField name="run_with_retries(request_spec, context, operation)" type="Awaitable[Any]">
      Executes an async operation with request outcome metrics and the configured eligibility, backoff, and jitter rules. Ordinary application exceptions are recorded and re-raised without retry.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Concurrency">
  <ApiFields ariaLabel="Transport concurrency extension methods">
    <ApiField name="request_slot()" type="AsyncContextManager[None]">
      Bounds outbound unary work and records admission. Pair it with `run_with_retries()` for complete outcome metrics.
    </ApiField>
    <ApiField name="inbound_request_slot()" type="AsyncContextManager[None]">
      Bounds inbound unary handler work and records success, failure, latency, and active-request gauges.
    </ApiField>
    <ApiField name="stream_slot()" type="AsyncContextManager[None]">
      Bounds a complete stream lifetime and records stream completion, failure, cancellation, and active-stream gauges.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Loop-owned resources">
  <ApiFields ariaLabel="Transport resource extension methods">
    <ApiField name="register_loop_resource(key, closer)" type="None">
      Records an async closer together with the event loop that owns its client connection or channel.
    </ApiField>
    <ApiField name="discard_loop_resource(key)" type="None">
      Removes a resource already invalidated or closed.
    </ApiField>
    <ApiField name="close_loop_resources()" type="Awaitable[None]">
      Runs every closer on its owning live loop, applying `shutdown_timeout` to each one. Cleanup timeouts and closer failures are suppressed; resources owned by closed loops are forgotten.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Idempotency">
  <ApiFields ariaLabel="Transport idempotency extension methods">
    <ApiField name="acquire_idempotent_response(key)" type="Awaitable[tuple[bool, Any | None]]">
      Claims a new operation or waits for/replays an existing one. A `None` key always returns ownership without caching.
    </ApiField>
    <ApiField name="complete_idempotent_response(key, response)" type="None">
      Publishes a completed response to concurrent waiters and retains it under the configured TTL and cache size.
    </ApiField>
    <ApiField name="abort_idempotent_response(key, error)" type="None">
      Releases concurrent waiters with the failure and removes the in-flight claim so a later request may try again.
    </ApiField>
  </ApiFields>
</ApiSection>

These hooks are an extension API for transport authors. Normal agent applications should configure the transport and call `AgentClient`, not manually coordinate slots or idempotency ownership.

#### Internal instance state

The base constructor creates the following private variables. They explain lifecycle behavior but are not a public mutation surface:

These variables are documented so transport authors can understand ownership and debugging output, not so applications can modify them. In particular, asyncio semaphores and client connections belong to the event loop that created them. The per-loop maps prevent an Agent started in a background thread from accidentally reusing an asyncio resource on the caller's loop.

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

### TransportMetricsSnapshot

<ApiReference
  kind="dataclass"
  path="protolink.TransportMetricsSnapshot"
  signature={`TransportMetricsSnapshot(
    requests_started: int = 0,
    requests_succeeded: int = 0,
    requests_failed: int = 0,
    retries: int = 0,
    streams_started: int = 0,
    streams_completed: int = 0,
    streams_failed: int = 0,
    active_requests: int = 0,
    active_streams: int = 0,
    bytes_sent: int = 0,
    bytes_received: int = 0,
    total_latency_ms: float = 0.0,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/metrics.py#L11"
>

`transport.metrics` returns a new immutable snapshot without resetting counters. Values are local to one transport instance and reset with the process.

<ApiSection title="Fields">
  <ApiFields ariaLabel="TransportMetricsSnapshot fields">
    <ApiField name="requests_started" type="int" defaultValue="0">
      Unary operations admitted by this instance. Runtime calls can increment both the caller's outbound and target's inbound instance independently.
    </ApiField>
    <ApiField name="requests_succeeded" type="int" defaultValue="0">
      Unary operations completed successfully.
    </ApiField>
    <ApiField name="requests_failed" type="int" defaultValue="0">
      Unary operations ending in an exception or terminal transport failure.
    </ApiField>
    <ApiField name="retries" type="int" defaultValue="0">
      Additional attempts started by `RetryPolicy`, excluding the initial attempt.
    </ApiField>
    <ApiField name="streams_started" type="int" defaultValue="0">
      Stream lifetimes admitted by this instance.
    </ApiField>
    <ApiField name="streams_completed" type="int" defaultValue="0">
      Streams that exited normally.
    </ApiField>
    <ApiField name="streams_failed" type="int" defaultValue="0">
      Streams that exited with an exception or cancellation.
    </ApiField>
    <ApiField name="active_requests" type="int" defaultValue="0">
      Current unary-operation gauge.
    </ApiField>
    <ApiField name="active_streams" type="int" defaultValue="0">
      Current stream gauge.
    </ApiField>
    <ApiField name="bytes_sent" type="int" defaultValue="0">
      Estimated normalized payload bytes attempted by outbound work. Retried wire attempts add their bytes again.
    </ApiField>
    <ApiField name="bytes_received" type="int" defaultValue="0">
      Estimated normalized result bytes accepted by outbound work.
    </ApiField>
    <ApiField name="total_latency_ms" type="float" defaultValue="0.0">
      Cumulative unary latency; this is neither an average nor a histogram.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="TransportMetricsSnapshot methods">
    <ApiField name="to_dict()" type="dict[str, Any]">
      Produces the exact JSON-compatible mapping embedded in `health()`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Observability scope">
  These counters are deliberately dependency-free and process-local. Export snapshots periodically or use ProtoLink telemetry when measurements must survive restarts. Set `collect_metrics=False` when another layer owns all measurement.
</ApiCallout>

</ApiReference>

For a rough average unary latency, divide `total_latency_ms` by the number of completed requests (`requests_succeeded + requests_failed`). Do not use this value as a percentile: a cumulative total cannot show whether a small number of requests were unusually slow.

### Transport errors

<ApiReference
  kind="exception"
  path="protolink.TransportError"
  signature={`TransportError(
    message: str,
    *,
    url: str | None = None,
    request_id: str | None = None,
    retryable: bool = False,
    status_code: int | str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/errors.py#L6"
>

Base exception for protocol-neutral transport failures. Typed subclasses let callers react without parsing messages or knowing whether HTTP, gRPC, WebSocket, SSE, or Runtime carried the request.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TransportError parameters">
    <ApiField name="message" type="str" required>
      Human-readable description passed to `Exception`.
    </ApiField>
    <ApiField name="url" type="str | None" defaultValue="None">
      Local or remote endpoint associated with the failure.
    </ApiField>
    <ApiField name="request_id" type="str | None" defaultValue="None">
      Correlation identifier for the logical request.
    </ApiField>
    <ApiField name="retryable" type="bool" defaultValue="False">
      Whether the failure category permits a retry. The request specification, method, and retry policy must also allow one.
    </ApiField>
    <ApiField name="status_code" type="int | str | None" defaultValue="None">
      Optional HTTP integer or protocol-native string such as a gRPC status name.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Subclasses">
  <ApiFields ariaLabel="TransportError subclasses">
    <ApiField name="TransportConnectionError" type="TransportError, ConnectionError">
      Connection establishment, retention, or peer-availability failure.
    </ApiField>
    <ApiField name="TransportTimeoutError" type="TransportError, TimeoutError">
      Request or stream deadline expiry.
    </ApiField>
    <ApiField name="TransportProtocolError" type="TransportError, RuntimeError">
      Invalid JSON or envelope shape, a mismatched request ID, or an incompatible wire response.
    </ApiField>
    <ApiField name="TransportRemoteError" type="TransportError, RuntimeError">
      A reachable peer returns an HTTP/gRPC status or protocol error result.
    </ApiField>
    <ApiField name="TransportLimitError" type="TransportError, ValueError">
      A serialized request, response, or event exceeds its configured byte limit.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

`retryable` describes the failure category only; the request spec and method must still permit retries. `status_code` is an HTTP integer or protocol-native string such as a gRPC status name. `request_id` lets logs and traces correlate the exception with request headers or envelopes.

The subclasses also inherit familiar Python exception types where useful. For example, `TransportConnectionError` is both a `TransportError` and a `ConnectionError`. Existing code that catches the standard exception remains compatible, while new code can use the richer transport metadata.

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

Health endpoints exist for process managers, container orchestrators, load balancers, and human diagnostics. They provide a cheap answer without submitting a real task or requiring model-provider access.

- `transport.health()` is useful from Python code and always returns JSON-safe data.
- `GET /healthz` and `GET /readyz` expose the same conservative payload over HTTP-compatible Agent and Registry servers.
- The `ready` field is `True` only after the transport starts serving and becomes `False` after shutdown.

ProtoLink currently gives both HTTP probe paths the same payload. Deployments can use `/healthz` for general monitoring and `/readyz` for traffic admission; the shared `ready` flag ensures a stopped transport is not treated as ready for requests.

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

Configure TLS on the network transport that owns the socket and certificate identity:

```python
from protolink import Agent, AgentCard, TLSConfig
from protolink.transport import HTTPTransport

tls = TLSConfig(
    certfile="certs/agent.pem",
    keyfile="certs/agent-key.pem",
    cafile="certs/ca.pem",
)

card = AgentCard(
    name="secure-agent",
    description="Agent served over HTTPS",
    url="https://agent.internal:8443",
)
transport = HTTPTransport(
    url=card.url,
    tls=tls,
)
agent = Agent(card=card, transport=transport)
```

The URL scheme activates encryption. The transport name does not change:

| Transport | Plain URL | TLS URL |
|-----------|-----------|---------|
| HTTP and SSE JSON-RPC | `http://` | `https://` |
| WebSocket | `ws://` | `wss://` |
| gRPC | `grpc://` | `grpcs://` |
| Runtime | `runtime://` | Not applicable; no network socket |

`certfile` and `keyfile` form the local certificate identity. A secure server URL requires both. `cafile` supplies trusted certificate authorities; outbound clients use the operating system trust store when it is omitted. Hostname verification is enabled by default and should remain enabled in production.

### TLSConfig

<ApiReference
  kind="dataclass"
  path="protolink.TLSConfig"
  signature={`TLSConfig(
    certfile: str | os.PathLike[str] | None = None,
    keyfile: str | os.PathLike[str] | None = None,
    cafile: str | os.PathLike[str] | None = None,
    require_client_cert: bool = False,
    check_hostname: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/security/tls.py#L20"
>

Immutable certificate configuration shared by HTTP/SSE, WebSocket, and gRPC. Path-like values are normalized with `os.fspath()` during construction; certificate contents are loaded only when a context or credential bundle is created.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TLSConfig parameters">
    <ApiField name="certfile" type="str | os.PathLike[str] | None" defaultValue="None">
      PEM certificate chain presented by a secure server or an mTLS client.
    </ApiField>
    <ApiField name="keyfile" type="str | os.PathLike[str] | None" defaultValue="None">
      PEM private key matching `certfile`. Identity files must be supplied together.
    </ApiField>
    <ApiField name="cafile" type="str | os.PathLike[str] | None" defaultValue="None">
      PEM CA bundle used to verify peers. Client contexts use system trust roots when omitted.
    </ApiField>
    <ApiField name="require_client_cert" type="bool" defaultValue="False">
      Requires every inbound TLS client to present a certificate trusted by `cafile`.
    </ApiField>
    <ApiField name="check_hostname" type="bool" defaultValue="True">
      Enables outbound certificate hostname verification. Turning it off does not disable CA verification.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="TLSConfig attributes">
    <ApiField name="has_identity" type="bool">
      `True` when both certificate and private-key paths are present.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Methods">
  <ApiFields ariaLabel="TLSConfig methods">
    <ApiField name="create_server_context()" type="ssl.SSLContext">
      Builds a TLS 1.2-or-newer server context, loads the certificate chain, and configures optional client-certificate verification.
    </ApiField>
    <ApiField name="create_client_context()" type="ssl.SSLContext">
      Builds a verified client context using `cafile` or system roots, applies hostname policy, and loads the optional mTLS identity.
    </ApiField>
    <ApiField name="require_server_identity(url=None)" type="None">
      Raises `ValueError` when a secure server is started without both identity files.
    </ApiField>
    <ApiField name="identity_paths()" type="tuple[str, str]">
      Returns the certificate and key paths, first requiring that both exist in the configuration.
    </ApiField>
    <ApiField name="certificate_chain_bytes()" type="bytes | None">
      Reads the configured certificate chain for gRPC credentials.
    </ApiField>
    <ApiField name="private_key_bytes()" type="bytes | None">
      Reads the configured private key for gRPC credentials.
    </ApiField>
    <ApiField name="ca_bytes()" type="bytes | None">
      Reads the configured CA bundle, or returns `None` so the client can use system roots.
    </ApiField>
    <ApiField name="to_dict()" type="dict[str, Any]">
      Serializes file paths and verification flags; it never embeds certificate or private-key bytes.
    </ApiField>
    <ApiField name="from_dict(data)" type="TLSConfig">
      Reconstructs the configuration from serialized paths and flags.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="TLSConfig errors">
    <ApiField name="ValueError">
      Raised when only one identity file is supplied, client certificates are required without a CA file, or a server context is requested without an identity.
    </ApiField>
    <ApiField name="OSError | ssl.SSLError">
      Raised when configured files cannot be read or OpenSSL cannot load their contents.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

For a client that only calls a secure service, certificate trust is enough:

```python
from protolink import TLSConfig
from protolink.client import AgentClient
from protolink.transport import GRPCTransport

transport = GRPCTransport(
    url="grpc://127.0.0.1:0",
    tls=TLSConfig(cafile="certs/ca.pem"),
)
client = AgentClient(transport)
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

Directly constructed `HTTPTransport`, `SSEJSONRPCTransport`, `WebSocketTransport`, and `GRPCTransport` instances accept `tls=`. `Agent`, `AgentClient`, and `Registry` keep transport security out of their constructors: pass a configured transport object instead. `Agent.to_dict()` and `to_yaml()` serialize certificate paths inside the transport block; private-key contents are never embedded.

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
| `GET /.well-known/agent-card.json` | Return the standard A2A 1.0 Agent Card. | Yes, JSON document; exact HTTP plus `a2a=True` only |
| `POST /` | Handle A2A 1.0 JSON-RPC task operations. | No, JSON API; exact HTTP plus `a2a=True` only |
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

`HTTPTransport` is the main network transport for communication in Protolink. It handles native Agent-to-Agent JSON HTTP APIs and Registry operations. On an `Agent`, `a2a=True` adds the canonical A2A 1.0 inbound routes and enables outbound translation through the same transport, preserving its TLS, authentication, pooling, limits, and metrics.

### Overview

- **Client side**
  - Uses `httpx.AsyncClient` to send JSON requests to other agents or registries.
  - Implements the generic `send` method to dispatch requests defined by `ClientRequestSpec`.

- **Server side**
  - Uses an ASGI app (Starlette or FastAPI) to expose endpoints like:
    - `POST /tasks/` - submit a `Task` to the agent.
    - `POST /tasks/cancel` - request best-effort cancellation of an active task ID.
    - `GET /.well-known/agent.json` - agent metadata.
    - `GET /.well-known/agent-card.json` and `POST /` - A2A 1.0 discovery and JSON-RPC when the Agent uses `a2a=True`.
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

ProtoLink's native `POST /tasks/cancel` endpoint accepts a task-ID payload such as `{"id": "task-id", "metadata": {"reason": "Stopped by user"}}`. The response is the updated serialized `Task`. The endpoint controls active execution only; it is not a durable task lookup API. The A2A 1.0 HTTP adapter exposes the canonical `CancelTask` operation separately.

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
| `role`      | `"user"` ⎪ `"agent"` ⎪ `"assistant"` ⎪ `"system"` | Sender role.               |
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
| `name`        | `str` ⎪ `null`    | Optional display or resource name. |
| `uri`         | `str` ⎪ `null`    | Optional URI identifying the represented resource. |
| `media_type`  | `str` ⎪ `null`    | Optional MIME type describing the artifact as a whole. |
| `action_id`   | `str` ⎪ `null`    | Optional ID of the `RunAction` that produced this artifact. |

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

#### HTTPTransport

<ApiReference
  kind="class"
  path="protolink.transport.HTTPTransport"
  signature={`HTTPTransport(
    url: str,
    timeout: float = 360.0,
    authenticator: Authenticator | None = None,
    backend: Literal["starlette", "fastapi"] = "starlette",
    *,
    validate_schema: bool = False,
    credentials: str | None = None,
    tls: TLSConfig | None = None,
    config: TransportConfig | None = None,
    log_level: str = "info",
    access_log: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/http_transport.py#L40"
>

Dual-role HTTP client/server transport. It mounts an ASGI backend for inbound endpoints and keeps a separate pooled `httpx.AsyncClient` for each event loop that performs outbound work.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HTTPTransport constructor parameters">
    <ApiField name="url" type="str" required>
      Server identity and bind URL. Use `http://` for cleartext or `https://` for native TLS.
    </ApiField>
    <ApiField name="timeout" type="float" defaultValue="360.0">
      Deadline in seconds for each outbound HTTP request.
    </ApiField>
    <ApiField name="authenticator" type="Authenticator | None" defaultValue="None">
      Optional provider used by `authenticate()` to obtain an outbound security context.
    </ApiField>
    <ApiField name="backend" type={'Literal["starlette", "fastapi"]'} defaultValue={'"starlette"'}>
      ASGI implementation. The current constructor selects FastAPI when `backend.lower() == "fastapi"`; every other value, including an unrecognized one, falls back to Starlette.
    </ApiField>
    <ApiField name="validate_schema" type="bool" defaultValue="False">
      Enables backend request-schema validation where supported.
    </ApiField>
    <ApiField name="credentials" type="str | None" defaultValue="None">
      Credentials retained for authentication headers or a later `authenticate()` call.
    </ApiField>
    <ApiField name="tls" type="TLSConfig | None" defaultValue="None">
      Certificate identity and trust settings. An HTTPS server requires a local identity.
    </ApiField>
    <ApiField name="config" type="TransportConfig | None" defaultValue="None">
      Shared limits, retries, keepalive, cleanup, idempotency, and metrics policy.
    </ApiField>
    <ApiField name="log_level" type="str" defaultValue={'"info"'}>
      Uvicorn log level forwarded to the selected backend.
    </ApiField>
    <ApiField name="access_log" type="bool" defaultValue="True">
      Enables Uvicorn request-access logging.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="HTTPTransport attributes">
    <ApiField name="url" type="str">
      Read-only configured base URL.
    </ApiField>
    <ApiField name="timeout" type="float">
      Read/write deadline used by future requests, including requests sent through an already-created client pool.
    </ApiField>
    <ApiField name="config" type="TransportConfig">
      Effective shared configuration.
    </ApiField>
    <ApiField name="capabilities" type="TransportCapabilities">
      Networked, TLS-capable, persistent, unary-only declaration.
    </ApiField>
    <ApiField name="metrics" type="TransportMetricsSnapshot">
      Current immutable counter snapshot.
    </ApiField>
    <ApiField name="is_running" type="bool">
      Whether the ASGI backend is currently serving.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Lifecycle and routing">
  <ApiFields ariaLabel="HTTPTransport lifecycle methods">
    <ApiField name="setup_routes(endpoints)" type="None">
      Mounts `EndpointSpec` values on the selected backend. `AgentServer` and `RegistryServer` call this before startup.
    </ApiField>
    <ApiField name="start()" type="Awaitable[None]">
      Starts the backend, marks the transport running, and primes a client for the current loop. Calling it while running is a no-op.
    </ApiField>
    <ApiField name="stop()" type="Awaitable[None]">
      Stops the backend, closes all loop-local clients on their owning loops, and clears lifecycle state. Repeated calls are safe.
    </ApiField>
    <ApiField name="validate_url()" type="bool">
      Returns `True` for configured `http://` and `https://` URLs.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### HTTPTransport.send

<ApiReference
  kind="async method"
  path="HTTPTransport.send"
  signature={`await transport.send(
    request_spec: ClientRequestSpec,
    base_url: str,
    data: Any = None,
    params: dict[str, Any] | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/http_transport.py#L146"
>

Serializes and size-checks one unary operation, applies correlation, idempotency, and authentication headers, and parses the JSON response through the request specification.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HTTPTransport send parameters">
    <ApiField name="request_spec" type="ClientRequestSpec" required>
      Supplies the HTTP method, path, parsers, and retry/idempotency metadata.
    </ApiField>
    <ApiField name="base_url" type="str" required>
      Destination HTTP or HTTPS base URL.
    </ApiField>
    <ApiField name="data" type="Any" defaultValue="None">
      Optional JSON body.
    </ApiField>
    <ApiField name="params" type="dict[str, Any] | None" defaultValue="None">
      Optional URL query parameters.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="HTTPTransport send return value">
    <ApiField name="result" type="Any">
      Parsed response returned by `request_spec.response_parser`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="HTTPTransport send errors">
    <ApiField name="TransportTimeoutError">
      The `httpx` request exceeded `timeout`; marked retryable.
    </ApiField>
    <ApiField name="TransportConnectionError">
      Connection establishment failed; marked retryable.
    </ApiField>
    <ApiField name="TransportProtocolError">
      The peer disconnected at the HTTP protocol layer, returned invalid JSON, or produced another incompatible response. Remote-protocol disconnects are retryable; malformed JSON is not.
    </ApiField>
    <ApiField name="TransportRemoteError">
      The peer returned an HTTP error. Status `429` and `5xx` are categorized as retryable; the request policy still decides whether another attempt occurs.
    </ApiField>
    <ApiField name="TransportLimitError">
      The normalized request or response exceeds its configured limit.
    </ApiField>
    <ApiField name="response parser error">
      Exceptions raised by `request_spec.response_parser` propagate unchanged.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### HTTPTransport.authenticate

<ApiReference
  kind="async method"
  path="HTTPTransport.authenticate"
  signature={`await transport.authenticate(
    credentials: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/http_transport.py#L353"
>

Asks the configured authenticator to create an outbound security context. Future sends translate that context into protocol headers.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HTTPTransport authenticate parameters">
    <ApiField name="credentials" type="str" required>
      Secret or token understood by the configured `Authenticator`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="HTTPTransport authenticate errors">
    <ApiField name="RuntimeError">
      Raised when no authenticator was configured.
    </ApiField>
    <ApiField name="authentication error">
      Errors raised by the authenticator propagate unchanged.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

---

## RuntimeTransport

`RuntimeTransport` is an in-process, in-memory transport that enables agents to communicate directly without network overhead. Perfect for testing, local multi-agent setups, and rapid prototyping.

### Overview

Unlike network transports (HTTP, WebSocket), RuntimeTransport avoids actual TCP I/O. However, it perfectly mirrors the behavioral boundaries of `HTTPTransport` ensuring seamless interchangeability:

- **Strict URL Routing** - each agent transport is initialized explicitly with a unique URL (e.g., `runtime://agent-name`).
- **Process-local registry** - started transports discover one another through a shared class-level dictionary. The dictionary has no locking; coordinate start/stop when multiple OS threads manage Runtime transports.
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

#### RuntimeTransport

<ApiReference
  kind="class"
  path="protolink.transport.RuntimeTransport"
  signature={`RuntimeTransport(
    url: str,
    *,
    config: TransportConfig | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/runtime_transport.py#L31"
>

Process-local transport that routes calls through registered Python objects while retaining the same serialization, byte-limit, concurrency, retry, idempotency, metrics, and endpoint-parser boundaries as network transports.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RuntimeTransport constructor parameters">
    <ApiField name="url" type="str" required>
      Unique process-local identity, conventionally using `runtime://`. Construction stores the value but does not reject an invalid scheme.
    </ApiField>
    <ApiField name="config" type="TransportConfig | None" defaultValue="None">
      Shared operational configuration.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="RuntimeTransport attributes">
    <ApiField name="url" type="str">
      Read-only registry key.
    </ApiField>
    <ApiField name="is_running" type="bool">
      Whether this instance is currently registered.
    </ApiField>
    <ApiField name="config" type="TransportConfig">
      Effective shared configuration.
    </ApiField>
    <ApiField name="capabilities" type="TransportCapabilities">
      In-process, streaming, non-networked capability declaration.
    </ApiField>
    <ApiField name="metrics" type="TransportMetricsSnapshot">
      Current immutable request, stream, retry, byte, and latency snapshot.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Lifecycle and lookup">
  <ApiFields ariaLabel="RuntimeTransport lifecycle methods">
    <ApiField name="get_transport(base_url)" type="RuntimeTransport | None">
      Class method returning the instance registered under `base_url`.
    </ApiField>
    <ApiField name="setup_routes(endpoints)" type="None">
      Adds or replaces cached endpoint specifications by uppercase method and path; entries omitted from a later call remain until `stop()` clears the cache.
    </ApiField>
    <ApiField name="start()" type="Awaitable[None]">
      Registers `self` under its URL and marks it running. Calling it while already running is a no-op.
    </ApiField>
    <ApiField name="stop()" type="Awaitable[None]">
      Unregisters the instance, clears every cached endpoint, and marks it stopped.
    </ApiField>
    <ApiField name="validate_url()" type="bool">
      Returns `True` when the configured URL starts with `runtime://`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Restart behavior">
  `stop()` clears the route cache. To restart the same low-level transport instance directly, call `setup_routes()` again before `start()`; the normal Agent/Registry server lifecycle performs route setup for you.
</ApiCallout>

<ApiCallout label="Threading">
  The class registry is an ordinary dictionary, not a thread-safe coordination service. Calls and asyncio concurrency are supported, but applications that start or stop Runtime transports from several OS threads must serialize those lifecycle changes.
</ApiCallout>

</ApiReference>

#### RuntimeTransport.send

<ApiReference
  kind="async method"
  path="RuntimeTransport.send"
  signature={`await transport.send(
    request_spec: ClientRequestSpec,
    base_url: str,
    data: Any = None,
    params: dict[str, Any] | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/runtime_transport.py#L106"
>

Finds the target instance and endpoint in memory and crosses the request and response parser boundaries. The caller enforces payload limits and an outbound request slot; the target independently enforces an inbound request slot.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RuntimeTransport send parameters">
    <ApiField name="request_spec" type="ClientRequestSpec" required>
      Method/path contract, parsers, and retry/idempotency declaration.
    </ApiField>
    <ApiField name="base_url" type="str" required>
      URL of a started Runtime transport in this process.
    </ApiField>
    <ApiField name="data" type="Any" defaultValue="None">
      Optional payload passed through the request parser.
    </ApiField>
    <ApiField name="params" type="dict[str, Any] | None" defaultValue="None">
      Accepted for transport-interface symmetry. The current Runtime implementation discards this value before endpoint invocation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="RuntimeTransport send return value">
    <ApiField name="result" type="Any">
      Parsed response from the matching target handler.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RuntimeTransport send errors">
    <ApiField name="TransportConnectionError">
      No started target is registered at `base_url`; marked retryable.
    </ApiField>
    <ApiField name="TransportRemoteError">
      No endpoint matches the method/path (`status_code=404`) or the endpoint/parser raises unexpectedly. Handler failures are wrapped as non-retryable remote errors.
    </ApiField>
    <ApiField name="TransportLimitError">
      Either instance rejects the normalized request or response size.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### RuntimeTransport.subscribe

<ApiReference
  kind="async iterator method"
  path="RuntimeTransport.subscribe"
  signature={`transport.subscribe(
    agent_url: str,
    task: Task,
) -> AsyncIterator[dict[str, Any]]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/runtime_transport.py#L278"
>

Streams task events directly from a target endpoint. If the target exposes no streaming endpoint, Runtime submits the task through its unary endpoint and yields one synthesized final event.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RuntimeTransport subscribe parameters">
    <ApiField name="agent_url" type="str" required>
      URL of the started target Runtime transport.
    </ApiField>
    <ApiField name="task" type="Task" required>
      Task sent to the target's streaming or unary fallback endpoint.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="RuntimeTransport subscribe yielded values">
    <ApiField name="event" type="dict[str, Any]">
      Normalized endpoint events, each checked against `max_event_bytes`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RuntimeTransport subscribe errors">
    <ApiField name="TransportConnectionError">
      The target is not registered.
    </ApiField>
    <ApiField name="TransportRemoteError">
      The selected streaming handler does not return an async iterator.
    </ApiField>
    <ApiField name="TransportLimitError">
      The caller's normalized task, unary fallback result, or a yielded event exceeds its limit.
    </ApiField>
    <ApiField name="parser or handler error">
      Exceptions raised while parsing the task or running the live-stream handler propagate unchanged.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="No stream retries">
  `subscribe()` is never passed through `run_with_retries()`. Consumers decide how to checkpoint and resume a failed event sequence.
</ApiCallout>

</ApiReference>

### Key Differences from HTTPTransport

| Aspect | HTTPTransport | RuntimeTransport |
|--------|---------------|------------------|
| Network | HTTP over TCP | Direct in-memory calls through a process-local class registry |
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

#### WebSocketTransport

<ApiReference
  kind="class"
  path="protolink.transport.WebSocketTransport"
  signature={`WebSocketTransport(
    url: str,
    timeout: float = 360.0,
    authenticator: Authenticator | None = None,
    credentials: str | None = None,
    *,
    tls: TLSConfig | None = None,
    config: TransportConfig | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/websocket_transport.py#L36"
>

Bidirectional JSON-envelope transport with loop-local persistent connections. Unary requests are serialized per connection, and request specifications marked for the control channel use a separate connection so cancellation does not wait behind active default-channel work.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="WebSocketTransport constructor parameters">
    <ApiField name="url" type="str" required>
      Server identity and bind URL using `ws://` or `wss://`.
    </ApiField>
    <ApiField name="timeout" type="float" defaultValue="360.0">
      Receive deadline in seconds for outbound unary calls and stream reads.
    </ApiField>
    <ApiField name="authenticator" type="Authenticator | None" defaultValue="None">
      Optional provider used to create outbound authentication headers.
    </ApiField>
    <ApiField name="credentials" type="str | None" defaultValue="None">
      Credentials retained for the authentication workflow.
    </ApiField>
    <ApiField name="tls" type="TLSConfig | None" defaultValue="None">
      Certificate and trust settings. A WSS server requires a local identity; clients without an explicit configuration use the WebSocket library's default verified TLS behavior.
    </ApiField>
    <ApiField name="config" type="TransportConfig | None" defaultValue="None">
      Frame limits, slots, ping/pong keepalive, retry, shutdown, idempotency, and metrics policy.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="WebSocketTransport attributes">
    <ApiField name="url" type="str">
      Read-only configured URL.
    </ApiField>
    <ApiField name="timeout" type="float">
      Read/write receive deadline applied to subsequent operations.
    </ApiField>
    <ApiField name="config" type="TransportConfig">
      Effective shared configuration.
    </ApiField>
    <ApiField name="capabilities" type="TransportCapabilities">
      Networked, streaming, TLS-capable, bidirectional, persistent declaration.
    </ApiField>
    <ApiField name="metrics" type="TransportMetricsSnapshot">
      Current immutable unary and stream counters.
    </ApiField>
    <ApiField name="is_running" type="bool">
      Whether the WebSocket server is accepting connections.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Lifecycle and routing">
  <ApiFields ariaLabel="WebSocketTransport lifecycle methods">
    <ApiField name="setup_routes(endpoints)" type="None">
      Caches endpoint specifications for method/path frame dispatch.
    </ApiField>
    <ApiField name="start()" type="Awaitable[None]">
      Starts the server with configured frame, queue, ping, TLS, and concurrency settings. Calling it while running is a no-op.
    </ApiField>
    <ApiField name="stop()" type="Awaitable[None]">
      Closes loop-local client connections, locks, and the server, then marks the transport stopped.
    </ApiField>
    <ApiField name="validate_url()" type="bool">
      Returns `True` for configured `ws://` and `wss://` URLs.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="WebSocketTransport lifecycle errors">
    <ApiField name="ImportError">
      Importing this transport fails when the optional `websockets` dependency is unavailable.
    </ApiField>
    <ApiField name="ValueError">
      `start()` requires a hostname and an explicit port. Default ports are not inferred from `ws` or `wss`; secure startup also requires a TLS identity.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### WebSocketTransport.send

<ApiReference
  kind="async method"
  path="WebSocketTransport.send"
  signature={`await transport.send(
    request_spec: ClientRequestSpec,
    base_url: str,
    data: Any = None,
    params: dict[str, Any] | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/websocket_transport.py#L229"
>

Sends one correlated JSON request envelope and waits under the connection's lock for the matching response. The lock prevents interleaved unary responses on the same channel.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="WebSocketTransport send parameters">
    <ApiField name="request_spec" type="ClientRequestSpec" required>
      Supplies method, path, channel, parsers, and idempotency metadata.
    </ApiField>
    <ApiField name="base_url" type="str" required>
      Destination WebSocket URL.
    </ApiField>
    <ApiField name="data" type="Any" defaultValue="None">
      Optional envelope payload.
    </ApiField>
    <ApiField name="params" type="dict[str, Any] | None" defaultValue="None">
      Optional envelope parameters.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="WebSocketTransport send return value">
    <ApiField name="result" type="Any">
      Parsed `result` from the matching successful envelope.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="WebSocketTransport send errors">
    <ApiField name="TransportTimeoutError">
      No response arrived before `timeout`; marked retryable.
    </ApiField>
    <ApiField name="TransportConnectionError">
      The connection closed while waiting; marked retryable.
    </ApiField>
    <ApiField name="TransportProtocolError">
      The response is invalid JSON, has the wrong request ID, or violates the envelope contract. The cached connection is discarded.
    </ApiField>
    <ApiField name="TransportRemoteError">
      The peer returned an `ok: false` envelope.
    </ApiField>
    <ApiField name="TransportLimitError">
      A request or response exceeds its configured normalized size.
    </ApiField>
    <ApiField name="response parser error">
      Parser exceptions propagate unchanged.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Cancellation">
  Cancelling the coroutine propagates `CancelledError` and discards its connection, preventing a late frame from being mistaken for the next request's response.
</ApiCallout>

</ApiReference>

#### WebSocketTransport.subscribe

<ApiReference
  kind="async iterator method"
  path="WebSocketTransport.subscribe"
  signature={`transport.subscribe(
    agent_url: str,
    task: Any,
) -> AsyncIterator[Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/websocket_transport.py#L297"
>

Submits a task to `/tasks/stream` and holds the selected connection lock until a final event arrives or the stream exits.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="WebSocketTransport subscribe parameters">
    <ApiField name="agent_url" type="str" required>
      Destination WebSocket URL.
    </ApiField>
    <ApiField name="task" type="Any" required>
      Task payload for the stream endpoint.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="WebSocketTransport subscribe yielded values">
    <ApiField name="event" type="Any">
      Each successful envelope's normalized result, up to and including the event marked final.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="WebSocketTransport subscribe errors">
    <ApiField name="TransportTimeoutError | TransportConnectionError">
      The read timed out or the connection closed. The error category may be retryable, but the stream is not retried automatically.
    </ApiField>
    <ApiField name="TransportProtocolError | TransportRemoteError">
      The peer sent an invalid/mismatched envelope or an explicit remote error.
    </ApiField>
    <ApiField name="TransportLimitError">
      The task or an event exceeds its configured limit.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Connection scheduling">
  The default-channel lock is held for the complete stream, so unary calls on that same connection wait. Control-plane requests use their dedicated channel and remain independent.
</ApiCallout>

</ApiReference>

#### WebSocketTransport.authenticate

<ApiReference
  kind="async method"
  path="WebSocketTransport.authenticate"
  signature={`await transport.authenticate(
    credentials: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/websocket_transport.py#L516"
>

Creates an outbound authentication context whose headers are included in later WebSocket upgrade handshakes.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="WebSocketTransport authenticate parameters">
    <ApiField name="credentials" type="str" required>
      Secret or token understood by the configured authenticator.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="WebSocketTransport authenticate errors">
    <ApiField name="RuntimeError">
      Raised when no authenticator was configured.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

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

#### GRPCTransport

<ApiReference
  kind="class"
  path="protolink.transport.GRPCTransport"
  signature={`GRPCTransport(
    url: str,
    timeout: float = 360.0,
    authenticator: Authenticator | None = None,
    credentials: str | None = None,
    *,
    channel_options: list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None = None,
    server_options: list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None = None,
    compression: Any | None = None,
    maximum_concurrent_rpcs: int | None = None,
    graceful_shutdown_timeout: float = 3.0,
    tls: TLSConfig | None = None,
    config: TransportConfig | None = None,
    enable_health: bool = True,
    enable_reflection: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/grpc_transport.py#L41"
>

Generic `grpc.aio` client/server transport. It multiplexes transport-neutral endpoint specifications over one unary `Invoke` method and one unary-stream `Stream` method and keeps outbound channels isolated per event loop.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="GRPCTransport constructor parameters">
    <ApiField name="url" type="str" required>
      Server identity and bind URL using `grpc://` or `grpcs://`.
    </ApiField>
    <ApiField name="timeout" type="float" defaultValue="360.0">
      Deadline in seconds for future outbound RPCs.
    </ApiField>
    <ApiField name="authenticator" type="Authenticator | None" defaultValue="None">
      Optional provider used for inbound metadata validation and outbound auth metadata.
    </ApiField>
    <ApiField name="credentials" type="str | None" defaultValue="None">
      Raw credentials authenticated lazily before the first outbound request.
    </ApiField>
    <ApiField name="channel_options" type="list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None" defaultValue="None">
      Low-level client-channel options. Explicit keys replace keepalive and message limits derived from `config`.
    </ApiField>
    <ApiField name="server_options" type="list[tuple[str, Any]] | tuple[tuple[str, Any], ...] | None" defaultValue="None">
      Low-level server options. Explicit keys replace derived receive/send limits.
    </ApiField>
    <ApiField name="compression" type="Any | None" defaultValue="None">
      Compression value accepted by grpcio for the server and outbound calls.
    </ApiField>
    <ApiField name="maximum_concurrent_rpcs" type="int | None" defaultValue="None">
      Server-wide concurrent RPC limit. `None` uses `config.limits.max_concurrent_requests`; the current implementation also treats `0` as use-the-configured-limit.
    </ApiField>
    <ApiField name="graceful_shutdown_timeout" type="float" defaultValue="3.0">
      Seconds the gRPC server gives in-flight RPCs to finish during `stop()`. This is distinct from `config.shutdown_timeout`, which bounds loop-owned channel closers.
    </ApiField>
    <ApiField name="tls" type="TLSConfig | None" defaultValue="None">
      Certificate identity and trust settings. A GRPCS server requires an identity; a GRPCS client without this object uses system roots.
    </ApiField>
    <ApiField name="config" type="TransportConfig | None" defaultValue="None">
      Shared limits, retries, keepalive, cleanup, idempotency, and metrics policy.
    </ApiField>
    <ApiField name="enable_health" type="bool" defaultValue="True">
      Registers the standard gRPC health service when its optional support package is importable.
    </ApiField>
    <ApiField name="enable_reflection" type="bool" defaultValue="True">
      Registers server reflection when its optional support package is importable.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="GRPCTransport attributes">
    <ApiField name="url" type="str">
      Read-only configured identity URL.
    </ApiField>
    <ApiField name="timeout" type="float">
      Read/write deadline for future calls.
    </ApiField>
    <ApiField name="config" type="TransportConfig">
      Effective shared configuration.
    </ApiField>
    <ApiField name="capabilities" type="TransportCapabilities">
      Networked, streaming, TLS-capable, persistent declaration.
    </ApiField>
    <ApiField name="metrics" type="TransportMetricsSnapshot">
      Current immutable request and stream snapshot.
    </ApiField>
    <ApiField name="is_running" type="bool">
      Whether the `grpc.aio` server is serving.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Lifecycle and routing">
  <ApiFields ariaLabel="GRPCTransport lifecycle methods">
    <ApiField name="setup_routes(endpoints)" type="None">
      Caches endpoint specifications by uppercase method and path.
    </ApiField>
    <ApiField name="start()" type="Awaitable[None]">
      Starts the generic service, optional health and reflection services, and native TLS when selected. Calling it while running is a no-op.
    </ApiField>
    <ApiField name="stop()" type="Awaitable[None]">
      Marks health not-serving, gives RPCs their graceful timeout, stops the server, and closes loop-local channels.
    </ApiField>
    <ApiField name="validate_url()" type="bool">
      Returns `True` for configured `grpc://` and `grpcs://` URLs.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="GRPCTransport constructor and lifecycle errors">
    <ApiField name="ImportError">
      Construction fails when `grpcio` is not installed.
    </ApiField>
    <ApiField name="ValueError">
      `start()` requires a hostname and port; secure server startup also requires a TLS identity.
    </ApiField>
    <ApiField name="RuntimeError">
      Raised when grpcio cannot bind the requested server address.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Optional services">
  Health and reflection are registered only when their support modules import successfully. The implementation imports those modules together, so if either support package is unavailable neither optional service is installed.
</ApiCallout>

</ApiReference>

#### GRPCTransport.send

<ApiReference
  kind="async method"
  path="GRPCTransport.send"
  signature={`await transport.send(
    request_spec: ClientRequestSpec,
    base_url: str,
    data: Any = None,
    params: dict[str, Any] | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/grpc_transport.py#L241"
>

Encodes one request as JSON bytes, invokes the peer's generic unary method with auth/correlation metadata and a deadline, then parses the successful envelope.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="GRPCTransport send parameters">
    <ApiField name="request_spec" type="ClientRequestSpec" required>
      Supplies the routed method/path, parsers, and retry/idempotency declaration.
    </ApiField>
    <ApiField name="base_url" type="str" required>
      Destination gRPC or GRPCS URL.
    </ApiField>
    <ApiField name="data" type="Any" defaultValue="None">
      Optional envelope payload.
    </ApiField>
    <ApiField name="params" type="dict[str, Any] | None" defaultValue="None">
      Optional envelope parameters.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="GRPCTransport send return value">
    <ApiField name="result" type="Any">
      Parsed successful result from the response envelope.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="GRPCTransport send errors">
    <ApiField name="TransportConnectionError">
      grpcio returned `UNAVAILABLE`; marked retryable.
    </ApiField>
    <ApiField name="TransportTimeoutError">
      grpcio returned `DEADLINE_EXCEEDED`; marked retryable.
    </ApiField>
    <ApiField name="TransportRemoteError">
      Other RPC failures or an explicit remote error envelope. `RESOURCE_EXHAUSTED` and `INTERNAL` RPC statuses are categorized as retryable.
    </ApiField>
    <ApiField name="TransportProtocolError">
      A decoded response carries a non-null correlation ID different from the request ID.
    </ApiField>
    <ApiField name="TransportLimitError">
      The request or response exceeds an explicit or grpcio-derived limit.
    </ApiField>
    <ApiField name="decoder or response parser error">
      JSON/deserializer failures and exceptions raised by `request_spec.response_parser` are not wrapped by this method unless grpcio reports them as an RPC status.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### GRPCTransport.subscribe

<ApiReference
  kind="async iterator method"
  path="GRPCTransport.subscribe"
  signature={`transport.subscribe(
    agent_url: str,
    task: Any,
) -> AsyncIterator[Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/grpc_transport.py#L299"
>

Calls the generic `Stream` RPC and yields each parsed task event until an envelope is marked final.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="GRPCTransport subscribe parameters">
    <ApiField name="agent_url" type="str" required>
      Destination gRPC or GRPCS agent URL.
    </ApiField>
    <ApiField name="task" type="Any" required>
      Task payload encoded into the stream request.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="GRPCTransport subscribe yielded values">
    <ApiField name="event" type="Any">
      Each successful event result, independently checked against `max_event_bytes`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="GRPCTransport subscribe errors">
    <ApiField name="TransportConnectionError | TransportTimeoutError | TransportRemoteError">
      Translated grpcio stream failures. Some categories carry `retryable=True`, but the stream is not restarted.
    </ApiField>
    <ApiField name="TransportProtocolError | TransportLimitError">
      A decoded event has a mismatched non-null request ID, or an event exceeds its configured limit.
    </ApiField>
    <ApiField name="decoder error">
      JSON/deserializer failures are not explicitly wrapped unless grpcio reports an RPC status.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="No stream retries">
  `subscribe()` does not use the unary retry loop. The consumer owns checkpointing and resubscription after a partial sequence.
</ApiCallout>

</ApiReference>

#### GRPCTransport.authenticate

<ApiReference
  kind="async method"
  path="GRPCTransport.authenticate"
  signature={`await transport.authenticate(
    credentials: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/grpc_transport.py#L355"
>

Creates the security context translated into outbound gRPC metadata.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="GRPCTransport authenticate parameters">
    <ApiField name="credentials" type="str" required>
      Secret or token understood by the configured authenticator.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="GRPCTransport authenticate errors">
    <ApiField name="RuntimeError">
      Raised when no authenticator was configured.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

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

#### SSEJSONRPCTransport

<ApiReference
  kind="class"
  path="protolink.transport.SSEJSONRPCTransport"
  signature={`SSEJSONRPCTransport(
    url: str,
    timeout: float = 360.0,
    authenticator: Authenticator | None = None,
    backend: Literal["starlette", "fastapi"] = "starlette",
    *,
    validate_schema: bool = False,
    credentials: str | None = None,
    tls: TLSConfig | None = None,
    config: TransportConfig | None = None,
    log_level: str = "info",
    access_log: bool = True,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/sse_jsonrpc_transport.py#L23"
>

HTTPTransport subclass that keeps the inherited unary API and ASGI lifecycle while adding a one-way server-to-client task stream.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SSEJSONRPCTransport constructor parameters">
    <ApiField name="url" type="str" required>
      HTTP or HTTPS server identity and bind URL.
    </ApiField>
    <ApiField name="timeout" type="float" defaultValue="360.0">
      Deadline for inherited unary calls and for opening/reading an SSE response.
    </ApiField>
    <ApiField name="authenticator" type="Authenticator | None" defaultValue="None">
      Optional authentication provider.
    </ApiField>
    <ApiField name="backend" type={'Literal["starlette", "fastapi"]'} defaultValue={'"starlette"'}>
      Inherited ASGI backend selector.
    </ApiField>
    <ApiField name="validate_schema" type="bool" defaultValue="False">
      Enables backend request-schema validation where supported.
    </ApiField>
    <ApiField name="credentials" type="str | None" defaultValue="None">
      Credentials used by the inherited authentication workflow.
    </ApiField>
    <ApiField name="tls" type="TLSConfig | None" defaultValue="None">
      HTTPS certificate and trust settings.
    </ApiField>
    <ApiField name="config" type="TransportConfig | None" defaultValue="None">
      Shared unary and stream limits, slots, retries, cleanup, idempotency, and metrics.
    </ApiField>
    <ApiField name="log_level" type="str" defaultValue={'"info"'}>
      Uvicorn log level.
    </ApiField>
    <ApiField name="access_log" type="bool" defaultValue="True">
      Enables Uvicorn access logging.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Inherited surface">
  <ApiFields ariaLabel="SSEJSONRPCTransport inherited members">
    <ApiField name="send(...)" type="Awaitable[Any]">
      Uses `HTTPTransport.send()` for ordinary request/response calls, including its pooling, retries, limits, authentication, and error mapping.
    </ApiField>
    <ApiField name="setup_routes(...) | start() | stop()" type="inherited">
      Uses the HTTP ASGI route and lifecycle implementation. The server adds `POST /tasks/stream` from the Agent endpoint specifications.
    </ApiField>
    <ApiField name="config | metrics | url | timeout | is_running" type="inherited properties">
      Exposes the same inspection surface as HTTP, with streaming enabled in `capabilities`.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### SSEJSONRPCTransport.subscribe

<ApiReference
  kind="async iterator method"
  path="SSEJSONRPCTransport.subscribe"
  signature={`transport.subscribe(
    agent_url: str,
    task: Any,
) -> AsyncIterator[Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/transport/sse_jsonrpc_transport.py#L40"
>

Posts a task to `/tasks/stream`, parses `text/event-stream` data frames as ProtoLink JSON-RPC envelopes, and yields each successful result.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SSEJSONRPCTransport subscribe parameters">
    <ApiField name="agent_url" type="str" required>
      Destination HTTP or HTTPS agent URL.
    </ApiField>
    <ApiField name="task" type="Any" required>
      Task encoded as the request JSON body.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Yields">
  <ApiFields ariaLabel="SSEJSONRPCTransport subscribe yielded values">
    <ApiField name="event" type="Any">
      Each normalized envelope result, independently checked against `max_event_bytes`.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SSEJSONRPCTransport subscribe errors">
    <ApiField name="TransportTimeoutError | TransportConnectionError">
      The HTTP stream timed out or could not remain connected.
    </ApiField>
    <ApiField name="TransportRemoteError">
      The peer returned an HTTP error or an `ok: false` event envelope.
    </ApiField>
    <ApiField name="TransportProtocolError">
      An event contains invalid JSON, a mismatched request ID, or an incompatible envelope.
    </ApiField>
    <ApiField name="TransportLimitError">
      The task or an event exceeds its configured limit.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Stream semantics">
  SSE is one-way and `subscribe()` does not send an idempotency key or automatically retry a partial stream. Reconnection and resume behavior belongs to the consumer.
</ApiCallout>

</ApiReference>
