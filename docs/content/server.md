import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

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
| `/tasks/cancel` | `POST` | **Task Cancellation**. Parses a `TaskCancellationRequest` and asks the Agent to cancel active work. |
| `/tasks/stream` | `POST` | **Task Streaming**. Accepts a `Task` object and streams status, LLM, tool, artifact, and final events. Only registered when the transport has `supports_streaming=True`. |
| `/llm/history/compact` | `POST` | **History Compaction**. Runs the Agent's explicit conversation-compaction control plane. |
| `/state/describe` | `POST` | **State Description**. Reports enabled persistent state stores. |
| `/state/reset` | `POST` | **State Reset**. Clears selected persistent state stores after policy authorization. |
| `/state/compact` | `POST` | **State Compaction**. Compacts selected persistent state stores after policy authorization. |
| `/.well-known/agent.json` | `GET` | **Agent Discovery**. Returns the `AgentCard` describing this agent. |
| `/.well-known/agent-card.json` | `GET` | **A2A 1.0 Agent Card**. Added only by `Agent(..., transport="http", a2a=True)`; returns the standard wire card. |
| `/` | `POST` | **A2A 1.0 JSON-RPC**. Added only with `a2a=True`; handles `SendMessage`, `GetTask`, `ListTasks`, and `CancelTask`. |
| `/status` | `GET` | **Status Page**. Returns a human-readable HTML status dashboard. |
| `/healthz` | `GET` | **Health**. Returns the underlying transport's health snapshot. |
| `/readyz` | `GET` | **Readiness**. Currently calls the same transport health method as `/healthz`. |
| `/chat` | `GET` | **Chat Page**. Returns a self-contained HTML/CSS/JS chat interface. Always registered; shows a fallback message if no LLM is configured. |
| `/chat` | `POST` | **Chat Message**. Accepts `{"message": "...", "session_id": "..."}` and returns the agent's response. *Only registered when the agent has an LLM.* |

The two A2A 1.0 routes require a transport whose `transport_type` is `"http"`
and `a2a=True`. With the default `False`, HTTP retains the native endpoint
contract and does not expose `/.well-known/agent-card.json` or `POST /`. Other
transports are not presented as A2A 1.0 wire bindings. See
[A2A Core and 1.0 Compatibility](a2a.md) for the implemented scope and TCK
evidence.

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
| `/agents/` | `DELETE` | **Unregister**. Removes an agent. Body: `{"agent_url": "..."}`. |
| `/agents/heartbeat` | `POST` | **Heartbeat**. Refreshes liveness for one agent URL. |
| `/agents/` | `GET` | **Discover**. Returns agents matching direct query filters such as `?name=worker&role=worker`. |
| `/status` | `GET` | **Status Page**. Returns a human-readable HTML status dashboard. |
| `/healthz` | `GET` | **Health**. Returns the underlying transport's health snapshot. |
| `/readyz` | `GET` | **Readiness**. Currently calls the same transport health method as `/healthz`. |

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

---

## Server API reference

The two server classes are the public package surface. `EndpointSpec` and
`EndpointRequest` live in `protolink.server.endpoint_handler`; they are included
here because custom transports and protocol adapters need the same declarative
route contract even though those types are not re-exported from
`protolink.server`.

### AgentInterface server protocol

