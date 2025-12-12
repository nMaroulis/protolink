# Transports

Protolink supports multiple transports for agent communication. A **transport** is responsible for delivering `Task` and `Message` objects between agents and for exposing an API surface (HTTP, WebSocket, in‑memory, etc.).

At a high level, all transports implement the same conceptual operations:

- **Send work**: send a `Task` or `Message` to another agent.
- **Receive work**: expose an endpoint / callback to handle incoming tasks.
- **Lifecycle**: start and stop the underlying server or runtime.

The sections below describe the available transports in more detail, with an emphasis on `HTTPTransport`.

## Supported Transports

- **HTTPTransport**
  - Uses HTTP/HTTPS for synchronous request/response.
  - Backed by ASGI frameworks:
    - `Starlette` + `httpx` + `uvicorn` (lightweight default backend).
    - `FastAPI` + `pydantic` + `uvicorn` (with optional request validation).
  - Great default choice for web‑based agents, simple deployments, and interoperable APIs.

- **WebSocketTransport**
  - Uses WebSocket for streaming requests and responses.
  - Built on top of libraries like `websockets` (and `httpx` for HTTP parts where applicable).
  - Useful for real‑time, bidirectional communication or token‑level streaming.

- **JSONRPCTransport** (TBD)
  - Planned JSON‑RPC based transport.
  - Intended for structured, RPC‑style interactions.

- **GRPCTransport** (TBD)
  - Planned gRPC transport.
  - Intended for high‑performance, strongly‑typed communication.

- **RuntimeTransport**
  - Simple **in‑process, in‑memory transport**.
  - Allows multiple agents to communicate within the same Python process.
  - Ideal for local development, testing, and tightly‑coupled agent systems.

## Choosing a Transport

Some rough guidelines:

- Use **RuntimeTransport** for local experiments, tests, or when all agents live in the same process.
- Use **HTTPTransport** when you want a simple, interoperable API surface (e.g. calling agents from other services or frontends).
- Use **WebSocketTransport** when you need streaming and interactive sessions.
- Plan for **JSONRPCTransport** or **GRPCTransport** if you need stricter schemas or higher performance across services.

The rest of this page dives into the API of each transport in more detail.

---

## HTTPTransport

`HTTPTransport` is the main network transport in Protolink. It exposes a simple JSON HTTP API compatible with the rest of the framework.

### Overview

- **Client side**
  - Uses `httpx.AsyncClient` to send JSON requests.
  - Provides helpers to send a full `Task` or a single `Message`.

- **Server side**
  - Uses an ASGI app (Starlette or FastAPI) to expose:
    - `POST /tasks/` — submit a `Task` to the agent.
    - `GET /.well-known/agent.json` — served by the agent itself, not the transport, but typically used together.
  - Uses a backend implementation of `BackendInterface` to manage the ASGI app and `uvicorn` server.

### Backends: Starlette vs FastAPI

`HTTPTransport` delegates server behavior to a **backend** implementing `BackendInterface`:

- **StarletteBackend** (default)
  - Minimal Starlette app with a single `POST /tasks/` route.
  - No extra request validation beyond what `Task.from_dict()` does.
  - Best when you want low overhead and trust callers to send valid payloads.

- **FastAPIBackend**
  - FastAPI app with optional Pydantic models mirroring the `Task`/`Message`/`Artifact` structures.
  - When `validate_schema=True`, incoming requests are validated against these models before being converted with `Task.from_dict()`.
  - Best when you want schema validation and better generated OpenAPI / docs.

Backend and validation are selected via the `HTTPTransport` constructor:

```python
from protolink.transport.http_transport import HTTPTransport

# Starlette backend (default)
transport = HTTPTransport()

# Explicit Starlette backend
transport = HTTPTransport(backend="starlette")

# FastAPI backend without schema validation
transport = HTTPTransport(backend="fastapi", validate_schema=False)

# FastAPI backend with full schema validation
transport = HTTPTransport(backend="fastapi", validate_schema=True)
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
| `role`      | `"user" \| "agent" \| "system"` | Sender role.               |
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
  "artifact_id": "a1b2c3",
  "parts": [
    {"type": "text", "content": "final report"}
  ],
  "metadata": {"kind": "report"},
  "created_at": "2025-01-01T12:00:00Z"
}
```

| Field         | Type             | Description                 |
|-------------- |------------------|-----------------------------|
| `artifact_id` | `str`            | Unique artifact identifier. |
| `parts`       | `list[Part]`     | Artifact content.           |
| `metadata`    | `dict[str, Any]` | Artifact metadata.          |
| `created_at`  | `str`            | ISO‑8601 timestamp.         |

### Typical Usage

#### Exposing an agent over HTTP

```python
from protolink.agents import Agent
from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.transport.http_transport import HTTPTransport


class EchoAgent(Agent):
    def __init__(self, port: int) -> None:
        card = AgentCard(
            name="echo", description="Echoes back the last user message", url=f"http://127.0.0.1:{port}",
        )
        transport = HTTPTransport(host="127.0.0.1", port=port)
        super().__init__(card, transport=transport)

    async def handle_task(self, task: Task) -> Task:
        last_msg = task.messages[-1]
        reply = Message.agent(f"echo: {last_msg.parts[0].content}")
        return Task(id=task.id, messages=task.messages + [reply])
```

Then run the agent and call it from another agent or client using `send_task` or `send_message`.

#### Calling a remote agent

