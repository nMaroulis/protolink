import ApiSurface from '@site/src/components/ApiSurface';

# Client

The **Client** layer in Protolink provides a high-level interface for agent-to-agent communication. It abstracts transport details and offers convenient methods for sending tasks, messages, and retrieving agent metadata.

## AgentClient

The `AgentClient` is the primary entry point for programmatic agent interactions. It wraps a transport and provides a unified interface for communicating with Protolink agents.

The distinction is useful because application code should think in Agent operations such as “send this task” or “cancel that task,” not in HTTP headers, WebSocket frames, or gRPC metadata. `AgentClient` chooses the operation contract and parses the result; the selected transport only maps that contract onto its wire protocol. Changing from HTTP to gRPC therefore does not require rewriting task-level client code.

AgentClient follows the same progressive-control rule as Agent and Registry: a transport name creates a default client quickly, while a concrete transport carries TLS, limits, retries, keepalive, and protocol-specific behavior. The read-only `client.transport` property exposes the resolved transport for health and metric inspection.

```python
from protolink import RetryPolicy, TransportConfig
from protolink.client import AgentClient
from protolink.transport import GRPCTransport

transport = GRPCTransport(
    url="grpc://127.0.0.1:0",
    config=TransportConfig(retry=RetryPolicy(max_attempts=3)),
)
client = AgentClient(transport)
print(client.transport.metrics)
```

<ApiSurface
  eyebrow="Client module"
  title="AgentClient"
  path="protolink.client.AgentClient"
  description="The typed application-facing client for sending tasks, messages, streaming requests, control-plane operations, registry calls, and LLM history actions over any supported transport."
  pills={[
    "Transport-backed",
    "Async first",
    "Sync wrapper available",
    "Streaming-aware",
    "Control-plane specs",
  ]}
  cards={[
    {
      title: "Submit work",
      text: "Send task and message payloads to a remote agent while keeping transport details behind the client.",
      code: "send_task()",
    },
    {
      title: "Stream progress",
      text: "Yield live task events for SSE, WebSocket, JSON-RPC, and runtime transports.",
      code: "send_task_streaming()",
    },
    {
      title: "Control runtime",
      text: "Cancel active work, inspect state, mutate state, and compact history through explicit request specs.",
      code: "cancel_task()",
    },
    {
      title: "Use scripts",
      text: "Access a blocking facade for CLIs, notebooks, and simple orchestration scripts.",
      code: "client.sync",
    },
  ]}
/>

### Design Philosophy: Async vs Sync

Protolink's client architecture exposes two APIs to accommodate different workflows:

1. **Async API (Recommended)**: The core implementation. Ideal for modern applications, web servers (e.g., FastAPI), and high-performance multi-agent orchestration where non-blocking I/O is crucial.
2. **Sync API (`client.sync`)**: A thin, blocking wrapper over the async methods. Designed for simple scripts, CLI tools, and environments where managing an `asyncio` event loop is cumbersome.

:::warning[Async Loop Constraint]

The Sync API (`client.sync`) uses `asyncio.run()` under the hood. It **cannot** be used inside an already running event loop (e.g., inside an async function). If you are inside an `async def`, always use the standard Async API.

:::
### Quick Start

```python
from protolink.client import AgentClient
from protolink.models import Task

# Create a client (transport type + URL)
client = AgentClient(transport="http", url="http://localhost:8000")

# Create a task with an inference request
task = Task.create_infer(prompt="Book me a vacation to Santorini")

# Send to a remote agent
result = await client.send_task(agent_url="http://localhost:8010", task=task)

# Get the response
print(result.get_last_part_content())
```

### Constructor

```python
AgentClient(
    transport: Transport | TransportType,
    url: str | None = None,
    timeout: int = 300,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `transport` | `Transport ⎪ str` | A Transport instance or type string (`"http"`, `"websocket"`, etc.) |
| `url` | `str ⎪ None` | Base URL when using a transport type string |
| `timeout` | `int` | Timeout in seconds for the request (default: 300) |

Use a string alias when ProtoLink should create a client transport with defaults. Use an existing transport object when the application needs TLS, production limits, retries, protocol-specific constructor options, or ownership of that exact instance. AgentClient never copies settings onto the transport and never creates a second hidden transport.

**Examples:**

```python
# Simple: construct by transport name
client = AgentClient(transport="http", url="http://localhost:8000", timeout=120)

