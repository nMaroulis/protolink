import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Type Aliases

ProtoLink centralizes the small vocabularies shared by agents, transports, request specifications, LLM adapters, state modules, models, security declarations, and structured flows. These aliases make accepted values visible to type checkers and IDEs while keeping public signatures consistent across packages.

<ApiSurface
  eyebrow="Typing layer"
  title="Type Aliases"
  path="protolink.types"
  description="The literal and alias vocabulary used to keep roles, transports, backends, MIME types, auth schemes, state modules, and flow targets stable across public APIs."
  pills={[
    "Roles",
    "Transports",
    "HTTP methods",
    "Auth schemes",
    "State modes",
    "Flow targets",
  ]}
  cards={[
    {
      title: "Topology",
      text: "Agent role aliases clarify whether a node orchestrates, works, observes, gates, or interfaces.",
      code: "AgentRoleType",
    },
    {
      title: "Protocols",
      text: "Transport and backend aliases keep factories and cards aligned with supported implementations.",
      code: "TransportType",
    },
    {
      title: "Content",
      text: "Message roles, part types, MIME types, and reasoning levels make data models easier to inspect.",
      code: "MimeType",
    },
    {
      title: "Control",
      text: "State modes, request sources, security schemes, and flow targets define runtime boundaries.",
      code: "StateMode",
    },
  ]}
/>

## How the typing layer works

Every alias on this page is exported from `protolink.types`:

```python
from protolink.types import (
    AgentRoleType,
    BackendType,
    ContentType,
    FlowTarget,
    HttpAuthScheme,
    HttpMethod,
    LLMProvider,
    LLMType,
    MessageRoleType,
    MimeType,
    PartType,
    ReasoningLevel,
    RequestSourceType,
    SecuritySchemeType,
    StateMode,
    TransportType,
)
```

Most are `Literal` aliases. They help static type checkers reject unsupported spelling and let IDEs offer completion, but `typing.Literal` does not validate a value at runtime. Whether an unknown string raises, falls back, or is preserved depends on the consuming constructor or factory and is called out below.

`FlowTarget` is different: it is stored as a string forward reference so importing `protolink.types` does not import `Agent` and `Flow` and create a circular dependency.

:::info[Public export boundary]

The aliases are exported from `protolink.types`, not from the top-level `protolink` package. Importing from the central types package is the stable public path; `protolink.types.types` is the defining implementation module.

:::

## Table of Contents