```python
from protolink.client.agent_client import AgentClient
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.transport.http_transport import HTTPTransport


client = AgentClient(HTTPTransport())


async def call_remote(url: str) -> None:
    hello = Task.create(Message.user("Hello over HTTP!"))
    result = await client.send_task(url, hello)
    print("Response:", result.messages[-1].parts[0].content)
```

### HTTPTransport API Reference

The most important public methods on `HTTPTransport` are summarized below.

#### Constructor & lifecycle

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | `host: str = "0.0.0.0"`, `port: int = 8000`, `timeout: float = 30.0`, `authenticator: Authenticator \| None = None`, `backend: Literal["starlette", "fastapi"] = "starlette"`, `validate_schema: bool = False` | `None` | Configure host/port, request timeout, optional authentication provider, backend implementation, and whether to enable FastAPI/Pydantic schema validation. |
| `start` | `self` | `Awaitable[None]` | Start the selected backend, register the `/tasks/` route and create the internal `httpx.AsyncClient`. Must be awaited before serving HTTP traffic. |
| `stop` | `self` | `Awaitable[None]` | Stop the backend server and close the internal HTTP client. Safe to call multiple times. |

#### Sending & receiving

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `on_task_received` | `handler: Callable[[Task], Awaitable[Task]]` | `None` | Register the callback that will handle incoming tasks on `POST /tasks/`. This must be set before `start()` when running as a server. |
| `send_task` | `agent_url: str`, `task: Task`, `skill: str \| None = None` | `Awaitable[Task]` | Send a `Task` to `POST {agent_url}/tasks/` and return the resulting `Task` from the remote agent. The optional `skill` is passed via headers and can be used by agents to route work. |
| `send_message` | `agent_url: str`, `message: Message` | `Awaitable[Message]` | Convenience wrapper that wraps a single `Message` in a new `Task`, calls `send_task`, and returns the last response message. Ideal for simple request/response interactions. |
| `get_agent_card` | `agent_url: str` | `Awaitable[AgentCard]` | Fetch the remote agent's `AgentCard` description from `GET {agent_url}/.well-known/agent.json`. Useful for discovery and capability inspection. |

#### Auth & utilities

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `authenticate` | `credentials: str` | `Awaitable[None]` | Use the configured `Authenticator` to obtain an auth context (for example, exchanging an API key for a bearer token). The resulting context is automatically injected into outgoing HTTP headers. |
| `_build_headers` | `skill: str \| None = None` | `dict[str, str]` | Internal helper that constructs HTTP headers (including `Authorization` when an auth context is present). Exposed here for completeness; you normally do not need to call it directly. |
| `validate_agent_url` | `agent_url: str` | `bool` | Return `True` if the URL is considered local to this transport's host/port (e.g. for allow‑listing), `False` otherwise. |

---

## RuntimeTransport

`RuntimeTransport` is an in‑process, in‑memory transport used primarily for tests, local experimentation, and tightly‑coupled multi‑agent systems.

Characteristics:

- No network hops, very low latency.
- Multiple agents share the same runtime transport instance.
- Ideal for composition and unit tests (see `tests/test_agent.py`).

### RuntimeTransport API

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | `...` | `None` | Create an in‑memory transport registry for agents that live in the same Python process. |
| `register` | `agent` | `None` | Add an agent to the runtime transport so it can receive tasks from others. |
| `unregister` | `agent` | `None` | Remove an agent from the runtime transport. |
| `send_task` | `agent_id_or_url`, `task: Task` | `Task \| Awaitable[Task]` | Dispatch a `Task` to another agent registered on the same runtime transport instance. Exact return type depends on the concrete implementation. |
| `start` / `stop` | `self` | `None` | Often no‑op or light‑weight setup/teardown. Provided for a consistent lifecycle API with other transports. |

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
| `send_task_stream` | `...` | `AsyncIterator[Task] \| AsyncIterator[Message]` | Send a `Task` and receive a stream of partial results or updates over a single WebSocket connection. (Exact type depends on implementation.) |
| `start` / `stop` | `self` | `Awaitable[None]` | Start or stop the WebSocket server. |

---

## Planned Transports

These transports are **not implemented yet** in the core library. The sections below describe the *intended* design so you can plan ahead, but there is currently no public API to import.

> **Status:** Design sketches only. Do not rely on these in production code.

### JSONRPCTransport (planned)

- JSON‑RPC 2.0 style envelope for structured requests and responses.
- Strong separation of methods, params, and results.
- Natural fit for RPC‑style integrations.

#### JSONRPCTransport design

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `send_request` | `method: str`, `params: dict` | `Awaitable[dict]` | (Planned) Send a JSON‑RPC request and return the decoded result payload. |
| `notify` | `method: str`, `params: dict` | `Awaitable[None]` | (Planned) Fire‑and‑forget notification without a response. |
| `start` / `stop` | `self` | `Awaitable[None]` | (Planned) Start/stop the JSON‑RPC server. |

### GRPCTransport (planned)

- gRPC‑based transport with protobuf definitions for tasks and messages.
- High‑performance, strongly‑typed, streaming‑friendly.

#### GRPCTransport design

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `send_task` | `...` | `Awaitable[...]` | (Planned) Unary RPC for sending tasks. |
| `send_task_stream` | `...` | `AsyncIterator[...]` | (Planned) Streaming RPC for long‑running tasks and progress updates. |
| `start` / `stop` | `self` | `Awaitable[None]` | (Planned) Start/stop the gRPC server. |

