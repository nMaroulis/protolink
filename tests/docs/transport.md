# Transport

Protolink implements a **pluggable transport layer** that decouples the agent's cognitive logic from the underlying communication protocol. This architectural pattern allows the same agent instance to effectively "exist" across multiple mediums—whether serving HTTP requests, holding a stateful WebSocket connection, or communicating over a fast in-memory channel—without changing a single line of business logic.

At its core, the Transport abstraction behaves as a **protocol adapter pattern**, normalizing disparate wire formats into standard `Task` and `Message` domain objects.

All transports implement a consistent interface:

- **Ingress bridge**: Maps transport-specific events (HTTP POST, WS frames) to the internal `handle_task` implementation.
- **Egress signaling**: Provides a generic `send` primitive to dispatch requests defined by `ClientRequestSpec` specifications.
- **Lifecycle management**: Handles the startup/shutdown sequence of underlying I/O reactors (e.g., `uvicorn` loops or connection pools).

## Relationship with Client Layer

The **Transport** layer is low-level and typically not used directly by application code. Instead, developers use the high-level **[Client](client.md)** layer (specifically `AgentClient`), which wraps a transport instance and provides convenient, typed methods like `send_task` and `send_message`.

## Supported Transports

All transports inherit from the base `Transport` class.

- **HTTPTransport**
    - Uses HTTP/HTTPS for synchronous request/response.
    - Used for both Agent-to-Agent and Agent-to-Registry communication.
    - Backed by ASGI frameworks:
        - `Starlette` + `httpx` + `uvicorn` (lightweight default backend).
        - `FastAPI` + `pydantic` + `uvicorn` (with optional request validation).
    - Great default choice for web‑based agents, simple deployments, and interoperable APIs.

- **WebSocketTransport**
    - Uses WebSocket for streaming requests and responses.
    - Built on top of libraries like `websockets` (and `httpx` for HTTP parts where applicable).
    - Useful for real‑time, bidirectional communication or token‑level streaming.

- **SSEJSONRPCTransport**
    - Uses HTTP request/response for normal calls and Server-Sent Events for task streams.
    - Streams JSON-RPC-style envelopes from `POST /tasks/stream`.
    - Useful for CLIs, browser clients, dashboards, and other consumers that want streaming without a WebSocket connection.

- **RuntimeTransport**
    - Simple **in‑process, in‑memory transport**.
    - Allows multiple agents to communicate within the same Python process.
    - Ideal for local development, test suites, and tightly‑coupled agent systems with zero network overhead.

### Planned Transports

- **GRPCTransport** (TBD)
  - Planned gRPC transport for agents.
  - Intended for high‑performance, strongly‑typed communication.

## Choosing a Transport

Some rough guidelines:

- Use **RuntimeTransport** for local experiments, tests, or when all agents live in the same process.
- Use **HTTPTransport** when you want a simple, interoperable API surface (e.g. calling agents from other services or frontends) and for communicating with the Registry.
- Use **SSEJSONRPCTransport** when you want HTTP-compatible streaming over `text/event-stream`.
- Use **WebSocketTransport** when you need streaming and interactive sessions.
- Plan for **GRPCTransport** if you need higher performance across services.

The rest of this page dives into the API of each transport in more detail.

---

## HTTPTransport

`HTTPTransport` is the main network transport for communication in Protolink. It handles both Agent-to-Agent JSON HTTP APIs and Registry operations.

### Overview

- **Client side**
  - Uses `httpx.AsyncClient` to send JSON requests to other agents or registries.
  - Implements the generic `send` method to dispatch requests defined by `ClientRequestSpec`.

- **Server side**
  - Uses an ASGI app (Starlette or FastAPI) to expose endpoints like:
    - `POST /tasks/` — submit a `Task` to the agent.
    - `GET /.well-known/agent.json` — agent metadata.
    - Registry endpoints (if acting as a registry).
  - Uses a backend implementation of `BackendInterface` to manage the ASGI app and `uvicorn` server.

### Backend Architecture

`HTTPTransport` separates the network transport logic from the underlying server implementation using the `BackendInterface`.

```python
class BackendInterface(ABC):
    @abstractmethod
    def setup_routes(self, endpoints: list[EndpointSpec]) -> None: ...
    @abstractmethod
    async def start(self, host: str, port: int) -> None: ...
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
| `state`      | `str`            | One of `"submitted"`, `"working"`, `"completed"`, etc. |
| `messages`   | `list[Message]`  | Conversation history for this task.           |
| `artifacts`  | `list[Artifact]` | Outputs produced by the task.                 |
| `metadata`   | `dict[str, Any]` | Arbitrary metadata attached to the task.      |
| `created_at` | `str`            | ISO‑8601 timestamp (UTC).                     |

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
| `role`      | `"user" ⎪ "agent" ⎪ "system"` | Sender role.               |
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
  "created_at": "2025-01-01T12:00:00Z"
}
```

