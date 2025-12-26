# Server API Reference

Servers in Protolink act as the **coordination layer** between business logic (Agents or Registries) and the underlying Transport mechanism. They are responsible for wiring endpoints, managing lifecycle, and ensuring that the core logic remains transport-agnostic.

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
- Serving the Agent's identity card (`/.well-known/agent.json`).
- Providing a status page.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks/` | `POST` | **Task Submission**. Accepts a `Task` object, processes it via the Agent, and returns the result. |
| `/.well-known/agent.json` | `GET` | **Agent Discovery**. Returns the `AgentCard` describing this agent. |
| `/status` | `GET` | **Status Page**. Returns a human-readable HTML status dashboard. |

### Usage

The `Agent` class automatically creates an `AgentServer` internally when a transport is provided. You rarely need to instantiate `AgentServer` directly.

```python
# AgentServer is created internally here
agent = Agent(card=card, transport=transport)

# This calls agent.server.start()
await agent.start()
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
from protolink.transport import HTTPRegistryTransport
from protolink.server.registry import RegistryServer

# Create Logic
registry = Registry()

# Create Transport
transport = HTTPRegistryTransport(port=8000)

# Create Server (wiring)
server = RegistryServer(registry, transport)

# Start
await server.start()
```

---

## Architecture

The server architecture relies on the `EndpointSpec` model to define routes in a generic way.

### EndpointSpec

The `EndpointSpec` class (defined in `protolink.core.endpoint_handler`) is the **contract** between a Server and a Transport.

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
    - It serializes the result back to the wire format.

This design ensures that your Agent logic deals only with `Task` and `Message` objects, never raw HTTP requests, while the Transport handles the nitty-gritty of networking protocols.

