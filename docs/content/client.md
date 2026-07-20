import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Client

The **Client** layer in Protolink provides a high-level interface for agent-to-agent communication. It abstracts transport details and offers convenient methods for sending tasks, messages, and retrieving agent metadata.

## AgentClient

The `AgentClient` is the primary entry point for programmatic agent interactions. It wraps a transport and provides a unified interface for communicating with Protolink agents.

The distinction is useful because application code should think in Agent operations such as “send this task” or “cancel that task,” not in HTTP headers, WebSocket frames, or gRPC metadata. `AgentClient` chooses the operation contract and parses the result; the selected transport only maps that contract onto its wire protocol. Changing from HTTP to gRPC therefore does not require rewriting task-level client code.

AgentClient follows the same progressive-control rule as Agent and Registry: a transport name creates a default client quickly, while a concrete transport carries TLS, limits, retries, keepalive, and protocol-specific behavior. The read-only `client.transport` property exposes the resolved transport for health and metric inspection.

By default, `AgentClient` uses ProtoLink's native request contract. `AgentClient(..., a2a=True)` requires HTTP and adds outbound A2A 1.0 discovery and translation. It does not remove the native methods: `protocol="auto"` prefers a native ProtoLink peer and selects A2A only for an A2A-only peer, while `"protolink"` and `"a2a"` are explicit choices. Advertised A2A interfaces must share the discovered card's origin unless the application explicitly sets `a2a_allow_cross_origin=True` for a trusted split-origin deployment.

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