| Field         | Type             | Description                 |
|-------------- |------------------|-----------------------------|
| `id` | `str`            | Unique artifact identifier. |
| `parts`       | `list[Part]`     | Artifact content.           |
| `metadata`    | `dict[str, Any]` | Artifact metadata.          |
| `created_at`  | `str`            | ISO‑8601 timestamp.         |

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
| `__init__` | `url: str`, `timeout: float = 360.0`, `authenticator: Authenticator ⎪ None = None`, `backend: Literal["starlette", "fastapi"] = "starlette"`, `validate_schema: bool = False`, `credentials: str ⎪ None = None`, `log_level: str = "info"`, `access_log: bool = True` | `None` | Configure URL, timeout, authentication, backend, validation, and Uvicorn logging behavior. |
| `start` | `self` | `Awaitable[None]` | Start the selected backend, register the `/tasks/` route and create the internal `httpx.AsyncClient`. Must be awaited before serving HTTP traffic. |
| `stop` | `self` | `Awaitable[None]` | Stop the backend server and close the internal HTTP client. Safe to call multiple times. |

#### Properties

| Name | Type | Access | Description |
| ---- | ---- | ------ | ----------- |
| `url` | `str` | Read-only | The base URL configured for this transport. |
| `timeout` | `float` | Read/Write | The request timeout (in seconds) for outgoing requests. This can be changed at runtime to easily adjust timeouts for subsequent requests without restarting the transport. |

#### Sending & receiving

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `on_task_received` | `handler: Callable[[Task], Awaitable[Task]]` | `None` | Register the callback that will handle incoming tasks on `POST /tasks/`. This must be set before `start()` when running as a server. |
| `send` | `request_spec: ClientRequestSpec`, `base_url: str`, `data: Any = None`, `params: dict ⎪ None = None` | `Awaitable[Any]` | Send a generic request to the agent. This is the low-level primitive used by `AgentClient`. |

#### Auth & utilities

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `authenticate` | `credentials: str` | `Awaitable[None]` | Use the configured `Authenticator` to obtain an auth context (for example, exchanging an API key for a bearer token). The resulting context is automatically injected into outgoing HTTP headers. |
| `_build_headers` | `skill: str ⎪ None = None` | `dict[str, str]` | Internal helper that constructs HTTP headers (including `Authorization` when an auth context is present). Exposed here for completeness; you normally do not need to call it directly. |
| `validate_url` | `-` | `-` | Return `True` if the URL is considered local to this transport's host/port (e.g. for allow‑listing), `False` otherwise. |

---

## RuntimeTransport

`RuntimeTransport` is an in-process, in-memory transport that enables agents to communicate directly without network overhead. Perfect for testing, local multi-agent setups, and rapid prototyping.

### Overview

Unlike network transports (HTTP, WebSocket), RuntimeTransport avoids actual TCP I/O. However, it perfectly mirrors the behavioral boundaries of `HTTPTransport` ensuring seamless interchangeability:

- **Strict URL Routing** — each agent transport is initialized explicitly with a unique URL (e.g., `runtime://agent-name`).
- **Global In-Memory Registry** — transports discover each other seamlessly through an automatic shared class-level global registry.
- **Serialization Isolation** — message models natively pass through Pydantic dict boundaries, maintaining process and state safety equivalently to HTTP wire framing.
- **Supports streaming** — agents can use generic `EndpointSpec` routing for real-time task streams.

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
| `__init__` | `url: str` | `None` | Create an isolated in-memory transport. Bound to a specified runtime URL. |
| `start` | `self` | `Awaitable[None]` | Register the allocated `url` actively directly on the class-level registry cache. |
| `stop` | `self` | `Awaitable[None]` | Detach registry allocations cleaning up in-memory routing bindings. |

#### Properties

| Name | Type | Access | Description |
| ---- | ---- | ------ | ----------- |
| `url` | `str` | Read-only | The unique runtime URL allocated to this transport. |
| `is_running` | `bool` | Read-only | Whether the transport is currently registered in the global in-memory registry. |

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
| `__init__` | `...` | `None` | Configure host/port and WebSocket settings for streaming connections. |
| `subscribe` | `agent_url: str`, `task: Any` | `AsyncIterator[Any]` | Send a `Task` to `/tasks/stream` and receive task event payloads over a single WebSocket connection. |
| `start` / `stop` | `self` | `Awaitable[None]` | Start or stop the WebSocket server. |

#### Properties

| Name | Type | Access | Description |
| ---- | ---- | ------ | ----------- |
| `url` | `str` | Read-only | The base URL configured for this transport. |
| `timeout` | `float` | Read/Write | The timeout (in seconds) for WebSocket receive operations. This can be changed at runtime to adjust response wait times for subsequent requests. |

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

### API

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `subscribe` | `agent_url: str`, `task: Any` | `AsyncIterator[Any]` | POST a task to `/tasks/stream`, parse SSE JSON-RPC envelopes, and yield each `result` payload. |
| `send` | `request_spec`, `base_url`, `data`, `params` | `Awaitable[Any]` | Inherited from `HTTPTransport` for normal request/response calls. |
