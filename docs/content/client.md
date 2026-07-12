import ApiSurface from '@site/src/components/ApiSurface';

# Client

The **Client** layer in Protolink provides a high-level interface for agent-to-agent communication. It abstracts transport details and offers convenient methods for sending tasks, messages, and retrieving agent metadata.

## AgentClient

The `AgentClient` is the primary entry point for programmatic agent interactions. It wraps a transport and provides a unified interface for communicating with Protolink agents.

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
    *,
    tls: TLSConfig | None = None,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `transport` | `Transport ⎪ str` | A Transport instance or type string (`"http"`, `"websocket"`, etc.) |
| `url` | `str ⎪ None` | Base URL when using a transport type string |
| `timeout` | `int` | Timeout in seconds for the request (default: 300) |
| `tls` | `TLSConfig ⎪ None` | Optional CA trust and client certificate identity for HTTPS, WSS, or secure gRPC calls. |

**Examples:**

```python
# Using transport type string
client = AgentClient(transport="http", url="http://localhost:8000", timeout=120)

# Using an existing transport instance
from protolink.transport import HTTPTransport
transport = HTTPTransport(url="http://localhost:8000")
client = AgentClient(transport=transport)
```

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

`cancel_task()` uses the A2A-style `POST /tasks/cancel` operation over HTTP, SSE JSON-RPC, WebSocket, gRPC, and RuntimeTransport. Cancellation is a control-plane request: WebSocket sends it over a separate connection so it does not queue behind the active task stream.

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

```python
@dataclass(frozen=True)
class ClientRequestSpec:
    name: str                    # Human-readable name (e.g., "send_task")
    path: str                    # URL path (e.g., "/tasks/")
    method: HttpMethod           # HTTP method (e.g., "POST")
    response_parser: Callable    # Function to parse response data
    request_source: str          # Where to put request data ("body", "query", etc.)
    channel: str = "default"     # Multiplexed transport channel
```

### Built-in Request Specs

| Spec | Path | Method | Description |
|------|------|--------|-------------|
| `TASK_REQUEST` | `/tasks/` | POST | Send a task to an agent |
| `TASK_CANCEL_REQUEST` | `/tasks/cancel` | POST | Cancel an active task over a control channel |
| `COMPACT_HISTORY_REQUEST` | `/llm/history/compact` | POST | Compact the target agent's LLM history over a control channel |
| `DESCRIBE_STATE_REQUEST` | `/state/describe` | POST | Inspect target agent state over a control channel |
| `RESET_STATE_REQUEST` | `/state/reset` | POST | Reset target agent state over a control channel |
| `COMPACT_STATE_REQUEST` | `/state/compact` | POST | Compact target agent conversation state over a control channel |
| `AGENT_CARD_REQUEST` | `/.well-known/agent.json` | GET | Retrieve agent metadata |
| `TASK_STREAM_REQUEST` | `/tasks/stream` | POST | Send task with streaming |

### How It Works

When you call a method like `send_task()`:

1. The client selects the appropriate `ClientRequestSpec` (e.g., `TASK_REQUEST`)
2. Passes the spec and data to `transport.send()`
3. The transport uses the spec to construct the wire request

This pattern allows new endpoints without modifying transport implementations.
