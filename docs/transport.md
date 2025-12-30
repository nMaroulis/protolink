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

- **RuntimeTransport**
  - Simple **in‑process, in‑memory transport**.
  - Allows multiple agents to communicate within the same Python process.
  - Ideal for local development, test suites, and tightly‑coupled agent systems with zero network overhead.

### Planned Transports

- **JSONRPCTransport** (TBD)
  - Planned JSON‑RPC based transport for agents.
  - Intended for structured, RPC‑style interactions.

- **GRPCTransport** (TBD)
  - Planned gRPC transport for agents.
  - Intended for high‑performance, strongly‑typed communication.

## Choosing a Transport

Some rough guidelines:

- Use **RuntimeTransport** for local experiments, tests, or when all agents live in the same process.
- Use **HTTPTransport** when you want a simple, interoperable API surface (e.g. calling agents from other services or frontends) and for communicating with the Registry.
- Use **WebSocketTransport** when you need streaming and interactive sessions.
- Plan for **JSONRPCTransport** or **GRPCTransport** if you need stricter schemas or higher performance across services.

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

Then run the agent and call it from another agent or client using `send_task_to` or `send_message_to`.

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
        result = await self.send_task_to(self.target_url, task)
        return result


async def call_remote(url: str) -> None:
    hello = Task.create(Message.user("Hello over HTTP!"))
    result = await caller_agent.send_task_to(url, hello)
    print("Response:", result.messages[-1].parts[0].content)
```

### HTTPTransport API Reference

The most important public methods on `HTTPTransport` are summarized below.

#### Constructor & lifecycle

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `__init__` | `url: str`, `timeout: float = 30.0`, `authenticator: Authenticator \| None = None`, `backend: Literal["starlette", "fastapi"] = "starlette"`, `validate_schema: bool = False` | `None` | Configure URL, request timeout, optional authentication provider, backend implementation, and whether to enable FastAPI/Pydantic schema validation. |
| `start` | `self` | `Awaitable[None]` | Start the selected backend, register the `/tasks/` route and create the internal `httpx.AsyncClient`. Must be awaited before serving HTTP traffic. |
| `stop` | `self` | `Awaitable[None]` | Stop the backend server and close the internal HTTP client. Safe to call multiple times. |

#### Sending & receiving

| Name | Parameters | Returns | Description |
| ---- | ---------- | ------- | ----------- |
| `on_task_received` | `handler: Callable[[Task], Awaitable[Task]]` | `None` | Register the callback that will handle incoming tasks on `POST /tasks/`. This must be set before `start()` when running as a server. |
| `send` | `request_spec: ClientRequestSpec`, `base_url: str`, `data: Any = None`, `params: dict \| None = None` | `Awaitable[Any]` | Send a generic request to the agent. This is the low-level primitive used by `AgentClient`. |

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
| `send` | `request_spec: ClientRequestSpec`, `base_url: str`, `data: Any = None`, `params: dict \| None = None` | `Any \| Awaitable[Any]` | Dispatch a generic request to another agent registered on the same runtime transport instance. |
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
| `send_task_stream` | `...` | `AsyncIterator[Task] \| AsyncIterator[Message]` | Send a `Task` and receive a stream of partial results or updates over a single WebSocket connection. |
| `start` / `stop` | `self` | `Awaitable[None]` | Start or stop the WebSocket server. |