# Advanced: configure the transport first
from protolink import TLSConfig, TransportConfig
from protolink.transport import HTTPTransport

transport = HTTPTransport(
    url="https://agent.internal:8443",
    tls=TLSConfig(cafile="certs/ca.pem"),
    config=TransportConfig(shutdown_timeout=10),
)
client = AgentClient(transport=transport)
```

### Transport Inspection

The read-only `transport` property exposes the concrete transport used by the client. This is the supported path for health, readiness, capability, and metric inspection:

```python
snapshot = client.transport.metrics
print(snapshot.requests_succeeded, snapshot.retries)

health = client.transport.health()
print(health["status"], health["ready"])
```

See the [Shared Transport API Reference](./transport.md#shared-transport-api-reference) for every configuration field, snapshot counter, exception type, and lifecycle probe.

---

## Core Methods

### `send_task()`

Sends a `Task` to a remote agent and returns the processed result.

```python
async def send_task(agent_url: str, task: Task) -> Task
```

| Parameter | Description |
|-----------|-------------|
| `agent_url` | The full URL of the target agent (e.g., `"http://localhost:8010"`) |
| `task` | The `Task` object to send |

**Example:**

```python
from protolink.models import Task

# Create an infer task
task = Task.create_infer(prompt="What's the weather in Athens?")

# Send and get result
result = await client.send_task("http://localhost:8010", task)
print(result.get_last_part_content())
```

---

### `send_task_streaming()`

Sends a task and yields streamed events as they arrive. This is the public client API for live task progress, LLM chunks, tool events, and final task completion.

```python
async def send_task_streaming(agent_url: str, task: Task) -> AsyncIterator[Any]
```

:::warning[Transport Support]

Requires a transport that advertises streaming support and implements `subscribe()`. Supported choices include `"sse"`, `"json-rpc"`, `"grpc"`, `"websocket"`, and `"runtime"`. Plain `"http"` remains request/response only and raises `NotImplementedError`.

:::
**Example with SSE JSON-RPC:**

```python
from protolink.client import AgentClient
from protolink.models import Task

client = AgentClient(transport="sse", url="http://localhost:8000")
task = Task.create_infer(prompt="Write a short haiku about agents")

async for event in client.send_task_streaming("http://localhost:8010", task):
    if event.get("type") == "task_llm_stream":
        print(event.get("content") or "", end="", flush=True)
    if event.get("final"):
        print("\nstream complete")