<ApiReference
  kind="protocol"
  path="protolink.server.agent.AgentInterface"
  signature={`class AgentInterface(Protocol)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/agent.py#L32"
>

Describe the structural surface that `AgentServer` calls. An object does not
need to inherit from this protocol; it only needs to provide compatible
attributes and methods.

<ApiSection title="Required surface">
  <ApiFields ariaLabel="AgentInterface server protocol members">
    <ApiField name="card" type="AgentCard">
      Public identity and capabilities.
    </ApiField>
    <ApiField name="handle_task / run_task" type="async (Task) -> Task">
      Business handler and its cancellation-aware execution wrapper.
    </ApiField>
    <ApiField name="handle_task_streaming / run_task_streaming" type="(Task) -> AsyncIterator[Any]">
      Business event stream and its cancellation-aware wrapper.
    </ApiField>
    <ApiField name="cancel_task" type="async (TaskCancellationRequest) -> Task">
      Active-task cancellation control.
    </ApiField>
    <ApiField name="compact_history" type="async (HistoryCompactionRequest) -> HistoryCompactionResult">
      Explicit LLM history compaction.
    </ApiField>
    <ApiField name="describe_state / reset_state / compact_state" type="async (StateOperationRequest) -> StateOperationResult">
      Persistent-state control-plane handlers.
    </ApiField>
    <ApiField name="get_agent_card" type="(*, as_json: bool = True) -> AgentCard | dict[str, Any]">
      Native discovery document.
    </ApiField>
    <ApiField name="get_status" type={'(output_format: "html" | "json" = "html") -> str'}>
      Render Agent status as HTML or, for <code>"json"</code>, the current
      Python <code>str(card.to_dict())</code> representation. That branch is not
      guaranteed to be valid JSON.
    </ApiField>
    <ApiField name="get_chat" type="() -> str">
      Render the HTML chat page.
    </ApiField>
    <ApiField name="handle_chat_message" type="async (dict[str, Any]) -> dict[str, str]">
      Chat message endpoint handler.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Name collision">
  This internal server protocol is not re-exported from
  <code>protolink.server</code>. The public
  <code>protolink.AgentInterface</code> name refers instead to the Agent Card
  interface dataclass containing a URL, transport, and protocol version.
</ApiCallout>

</ApiReference>

### AgentServer

<ApiReference
  kind="class"
  path="protolink.server.AgentServer"
  signature={`class AgentServer(
    transport: Transport,
    agent: AgentInterface,
    *,
    a2a: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/agent.py#L82"
>

Bind an Agent-compatible object to a configured transport. Construction records
the collaborators and validates A2A compatibility; endpoint registration and
network startup are deferred until `start()`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentServer constructor parameters">
    <ApiField name="transport" type="Transport" required>
      Concrete transport that receives endpoint specifications and owns the
      listening lifecycle. Passing <code>None</code> is rejected immediately.
    </ApiField>
    <ApiField name="agent" type="AgentInterface" required>
      Structurally compatible object implementing task execution, streaming,
      cancellation, history/state controls, card/status/chat rendering, and chat
      message handling. Runtime inheritance from the protocol is not required.
    </ApiField>
    <ApiField name="a2a" type="bool" defaultValue="False">
      Build an A2A 1.0 JSON-RPC adapter and its two additional endpoints. When
      enabled, <code>transport.transport_type</code> must equal
      <code>"http"</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="AgentServer constructor errors">
    <ApiField name="ValueError">
      Raised when no transport is supplied, or when <code>a2a=True</code> is
      paired with a non-HTTP transport type.
    </ApiField>
    <ApiField name="adapter construction error">
      A2A adapter initialization errors propagate when A2A support is enabled.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Endpoint timing">
  Constructing the server does not call <code>setup_routes()</code>. Route
  declarations are built during the first successful <code>start()</code>.
</ApiCallout>

</ApiReference>

### AgentServer.start

<ApiReference
  kind="async method"
  path="protolink.server.AgentServer.start"
  signature={`await start() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/agent.py#L260"
>

Build the complete endpoint table, pass it to the transport, and await the
transport's server startup.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentServer.start return value">
    <ApiField name="None" type="None">
      The server records itself as running only after
      <code>transport.start()</code> completes successfully.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Side effects">
  <ApiFields ariaLabel="AgentServer.start side effects">
    <ApiField name="native routes" type="EndpointSpec[]">
      Registers task submission/cancellation, history and state controls, card,
      status, health/readiness, and chat-page endpoints.
    </ApiField>
    <ApiField name="task stream" type="conditional route">
      Adds <code>POST /tasks/stream</code> only when the transport advertises
      <code>supports_streaming=True</code>.
    </ApiField>
    <ApiField name="chat message" type="conditional route">
      Adds <code>POST /chat</code> when the Agent has an <code>llm</code>, or
      its card capabilities advertise <code>has_llm=True</code>.
    </ApiField>
    <ApiField name="A2A routes" type="conditional routes">
      Adds the standard Agent Card and root JSON-RPC routes when the server owns
      an A2A adapter.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="AgentServer.start errors">
    <ApiField name="route or transport error">
      Exceptions from endpoint construction, <code>setup_routes()</code>, or
      <code>transport.start()</code> propagate. The running flag remains
      <code>False</code> if startup does not complete.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Idempotence">
  Calling <code>start()</code> again while the server is running is a no-op.
  A stop-then-start cycle builds and submits the routes again; whether duplicate
  route registration is accepted depends on the transport implementation.
</ApiCallout>

</ApiReference>

### AgentServer.stop

<ApiReference
  kind="async method"
  path="protolink.server.AgentServer.stop"
  signature={`await stop() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/agent.py#L277"
>

Stop the underlying transport and close the optional A2A adapter.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentServer.stop return value">
    <ApiField name="None" type="None">
      Returns immediately when the server is not marked as running.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Shutdown order">
  <ApiFields ariaLabel="AgentServer.stop shutdown order">
    <ApiField name="1" type="transport">
      Await <code>transport.stop()</code>.
    </ApiField>
    <ApiField name="2" type="A2A adapter">
      Await adapter closure when A2A support was enabled.
    </ApiField>
    <ApiField name="3" type="server state">
      Mark the server idle after both preceding operations complete.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="AgentServer.stop errors">
    <ApiField name="shutdown error">
      Transport and A2A closure exceptions propagate. If either operation fails,
      the running flag is not cleared by the current implementation.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RegistryInterface server protocol

<ApiReference
  kind="protocol"
  path="protolink.server.registry.RegistryInterface"
  signature={`class RegistryInterface(Protocol)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L12"
>

Describe the structural registry behavior consumed by `RegistryServer`.

<ApiSection title="Required surface">
  <ApiFields ariaLabel="RegistryInterface server protocol members">
    <ApiField name="handle_register" type="async (AgentCard) -> dict[str, str]">
      Store or replace one agent card.
    </ApiField>
    <ApiField name="handle_unregister" type="async (agent_url: str) -> dict[str, str]">
      Remove one URL.
    </ApiField>
    <ApiField name="handle_heartbeat" type="async (agent_url: str) -> dict[str, str]">
      Refresh liveness metadata.
    </ApiField>
    <ApiField name="handle_discover" type="async (filter_by: dict[str, Any] | None = None) -> list[dict[str, Any]] | list[AgentCard]">
      Return cards matching optional filters.
    </ApiField>
    <ApiField name="handle_status_html" type="() -> str">
      Render the registry status page.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Structural typing">
  The protocol is a server-module implementation detail and is not re-exported.
  Ordinary applications pass a <code>Registry</code> instance rather than
  implementing it directly.
</ApiCallout>

</ApiReference>

### RegistryServer

<ApiReference
  kind="class"
  path="protolink.server.RegistryServer"
  signature={`class RegistryServer(
    registry: RegistryInterface,
    transport: Transport,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L35"
>

Bind a Registry-compatible object to its transport endpoint table. As with
`AgentServer`, the registry object supplies business behavior and the transport
supplies route binding and networking.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RegistryServer constructor parameters">
    <ApiField name="registry" type="RegistryInterface" required>
      Structurally compatible object implementing register, unregister,
      heartbeat, discovery, and HTML status handlers.
    </ApiField>
    <ApiField name="transport" type="Transport" required>
      Concrete route-binding and server-lifecycle implementation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RegistryServer constructor errors">
    <ApiField name="ValueError">
      Raised when <code>transport</code> is <code>None</code>. The registry
      argument is stored without runtime validation.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RegistryServer.register_parser

<ApiReference
  kind="async method"
  path="protolink.server.RegistryServer.register_parser"
  signature={`await register_parser(
    request: Any,
) -> AgentCard`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L50"
>

Convert an inbound registration body into ProtoLink's runtime `AgentCard`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RegistryServer.register_parser parameters">
    <ApiField name="request" type="Any" required>
      Value forwarded directly to <code>AgentCard.from_dict()</code>. Normal
      transport usage supplies a decoded mapping.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="RegistryServer.register_parser return value">
    <ApiField name="card" type="AgentCard">
      Normalized agent identity and capability model passed to the registry's
      registration handler.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RegistryServer.register_parser errors">
    <ApiField name="deserialization error">
      Mapping-shape, required-field, and nested model errors from
      <code>AgentCard.from_dict()</code> propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RegistryServer.unregister_parser

<ApiReference
  kind="async method"
  path="protolink.server.RegistryServer.unregister_parser"
  signature={`await unregister_parser(
    request: Any,
) -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L53"
>

Read the `agent_url` value from an unregistration request body.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RegistryServer.unregister_parser parameters">
    <ApiField name="request" type="Any" required>
      Mapping-like object expected to provide <code>.get("agent_url")</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="RegistryServer.unregister_parser return value">
    <ApiField name="agent_url" type="str">
      URL forwarded to <code>handle_unregister()</code>. Despite the annotation,
      a missing key currently produces <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RegistryServer.unregister_parser errors">
    <ApiField name="AttributeError">
      Raised when the request has no compatible <code>.get()</code> method.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RegistryServer.heartbeat_parser

<ApiReference
  kind="async method"
  path="protolink.server.RegistryServer.heartbeat_parser"
  signature={`await heartbeat_parser(
    request: Any,
) -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L56"
>

Read the `agent_url` value from a heartbeat body.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RegistryServer.heartbeat_parser parameters">
    <ApiField name="request" type="Any" required>
      Mapping-like object expected to provide <code>.get("agent_url")</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="RegistryServer.heartbeat_parser return value">
    <ApiField name="agent_url" type="str">
      URL forwarded to <code>handle_heartbeat()</code>. A missing key currently
      yields <code>None</code> despite the declared return type.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RegistryServer.heartbeat_parser errors">
    <ApiField name="AttributeError">
      Raised when the request has no compatible <code>.get()</code> method.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RegistryServer.discover_parser

<ApiReference
  kind="async method"
  path="protolink.server.RegistryServer.discover_parser"
  signature={`await discover_parser(
    request: Any,
) -> dict[str, Any] | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L59"
>

Normalize discovery query data into the filter mapping expected by the registry
handler.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RegistryServer.discover_parser parameters">
    <ApiField name="request" type="Any" required>
      Decoded query mapping. A wrapper key named <code>filter_by</code> is
      unwrapped when present.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="RegistryServer.discover_parser return value">
    <ApiField name="filter_by" type="dict[str, Any] | None">
      <code>None</code> for a non-dictionary request; the nested
      <code>filter_by</code> value when that key exists; otherwise the request
      dictionary itself.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Current validation">
  A nested <code>filter_by</code> value is returned without checking that it is
  a dictionary. Normal <code>RegistryClient</code> discovery sends filter keys
  directly, such as <code>?name=worker</code>; a raw
  <code>?filter_by=&#123;...&#125;</code> query value is only a string and is
  not JSON-decoded by this parser.
</ApiCallout>

</ApiReference>

### RegistryServer.start

<ApiReference
  kind="async method"
  path="protolink.server.RegistryServer.start"
  signature={`await start() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L140"
>

Register all registry, status, health, and readiness routes, then await
transport startup.

<ApiSection title="Returns">
  <ApiFields ariaLabel="RegistryServer.start return value">
    <ApiField name="None" type="None">
      The running flag is set only after the transport starts successfully.
      Repeated calls while running return immediately.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RegistryServer.start errors">
    <ApiField name="route or transport error">
      Exceptions from <code>setup_routes()</code> or
      <code>transport.start()</code> propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RegistryServer.stop

<ApiReference
  kind="async method"
  path="protolink.server.RegistryServer.stop"
  signature={`await stop() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/registry.py#L149"
>

Await transport shutdown and mark the registry server idle.

<ApiSection title="Returns">
  <ApiFields ariaLabel="RegistryServer.stop return value">
    <ApiField name="None" type="None">
      Returns immediately when the server is not running.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="RegistryServer.stop errors">
    <ApiField name="transport error">
      Shutdown exceptions propagate, and the running flag remains set when
      transport shutdown fails.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Endpoint declaration reference

### EndpointSpec

<ApiReference
  kind="frozen dataclass"
  path="protolink.server.endpoint_handler.EndpointSpec"
  signature={`class EndpointSpec(
    name: str,
    path: str,
    method: HttpMethod,
    handler: Callable[..., Any],
    content_type: Literal["json", "html"] = "json",
    streaming: bool = False,
    mode: Literal["request_response", "stream"] = "request_response",
    request_parser: Callable[[Any], Any] | None = None,
    request_source: RequestSourceType = "none",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/endpoint_handler.py#L9"
>

Describe one transport-neutral route. Server classes create these immutable
declarations; each transport interprets their path, extraction, parsing,
invocation, serialization, and streaming fields for its own backend.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="EndpointSpec constructor parameters">
    <ApiField name="name" type="str" required>
      Logical route identifier. EndpointSpec itself does not enforce uniqueness.
    </ApiField>
    <ApiField name="path" type="str" required>
      Protocol-facing route path, conventionally beginning with
      <code>/</code>. No syntax validation is performed by the dataclass.
    </ApiField>
    <ApiField name="method" type={'"GET" | "POST" | "DELETE" | "PUT" | "PATCH"'} required>
      HTTP-style operation used by applicable transports.
    </ApiField>
    <ApiField name="handler" type="Callable[..., Any]" required>
      Synchronous function, coroutine function, or streaming callable invoked
      after extraction and optional parsing.
    </ApiField>
    <ApiField name="content_type" type={'"json" | "html"'} defaultValue={'"json"'}>
      Response rendering mode interpreted by the HTTP/ASGI backends.
      WebSocket, gRPC, and Runtime transports serialize returned string values
      through their normal protocol envelope instead.
    </ApiField>
    <ApiField name="streaming" type="bool" defaultValue="False">
      Signals that the handler returns an asynchronous stream rather than one
      response value.
    </ApiField>
    <ApiField name="mode" type={'"request_response" | "stream"'} defaultValue={'"request_response"'}>
      Explicit execution mode consumed by transports. It is separate from
      <code>streaming</code>; the dataclass does not require the two fields to
      agree.
    </ApiField>
    <ApiField name="request_parser" type="Callable[[Any], Any] | None" defaultValue="None">
      Optional transformer applied to the extracted request value before
      handler invocation. Transports may support synchronous and asynchronous
      parser results.
    </ApiField>
    <ApiField name="request_source" type="RequestSourceType" defaultValue={'"none"'}>
      Select <code>none</code>, <code>body</code>,
      <code>query_params</code>, <code>form</code>, <code>headers</code>,
      <code>path_params</code>, or <code>request</code>. The last form supplies
      an <code>EndpointRequest</code> containing several request facets.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Frozen, not validated">
  Attribute reassignment is blocked by the frozen dataclass, but contained
  callables and other referenced values remain mutable. Construction does not
  validate paths, method strings at runtime, handler callability, unique names,
  or streaming-field consistency.
</ApiCallout>

<ApiCallout label="Request-source support">
  The shared type includes <code>form</code>, but current built-in transports do
  not extract form data. HTTP backends support body, query, headers, path
  parameters, and the combined request view; WebSocket, gRPC, and Runtime
  currently bind body and query-parameter sources.
</ApiCallout>

</ApiReference>

### EndpointRequest

<ApiReference
  kind="frozen dataclass"
  path="protolink.server.endpoint_handler.EndpointRequest"
  signature={`class EndpointRequest(
    body: Any = None,
    query_params: Mapping[str, str] = field(default_factory=dict),
    path_params: Mapping[str, str] = field(default_factory=dict),
    headers: Mapping[str, str] = field(default_factory=dict),
    method: str = "",
    url: str = "",
    principal_id: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/server/endpoint_handler.py#L30"
>

Provide a small, framework-independent view of an inbound HTTP-style request.
It is used by endpoints whose adapters need more than one extracted source, such
as A2A JSON-RPC requests that also need authenticated-principal information.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="EndpointRequest constructor parameters">
    <ApiField name="body" type="Any" defaultValue="None">
      Decoded or raw body value supplied by the transport.
    </ApiField>
    <ApiField name="query_params" type="Mapping[str, str]" defaultValue="{}">
      Query parameter view. A new dictionary is used when omitted.
    </ApiField>
    <ApiField name="path_params" type="Mapping[str, str]" defaultValue="{}">
      Route parameter view. A new dictionary is used when omitted.
    </ApiField>
    <ApiField name="headers" type="Mapping[str, str]" defaultValue="{}">
      Request header view. Header normalization depends on the transport.
    </ApiField>
    <ApiField name="method" type="str" defaultValue={'""'}>
      Incoming protocol method.
    </ApiField>
    <ApiField name="url" type="str" defaultValue={'""'}>
      Incoming request URL as supplied by the transport.
    </ApiField>
    <ApiField name="principal_id" type="str | None" defaultValue="None">
      Authenticated principal propagated by the transport when available.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Shallow immutability">
  The dataclass is frozen and slot-based, but mappings supplied by the caller
  are not copied or wrapped. Their contents can still change after the request
  object is constructed.
</ApiCallout>

</ApiReference>
