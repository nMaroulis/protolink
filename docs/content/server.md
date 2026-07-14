import ApiSurface from '@site/src/components/ApiSurface';

# Server

Servers in Protolink act as the **coordination layer** between business logic (Agents or Registries) and the underlying Transport mechanism. They are responsible for wiring endpoints, managing lifecycle, and ensuring that the core logic remains transport-agnostic.

`AgentServer` always binds ProtoLink's native endpoints. When an HTTP agent is created with `a2a=True`, it additionally binds the A2A 1.0 adapter to the same execution logic. Agent authors still implement `handle_task(Task)` once.

<ApiSurface
  eyebrow="Server coordination layer"
  title="AgentServer and RegistryServer"
  path="protolink.server"
  description="The endpoint declaration layer that binds Agent and Registry behavior to whatever transport backend is running the process."
  pills={[
    "EndpointSpec-driven",
    "Transport-agnostic",
    "Agent and registry servers",
    "Streaming routes",
    "A2A 1.0 HTTP routes",
    "Status and chat endpoints",
  ]}
  cards={[
    {
      title: "AgentServer",
      text: "Exposes native task, streaming, discovery, cancellation, status, chat, and LLM control endpoints, with an opt-in A2A 1.0 JSON-RPC boundary.",
      code: "/tasks/",
    },
    {
      title: "RegistryServer",
      text: "Exposes registration, deregistration, discovery, liveness, and status endpoints.",
      code: "/agents/",
    },
    {
      title: "EndpointSpec",
      text: "Keeps route definitions declarative so transports can bind the same contract to different backends.",
      code: "EndpointSpec",
    },
    {
      title: "Lifecycle",
      text: "Starts and stops the transport without moving business behavior into network adapters.",
      code: "start() / stop()",
    },
  ]}
/>

## Concept

A **Server** does **not** implement networking itself. Instead, it:
1.  **Defines Endpoints**: Declares the API surface (paths, methods, handlers).
2.  **Binds Handlers**: Connects these endpoints to the implementation (Agent or Registry).
3.  **Manages Lifecycle**: Starts and stops the underlying transport.

This separation allows an Agent to run over HTTP, WebSocket, or in-memory transports without changing a single line of agent code.

---

## AgentServer

The `AgentServer` exposes an `Agent` over a Transport.

### Responsibilities
- Exposing the Task submission endpoint.
- Exposing the Task streaming endpoint when the transport supports streaming.
- Serving the Agent's identity card (`/.well-known/agent.json`).
- On HTTP with `a2a=True`, serving the A2A 1.0 Agent Card and JSON-RPC adapter.
- Providing a status page.
- Exposing the Chat Gateway when the agent has an LLM.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks/` | `POST` | **Task Submission**. Accepts a `Task` object, processes it via the Agent, and returns the result. |
| `/tasks/stream` | `POST` | **Task Streaming**. Accepts a `Task` object and streams status, LLM, tool, artifact, and final events. Only registered when the transport has `supports_streaming=True`. |
| `/.well-known/agent.json` | `GET` | **Agent Discovery**. Returns the `AgentCard` describing this agent. |
| `/.well-known/agent-card.json` | `GET` | **A2A 1.0 Agent Card**. Added only by `Agent(..., transport="http", a2a=True)`; returns the standard wire card. |
| `/` | `POST` | **A2A 1.0 JSON-RPC**. Added only with `a2a=True`; handles `SendMessage`, `GetTask`, `ListTasks`, and `CancelTask`. |
| `/status` | `GET` | **Status Page**. Returns a human-readable HTML status dashboard. |
| `/chat` | `GET` | **Chat Page**. Returns a self-contained HTML/CSS/JS chat interface. Always registered; shows a fallback message if no LLM is configured. |
| `/chat` | `POST` | **Chat Message**. Accepts `{"message": "...", "session_id": "..."}` and returns the agent's response. *Only registered when the agent has an LLM.* |

The two A2A 1.0 routes require both the exact `HTTPTransport` and `a2a=True`. With the default `False`, HTTP retains the native endpoint contract and does not expose `/.well-known/agent-card.json` or `POST /`. Other transports are not presented as A2A 1.0 wire bindings. See [A2A Core and 1.0 Compatibility](a2a.md) for the implemented scope and TCK evidence.

### Usage

The `Agent` class automatically creates an `AgentServer` internally when a transport is provided. You rarely need to instantiate `AgentServer` or wire the A2A adapter directly.

```python
# AgentServer is created internally; A2A routes are explicit and additive.
agent = Agent(card=card, transport="http", a2a=True)

agent.start()
```

---

## RegistryServer

The `RegistryServer` exposes a `Registry` over a Transport.

### Responsibilities
- Handling agent registration and deregistration.
- Serving the discovery endpoint for finding agents.
- Providing a status page.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agents/` | `POST` | **Register**. Registers an agent with the registry. Body: `AgentCard`. |
| `/agents/` | `DELETE` | **Unregister**. Removes an agent. Query Param: `agent_url`. |
| `/agents/` | `GET` | **Discover**. Returns a list of agents matching filter criteria. Query Param: `filter_by` (JSON). |
| `/status` | `GET` | **Status Page**. Returns a human-readable HTML status dashboard. |

### Usage

```python
from protolink.discovery.registry import Registry
from protolink.transport import HTTPTransport
from protolink.server.registry import RegistryServer

# Create logic and transport
transport = HTTPTransport(url="http://localhost:8000")
registry = Registry(transport=transport)

# Create Server (wiring)
server = RegistryServer(registry, transport)

# Start
await server.start()
```

---

## Architecture

The server architecture relies on the `EndpointSpec` model to define routes in a generic way.

### EndpointSpec

The `EndpointSpec` class (defined in `protolink.server.endpoint_handler`) is the **contract** between a Server and a Transport.

```python
@dataclass(frozen=True)
class EndpointSpec:
    name: str              # Internal unique name for the endpoint
    path: str              # URL path (e.g. "/tasks/")
    method: HttpMethod     # HTTP Method (GET, POST, etc.)
    handler: Callable      # Async function to process the request
    
    # Configuration
    content_type: Literal["json", "html"] = "json"
    streaming: bool = False
    mode: Literal["request_response", "stream"] = "request_response"
    
    # Request Parsing
    request_parser: Callable[[Any], Any] | None = None
    request_source: RequestSourceType = "none"
```

### How it Works

1.  **Transport-Agnostic Definition**: The Server creates a list of `EndpointSpec` objects describing what it needs to expose.
2.  **Transport Implementation**: The Transport iterates over these specs and registers them with its underlying web framework (e.g., Starlette or FastAPI).
3.  **Request Handling**:
    - The Transport receives a raw HTTP request.
    - It extracts data based on `request_source` (e.g., reads the body JSON).
    - It passes this data to the `request_parser` (if defined) to convert it into a domain object.
    - It calls the `handler` with the domain object.
    - For request/response endpoints, it serializes the result back to the wire format.
    - For streaming endpoints, it iterates the handler and serializes each event until a final event closes the stream.

This design ensures that your Agent logic deals only with `Task` and `Message` objects, never raw HTTP requests, while the Transport handles the nitty-gritty of networking protocols.