```

Applications that need a stable UI or replay contract can normalize these transport events with `RunEvent.from_task_event(...)` or record them through `InMemoryEventSink`. See [Runtime](runtime.md) for the versioned run-event envelope.

SSE, WebSocket, and gRPC transports recursively convert nested Protolink models and dataclasses into JSON-compatible values. Tool and delegated-agent events therefore preserve structured results such as `ToolOutput` inside `content` or `metadata`; clients do not need a custom encoder for these framework event payloads.

---

### `cancel_task()`

Requests best-effort cancellation of a task currently executing on an agent and returns the task after the request is accepted.

```python
async def cancel_task(
    agent_url: str,
    task_id: str,
    *,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Task
```

The task ID is known before submission because the caller creates the `Task`. Cancellation should be sent from another coroutine or control handler after the task has been accepted, usually after the first streamed status or progress event.

```python
import asyncio

task = Task.create_infer(prompt="Perform long-running work")
running = asyncio.create_task(client.send_task(agent_url, task))

# Wait for application-specific acceptance or progress before canceling.
await task_started.wait()
canceled = await client.cancel_task(
    agent_url,
    task.id,
    reason="Stopped by the user",
    metadata={"source": "cli"},
)
result = await running

assert canceled.state.value == "canceled"
assert result.state.value == "canceled"
```

`cancel_task()` uses ProtoLink's native `POST /tasks/cancel` operation over HTTP, SSE JSON-RPC, WebSocket, gRPC, and RuntimeTransport. This is separate from the canonical A2A 1.0 `CancelTask` operation exposed by the HTTP adapter. Cancellation is a control-plane request: WebSocket sends it over a separate connection so it does not queue behind the active task stream.

Cancellation is intentionally best-effort. Async work normally stops at an `await` boundary; synchronous work and external systems may need their own cooperative cancellation or rollback mechanism. See [Runtime cancellation](runtime.md#canceling-running-tasks) for lifecycle, custom-handler, and side-effect guidance.

---

### `compact_history()`

Requests LLM conversation-history compaction from an agent over the control plane.

```python
async def compact_history(
    agent_url: str,
    *,
    strategy: str = "recent",
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> HistoryCompactionResult
```

This uses the built-in `COMPACT_HISTORY_REQUEST` spec (`POST /llm/history/compact`). It does not send a `Task`, does not create a model-visible tool, and does not add anything to the LLM prompt.

```python
report = await client.compact_history(
    agent_url,
    strategy="tokens",
    max_tokens=8_000,
    preserve_recent=6,
    session_id="customer-42",
)
```

When the target agent has `state=["conversation"]` and `session_id` is supplied, the agent loads that session history, compacts it, and saves it back.

---

### State Control Plane

Inspect, reset, or compact a remote agent's persistent state without sending a
model-visible task.

```python
state = await client.describe_state(
    agent_url,
    session_id="customer-42",
)

reset = await client.reset_state(
    agent_url,
    session_id="customer-42",
)

compacted = await client.compact_state(
    agent_url,
    session_id="customer-42",
    strategy="tokens",
    max_tokens=8_000,
)
```

These methods return `StateOperationResult`. They use control-channel request
specs: `DESCRIBE_STATE_REQUEST` (`POST /state/describe`),
`RESET_STATE_REQUEST` (`POST /state/reset`), and `COMPACT_STATE_REQUEST`
(`POST /state/compact`).

---

### `send_message()`

Convenience wrapper that creates a Task from a Message, sends it, and returns the response message.

```python
async def send_message(agent_url: str, message: Message) -> Message
```

**Example:**

```python
from protolink.models import Message

response = await client.send_message(
    agent_url="http://localhost:8010",
    message=Message.user("Hello, agent!")
)
print(response.parts[0].content)
```

---

### `get_agent_card()`

Retrieves the public `AgentCard` from a remote agent. Useful for discovery and capability inspection.

```python
async def get_agent_card(agent_url: str) -> AgentCard
```

**Example:**

```python
card = await client.get_agent_card("http://localhost:8010")
print(f"Agent: {card.name}")
print(f"Description: {card.description}")
print(f"Skills: {[s.id for s in card.skills]}")
```

---

## Synchronous API

The `AgentClient` provides synchronous versions of its core methods for use in non-async contexts (scripts, notebooks, CLI tools). These are accessible via the `client.sync` property.

Internally, these methods use `asyncio.run()` to handle the asynchronous transport logic.

:::warning[Do Not Use in Async Loops]

The synchronous API should **NOT** be used inside an active event loop (e.g., inside FastAPI endpoints or async Jupyter cells) as it uses `asyncio.run()`, which will raise a `RuntimeError`.

:::
| Async Method | Synchronous Equivalent | Description |
|--------------|------------------------|-------------|
| `send_task()` | `client.sync.send_task()` | Synchronously send a task and wait for the result. |
| `send_task_streaming()` | `client.sync.send_task_streaming()` | Synchronously iterate over streamed task events. |
| `cancel_task()` | `client.sync.cancel_task()` | Synchronously request cancellation of a task running elsewhere. |
| `compact_history()` | `client.sync.compact_history()` | Synchronously request LLM history compaction from an agent. |
| `describe_state()` | `client.sync.describe_state()` | Synchronously inspect remote persistent state. |
| `reset_state()` | `client.sync.reset_state()` | Synchronously reset remote persistent state. |
| `compact_state()` | `client.sync.compact_state()` | Synchronously compact remote persistent conversation state. |
| `send_message()` | `client.sync.send_message()` | Synchronously send a message and wait for the response message. |
| `get_agent_card()` | `client.sync.get_agent_card()` | Synchronously retrieve an agent's public card. |

**Example:**

```python
from protolink.client import AgentClient
from protolink.models import Task

client = AgentClient(transport="http", url="http://localhost:8000")
task = Task.create_infer(prompt="Hello, agent!")

# No 'await' or 'async def' needed. Use the .sync property!
result = client.sync.send_task("http://localhost:8010", task)
print(result.get_last_part_content())
```

**Synchronous streaming example:**

```python
client = AgentClient(transport="sse", url="http://localhost:8000")
task = Task.create_infer(prompt="Stream this response")

for event in client.sync.send_task_streaming("http://localhost:8010", task):
    print(event)
```

---

## ClientRequestSpec

`ClientRequestSpec` defines the contract for an API endpoint in a transport-agnostic way.

It is the small description that sits between the high-level client and the wire transport. For example, “send a task” is a `POST` operation with a body and a `Task` response parser. HTTP turns that description into a route request, while WebSocket and gRPC place the same method and path in their envelopes. The client behavior stays identical because the specification describes the operation rather than the protocol.

Normal users rarely need to create request specs; the built-in Agent and Registry clients provide them. They become relevant when adding a new endpoint or implementing a custom client operation. At that point, `idempotent` deserves particular care because it authorizes the retry and duplicate-replay machinery.

```python
@dataclass(frozen=True)
class ClientRequestSpec:
    name: str
    path: str
    method: HttpMethod
    response_parser: Callable[[Any], Any] | None = None
    request_source: RequestSourceType = "body"
    content_type: ContentType | None = None
    accept: ContentType | None = None
    channel: str = "default"
    idempotent: bool = False
```

| Field | Default | Transport behavior |
|------|---------|--------------------|
| `name` | Required | Stable operation name used by request contexts, metrics, and diagnostics. |
| `path` | Required | Protocol-neutral endpoint path. HTTP-based transports use it directly; multiplexed transports carry it in the request envelope. |
| `method` | Required | Logical HTTP method used by HTTP routing and retry-method filtering. |
| `response_parser` | `None` | Optional callable that converts the decoded response into a model such as `Task` or `AgentCard`. |
| `request_source` | `"body"` | Selects body, query, path, or no request data according to `RequestSourceType`. |
| `content_type` | `None` | Optional outbound media type override. The transport default is used when omitted. |
| `accept` | `None` | Optional accepted response media type. The transport default is used when omitted. |
| `channel` | `"default"` | Logical multiplexing channel. Control operations use `"control"` so persistent transports can isolate them from stream traffic. |
| `idempotent` | `False` | Explicit declaration that the logical operation can be retried and replayed under one idempotency key. Retries never run unless this is `True`. |

`idempotent=True` is an application-level safety promise, not an inference made from `POST` or a URL. Custom request specs should enable it only when repeating the operation with the same payload and idempotency key cannot apply the effect twice.

The `channel` field matters only to transports that multiplex several logical operations. Control requests such as cancellation use a separate channel so they are not forced to wait behind the long-running task they are intended to stop. Request/response transports may ignore the distinction while preserving the same client contract.

### Built-in Request Specs

| Spec | Path | Method | Channel | Idempotent | Description |
|------|------|--------|---------|------------|-------------|
| `TASK_REQUEST` | `/tasks/` | POST | default | Yes | Send a task to an agent. The task ID and idempotency key prevent duplicate execution. |
| `TASK_CANCEL_REQUEST` | `/tasks/cancel` | POST | control | Yes | Cancel an active task. Repeating cancellation has the same terminal effect. |
| `COMPACT_HISTORY_REQUEST` | `/llm/history/compact` | POST | control | No | Compact the target agent's LLM history. |
| `DESCRIBE_STATE_REQUEST` | `/state/describe` | POST | control | Yes | Inspect target agent state without mutating it. |
| `RESET_STATE_REQUEST` | `/state/reset` | POST | control | No | Reset target agent state. |
| `COMPACT_STATE_REQUEST` | `/state/compact` | POST | control | No | Compact target agent conversation state. |
| `AGENT_CARD_REQUEST` | `/.well-known/agent.json` | GET | default | Yes | Retrieve agent metadata. |
| `TASK_STREAM_REQUEST` | `/tasks/stream` | POST | default | No | Send a task and receive a live event stream. Streams are not replayed by the retry layer. |

### How It Works

When you call a method like `send_task()`:

1. The client selects the appropriate `ClientRequestSpec` (for example, `TASK_REQUEST`).
2. It passes the specification and task data to `transport.send()`.
3. The transport creates correlation and idempotency metadata, applies limits, and constructs the protocol-specific request.
4. The decoded response passes through `response_parser`, so the caller receives a `Task`, `AgentCard`, or another domain model rather than a raw wire dictionary.

If the spec is idempotent and the configured retry policy permits its method, the transport preserves one request ID and idempotency key across attempts. This pattern allows new endpoints without modifying transport implementations while keeping retry safety explicit at the operation boundary.
