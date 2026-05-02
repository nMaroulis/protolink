# Type Aliases API Reference

This section provides detailed documentation for the type aliases used throughout the Protolink framework. Type aliases improve code readability, provide type safety, and make the API more consistent across different modules.

## Table of Contents

- [AgentRoleType](#agentroletype)
- [BackendType](#backendtype)
- [HttpAuthScheme](#httpauthscheme)
- [HttpMethod](#httpmethod)
- [LLMProvider](#llmprovider)
- [LLMType](#llmtype)
- [MemoryModeType](#memorymodetype)
- [MimeType](#mimetype)
- [PartType](#parttype)
- [ReasoningLevelType](#reasoningleveltype)
- [RequestSourceType](#requestsourcetype)
- [MessageRoleType](#messageroletype)
- [SecuritySchemeType](#securityschemetype)
- [TransportType](#transporttype)
- [FlowTarget](#flowtarget)

---

## AgentRoleType

```python
AgentRoleType: TypeAlias = Literal["gateway", "interface", "observer", "orchestrator", "worker"]
```

**Agent roles** define an agent’s **responsibility in the system topology**, not its
capabilities, tools, memory, or internal implementation.

Roles are **protocol-level contracts** and are intentionally minimal and stable.

---

### Orchestrator

**Purpose:** Control and coordination of the agent system.

The Orchestrator owns the **global flow of execution**. It decides which agent
acts next, when a task is complete, and how failures are handled.

**Responsibilities**
- Interpret high-level goals
- Select and invoke worker agents
- Manage branching, retries, and termination
- Aggregate or route intermediate results

**Non-responsibilities**
- Performing domain work
- Calling tools for execution
- Enforcing security or protocol boundaries

---

### Worker

**Purpose:** Execute tasks and produce outputs.

A Worker performs concrete work when invoked by an Orchestrator. Workers have
no authority over system flow and do not make global decisions.

**Responsibilities**
- Execute assigned tasks
- Generate outputs (text, structured data, actions)
- Use tools, memory, or retrieval as needed

**Non-responsibilities**
- Choosing which agent runs next
- Managing task lifecycle
- Acting as a system entry or exit point

---

### Observer

**Purpose:** Observe system behavior without influencing it.

An Observer has read-only visibility into agent interactions. It exists for
monitoring, evaluation, auditing, and human-in-the-loop inspection.

**Responsibilities**
- Log events and messages
- Collect metrics and traces
- Evaluate outputs or system behavior
- Support auditing and compliance

**Non-responsibilities**
- Modifying messages
- Influencing routing or decisions
- Executing tasks

---

### Gateway

**Purpose:** Define the boundary between external systems and the A2A network.

A Gateway is an edge agent responsible for ingress and egress. It translates
external protocols into A2A messages and enforces trust and security policies.

**Responsibilities**
- Accept inbound requests from external systems
- Translate protocols (e.g. HTTP, WebSocket, gRPC) into A2A messages
- Authenticate and authorize requests
- Enforce rate limits, validation, and redaction
- Emit final responses back to external systems

**Non-responsibilities**
- Task planning or execution
- Agent routing or coordination
- Evaluating correctness of results

---

### Design Notes

- Roles describe **why an agent exists**, not how it works.
- Tools, memory, retrieval, and reasoning are **capabilities**, not roles.
- Systems may omit roles they do not need.
- Custom roles may be layered on top, but these roles should remain stable.


## BackendType

```python
BackendType: TypeAlias = Literal["starlette", "fastapi"]
```

Type alias for supported HTTP backend implementations in Protolink transports.

### Supported Backends

| Backend | Description |
|---------|-------------|
| **starlette** | Lightweight ASGI framework (default) |
| **fastapi** | Full-featured API framework with automatic validation |

### Usage Example

```python
from protolink.types import BackendType
from protolink.transport import HTTPTransport

# Use Starlette backend (default)
transport = HTTPTransport(backend="starlette")

# Use FastAPI backend for automatic validation
transport = HTTPTransport(backend="fastapi", validate_schema=True)
```

---

## HttpAuthScheme

```python
HttpAuthScheme: TypeAlias = Literal[
    "bearer", "basic", "digest", "hmac", "negotiate", "ntlm",
    "aws4auth", "hawk", "edgegrid"
]
```

Type alias for supported HTTP authentication schemes.

### Supported Schemes

| Scheme | Description |
|--------|-------------|
| **bearer** | OAuth access token |
| **basic** | Basic Auth (username:password) |
| **digest** | Digest Auth (challenge-response) |
| **hmac** | Custom HMAC headers |
| **negotiate** | Kerberos / SPNEGO |
| **ntlm** | NT LAN Manager protocol |
| **aws4auth** | AWS SigV4 (Vendor) |
| **hawk** | HAWK MAC authentication (Vendor) |
| **edgegrid** | Akamai (Vendor) |

---

## HttpMethod

```python
HttpMethod: TypeAlias = Literal["GET", "POST", "DELETE", "PUT", "PATCH"]
```

Type alias for supported HTTP methods.

---

## LLMProvider

```python
LLMProvider: TypeAlias = Literal[
    "anthropic", "deepseek", "gemini", "grok", "huggingface", 
    "llama.cpp-local", "llama.cpp-server", "ollama", "openai"
]
```

Type alias for supported Large Language Model providers in Protolink.

### Supported Providers

| Provider | Description |
|----------|-------------|
| **openai** | OpenAI API (GPT models) |
| **anthropic** | Anthropic Claude API |
| **gemini** | Google AI models |
| **grok** | xAI Grok API |
| **deepseek** | DeepSeek API (OpenAI-compatible) |
| **huggingface** | Hugging Face Inference API |
| **llama.cpp-local** | Local LLaMA models via llama-cpp-python |
| **llama.cpp-server** | Remote LLaMA models via llama.cpp server |
| **ollama** | Ollama local models |

### Usage Example

```python
from protolink.types import LLMProvider
from protolink.llms.api import OpenAILLM

# Specify provider when creating LLM
llm = OpenAILLM(model="gpt-4", provider="openai")
```

---

## LLMType

```python
LLMType: TypeAlias = Literal["api", "local", "server"]
```

Type alias for different types of LLM deployment methods.

### LLM Types

| Type | Description |
|------|-------------|
| **api** | Cloud-based API models |
| **local** | Local model execution |
| **server** | Self-hosted server models |

### Usage Example

```python
from protolink.types import LLMType

# Different LLM deployment types
api_llm = OpenAILLM(model="gpt-4")  # API type
local_llm = LocalLLM(model_path="./model.gguf")  # Local type
server_llm = ServerLLM(endpoint="http://localhost:8080")  # Server type
```

---

## MemoryModeType

```python
MemoryModeType: TypeAlias = Literal["none", "session"]
```

Type alias for agent conversation memory modes.

### Memory Modes

| Mode | Description |
|------|-------------|
| **none** | Stateless operation. Conversation history is wiped after every task execution. |
| **session** | Stateful operation. Conversation history is preserved across tasks sharing the same `session_id`. |

### Usage Example

```python
from protolink.types import MemoryModeType
from protolink.agents import Agent

# Create a stateful agent
agent = Agent(card=card, memory="session")
```

---

## MimeType

Type alias for supported MIME types in Protolink. These are used to specify the **input** and **output** **formats** that agents can handle.

### Supported Types

| Category | MIME Types |
|----------|------------|
| **Text** | `text/plain`, `text/markdown`, `text/html` |
| **Structured Data** | `application/json` |
| **Images** | `image/png`, `image/jpeg`, `image/webp` |
| **Audio** | `audio/wav`, `audio/mpeg`, `audio/ogg` |
| **Video** | `video/mp4`, `video/webm` |
| **Documents** | `application/pdf` |

### Usage Example

```python
from protolink.types import MimeType
from protolink.models import AgentCard

# Specify supported formats in AgentCard
card = AgentCard(
    name="multimedia-agent",
    description="Agent that handles various media formats",
    url="http://localhost:8000",
    input_formats=["text/plain", "application/json", "image/png"],
    output_formats=["text/plain", "application/json", "image/jpeg"]
)
```

---

## PartType

```python
PartType: TypeAlias = Literal[
    # ---- Core content ----
    "text",
    "json",
    # ---- Files & references ----
    "file",
    "bytes",
    "uri",
    # ---- Media ----
    "image",
    "audio",
    "video",
    # ---- Control & meta ----
    "status",
    "error",
    "warning",
    # ---- LLM Call ----
    "infer",
    "infer_output",
    # ---- Tool interaction ----
    "tool_call",
    "tool_output",
    # ---- Reasoning / observability (optional) ----
    "trace",
    "summary",
    "confidence",
    # ---- Contracts ----
    "schema",
]
```

**Part content types** define the format and purpose of individual parts within messages, artifacts, and other data structures. Each part has a specific type that determines how its content should be interpreted and processed.

### Core Content Types

| Type | Description | Use Case |
|-------|-------------|-----------|
| **text** | Plain text content | User messages, simple responses |
| **json** | Structured data | Tool parameters, configuration objects |

### Files & References

| Type | Description | Use Case |
|-------|-------------|-----------|
| **file** | File attachment | Documents, images, code files |
| **bytes** | Raw binary data | File uploads, binary content |
| **uri** | Resource reference | Links to external resources |

### Media Types

| Type | Description | Use Case |
|-------|-------------|-----------|
| **image** | Image content | Visual data, screenshots |
| **audio** | Audio content | Voice messages, audio files |
| **video** | Video content | Video messages, screen recordings |

### Control & Meta

| Type | Description | Use Case |
|-------|-------------|-----------|
| **status** | Status updates | Progress indicators, state changes |
| **error** | Error information | Failure details, error messages |
| **warning** | Warning information | Non-fatal issues, deprecation notices |

### Tool Interaction

| Type | Description | Use Case |
|-------|-------------|-----------|
| **tool_call** | Tool invocation request | Function calls with parameters |
| **tool_output** | Tool execution result | Function return values, tool outputs |

### LLM Call

| Type | Description | Use Case |
|-------|-------------|-----------|
| **infer** | Inference instruction | Explicit request for LLM reasoning |
| **infer_output** | Inference result | Final response or tool calls from LLM |

### Reasoning & Observability

| Type | Description | Use Case |
|-------|-------------|-----------|
| **trace** | Execution trace | Debug information, step-by-step logs |
| **summary** | Content summary | Condensed results, key points |
| **confidence** | Confidence score | Reliability indicators, probability scores |

### Contracts

| Type | Description | Use Case |
|-------|-------------|-----------|
| **schema** | Schema definition | Validation rules, API contracts |

!!! info "Part Structure"
    Each part consists of:
    - **type**: One of the PartType values above
    - **content**: The actual data (varies by type)
    
    Example:
    ```python
    # Text part
    Part(type="text", content="Hello, world!")
    
    # JSON part
    Part(type="json", content={"key": "value"})
    
    # Error part
    Part(type="error", content={"code": "validation_error", "message": "Invalid input"})
    ```

!!! tip "Choosing Part Types"
    - Use **text** for simple user messages and responses
    - Use **json** for structured data and tool parameters
    - Use **file** for binary content with metadata
    - Use **error** for structured error information
    - Use **status** for progress and state updates

---

## ReasoningLevel

```python
ReasoningLevel: TypeAlias = Literal["none", "low", "medium", "high"]
```

Type alias for supported reasoning levels for agent reasoning. A different prompt is injected into the LLM system prompt based on the reasoning level.

### Levels

| Level | Description |
|-------|-------------|
| **none** | No reasoning |
| **low** | Basic reasoning |
| **medium** | Detailed reasoning |
| **high** | Deep reasoning |

---

## RequestSourceType

```python
RequestSourceType: TypeAlias = Literal["none", "body", "query_params", "form", "headers", "path_params"]
```

Type alias for supported request sources for endpoint parameter extraction.

### Sources

| Source | Description |
|--------|-------------|
| **none** | No request extraction |
| **body** | Extract from request body (JSON) |
| **query_params** | Extract from URL query parameters |
| **form** | Extract from form data |
| **headers** | Extract from HTTP headers |
| **path_params** | Extract from URL path parameters |

---

## MessageRoleType

```python
MessageRoleType: TypeAlias = Literal["agent", "assistant", "system", "user"]

```

Type alias for supported message roles in agent communication.

### Message Roles

| Role | Description |
|------|-------------|
| **user** | Human user messages |
| **agent** | Higher-level agent responses |
| **assistant** | Core LLM responses / thoughts |
| **system** | System instructions |

### Usage Example

```python
from protolink.types import MessageRoleType
from protolink.models import Message

# Create messages with different roles
user_msg = Message(role="user", content="Hello, how are you?")
agent_msg = Message(role="agent", content="I'm doing well, thank you!")
system_msg = Message(role="system", content="You are a helpful assistant.")
```

---

## SecuritySchemeType

Type alias for supported security schemes in Protolink. These are used to specify the **authentication methods** that agents can use.

### Supported Schemes

| Category | Security Schemes |
|----------|------------|
| **API key** | `apiKey` |
| **HTTP** (bearer/basic/digest) | `http` |
| **full OAuth OAuth2** | `oauth2` |
| **Certificates** | `mutualTLS` |
| **OIDC auto-discovery** | `openIdConnect` |

### Usage Example

```python
from protolink.types import SecuritySchemeType
from protolink.models import AgentCard

# Define security schemes in AgentCard
card = AgentCard(
    name="secure-agent",
    description="Agent with multiple auth methods",
    url="http://localhost:8000",
    security_schemes={
        "bearer": {"type": "http", "description": "Bearer token authentication"},
        "api_key": {"type": "apiKey", "description": "API key authentication"},
        "oauth2": {"type": "oauth2", "description": "OAuth 2.0 authentication"}
    }
)
```

---

## TransportType

```python
TransportType: TypeAlias = Literal["http", "websocket", "sse", "json-rpc", "grpc", "runtime"]
```

Type alias for supported transport protocols.

### Supported Transports

| Transport | Description |
|-----------|-------------|
| **http** | Standard HTTP transport |
| **websocket** | WebSocket transport for bidirectional comms |
| **sse** | Server-Sent Events |
| **json-rpc** | JSON-RPC over HTTP/WS |
| **grpc** | gRPC transport |
| **runtime** | In-memory transport for local agent composition |

---

## FlowTarget

```python
FlowTarget: TypeAlias = "Agent" | str | "Flow"
```

A polymorphic type alias used in the **Structured Flows** architecture. It represents any valid target that can act as a step or node in a workflow.

### Supported Targets

| Target Type | Description |
|-------------|-------------|
| **Agent** | A local `Agent` instance. Execution happens via `agent.handle_task()`. |
| **str** | An agent name or URL. It is resolved via the `Registry` and executed remotely via A2A. |
| **Flow** | Another `Flow` instance (e.g., `Pipeline`, `Parallel`). Enables **recursive nesting** of workflows. |

### Usage Example

```python
from protolink.flows import Pipeline, Parallel
from protolink.agents import Agent

class Researcher(Agent): ...

researcher = Researcher(...)

# Building a flow with mixed target types
complex_flow = Pipeline()
complex_flow.add_step(researcher)          # Target: Agent
complex_flow.add_step("quality_agent")     # Target: str
complex_flow.add_step(Parallel(branches=[...])) # Target: Flow
```

---

## Benefits of Type Aliases

Using type aliases in Protolink provides several advantages:

### 1. **Type Safety**
```python
# Compiler catches invalid values
backend: BackendType = "invalid"  # Type error!
```

### 2. **IDE Support**
```python
# Autocomplete shows valid options
transport = HTTPTransport(backend="")  # IDE shows: "starlette" | "fastapi"
```

### 3. **Documentation**
```python
# Clear intent in function signatures
def create_llm(provider: LLMProvider, model: str) -> LLM:
    # Implementation
```

### 4. **Refactoring**
```python
# Easy to update across the entire codebase
BackendType = Literal["starlette", "fastapi", "new_backend"]
```

### 5. **Consistency**
```python
# Same type used across multiple modules
from protolink.types import MimeType
from protolink.models import AgentCard
from protolink.transport import HTTPTransport
```

---

## Importing Types

All type aliases are available from the central types module:

```python
# Import individual types
from protolink.types import MimeType, SecuritySchemeType, MessageRoleType

# Import all types
from protolink.types import BackendType, LLMProvider, LLMType
```

The types module is organized to provide a single source of truth for all shared type definitions in the Protolink framework, making the codebase more maintainable and easier to understand.