- [Topology](#topology)
  - [AgentRoleType](#agentroletype)
- [Protocols and requests](#protocols-and-requests)
  - [BackendType](#backendtype)
  - [ContentType](#contenttype)
  - [HttpAuthScheme](#httpauthscheme)
  - [HttpMethod](#httpmethod)
  - [RequestSourceType](#requestsourcetype)
  - [SecuritySchemeType](#securityschemetype)
  - [TransportType](#transporttype)
- [LLM classification](#llm-classification)
  - [LLMProvider](#llmprovider)
  - [LLMType](#llmtype)
  - [ReasoningLevel](#reasoninglevel)
- [Messages and media](#messages-and-media)
  - [MessageRoleType](#messageroletype)
  - [MimeType](#mimetype)
  - [PartType](#parttype)
- [State](#state)
  - [StateMode](#statemode)
- [Structured flows](#structured-flows)
  - [FlowTarget](#flowtarget)

---

## Topology

### AgentRoleType

<ApiReference
  kind="type alias"
  path="protolink.types.AgentRoleType"
  signature={`AgentRoleType: TypeAlias = Literal[
    "gateway",
    "interface",
    "observer",
    "orchestrator",
    "worker",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L14"
>

Agent roles describe why an agent exists in the system topology. They do not describe its tools, memory, model, transport, policy, or actual capabilities. `AgentCard.role` uses this alias as native runtime metadata.

<ApiSection title="Values">

| Role | Architectural purpose | Typical responsibilities |
|------|-----------------------|--------------------------|
| `gateway` | External trust and protocol boundary | Ingress/egress, authentication, authorization, validation, rate limits, redaction, and protocol translation |
| `interface` | User- or application-facing interaction surface | Presenting input/output, adapting product interactions, and mediating a focused interface without owning global orchestration |
| `observer` | Read-only system visibility | Logs, metrics, traces, evaluation, auditing, compliance, and human review |
| `orchestrator` | Global coordination | Interpreting goals, selecting agents, managing branches/retries/termination, and aggregating results |
| `worker` | Concrete task execution | Domain work, tool use, retrieval, computation, and producing outputs |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="AgentRoleType consumers">
    <ApiField name="AgentCard.role" type="AgentRoleType" defaultValue={'"worker"'}>
      Labels the agent's responsibility for native discovery and application logic.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Convention, not authorization">
  Role values do not enable behavior or grant authority. A gateway still needs an authenticator and policy; an observer is read-only only if the application enforces that boundary; a worker may still have an LLM or tools.
</ApiCallout>

<ApiCallout label="Current card serialization">
  <code>AgentCard.role</code> is currently retained in memory but omitted by the native <code>AgentCard.to_dict()</code> and <code>from_dict()</code> paths. See the Models reference for the full card behavior.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import AgentCard
from protolink.types import AgentRoleType

role: AgentRoleType = "orchestrator"

card = AgentCard(
    name="coordinator",
    description="Routes work across a specialist agent team.",
    url="runtime://coordinator",
    role=role,
)
```

</ApiSection>

</ApiReference>

#### Role design notes

The role vocabulary is intentionally small and stable:

- An **orchestrator** owns global flow, but should normally delegate domain execution.
- A **worker** produces concrete results, but does not need authority over system-wide routing.
- An **observer** watches or evaluates execution without being part of the decision path.
- A **gateway** marks an external boundary where trust, policy, and protocol adaptation commonly belong.
- An **interface** provides a user or application interaction surface without necessarily being the perimeter security boundary.
- Tools, retrieval, code execution, model access, and memory remain capabilities or implementation details rather than roles.

Systems may omit roles they do not need. Applications can maintain additional domain-specific role metadata, but the public alias remains the common ProtoLink vocabulary.

#### Orchestrator

An orchestrator owns the global flow of execution. It interprets high-level goals, selects and invokes workers, manages branching and retries, decides when work is complete, and aggregates intermediate results.

It normally should not perform every domain operation itself. Keeping planning and coordination separate from privileged or specialized execution makes policy, testing, and failure recovery easier to reason about.

#### Worker

A worker performs concrete work when invoked. It may call tools, retrieve information, run a model, transform data, or produce artifacts, but it does not inherently own global routing or task-system policy.

Worker is the default `AgentCard` role because a focused execution unit is the most common agent shape.

#### Observer

An observer has visibility into execution for monitoring, evaluation, auditing, compliance, or human review. Typical observers collect events, metrics, traces, and outputs.

The role name alone does not make an agent read-only. Applications must still withhold write tools and enforce a policy that prevents the observer from changing runtime state.

#### Gateway

A gateway marks the boundary between external systems and the agent mesh. It commonly accepts inbound requests, translates protocols, authenticates principals, enforces authorization and limits, validates or redacts content, and returns the final external response.

A gateway is not automatically an orchestrator: it may hand accepted work to a coordinator without deciding the execution plan itself.

#### Interface

An interface is a user- or application-facing interaction layer inside the topology. It can adapt a product-specific input or presentation model to ProtoLink tasks without necessarily owning perimeter security or global orchestration.

Use `gateway` when the trust and protocol boundary is the defining responsibility; use `interface` when interaction and presentation are the defining responsibility.

---

## Protocols and requests

### BackendType

<ApiReference
  kind="type alias"
  path="protolink.types.BackendType"
  signature={`BackendType: TypeAlias = Literal[
    "starlette",
    "fastapi",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L16"
>

Selects the ASGI backend used by `HTTPTransport` to bind transport-neutral endpoint declarations to concrete server routes.

<ApiSection title="Values">

| Backend | Behavior |
|---------|----------|
| `starlette` | Lightweight default backend. Request parsers and ProtoLink model normalization remain explicit. |
| `fastapi` | FastAPI-backed routes with optional schema validation through `validate_schema=True`. |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="BackendType consumers">
    <ApiField name="HTTPTransport.backend" type="BackendType" defaultValue={'"starlette"'}>
      Chooses the backend instance created during HTTP transport initialization.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Current runtime fallback">
  <code>HTTPTransport</code> lowercases the supplied value and selects FastAPI only when it equals <code>fastapi</code>. Any other runtime string currently falls back to Starlette instead of raising. Static checking is therefore stricter than the constructor's runtime behavior.
</ApiCallout>

<ApiCallout label="Optional dependencies">
  The chosen backend requires its corresponding optional dependency. FastAPI schema validation may require additional Pydantic support.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.transport import HTTPTransport
from protolink.types import BackendType

backend: BackendType = "fastapi"

transport = HTTPTransport(
    url="http://localhost:8000",
    backend=backend,
    validate_schema=True,
)
```

</ApiSection>

</ApiReference>

### ContentType

<ApiReference
  kind="type alias"
  path="protolink.types.ContentType"
  signature={`ContentType: TypeAlias = Literal[
    "application/json",
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L18"
>

Media-type vocabulary for outbound request and response headers. `ClientRequestSpec.content_type` controls `Content-Type`; `ClientRequestSpec.accept` controls `Accept`.

<ApiSection title="Values">

| Content type | Intended wire content |
|--------------|-----------------------|
| `application/json` | JSON request or response documents |
| `application/x-www-form-urlencoded` | URL-encoded form data |
| `multipart/form-data` | Multipart form and file upload bodies |
| `text/plain` | Unstructured text |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="ContentType consumers">
    <ApiField name="ClientRequestSpec.content_type" type="ContentType | None" defaultValue="None">
      Optional outbound <code>Content-Type</code> header.
    </ApiField>
    <ApiField name="ClientRequestSpec.accept" type="ContentType | None" defaultValue="None">
      Optional outbound <code>Accept</code> header describing the expected response media type.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Header declaration only">
  The alias does not select a request encoder. Current <code>HTTPTransport.send()</code> serializes <code>request_source="body"</code> through its JSON path even when another content-type header is declared. Form and multipart payload construction requires transport or application handling beyond this alias.
</ApiCallout>

<ApiCallout label="Different from MimeType">
  <code>ContentType</code> is the narrow request-header vocabulary. <code>MimeType</code> is the broader media capability vocabulary advertised by <code>AgentCard.input_formats</code> and <code>output_formats</code>.
</ApiCallout>

</ApiReference>

### HttpAuthScheme

<ApiReference
  kind="type alias"
  path="protolink.types.HttpAuthScheme"
  signature={`HttpAuthScheme: TypeAlias = Literal[
    "bearer",
    "basic",
    "digest",
    "hmac",
    "negotiate",
    "ntlm",
    "aws4auth",
    "hawk",
    "edgegrid",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L25"
>

Names the HTTP authentication scheme inside a `SecurityScheme` whose top-level `auth_type` is `http`. The value describes a scheme; it does not construct an authenticator or credentials.

<ApiSection title="Values">

| Scheme | Meaning |
|--------|---------|
| `bearer` | Bearer token carried in the `Authorization` header, commonly OAuth access tokens or JWTs |
| `basic` | Base64-encoded username and password credentials |
| `digest` | HTTP Digest challenge-response authentication |
| `hmac` | Application-defined HMAC request signing |
| `negotiate` | SPNEGO/Kerberos negotiation |
| `ntlm` | NT LAN Manager authentication |
| `aws4auth` | AWS Signature Version 4 |
| `hawk` | Hawk message authentication code scheme |
| `edgegrid` | Akamai EdgeGrid request signing |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="HttpAuthScheme consumers">
    <ApiField name="SecurityScheme.auth_scheme" type="HttpAuthScheme | None" required>
      Describes the HTTP-specific scheme exposed by an authenticator.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Declaration versus implementation">
  ProtoLink includes built-in bearer and basic authenticators. The wider literal set allows custom authenticators and discovery metadata; names such as digest, HMAC, Negotiate, NTLM, AWS4Auth, Hawk, and EdgeGrid do not imply a built-in implementation.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.security.auth import SecurityScheme
from protolink.types import HttpAuthScheme

scheme: HttpAuthScheme = "bearer"

security = SecurityScheme(
    auth_type="http",
    auth_scheme=scheme,
    description="Bearer JWT authentication",
)
```

</ApiSection>

</ApiReference>

### HttpMethod

<ApiReference
  kind="type alias"
  path="protolink.types.HttpMethod"
  signature={`HttpMethod: TypeAlias = Literal[
    "GET",
    "POST",
    "DELETE",
    "PUT",
    "PATCH",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L38"
>

HTTP-style verbs shared by inbound `EndpointSpec` declarations and outbound `ClientRequestSpec` operations. Keeping the same alias at both boundaries prevents client and server request definitions from drifting.

<ApiSection title="Values">

| Method | Typical use |
|--------|-------------|
| `GET` | Retrieve a resource or status without a request body |
| `POST` | Submit work, create a resource, or invoke a control operation |
| `DELETE` | Remove or cancel a resource |
| `PUT` | Replace a resource |
| `PATCH` | Partially update a resource |

</ApiSection>

<ApiCallout label="Exact casing">
  The literal values are uppercase. Dataclass construction does not normalize or validate method strings, so lowercase values may reach a backend despite failing static checking.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.models import EndpointSpec
from protolink.types import HttpMethod

method: HttpMethod = "POST"

endpoint = EndpointSpec(
    name="create_task",
    path="/tasks/",
    method=method,
    handler=handle_task,
    request_source="body",
)
```

</ApiSection>

</ApiReference>

### RequestSourceType

<ApiReference
  kind="type alias"
  path="protolink.types.RequestSourceType"
  signature={`RequestSourceType: TypeAlias = Literal[
    "none",
    "body",
    "query_params",
    "form",
    "headers",
    "path_params",
    "request",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L90"
>

Describes which part of an inbound or outbound request supplies an operation's data. Endpoint backends use it to choose handler input; clients use it to choose how request data is marshalled.

<ApiSection title="Values">

| Source | Intended value |
|--------|----------------|
| `none` | No request-derived handler argument |
| `body` | Parsed JSON request body |
| `query_params` | URL query-parameter mapping |
| `form` | Form fields |
| `headers` | Request-header mapping |
| `path_params` | Route-parameter mapping |
| `request` | Transport-neutral `EndpointRequest` containing body, query, path, headers, method, URL, and authenticated principal ID |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="RequestSourceType consumers">
    <ApiField name="EndpointSpec.request_source" type="RequestSourceType" defaultValue={'"none"'}>
      Selects the value passed to an inbound endpoint handler.
    </ApiField>
    <ApiField name="ClientRequestSpec.request_source" type="RequestSourceType" defaultValue={'"body"'}>
      Selects how outbound request data is marshalled by a transport.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Backend coverage">
  Current Starlette and FastAPI endpoint binders extract body, query parameters, headers, path parameters, and the complete request view. The alias includes <code>form</code>, but those binders do not currently implement form extraction; it falls through to no payload.
</ApiCallout>

<ApiCallout label="Outbound coverage">
  Current HTTP client marshalling sends data only for <code>body</code> and <code>query_params</code>. Other source names are primarily server-side declarations or require a transport-specific implementation.
</ApiCallout>

</ApiReference>

### SecuritySchemeType

<ApiReference
  kind="type alias"
  path="protolink.types.SecuritySchemeType"
  signature={`SecuritySchemeType: TypeAlias = Literal[
    "apiKey",
    "http",
    "oauth2",
    "mutualTLS",
    "openIdConnect",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L134"
>

Top-level authentication scheme categories used by `AgentCard.security_schemes` and `SecurityScheme.auth_type`. Names follow the OpenAPI-style discovery vocabulary.

<ApiSection title="Values">

| Category | Meaning |
|----------|---------|
| `apiKey` | API key supplied in a header, query parameter, or another declared location |
| `http` | HTTP authentication with a nested `HttpAuthScheme`, such as bearer or basic |
| `oauth2` | OAuth 2.0 flow declaration |
| `mutualTLS` | Client certificate authentication |
| `openIdConnect` | OpenID Connect discovery |

</ApiSection>

<ApiCallout label="Exact spelling">
  <code>apiKey</code>, <code>mutualTLS</code>, and <code>openIdConnect</code> are case-sensitive literal values. The alias does not accept snake-case alternatives such as <code>api_key</code>.
</ApiCallout>

<ApiCallout label="Metadata, not activation">
  Adding a scheme to an <code>AgentCard</code> advertises it but does not protect endpoints. Configure an <code>Authenticator</code> and transport security separately.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import AgentCard
from protolink.types import SecuritySchemeType

scheme_type: SecuritySchemeType = "http"

card = AgentCard(
    name="secure-agent",
    description="Agent protected by bearer authentication.",
    url="https://agent.example",
    security_schemes={
        scheme_type: {
            "type": "http",
            "scheme": "bearer",
        }
    },
)
```

</ApiSection>

</ApiReference>

### TransportType

<ApiReference
  kind="type alias"
  path="protolink.types.TransportType"
  signature={`TransportType: TypeAlias = Literal[
    "http",
    "websocket",
    "sse",
    "json-rpc",
    "sse-json-rpc",
    "grpc",
    "runtime",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L142"
>

Built-in transport names used by agent configuration, discovery cards, registry clients, and the lazy transport factory.

<ApiSection title="Values">

| Transport | Factory mapping | Communication model |
|-----------|-----------------|---------------------|
| `http` | `HTTPTransport` | HTTP request/response |
| `websocket` | `WebSocketTransport` | Persistent bidirectional connection with streaming |
| `sse` | `SSEJSONRPCTransport` | Server-Sent Events using JSON-RPC-style envelopes |
| `json-rpc` | `SSEJSONRPCTransport` | Alias for the SSE JSON-RPC implementation |
| `sse-json-rpc` | `SSEJSONRPCTransport` | Explicit alias for the SSE JSON-RPC implementation |
| `grpc` | `GRPCTransport` | gRPC unary and unary-stream JSON envelopes over `grpc.aio` |
| `runtime` | `RuntimeTransport` | In-process agent composition without network I/O |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="TransportType consumers">
    <ApiField name="AgentCard.transport" type="TransportType" defaultValue={'"http"'}>
      Advertises the primary route for an agent.
    </ApiField>
    <ApiField name="Agent.transport" type="TransportType | Transport | None" defaultValue="None">
      Selects a built-in factory name or accepts an already constructed transport.
    </ApiField>
    <ApiField name="get_transport()" type="str">
      Lazily resolves names case-insensitively and constructs the registered class.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Built-ins, not a closed registry">
  <code>register_transport()</code> can add runtime transport names that are not part of this static literal alias. Conversely, a literal value may still require an optional dependency, valid URL, credentials, or TLS configuration before it can operate.
</ApiCallout>

<ApiCallout label="TLS keeps the transport name">
  Secure deployments continue to use the same transport literal. Choose <code>https://</code> for HTTP, SSE, and JSON-RPC aliases; <code>wss://</code> for WebSocket; and <code>grpcs://</code> for gRPC.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.transport import get_transport
from protolink.types import TransportType

transport_name: TransportType = "runtime"
transport = get_transport(
    transport_name,
    url="runtime://local-agent",
)
```

</ApiSection>

</ApiReference>

---

## LLM classification

### LLMProvider

<ApiReference
  kind="type alias"
  path="protolink.types.LLMProvider"
  signature={`LLMProvider: TypeAlias = Literal[
    "anthropic",
    "deepseek",
    "gemini",
    "grok",
    "huggingface",
    "llama.cpp-local",
    "llama.cpp-server",
    "lmstudio",
    "mock",
    "ollama",
    "openai",
    "openai-compatible",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L40"
>

Provider identifier stored on concrete LLM adapters and mirrored by the lazy LLM factory's registered names.

<ApiSection title="Values">

| Provider | Adapter and deployment |
|----------|------------------------|
| `anthropic` | `AnthropicLLM`, Anthropic Messages API |
| `deepseek` | `DeepSeekLLM`, DeepSeek Chat Completions API |
| `gemini` | `GeminiLLM`, Google GenAI API |
| `grok` | `GrokLLM`, xAI Chat Completions API |
| `huggingface` | `HuggingFaceLLM`, Hugging Face Inference API |
| `llama.cpp-local` | `LlamaCPPLocalLLM`, in-process GGUF execution |
| `llama.cpp-server` | `LlamaCPPServerLLM`, remote or local `llama-server` |
| `lmstudio` | `LMStudioLLM`, LM Studio's OpenAI-compatible server |
| `mock` | `MockLLM`, deterministic offline testing |
| `ollama` | `OllamaLLM`, Ollama `/api/chat` server |
| `openai` | `OpenAILLM`, OpenAI Responses API |
| `openai-compatible` | `OpenAICompatibleLLM`, `/v1/chat/completions` and `/v1/models` server |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="LLMProvider consumers">
    <ApiField name="LLM.provider" type="ClassVar[LLMProvider]">
      Concrete adapter identifier used in metrics, events, prompts, and diagnostics.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Literal alias versus factory enum">
  <code>protolink.types.LLMProvider</code> is a <code>Literal</code> alias. <code>protolink.llms.factory.LLMProvider</code> is a separate string enum containing the same names. They serve different typing roles and are not the same object.
</ApiCallout>

<ApiCallout label="Factory usage">
  Pass provider names as strings to <code>create_llm()</code>. The current factory lowercases string input, rejects unknown names with <code>ValueError</code>, and lazily imports the selected adapter. Its separate enum instances are not currently normalized correctly.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import create_llm
from protolink.types import LLMProvider

provider: LLMProvider = "openai"
llm = create_llm(provider, model="gpt-4o-mini")
```

</ApiSection>

</ApiReference>

### LLMType

<ApiReference
  kind="type alias"
  path="protolink.types.LLMType"
  signature={`LLMType: TypeAlias = Literal[
    "api",
    "local",
    "server",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L55"
>

Classifies where an LLM adapter executes or connects. It is adapter metadata rather than a factory selector.

<ApiSection title="Values">

| Type | Meaning | Examples |
|------|---------|----------|
| `api` | Remote hosted provider API | OpenAI, Anthropic, Gemini, DeepSeek, Grok, Hugging Face |
| `local` | Model executes inside the Python process | `LlamaCPPLocalLLM` |
| `server` | Adapter connects to a model server managed separately | Ollama, llama.cpp server, LM Studio, OpenAI-compatible servers |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="LLMType consumers">
    <ApiField name="LLM.model_type" type="ClassVar[LLMType]">
      Set by API, local, and server base classes for introspection and shared runtime behavior.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Not a provider name">
  <code>create_llm()</code> selects a concrete adapter with <code>LLMProvider</code> values such as <code>openai</code> or <code>ollama</code>. It does not accept <code>api</code>, <code>local</code>, or <code>server</code> as provider selectors.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import create_llm

api_llm = create_llm(
    "openai",
    model="gpt-4o-mini",
)
local_llm = create_llm(
    "llama.cpp-local",
    model="./model.gguf",
)
server_llm = create_llm(
    "ollama",
    base_url="http://localhost:11434",
    model="llama3",
)

print(api_llm.model_type)     # "api"
print(local_llm.model_type)   # "local"
print(server_llm.model_type)  # "server"
```

</ApiSection>

</ApiReference>

### ReasoningLevel

<ApiReference
  kind="type alias"
  path="protolink.types.ReasoningLevel"
  signature={`ReasoningLevel: TypeAlias = Literal[
    "none",
    "low",
    "medium",
    "high",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L87"
>

Selects the reasoning instruction family compiled into the shared LLM system prompt. It is an instruction-level configuration, not a guarantee that a provider exposes private chain-of-thought or follows a particular reasoning depth.

<ApiSection title="Values">

| Level | Prompt behavior |
|-------|-----------------|
| `none` | Omits the optional reasoning instruction block |
| `low` | Adds concise reasoning guidance |
| `medium` | Adds more structured multi-step guidance |
| `high` | Adds the most detailed reasoning guidance in the built-in prompt family |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="ReasoningLevel consumers">
    <ApiField name="LLM.__init__.reasoning" type="ReasoningLevel" defaultValue={'"none"'}>
      Stored privately as <code>_reasoning</code> and consulted when the system prompt is built.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Current exposure">
  The base <code>LLM</code> constructor accepts this value, but current concrete provider constructors do not expose a public reasoning parameter. It is mainly relevant to custom subclasses.
</ApiCallout>

<ApiCallout label="No runtime validator">
  The base class stores the value as supplied. An unknown runtime string currently resolves to an empty reasoning instruction because prompt maps use a default lookup.
</ApiCallout>

</ApiReference>

---

## Messages and media

### MessageRoleType

<ApiReference
  kind="type alias"
  path="protolink.types.MessageRoleType"
  signature={`MessageRoleType: TypeAlias = Literal[
    "agent",
    "assistant",
    "system",
    "user",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L61"
>

Sender roles for task-level `Message` objects. The alias preserves the distinction between the broader agent runtime and its embedded LLM assistant.

<ApiSection title="Values">

| Role | Meaning |
|------|---------|
| `user` | Human or calling-client input |
| `agent` | Response or control message produced by the agent runtime |
| `assistant` | Response attributed specifically to an embedded LLM assistant |
| `system` | System-level instruction or control context |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="MessageRoleType consumers">
    <ApiField name="Message.role" type="MessageRoleType" defaultValue={'"user"'}>
      Serialized verbatim in task protocol messages.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Runtime construction">
  <code>Message</code> does not validate the literal at construction or deserialization. Prefer <code>Message.user()</code>, <code>Message.agent()</code>, and <code>Message.assistant()</code> when a convenience constructor matches the intended role.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import Message
from protolink.types import MessageRoleType

role: MessageRoleType = "system"
system_message = Message(role=role).add_text("Answer concisely.")

user_message = Message.user("Hello")
agent_message = Message.agent("Hello!")
assistant_message = Message.assistant("Draft response")
```

</ApiSection>

</ApiReference>

### MimeType

<ApiReference
  kind="type alias"
  path="protolink.types.MimeType"
  signature={`MimeType: TypeAlias = Literal[
    "text/plain",
    "text/markdown",
    "text/html",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/webp",
    "audio/wav",
    "audio/mpeg",
    "audio/ogg",
    "video/mp4",
    "video/webm",
    "application/pdf",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L64"
>

Media capability vocabulary advertised by `AgentCard.input_formats` and `AgentCard.output_formats`. It tells discovery consumers what an agent says it can accept or produce; it does not transcode or inspect content.

<ApiSection title="Values">

| Category | MIME types |
|----------|------------|
| **Text** | `text/plain`, `text/markdown`, `text/html` |
| **Structured data** | `application/json` |
| **Images** | `image/png`, `image/jpeg`, `image/webp` |
| **Audio** | `audio/wav`, `audio/mpeg`, `audio/ogg` |
| **Video** | `video/mp4`, `video/webm` |
| **Documents** | `application/pdf` |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="MimeType consumers">
    <ApiField name="AgentCard.input_formats" type="list[MimeType]" defaultValue={'["text/plain"]'}>
      Media formats the agent advertises as accepted input.
    </ApiField>
    <ApiField name="AgentCard.output_formats" type="list[MimeType]" defaultValue={'["text/plain"]'}>
      Media formats the agent advertises as possible output.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Discovery metadata">
  <code>AgentCard</code> stores format strings without runtime validation and does not reject content that falls outside the advertised list. Transports and application handlers remain responsible for actual media parsing.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import AgentCard
from protolink.types import MimeType

input_formats: list[MimeType] = [
    "text/plain",
    "application/json",
    "image/png",
]

card = AgentCard(
    name="multimedia-agent",
    description="Analyzes text, JSON, and PNG images.",
    url="http://localhost:8000",
    input_formats=input_formats,
    output_formats=["text/plain", "application/json"],
)
```

</ApiSection>

</ApiReference>

### PartType

<ApiReference
  kind="type alias"
  path="protolink.types.PartType"
  signature={`PartType: TypeAlias = Literal[
    "text",
    "json",
    "file",
    "bytes",
    "uri",
    "image",
    "audio",
    "video",
    "status",
    "error",
    "warning",
    "route",
    "decision",
    "infer",
    "infer_output",
    "tool_call",
    "tool_output",
    "trace",
    "summary",
    "confidence",
    "schema",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L101"
>

Discriminator vocabulary for atomic `Part` content inside messages and artifacts. The selected value tells agents, flows, transports, and renderers how the accompanying `content` should be interpreted.

<ApiSection title="Core content">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `text` | Plain text | User messages and simple responses |
| `json` | Structured data | JSON-compatible mappings and lists |

</ApiSection>

<ApiSection title="Files and references">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `file` | File attachment or descriptor | File metadata plus represented data |
| `bytes` | Raw binary data | Upload or generated binary content |
| `uri` | Resource reference | URL, object-store URI, or other resolvable identifier |

</ApiSection>

<ApiSection title="Media">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `image` | Image content or reference | Screenshots, charts, and visual inputs |
| `audio` | Audio content or reference | Voice input and generated audio |
| `video` | Video content or reference | Video messages and recordings |

</ApiSection>

<ApiSection title="Control and metadata">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `status` | Runtime status update | State plus optional message |
| `error` | Structured failure | Code, message, and retryability |
| `warning` | Non-fatal issue | Warning code or explanatory data |
| `route` | Explicit flow route selection | Typed `RouteDecision` |
| `decision` | General structured branching decision | Typed `RouteDecision` |

</ApiSection>

<ApiSection title="LLM operations">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `infer` | Instruction to invoke the agent's LLM | Prompt, user context, output schema, and metadata |
| `infer_output` | Result of an LLM inference | Text or structured output |

</ApiSection>

<ApiSection title="Tool operations">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `tool_call` | Tool invocation request | Typed tool name, arguments, and correlation ID |
| `tool_output` | Tool execution result | Correlated result or structured error |

</ApiSection>

<ApiSection title="Reasoning and observability">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `trace` | Execution trace | Debug or step-level observability data |
| `summary` | Condensed context or result | Summary text or structured summary |
| `confidence` | Reliability indicator | Score plus optional explanation |

</ApiSection>

<ApiSection title="Contracts">

| Type | Meaning | Typical content |
|------|---------|-----------------|
| `schema` | Schema definition | Validation or API contract data |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="PartType consumers">
    <ApiField name="Part.type" type="PartType" required>
      Serialized discriminator used to dispatch structured content.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Type does not validate content">
  <code>Part</code> preserves arbitrary content during direct construction. Factories such as <code>Part.error()</code>, <code>Part.route()</code>, <code>Part.tool_call()</code>, and <code>Part.infer()</code> create the expected shape, while <code>Part.from_dict()</code> hydrates selected structured types.
</ApiCallout>

<ApiCallout label="Extensibility boundary">
  The literal is the supported ProtoLink vocabulary for static checking. A runtime <code>Part</code> can still carry an unknown string because the dataclass does not validate it, but built-in agents, transports, or renderers may not understand that value.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import Part
from protolink.types import PartType

part_type: PartType = "text"
text = Part(type=part_type, content="Hello, world!")

structured = Part.json({"key": "value"})
failure = Part.error(
    "validation_error",
    "The location field is required.",
)
route = Part.route(
    "review",
    reason="Draft is ready for quality review.",
)
```

</ApiSection>

</ApiReference>

:::tip[Choosing part types]

- Use `text` for ordinary user-visible text and `json` for structured application data.
- Use `tool_call` and `tool_output` for executable tool interactions rather than placing tool arguments in a generic JSON part.
- Use `infer` when a task explicitly asks an agent to run its LLM, and `infer_output` for the resulting content.
- Use `route` or `decision` for structured flow branching instead of parsing labels from prose.
- Use `error`, `warning`, and `status` for inspectable control information.

:::

---

## State

### StateMode

<ApiReference
  kind="type alias"
  path="protolink.types.StateMode"
  signature={`StateMode: TypeAlias = Literal[
    "conversation",
    "tools",
    "task",
    "flow",
]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L58"
>

Names the persistent state modules an agent can enable. Each selected mode creates a module over the agent's shared storage backend.

<ApiSection title="Values">

| Mode | Persisted concern |
|------|-------------------|
| `conversation` | LLM conversation history partitioned by session |
| `tools` | Tool-specific persistent state |
| `task` | Task-related metadata and operational state |
| `flow` | Structured-flow progress and checkpoint data |

</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="StateMode consumers">
    <ApiField name="Agent.state" type="list[StateMode] | State | None" defaultValue="None">
      Enables selected modules or accepts a preconfigured <code>State</code> container.
    </ApiField>
    <ApiField name="State.enabled" type="list[StateMode]" required>
      Instantiates modules from the internal state registry.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Runtime validation">
  Unlike many model fields, the <code>State</code> constructor checks each name against its registry and raises <code>ValueError</code> for an unknown module.
</ApiCallout>

<ApiCallout label="Persistence is modular">
  Enabling a mode creates access to its state store; it does not imply that every framework operation writes to every store automatically. Conversation state has the deepest automatic integration with agent inference and session IDs.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import Agent
from protolink.types import StateMode

modes: list[StateMode] = ["conversation", "tools"]

agent = Agent(
    card=card,
    llm=llm,
    storage=storage,
    state=modes,
)
```

</ApiSection>

</ApiReference>

---

## Structured flows

### FlowTarget

<ApiReference
  kind="type alias"
  path="protolink.types.FlowTarget"
  signature={`FlowTarget: TypeAlias = "Agent | str | Flow"`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/types/types.py#L144"
>

Polymorphic execution target used by `Pipeline`, `Parallel`, `Router`, and `Graph`. A flow can call a local agent, dispatch to a remote or registry-discovered agent named by a string, or recursively execute another flow.

<ApiSection title="Variants">
  <ApiFields ariaLabel="FlowTarget variants">
    <ApiField name="Agent" type="protolink.agents.base.Agent">
      Executes locally with <code>await agent.handle_task(task)</code>. Before dispatch, the flow can bridge a previous non-executable result into a new infer message for the downstream agent.
    </ApiField>
    <ApiField name="str" type="agent URL or registry name">
      Direct URLs are sent through an <code>AgentClient</code>. Other strings are resolved by agent name through the configured registry, then dispatched remotely.
    </ApiField>
    <ApiField name="Flow" type="protolink.flows.base.Flow">
      Executes recursively. Missing client and registry configuration is inherited from the parent flow before the nested flow runs.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Used by">
  <ApiFields ariaLabel="FlowTarget consumers">
    <ApiField name="Pipeline.steps" type="list[FlowTarget]">
      Ordered sequential execution targets.
    </ApiField>
    <ApiField name="Parallel.branches" type="list[FlowTarget]">
      Concurrent fan-out targets whose new messages and artifacts are merged back into one task.
    </ApiField>
    <ApiField name="Router.routes" type="dict[str, FlowTarget]">
      Branch map selected by a structured route decision.
    </ApiField>
    <ApiField name="Graph.nodes" type="dict[str, FlowTarget]">
      Named graph execution nodes.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Forward-reference representation">
  The exact definition is one string, <code>"Agent | str | Flow"</code>. <code>Agent</code> and <code>Flow</code> are imported only under <code>TYPE_CHECKING</code>, avoiding circular imports when <code>protolink.types</code> is loaded at runtime.
</ApiCallout>

<ApiCallout label="Runtime validation">
  The centralized flow dispatcher checks concrete targets with <code>isinstance()</code> and raises <code>ValueError</code> for unsupported objects. The string forward reference itself cannot perform validation or provide useful <code>typing.get_args()</code> runtime introspection.
</ApiCallout>

<ApiCallout label="Direct URL recognition">
  The current flow resolver recognizes <code>http://</code>, <code>https://</code>, <code>ws://</code>, <code>wss://</code>, and <code>runtime://</code> strings as direct URLs. Other strings are treated as registry names.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import Agent
from protolink.flows import Parallel, Pipeline
from protolink.types import FlowTarget

researcher: Agent = ...
quality_url = "https://quality.example"

review: FlowTarget = Parallel(
    branches=[
        researcher,
        quality_url,
    ]
)

flow = (
    Pipeline()
    .add_step(researcher)
    .add_step("writer_agent")
    .add_step(review)
)
```

</ApiSection>

</ApiReference>

---

## Why use these aliases?

### Static safety

A type checker can catch unsupported values before execution:

```python
from protolink.types import BackendType

backend: BackendType = "invalid"  # Static type error
```

### IDE completion

Literal aliases let an editor suggest valid values at call sites:

```python
transport = HTTPTransport(
    url="http://localhost:8000",
    backend="",  # IDE can suggest "starlette" or "fastapi"
)
```

### Clear public signatures

Aliases communicate intent more precisely than an unrestricted string:

```python
from protolink.types import LLMProvider

def build_model(provider: LLMProvider, model: str):
    return create_llm(provider, model=model)
```

### One source of truth

Consumers import shared definitions instead of duplicating literal unions:

```python
from protolink.types import MimeType, SecuritySchemeType, TransportType
```

When ProtoLink adds or removes a built-in value, updating the alias updates type checking and generated documentation across every consumer.

:::warning[Type aliases are not schemas]

Use aliases for annotations and editor support. Use a validating constructor, parser, registry, enum, or schema when untrusted runtime input must be rejected.

:::

## See also

- [Models](models.md) - fields that consume message, media, role, security, and transport aliases.
- [Transports](transport.md) - built-in transport implementations and registration.
- [Authentication](authentication.md) - authenticators and security scheme models.
- [LLMs](llm.md) - provider adapters, LLM types, and reasoning behavior.
- [State](state.md) - persistent state modules.
- [Flows](flows.md) - execution semantics for `FlowTarget`.