<ApiReference kind="class" path="protolink.client.AgentClient" signature={`AgentClient(
    transport: Transport | TransportType,
    url: str | None = None,
    timeout: int = 300,
    *,
    a2a: bool = False,
    a2a_allow_cross_origin: bool = False,
) -> None`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Create a high-level Agent client around one concrete transport. Construction also creates the per-instance blocking facade and, when requested, an A2A JSON-RPC adapter and bounded protocol-selection cache.

<ApiSection title="Parameters"><ApiFields ariaLabel="AgentClient constructor parameters">
  <ApiField name="transport" type="Transport | TransportType" required>Configured transport instance or registered alias such as <code>"http"</code>, <code>"websocket"</code>, <code>"sse"</code>, <code>"json-rpc"</code>, <code>"sse-json-rpc"</code>, <code>"grpc"</code>, or <code>"runtime"</code>. Existing instances are used directly and retain ownership of TLS, retries, limits, keepalive, and metrics.</ApiField>
  <ApiField name="url" type="str | None" defaultValue="None">Base address supplied to the transport factory when <code>transport</code> is an alias. It is ignored for an existing transport object.</ApiField>
  <ApiField name="timeout" type="int" defaultValue="300">Factory timeout in seconds for an alias-created transport. It does not overwrite a configured transport instance.</ApiField>
  <ApiField name="a2a" type="bool" defaultValue="False">Enable outbound A2A card discovery, interface validation, task translation, and cancellation mapping while retaining native ProtoLink calls.</ApiField>
  <ApiField name="a2a_allow_cross_origin" type="bool" defaultValue="False">Trust a standard Agent Card whose selected JSON-RPC interface has another origin. Keep the default unless that split-origin deployment is explicitly trusted.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Attributes"><ApiFields ariaLabel="AgentClient attributes">
  <ApiField name="transport" type="Transport">Read-only resolved transport.</ApiField>
  <ApiField name="a2a" type="bool">Read-only A2A-enabled flag.</ApiField>
  <ApiField name="sync" type="SyncAgentClient">Blocking facade bound to this client.</ApiField>
</ApiFields></ApiSection>

<ApiCallout label="A2A transport requirement">When <code>a2a=True</code>, construction immediately validates that the resolved transport's <code>transport_type</code> is exactly <code>"http"</code> and raises <code>ValueError</code> otherwise.</ApiCallout>

</ApiReference>

Use a string alias when ProtoLink should create a client transport with defaults. Use an existing transport object when the application needs TLS, production limits, retries, protocol-specific constructor options, or ownership of that exact instance. AgentClient never copies settings onto the transport and never creates a second hidden transport.

**Examples:**

```python
# Simple: construct by transport name
client = AgentClient(transport="http", url="http://localhost:8000", timeout=120)

# Add A2A 1.0 outbound interoperability while retaining native calls
a2a_client = AgentClient(
    transport="http",
    url="http://localhost:8000",
    a2a=True,
)

# Only for a trusted deployment whose card intentionally advertises another origin
split_origin_client = AgentClient(
    transport="http",
    url="https://discovery.example",
    a2a=True,
    a2a_allow_cross_origin=True,
)

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

<ApiReference kind="async method" path="protolink.client.AgentClient.send_task" signature={`async send_task(
    agent_url: str,
    task: Task,
    *,
    protocol: Literal["auto", "protolink", "a2a"] = "auto",
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Submit a complete task through the native request spec or the optional A2A adapter and wait for the processed Task result.

<ApiSection title="Parameters"><ApiFields ariaLabel="send task parameters">
  <ApiField name="agent_url" type="str" required>Peer base URL or transport-specific URI.</ApiField>
  <ApiField name="task" type="Task" required>Caller-created Task. Native submission is explicitly idempotent; A2A SendMessage is non-idempotent because the peer assigns its task ID.</ApiField>
  <ApiField name="protocol" type={'Literal["auto", "protolink", "a2a"]'} defaultValue={'"auto"'}><code>"protolink"</code> skips discovery, <code>"a2a"</code> requires enabled A2A and validates a standard card, and <code>"auto"</code> probes the native card before falling back to A2A only on 404 or 405.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="send task return value"><ApiField name="task" type="Task">Remote task state, messages, artifacts, and metadata normalized into ProtoLink's model.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="send task errors"><ApiField name="ValueError">Invalid protocol value.</ApiField><ApiField name="RuntimeError">A2A was explicitly requested but disabled.</ApiField><ApiField name="transport or A2A error">Discovery, origin validation, authentication, timeout, network, translation, and remote failures propagate.</ApiField></ApiFields></ApiSection>

</ApiReference>

**Example:**

```python
from protolink.models import Task

# Create an infer task
task = Task.create_infer(prompt="What's the weather in Athens?")

# Send and get result
result = await client.send_task("http://localhost:8010", task)
print(result.get_last_part_content())
```

With A2A enabled, automatic selection performs discovery before task
submission. It probes `/.well-known/agent.json` first and falls back to
`/.well-known/agent-card.json` only after a `404` or `405`; authentication,
network, timeout, and server failures are propagated rather than retried through
another protocol. The process-local selection cache holds at most 1,024 peers,
expires entries after five minutes, and removes the oldest entries when full.
A2A `SendMessage` itself is non-idempotent and is not automatically retried
because the remote server assigns the task ID.

```python
client = AgentClient(transport="http", url="http://localhost:8000", a2a=True)

automatic = await client.send_task(peer_url, task)
a2a_only = await client.send_task(peer_url, task, protocol="a2a")
native_only = await client.send_task(peer_url, task, protocol="protolink")
```

Outbound A2A translation keeps the caller's local task ID and records the
remote task ID, context, state, status timestamp, and agent URL in namespaced
metadata. A fresh task does not send its local ID as an A2A `taskId`; that field
is used only when continuing work previously returned by the same remote peer.
The process-local local-to-remote mapping holds at most 1,024 tasks for one hour
and removes expired or oldest entries. Continuation and A2A cancellation require
a live mapping in the same client process.

---

### `send_task_streaming()`

Sends a task and yields streamed events as they arrive. This is the public client API for live task progress, LLM chunks, tool events, and final task completion.

<ApiReference kind="async generator" path="protolink.client.AgentClient.send_task_streaming" signature={`send_task_streaming(
    agent_url: str,
    task: Task,
) -> AsyncIterator[Any]`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Delegate a live task subscription to the configured transport. Unlike <code>send_task()</code>, this method has no protocol selector and uses ProtoLink's native streaming contract.

<ApiSection title="Parameters"><ApiFields ariaLabel="stream task parameters"><ApiField name="agent_url" type="str" required>Peer address understood by the transport.</ApiField><ApiField name="task" type="Task" required>Task serialized into the subscription request.</ApiField></ApiFields></ApiSection>

<ApiSection title="Yields"><ApiFields ariaLabel="stream task yields"><ApiField name="event" type="Any">Transport-decoded status, progress, LLM, artifact, or error event. Backends may yield dictionaries or typed objects.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="stream task errors"><ApiField name="NotImplementedError">The transport does not advertise streaming or implement <code>subscribe()</code>.</ApiField><ApiField name="transport or remote error">Subscription failures propagate while iterating.</ApiField></ApiFields></ApiSection>

</ApiReference>

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

<ApiReference kind="async method" path="protolink.client.AgentClient.cancel_task" signature={`async cancel_task(
    agent_url: str,
    task_id: str,
    *,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    protocol: Literal["auto", "protolink", "a2a"] = "auto",
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Send a control-plane cancellation request for active remote work. Native cancellation carries the caller-created task ID; A2A cancellation requires this client process to know the server-assigned ID mapping.

<ApiSection title="Parameters"><ApiFields ariaLabel="cancel task parameters">
  <ApiField name="agent_url" type="str" required>Peer running the task.</ApiField>
  <ApiField name="task_id" type="str" required>Local ProtoLink task ID.</ApiField>
  <ApiField name="reason" type="str | None" defaultValue="None">Human-readable reason propagated into task cancellation metadata.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Additional cancellation metadata; A2A translation carries it on the TaskId request.</ApiField>
  <ApiField name="protocol" type={'Literal["auto", "protolink", "a2a"]'} defaultValue={'"auto"'}>Native, mapped A2A, or automatic selection.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="cancel task return value"><ApiField name="task" type="Task">Remote task after cancellation acceptance.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="cancel task errors"><ApiField name="ValueError">Invalid protocol.</ApiField><ApiField name="RuntimeError | A2AClientError">A2A is disabled or no safe remote mapping exists.</ApiField><ApiField name="remote error">Unknown or terminal tasks and transport failures propagate.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Best effort">Acceptance cannot roll back completed external side effects or forcibly interrupt synchronous code.</ApiCallout>

</ApiReference>

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

For native tasks, `cancel_task()` uses `POST /tasks/cancel` over HTTP, SSE JSON-RPC, WebSocket, gRPC, and RuntimeTransport. For a task previously returned through this client's A2A adapter, `protocol="auto"` uses the stored local-to-remote ID mapping and sends canonical A2A `CancelTask`; `protocol="a2a"` selects that path explicitly. The optional `reason` and `metadata` are translated into A2A cancellation metadata and reconstructed by a ProtoLink A2A server.

A blocking outbound A2A `SendMessage` does not reveal its server-assigned task ID until a response is returned, so it cannot be canceled through this client while that initial call is still blocked. An A2A task unknown to this client has no safe local-to-remote mapping and raises `A2AClientError`. In `"auto"`, the client confirms an A2A peer and raises instead of sending the local ID to the native cancellation route. Cancellation remains a control-plane request: WebSocket sends native cancellation over a separate connection so it does not queue behind the active task stream.

Cancellation is intentionally best-effort. Async work normally stops at an `await` boundary; synchronous work and external systems may need their own cooperative cancellation or rollback mechanism. See [Runtime cancellation](runtime.md#canceling-running-tasks) for lifecycle, custom-handler, and side-effect guidance.

---

### `compact_history()`

Requests LLM conversation-history compaction from an agent over the control plane.

<ApiReference kind="async method" path="protolink.client.AgentClient.compact_history" signature={`async compact_history(
    agent_url: str,
    *,
    strategy: HistoryCompactionStrategy = "recent",
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> HistoryCompactionResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Request explicit LLM-history reduction through the non-idempotent control channel.

<ApiSection title="Parameters"><ApiFields ariaLabel="compact history parameters">
  <ApiField name="agent_url" type="str" required>Target Agent address.</ApiField>
  <ApiField name="strategy" type={'Literal["recent", "tokens", "summary"]'} defaultValue={'"recent"'}>History reduction algorithm.</ApiField>
  <ApiField name="max_messages" type="int" defaultValue="20">Message-count budget for recent compaction.</ApiField>
  <ApiField name="max_tokens" type="int" defaultValue="4000">Estimated token budget.</ApiField>
  <ApiField name="preserve_recent" type="int" defaultValue="6">Recent messages protected from summarization.</ApiField>
  <ApiField name="summary_max_tokens" type="int" defaultValue="512">Requested summary output budget.</ApiField>
  <ApiField name="session_id" type="str | None" defaultValue="None">Persisted conversation session to load, compact, and save; omission targets the Agent LLM's current history.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Application context attached to the control request.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="compact history return value"><ApiField name="result" type="HistoryCompactionResult">Before/after counts and strategy metadata.</ApiField></ApiFields></ApiSection>

</ApiReference>

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

### AgentClient.describe_state

<ApiReference kind="async method" path="protolink.client.AgentClient.describe_state" signature={`async describe_state(
    agent_url: str,
    *,
    session_id: str | None = None,
    stores: tuple[str, ...] | list[str] | None = None,
    include_data: bool = False,
    metadata: dict[str, Any] | None = None,
) -> StateOperationResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Inspect selected persistent stores through an idempotent control request.

<ApiSection title="Parameters"><ApiFields ariaLabel="describe state parameters"><ApiField name="agent_url" type="str" required>Target Agent.</ApiField><ApiField name="session_id" type="str | None" defaultValue="None">Optional logical session.</ApiField><ApiField name="stores" type="tuple[str, ...] | list[str] | None" defaultValue="None">Requested store names; omission serializes an empty tuple for the server's default scope.</ApiField><ApiField name="include_data" type="bool" defaultValue="False">Include store data when supported, not only existence and counts.</ApiField><ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Request context.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="describe state return"><ApiField name="result" type="StateOperationResult">Per-store enabled, missing, count, data, and error reports.</ApiField></ApiFields></ApiSection>

</ApiReference>

### AgentClient.reset_state

<ApiReference kind="async method" path="protolink.client.AgentClient.reset_state" signature={`async reset_state(
    agent_url: str,
    *,
    session_id: str | None = None,
    stores: tuple[str, ...] | list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> StateOperationResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Request a non-idempotent persistent-state reset. A session ID narrows conversation deletion; without one, the server may reset its enabled namespace.

<ApiSection title="Parameters"><ApiFields ariaLabel="reset state parameters"><ApiField name="agent_url" type="str" required>Target Agent.</ApiField><ApiField name="session_id" type="str | None" defaultValue="None">Optional conversation session to clear.</ApiField><ApiField name="stores" type="tuple[str, ...] | list[str] | None" defaultValue="None">Requested stores; omission serializes an empty tuple for server-side default scope.</ApiField><ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Control-request metadata.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="reset state return"><ApiField name="result" type="StateOperationResult">Structured per-store reset and error report.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Destructive operation">The remote Agent's policy and approval handler authorize the actual mutation. The client does not ask for confirmation itself.</ApiCallout>

</ApiReference>

### AgentClient.compact_state

<ApiReference kind="async method" path="protolink.client.AgentClient.compact_state" signature={`async compact_state(
    agent_url: str,
    *,
    session_id: str,
    strategy: HistoryCompactionStrategy = "tokens",
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    metadata: dict[str, Any] | None = None,
) -> StateOperationResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Compact one required persisted conversation session and return its structured state report. The request always selects the <code>"conversation"</code> store.

<ApiSection title="Parameters"><ApiFields ariaLabel="compact state parameters"><ApiField name="agent_url" type="str" required>Target Agent.</ApiField><ApiField name="session_id" type="str" required>Existing persisted session.</ApiField><ApiField name="strategy" type={'Literal["recent", "tokens", "summary"]'} defaultValue={'"tokens"'}>Reduction strategy.</ApiField><ApiField name="max_messages" type="int" defaultValue="20">Message limit.</ApiField><ApiField name="max_tokens" type="int" defaultValue="4000">Estimated token limit.</ApiField><ApiField name="preserve_recent" type="int" defaultValue="6">Protected recent messages.</ApiField><ApiField name="summary_max_tokens" type="int" defaultValue="512">Summary budget.</ApiField><ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Control-request metadata.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="compact state return"><ApiField name="result" type="StateOperationResult">Compaction, missing-session, disabled-store, and error reports.</ApiField></ApiFields></ApiSection>

</ApiReference>

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

<ApiReference kind="async method" path="protolink.client.AgentClient.send_message" signature={`async send_message(
    agent_url: str,
    message: Message,
    *,
    protocol: Literal["auto", "protolink", "a2a"] = "auto",
) -> Message`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Wrap one Message in a new Task, delegate to <code>send_task()</code>, then return the newest agent or assistant message.

<ApiSection title="Parameters"><ApiFields ariaLabel="send message parameters"><ApiField name="agent_url" type="str" required>Peer address.</ApiField><ApiField name="message" type="Message" required>Input role and parts.</ApiField><ApiField name="protocol" type={'Literal["auto", "protolink", "a2a"]'} defaultValue={'"auto"'}>Same native/A2A selection as <code>send_task()</code>.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="send message return"><ApiField name="message" type="Message">Last response whose role is <code>"agent"</code> or <code>"assistant"</code>.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="send message errors"><ApiField name="RuntimeError">The returned task has artifacts but no response message, or no response message at all.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Lossy convenience">Use <code>send_task()</code> when callers need task state, artifacts, context, metadata, or non-message results.</ApiCallout>

</ApiReference>

**Example:**

```python
from protolink.models import Message

response = await client.send_message(
    agent_url="http://localhost:8010",
    message=Message.user("Hello, agent!")
)
print(response.parts[0].content)
```

`send_message()` requires a response message. If an A2A peer returns a
completed task containing artifacts but no agent message, this convenience
method raises `RuntimeError`; call `send_task()` to receive the full task and
inspect its artifacts.

---

### `get_agent_card()`

Retrieves the public `AgentCard` from a remote agent. Useful for discovery and capability inspection.

<ApiReference kind="async method" path="protolink.client.AgentClient.get_agent_card" signature={`async get_agent_card(
    agent_url: str,
) -> AgentCard`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py">
Fetch ProtoLink's native well-known card through an idempotent GET request and parse it into <code>AgentCard</code>.

<ApiSection title="Parameters"><ApiFields ariaLabel="get agent card parameters"><ApiField name="agent_url" type="str" required>Peer base address.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="get agent card return"><ApiField name="card" type="AgentCard">Validated identity, skills, interfaces, security, and capabilities.</ApiField></ApiFields></ApiSection>

</ApiReference>

**Example:**

```python
card = await client.get_agent_card("http://localhost:8010")
print(f"Agent: {card.name}")
print(f"Description: {card.description}")
print(f"Skills: {[s.id for s in card.skills]}")
```

`get_agent_card()` reads ProtoLink's native card. When A2A is enabled, use
`get_a2a_agent_card()` to fetch and validate the standard card and its JSON-RPC
1.0 interface:

### AgentClient.get_a2a_agent_card

<ApiReference kind="async method" path="protolink.client.AgentClient.get_a2a_agent_card" signature={`async get_a2a_agent_card(
    agent_url: str,
) -> dict[str, Any]`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L568-L574">
Discover and validate the standard A2A 1.0 Agent Card, including its selected JSON-RPC interface and origin policy, then return a plain dictionary copy.

<ApiSection title="Parameters"><ApiFields ariaLabel="get A2A agent card parameters"><ApiField name="agent_url" type="str" required>Base URL of the peer whose standard card should be discovered. Discovery starts from the well-known A2A card location and validates the advertised interface before returning.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="get A2A agent card return value"><ApiField name="card" type="dict[str, Any]">Validated standard A2A 1.0 Agent Card copied into a plain dictionary, including its supported interfaces and capabilities.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="get A2A card errors"><ApiField name="RuntimeError">A2A was not enabled at construction.</ApiField><ApiField name="A2AClientError">Discovery, schema, compatible-interface, or origin validation fails.</ApiField></ApiFields></ApiSection>

</ApiReference>

```python
card = await client.get_a2a_agent_card("http://localhost:8010")
print(card["supportedInterfaces"])
```

---

## Synchronous API

The `AgentClient` provides synchronous versions of its core methods for use in non-async contexts (scripts, notebooks, CLI tools). These are accessible via the `client.sync` property.

Internally, these methods use `asyncio.run()` to handle the asynchronous transport logic.

:::warning[Do Not Use in Async Loops]

The synchronous API should **NOT** be used inside an active event loop (e.g., inside FastAPI endpoints or async Jupyter cells) as it uses `asyncio.run()`, which will raise a `RuntimeError`.

:::

The facade mirrors the asynchronous client method by method. Its arguments,
return values, protocol selection, and control-plane behavior are identical;
only the calling convention changes from `await` to a blocking call.

### SyncAgentClient.send_task

<ApiReference kind="method" path="protolink.client.SyncAgentClient.send_task" signature={`send_task(
    agent_url: str,
    task: Task,
    *,
    protocol: Literal["auto", "protolink", "a2a"] = "auto",
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L603-L622">
Block until a remote agent finishes processing a complete Task. This is the synchronous entry point for the same native or A2A submission path used by <code>AgentClient.send_task()</code>.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous send task parameters">
  <ApiField name="agent_url" type="str" required>Peer base URL or transport-specific URI that should receive the task.</ApiField>
  <ApiField name="task" type="Task" required>Caller-created task containing the request messages, metadata, and any continuation state.</ApiField>
  <ApiField name="protocol" type={'Literal["auto", "protolink", "a2a"]'} defaultValue={'"auto"'}>Select native ProtoLink, require A2A, or automatically probe the native card before falling back to A2A on a 404 or 405 response.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous send task return value"><ApiField name="task" type="Task">Processed remote task normalized into ProtoLink's task model.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Event-loop boundary">This method calls <code>asyncio.run()</code>. Do not invoke it from an active event loop; await <code>client.send_task()</code> instead.</ApiCallout>

</ApiReference>

### SyncAgentClient.send_task_streaming

<ApiReference kind="generator method" path="protolink.client.SyncAgentClient.send_task_streaming" signature={`send_task_streaming(
    agent_url: str,
    task: Task,
) -> Iterator[Any]`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L624-L664">
Return a blocking iterator over the native streaming subscription. A daemon worker thread consumes the asynchronous iterator and forwards each decoded event, preserving the original event order and exception.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous streaming task parameters">
  <ApiField name="agent_url" type="str" required>Peer address understood by the configured streaming transport.</ApiField>
  <ApiField name="task" type="Task" required>Task serialized into the streaming subscription request.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Yields"><ApiFields ariaLabel="synchronous streaming task yields"><ApiField name="event" type="Any">Next transport-decoded status, progress, LLM, artifact, or completion event.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="synchronous streaming task errors"><ApiField name="NotImplementedError">The configured transport does not support subscriptions.</ApiField><ApiField name="stream error">The worker re-raises the original transport or remote exception in the consuming thread.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Streaming implementation">Unlike the other synchronous methods, this generator owns an asynchronous event loop in a daemon worker thread and relays values through a blocking queue.</ApiCallout>

</ApiReference>

### SyncAgentClient.cancel_task

<ApiReference kind="method" path="protolink.client.SyncAgentClient.cancel_task" signature={`cancel_task(
    agent_url: str,
    task_id: str,
    *,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    protocol: Literal["auto", "protolink", "a2a"] = "auto",
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L666-L684">
Synchronously request best-effort cancellation of active remote work. Native cancellation sends the local task ID; A2A cancellation uses the server-assigned mapping retained by this client process.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous cancel task parameters">
  <ApiField name="agent_url" type="str" required>Peer currently running the task.</ApiField>
  <ApiField name="task_id" type="str" required>Local ProtoLink task identifier created by the caller.</ApiField>
  <ApiField name="reason" type="str | None" defaultValue="None">Optional human-readable cancellation reason propagated to the peer.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Additional application context attached to the cancellation request.</ApiField>
  <ApiField name="protocol" type={'Literal["auto", "protolink", "a2a"]'} defaultValue={'"auto"'}>Choose native cancellation, mapped A2A cancellation, or automatic selection.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous cancel task return value"><ApiField name="task" type="Task">Remote task after the peer accepts and records the cancellation request.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Best effort">Acceptance does not roll back completed external side effects or forcibly interrupt synchronous work.</ApiCallout>

</ApiReference>

### SyncAgentClient.compact_history

<ApiReference kind="method" path="protolink.client.SyncAgentClient.compact_history" signature={`compact_history(
    agent_url: str,
    *,
    strategy: HistoryCompactionStrategy = "recent",
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> HistoryCompactionResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L686-L710">
Block while the target agent reduces its LLM conversation history through the control plane. Supplying a persisted session loads, compacts, and saves that session; omitting it targets the agent LLM's current in-memory history.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous compact history parameters">
  <ApiField name="agent_url" type="str" required>Address of the target agent.</ApiField>
  <ApiField name="strategy" type={'Literal["recent", "tokens", "summary"]'} defaultValue={'"recent"'}>History-reduction algorithm selected by the server.</ApiField>
  <ApiField name="max_messages" type="int" defaultValue="20">Maximum message count used by recent-history compaction.</ApiField>
  <ApiField name="max_tokens" type="int" defaultValue="4000">Estimated token budget used by token-aware compaction.</ApiField>
  <ApiField name="preserve_recent" type="int" defaultValue="6">Number of newest messages protected from summarization.</ApiField>
  <ApiField name="summary_max_tokens" type="int" defaultValue="512">Requested maximum token budget for the generated summary.</ApiField>
  <ApiField name="session_id" type="str | None" defaultValue="None">Optional persisted conversation session to compact.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Application context attached to the control request.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous compact history return value"><ApiField name="result" type="HistoryCompactionResult">Strategy metadata and the history's before-and-after message and token counts.</ApiField></ApiFields></ApiSection>

</ApiReference>

### SyncAgentClient.describe_state

<ApiReference kind="method" path="protolink.client.SyncAgentClient.describe_state" signature={`describe_state(
    agent_url: str,
    *,
    session_id: str | None = None,
    stores: tuple[str, ...] | list[str] | None = None,
    include_data: bool = False,
    metadata: dict[str, Any] | None = None,
) -> StateOperationResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L712-L730">
Inspect selected persistent stores without mutating them. The blocking wrapper preserves the asynchronous method's idempotent request semantics and structured per-store report.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous describe state parameters">
  <ApiField name="agent_url" type="str" required>Address of the agent whose state should be inspected.</ApiField>
  <ApiField name="session_id" type="str | None" defaultValue="None">Optional logical conversation session used to scope the inspection.</ApiField>
  <ApiField name="stores" type="tuple[str, ...] | list[str] | None" defaultValue="None">Specific store names to inspect. Omission sends an empty selection so the server can apply its default scope.</ApiField>
  <ApiField name="include_data" type="bool" defaultValue="False">Include stored values when supported instead of returning only availability and count metadata.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Additional context sent with the control request.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous describe state return value"><ApiField name="result" type="StateOperationResult">Per-store enabled, missing, count, data, and error information.</ApiField></ApiFields></ApiSection>

</ApiReference>

### SyncAgentClient.reset_state

<ApiReference kind="method" path="protolink.client.SyncAgentClient.reset_state" signature={`reset_state(
    agent_url: str,
    *,
    session_id: str | None = None,
    stores: tuple[str, ...] | list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> StateOperationResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L732-L748">
Synchronously request deletion or reset of selected persistent state. A session ID narrows conversation deletion; without one, the server applies its configured default scope.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous reset state parameters">
  <ApiField name="agent_url" type="str" required>Address of the agent whose state should be reset.</ApiField>
  <ApiField name="session_id" type="str | None" defaultValue="None">Optional conversation session to clear.</ApiField>
  <ApiField name="stores" type="tuple[str, ...] | list[str] | None" defaultValue="None">Specific stores to reset. Omission leaves store selection to the server's default scope.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Application context attached to the reset request.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous reset state return value"><ApiField name="result" type="StateOperationResult">Structured per-store reset, missing-store, and error report.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Destructive operation">The remote agent's policy and approval handler authorize the mutation. This client wrapper does not prompt for confirmation.</ApiCallout>

</ApiReference>

### SyncAgentClient.compact_state

<ApiReference kind="method" path="protolink.client.SyncAgentClient.compact_state" signature={`compact_state(
    agent_url: str,
    *,
    session_id: str,
    strategy: HistoryCompactionStrategy = "tokens",
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    metadata: dict[str, Any] | None = None,
) -> StateOperationResult`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L750-L774">
Compact one persisted conversation session and return its state report. This operation always targets the <code>"conversation"</code> store and therefore requires an explicit session identifier.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous compact state parameters">
  <ApiField name="agent_url" type="str" required>Address of the agent that owns the persisted conversation.</ApiField>
  <ApiField name="session_id" type="str" required>Existing persisted session to compact.</ApiField>
  <ApiField name="strategy" type={'Literal["recent", "tokens", "summary"]'} defaultValue={'"tokens"'}>Conversation-history reduction strategy.</ApiField>
  <ApiField name="max_messages" type="int" defaultValue="20">Maximum message count used by recent-history compaction.</ApiField>
  <ApiField name="max_tokens" type="int" defaultValue="4000">Estimated token budget used by token-aware compaction.</ApiField>
  <ApiField name="preserve_recent" type="int" defaultValue="6">Number of newest messages protected from summarization.</ApiField>
  <ApiField name="summary_max_tokens" type="int" defaultValue="512">Requested maximum token budget for the summary.</ApiField>
  <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">Application context attached to the control request.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous compact state return value"><ApiField name="result" type="StateOperationResult">Compaction, missing-session, disabled-store, and error information.</ApiField></ApiFields></ApiSection>

</ApiReference>

### SyncAgentClient.send_message

<ApiReference kind="method" path="protolink.client.SyncAgentClient.send_message" signature={`send_message(
    agent_url: str,
    message: Message,
    *,
    protocol: Literal["auto", "protolink", "a2a"] = "auto",
) -> Message`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L776-L793">
Wrap one Message in a new Task, wait for remote processing, and return the newest agent or assistant response. Use <code>send_task()</code> when the caller must retain artifacts, task state, context, or metadata.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous send message parameters">
  <ApiField name="agent_url" type="str" required>Peer address that should receive the message.</ApiField>
  <ApiField name="message" type="Message" required>Input role and parts to place in the generated task.</ApiField>
  <ApiField name="protocol" type={'Literal["auto", "protolink", "a2a"]'} defaultValue={'"auto"'}>Use the same native, A2A, or automatic protocol selection as synchronous task submission.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous send message return value"><ApiField name="message" type="Message">Last returned message whose role is <code>"agent"</code> or <code>"assistant"</code>.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="synchronous send message errors"><ApiField name="RuntimeError">The returned task contains artifacts but no response message, or contains no response message at all.</ApiField></ApiFields></ApiSection>

</ApiReference>

### SyncAgentClient.get_agent_card

<ApiReference kind="method" path="protolink.client.SyncAgentClient.get_agent_card" signature={`get_agent_card(
    agent_url: str,
) -> AgentCard`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/agent.py#L795-L802">
Fetch ProtoLink's native well-known card through the configured transport and parse it into a validated <code>AgentCard</code>.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous get agent card parameters"><ApiField name="agent_url" type="str" required>Base address of the peer whose native ProtoLink card should be retrieved.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous get agent card return value"><ApiField name="card" type="AgentCard">Validated identity, skills, interfaces, security, and capability metadata.</ApiField></ApiFields></ApiSection>

</ApiReference>

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

<ApiReference kind="frozen dataclass" path="protolink.models.ClientRequestSpec" signature={`ClientRequestSpec(
    name: str,
    path: str,
    method: HttpMethod,
    response_parser: Callable[[Any], Any] | None = None,
    request_source: RequestSourceType = "body",
    content_type: ContentType | None = None,
    accept: ContentType | None = None,
    channel: str = "default",
    idempotent: bool = False,
    headers: Mapping[str, str] | None = None,
)`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/client/request_spec.py">
Declare one transport-neutral operation. The dataclass is frozen so clients and transports can safely share a specification as a class-level constant.

<ApiSection title="Fields"><ApiFields ariaLabel="ClientRequestSpec fields">
  <ApiField name="name" type="str" required>Stable operation name used in request contexts, metrics, and diagnostics.</ApiField>
  <ApiField name="path" type="str" required>Protocol-neutral endpoint path carried directly by HTTP or inside multiplexed envelopes.</ApiField>
  <ApiField name="method" type="HttpMethod" required>Logical GET, POST, DELETE, PUT, or PATCH method used by routing and retry-method filtering.</ApiField>
  <ApiField name="response_parser" type="Callable[[Any], Any] | None" defaultValue="None">Conversion from decoded wire data to a domain model.</ApiField>
  <ApiField name="request_source" type="RequestSourceType" defaultValue={'"body"'}>Body, query parameters, form, headers, path parameters, raw request, or no request data.</ApiField>
  <ApiField name="content_type" type="ContentType | None" defaultValue="None">Outbound media-type override.</ApiField>
  <ApiField name="accept" type="ContentType | None" defaultValue="None">Expected response media type.</ApiField>
  <ApiField name="channel" type="str" defaultValue={'"default"'}>Multiplexing lane; control operations use <code>"control"</code>.</ApiField>
  <ApiField name="idempotent" type="bool" defaultValue="False">Explicit promise that replay under one idempotency key is safe. Retry machinery never retries a spec unless this is true.</ApiField>
  <ApiField name="headers" type="Mapping[str, str] | None" defaultValue="None">Optional protocol headers; transports without a header concept may ignore them.</ApiField>
</ApiFields></ApiSection>

</ApiReference>

`idempotent=True` is an application-level safety promise, not an inference made from `POST` or a URL. Custom request specs should enable it only when repeating the operation with the same payload and idempotency key cannot apply the effect twice.

The `channel` field matters only to transports that multiplex several logical operations. Control requests such as cancellation use a separate channel so they are not forced to wait behind the long-running task they are intended to stop. Request/response transports may ignore the distinction while preserving the same client contract.

### Built-in Request Specs

| Spec | Request contract | Description |
|------|------------------|-------------|
| `TASK_REQUEST` | `POST`, `/tasks/`, `channel: default`, `idempotent: True` | Send a task to an agent. The task ID and idempotency key prevent duplicate execution. |
| `TASK_CANCEL_REQUEST` | `POST`, `/tasks/cancel`, `channel: control`, `idempotent: True` | Cancel an active task. Repeating cancellation has the same terminal effect. |
| `COMPACT_HISTORY_REQUEST` | `POST`, `/llm/history/compact`, `channel: control`, `idempotent: False` | Compact the target agent's LLM history. |
| `DESCRIBE_STATE_REQUEST` | `POST`, `/state/describe`, `channel: control`, `idempotent: True` | Inspect target agent state without mutating it. |
| `RESET_STATE_REQUEST` | `POST`, `/state/reset`, `channel: control`, `idempotent: False` | Reset target agent state. |
| `COMPACT_STATE_REQUEST` | `POST`, `/state/compact`, `channel: control`, `idempotent: False` | Compact target agent conversation state. |
| `AGENT_CARD_REQUEST` | `GET`, `/.well-known/agent.json`, `channel: default`, `idempotent: True` | Retrieve agent metadata. |
| `TASK_STREAM_REQUEST` | `POST`, `/tasks/stream`, `channel: default`, `idempotent: False` | Send a task and receive a live event stream. Streams are not replayed by the retry layer. |

The outbound A2A adapter owns separate card-discovery and JSON-RPC request
specifications. Card discovery is idempotent; `SendMessage` is deliberately not,
so transport retry policy cannot create duplicate server-assigned tasks.

### How It Works

When you call a method like `send_task()`:

1. The client selects the appropriate `ClientRequestSpec` (for example, `TASK_REQUEST`).
2. It passes the specification and task data to `transport.send()`.
3. The transport creates correlation and idempotency metadata, applies limits, and constructs the protocol-specific request.
4. The decoded response passes through `response_parser`, so the caller receives a `Task`, `AgentCard`, or another domain model rather than a raw wire dictionary.

If the spec is idempotent and the configured retry policy permits its method, the transport preserves one request ID and idempotency key across attempts. This pattern allows new endpoints without modifying transport implementations while keeping retry safety explicit at the operation boundary.
