# Models API Reference

This section provides detailed API documentation for the core data models in Protolink. These models represent the fundamental data structures used throughout the framework for agent communication, task management, and data exchange.

## Table of Contents

- [AgentCard](#agentcard)
- [AgentCapabilities](#agentcapabilities)
- [AgentSkill](#agentskill)
- [Task](#task)
- [TaskState](#taskstate)
- [Message](#message)
- [Part](#part)
- [Artifact](#artifact)
- [EndpointSpec](#endpointspec)
- [LLMMessage](#llmmessage)
- [ConversationHistory](#conversationhistory)

---
## AgentCard

```python
@dataclass
class AgentCard:
    name: str
    description: str
    url: str
    transport: TransportType = "http"
    version: str = "1.0.0"
    protocol_version: str = protolink_version
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = field(default_factory=list)
    input_formats: list[MimeType] = field(default_factory=lambda: ["text/plain"])
    output_formats: list[MimeType] = field(default_factory=lambda: ["text/plain"])
    security_schemes: dict[str, dict[str, Any]] | None = field(default_factory=dict)
    role: AgentRoleType = "worker"
    tags: list[str] = field(default_factory=list)
```

Agent identity and capability declaration. This is the main metadata card that describes an agent's identity, capabilities, and security requirements.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `name` | `str` | — | **Required.** Agent name |
| `description` | `str` | — | **Required.** Agent purpose/description |
| `url` | `str` | — | **Required.** Service endpoint URL |
| `transport` | `TransportType` | `"http"` | Transport protocol to use (e.g. `"http"`, `"sse"`, `"websocket"`, `"runtime"`) |
| `version` | `str` | `"1.0.0"` | Agent version |
| `protocol_version` | `str` | `protolink_version` | Protolink Protocol version |
| `capabilities` | `AgentCapabilities` | `AgentCapabilities()` | Supported features |
| `skills` | `list[AgentSkill]` | `[]` | List of skills the agent can perform |
| `input_formats` | `list[MimeType]` | `["text/plain"]` | Supported input MIME types |
| `output_formats` | `list[MimeType]` | `["text/plain"]` | Supported output MIME types |
| `security_schemes` | `dict[SecuritySchemeType, dict[str, Any]] | None` | `{}` | Authentication schemes |
| `role` | `AgentRoleType` | `"worker"` | Agent role is a protocol-level contract that defines the agent's responsibility in the system topology (Extends A2A spec) |
| `tags` | `list[str]` | `[]` | List of tags for categorization. These tags can be used for filtering during discovery (Protolink extension to A2A spec) E.g. "finance", "travel", "math" etc. (Extends A2A spec) |

### Methods

#### `to_dict() -> dict[str, Any]`

Convert the AgentCard to Python Dictionary / JSON format compatible with the A2A agent card specification.

**Returns:**
```python
dict[str, Any]  # JSON dictionary representation
```

**Example:**
```python
card = AgentCard(
    name="weather_agent",
    description="Weather service",
    url="https://api.example.com/weather",
)
json_data = card.to_dict()
print(json_data["name"])  # "weather_agent"
```

---

#### `from_dict(data: dict[str, Any]) -> AgentCard` `classmethod`

Create an AgentCard from Python dict/JSON data. This method can also handle regular Python dictionaries and includes basic field validation via `_validate_fields`.
```python
data: dict[str, Any]  # JSON dictionary or Python dict containing agent card data
```

**Returns:**
```python
AgentCard  # New AgentCard instance
```

**Example:**
```python
json_data = {
    "name": "weather_agent",
    "description": "Weather service",
    "url": "https://api.example.com/weather"
}
card = AgentCard.from_dict(json_data)
```

---

#### `_validate_fields(data: dict[str, Any]) -> None` `staticmethod`

Validate the fields of the AgentCard.

**Returns:**
```python
None
```

---

#### `get_prompt_format() -> str`

Generate a structured, human-readable text representation of the agent and its skills for use in LLM system prompts. This is used by other agents to understand how to delegate tasks to this agent.

**Returns:**
```python
str  # Multi-line formatted string
```


### Example

```python
from protolink.models import AgentCard, AgentCapabilities

card = AgentCard(
    name="weather_agent",
    description="Provides weather information",
    url="https://api.example.com/weather",
    version="1.2.0",
    input_formats=["text/plain", "application/json"],
    output_formats=["text/plain", "application/json", "text/markdown"],
    capabilities=AgentCapabilities(
        streaming=True,
        tool_calling=True,
        max_concurrency=5
    )
)

# Convert to Python dict
json_data = card.to_dict()
```

---

## AgentCapabilities

```python
@dataclass
class AgentCapabilities:
    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False
    has_llm: bool = False
    max_concurrency: int = 1
    message_batching: bool = False
    tool_calling: bool = False
    multi_step_reasoning: bool = False
    timeout_support: bool = False
    delegation: bool = True
    rag: bool = False
    code_execution: bool = False
```

Defines the capabilities and limitations of an agent. This extends the A2A specification with additional capability flags.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `streaming` | `bool` | `False` | Supports streaming task events over a streaming-capable transport |
| `push_notifications` | `bool` | `False` | Supports push notifications (webhooks) |
| `state_transition_history` | `bool` | `False` | Provides detailed task state history |
| `has_llm` | `bool` | `False` | Has an LLM component for AI processing |
| `max_concurrency` | `int` | `1` | Maximum concurrent tasks |
| `message_batching` | `bool` | `False` | Processes multiple messages per request |
| `tool_calling` | `bool` | `False` | Can call external tools/APIs |
| `multi_step_reasoning` | `bool` | `False` | Performs multi-step reasoning |
| `timeout_support` | `bool` | `False` | Respects operation timeouts |
| `delegation` | `bool` | `True` | Can delegate tasks to other agents |
| `rag` | `bool` | `False` | Supports Retrieval-Augmented Generation |
| `code_execution` | `bool` | `False` | Has access to safe execution sandbox |

### Methods

#### `as_dict() -> dict[str, Any]`

Return all capabilities as a flat dictionary.

---

#### `enabled() -> list[str]`

Return a list of all enabled (truthy) capabilities. Useful for quick inspection.

---

## AgentSkill

```python
@dataclass
class AgentSkill:
    id: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
```

Represents a task that an agent can perform. Skills are used to advertise specific capabilities to other agents.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `id` | `str` | — | **Required.** Unique Human-readable identifier for the task |
| `description` | `str` | `""` | Detailed description of what the task does |
| `input_schema` | `dict[str, Any]` | `{}` | Flattened dictionary of parameter definitions with `type`, `required`, and `default` keys |
| `output_schema` | `dict[str, Any]` | `{}` | JSON-schema-like description of the output payload |
| `tags` | `list[str]` | `[]` | List of tags for categorization |
| `examples` | `list[str]` | `[]` | Example inputs or usage scenarios |

### Example

```python
skill = AgentSkill(
    id="weather_forecast",
    description="Get weather forecast for any location",
    tags=["weather", "forecast", "location"],
    examples=[
        "What's the weather in New York?",
        "Forecast for London tomorrow",
        "Weather in 90210"
    ]
)
```

---

### Type Aliases in AgentCard

#### MimeType

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

#### SecuritySchemeType
Type alias for supported security schemes in Protolink. These are used to specify the **authentication methods** that agents can use.

| Category | Security Schemes |
|----------|------------|
| **API key** | `apiKey` |
| **HTTP** (bearer/basic/digest) | `http` |
| **OAuth 2.0** | `oauth2` |
| **Certificates** | `mutualTLS` |
| **OIDC auto-discovery** | `openIdConnect` |

---

## Task

```python
@dataclass
class Task:
    id: str = field(default_factory=IDGenerator.generate_task_id)
    state: TaskState = TaskState.SUBMITTED
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    flow_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
```

Unit of work exchanged between agents. Tasks encapsulate a complete unit of work including messages, state, and output artifacts.

!!! tip "Performance Note"
    The `Task` model implements internal caching for the most recent activity. Calling `get_last_item()` is an **$O(1)$** operation, avoiding expensive list indexing or timestamp comparisons.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `id` | `str` | `uuid4()` | Unique task identifier |
| `state` | `TaskState` | `SUBMITTED` | Current task state |
| `messages` | `list[Message]` | `[]` | Communication history |
| `artifacts` | `list[Artifact]` | `[]` | Output artifacts |
| `metadata` | `dict[str, Any]` | `{}` | Additional metadata |
| `flow_state` | `dict[str, Any]` | `{}` | Flow/orchestration context |
| `created_at` | `str` | `utc now` | Creation timestamp |

### Lifecycle

`Task.state` is an enforced lifecycle value, not a loose label. Valid transitions are:

```text
submitted -> working -> completed
submitted -> working -> input-required -> working -> completed
submitted -> working -> failed
submitted -> failed
submitted -> canceled
input-required -> failed
input-required -> canceled
```

`completed`, `failed`, and `canceled` are terminal states. Once a task reaches one of them, it should not be processed again.

Every successful state change is recorded in `task.metadata["state_history"]`:

```python
[
    {
        "previous_state": "submitted",
        "new_state": "working",
        "timestamp": "2026-06-12T08:30:00Z",
    }
]
```

The default `Agent.execute_task()` lifecycle is:

1. Move a non-terminal task to `WORKING`.
2. Execute explicit `tool_call` and `infer` parts from the latest message or artifact.
3. Append outputs as artifacts or messages.
4. Set the final state:
   - `COMPLETED` for successful outputs
   - `FAILED` for error parts, failed tool outputs, or exceptions
   - `INPUT_REQUIRED` for status parts requesting more input

### Methods

---

#### `add_message(message: Message) -> Task` { #task-add-message }

Add a message to the task's communication history.

**Parameters:**
```python
message: Message  # Message object to add to the task
```

**Returns:**
```python
Task  # Self for method chaining
```

**Example:**
```python
task = Task()
task.add_message(Message.user("What's the weather?"))
task.add_message(Message.agent("It's sunny!"))
```

---

#### `add_artifact(artifact: Artifact) -> Task` { #task-add-artifact }

Add an output artifact to the task (v0.2.0+).

**Parameters:**
```python
artifact: Artifact  # Artifact representing task output
```

**Returns:**
```python
Task  # Self for method chaining
```

**Example:**
```python
artifact = Artifact()
artifact.add_text("Weather analysis complete")
task.add_artifact(artifact)
```

---

#### `update_state(state: TaskState | str) -> Task` { #task-update-state }

Transition the task to a new state.

The transition must be valid according to the lifecycle graph above. Repeating the current state is a no-op. Invalid transitions raise `ValueError`.

**Parameters:**
```python
state: TaskState | str  # New task state
```

**Returns:**
```python
Task  # Self for method chaining
```

**Example:**
```python
task.update_state(TaskState.WORKING)
# ... process task ...
task.update_state(TaskState.COMPLETED)
```

Invalid direct jumps are rejected:

```python
task = Task.create(Message.user("hello"))
task.update_state(TaskState.COMPLETED)
# ValueError: Invalid task state transition: submitted -> completed
```

---

#### `begin() -> Task` { #task-begin }

Mark the task as actively being processed.

This is equivalent to `task.update_state(TaskState.WORKING)`.

---

#### `require_input(message: Message | None = None) -> Task` { #task-require-input }

Mark the task as waiting for more input.

If the task is still `SUBMITTED`, this convenience method first transitions through `WORKING` so the lifecycle history remains valid.

---

#### `complete(response_text: str) -> Task` { #task-complete }

Mark the task as completed with a response message.

**Parameters:**
```python
response_text: str  # Final response message text
```

**Returns:**
```python
Task  # Self for method chaining
```

**Example:**
```python
task.complete("The weather is sunny and 75°F.")
print(task.state)  # TaskState.COMPLETED
print(task.metadata["state_history"][-1]["new_state"])  # "completed"
```

---

#### `fail(error_message: str) -> Task` { #task-fail }

Mark the task as failed with an error message.

**Parameters:**
```python
error_message: str  # Description of the error
```

**Returns:**
```python
Task  # Self for method chaining
```

**Example:**
```python
task.fail("Weather API unavailable")
print(task.state)  # TaskState.FAILED
print(task.metadata["error"])  # "Weather API unavailable"
```

---

#### `cancel(reason: str | None = None) -> Task` { #task-cancel }

Mark the task as canceled.

**Parameters:**
```python
reason: str | None  # Optional cancellation reason stored in metadata
```

---

#### `to_dict() -> dict[str, Any]` { #task-to-dict }

Convert the task to a dictionary for serialization.

**Returns:**
```python
dict[str, Any]  # Dictionary representation of the task
```

**Example:**
```python
task_dict = task.to_dict()
print(task_dict["id"])  # Task UUID
print(task_dict["state"])  # Current state as string
```

---

#### `from_dict(data: dict[str, Any]) -> Task` `classmethod` { #task-from-dict }

Create a task from a dictionary.

**Parameters:**
```python
data: dict[str, Any]  # Dictionary containing task data
```

**Returns:**
```python
Task  # New Task instance
```

**Example:**
```python
task_dict = {"state": "working", "messages": [], "artifacts": []}
task = Task.from_dict(task_dict)
print(task.state)  # TaskState.WORKING
```

---

#### `create(message: Message) -> Task` `classmethod` { #task-create }

Create a new task with an initial message.

**Parameters:**
```python
message: Message  # Initial message for the task
```

**Returns:**
```python
Task  # New Task instance with the message added
```

**Example:**
```python
task = Task.create(Message.user("Analyze this data"))
print(len(task.messages))  # 1
print(task.state)  # TaskState.SUBMITTED
```

---

#### `create_infer(...) -> Task` `classmethod` { #task-create-infer }

Create a new task initialized with an infer message.

**Parameters:**
- `prompt`: `str | None`
- `user`: `str | None`
- `output_schema`: `dict[str, Any] | None`
- `metadata`: `dict[str, Any] | None`

**Returns:**
```python
Task  # New Task instance
```

**Example:**
```python
task = Task.create_infer(prompt="Calculate this")
```

### Example

```python
from protolink.models import Task, Message

# Create task with initial message
task = Task.create(Message.user("What's the weather in New York?"))

# Process it through the default lifecycle
task.begin()
task.complete("It's 72°F and sunny in New York.")

# Or use convenience method
task = Task.create(Message.user("Hello")).complete("Hi there!")
```

---

## TaskState

```python
class TaskState(Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"
```

Enumeration of possible task states.

!!! note "Terminal States"
    `COMPLETED`, `CANCELED`, and `FAILED` are terminal. They intentionally have no outgoing transitions.

### Values

| Value | Description |
|-------|-------------|
| `SUBMITTED` | Task has been submitted to the agent |
| `WORKING` | Agent is actively processing the task |
| `INPUT_REQUIRED` | Agent needs additional input from user |
| `COMPLETED` | Task has been successfully completed |
| `CANCELED` | Task was canceled by user or agent |
| `FAILED` | Task failed due to an error |
| `UNKNOWN` | Task state is unknown |

---

## Message

```python
@dataclass
class Message:
    id: str = field(default_factory=IDGenerator.generate_message_id)
    role: MessageRoleType = "user"
    parts: list[Part] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now)
```

Single unit of communication between agents. Messages contain one or more parts and have a specific role.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `id` | `str` | `uuid4()` | Unique message identifier |
| `role` | `MessageRoleType` | `"user"` | Sender role |
| `parts` | `list[Part]` | `[]` | Message content parts |
| `timestamp` | `str` | `now` | Creation timestamp |

### Role Types

- `"user"`: Message from a human user
- `"agent"`: Message from an agent
- `"assistant"`: LLM assistant response
- `"system"`: System-level message

### Methods

---

#### `add_text(text: str) -> Message` { #message-add-text }

Add a text part to the message.

**Parameters:**
```python
text: str  # Text content to add
```

**Returns:**
```python
Message  # Self for method chaining
```

**Example:**
```python
msg = Message(role="user")
msg.add_text("Hello, world!")
print(len(msg.parts))  # 1
print(msg.parts[0].content)  # "Hello, world!"
```

---

#### `add_part(part: Part) -> Message` { #message-add-part }

Add a content part to the message.

**Parameters:**
```python
part: Part  # Part object to add (text, image, file, etc.)
```

**Returns:**
```python
Message  # Self for method chaining
```

**Example:**
```python
msg = Message(role="agent")
msg.add_part(Part.text("Here's the analysis:"))
msg.add_part(Part.json({"result": "success"}))
```

---

#### `to_dict() -> dict[str, Any]` { #message-to-dict }

Convert the message to a dictionary for serialization.

**Returns:**
```python
dict[str, Any]  # Dictionary representation of the message
```

**Example:**
```python
msg = Message.user("Hello")
msg_dict = msg.to_dict()
print(msg_dict["role"])  # "user"
print(msg_dict["parts"][0]["content"])  # "Hello"
```

---

#### `from_dict(data: dict[str, Any]) -> Message` `classmethod` { #message-from-dict }

Create a message from a dictionary.

**Parameters:**
```python
data: dict[str, Any]  # Dictionary containing message data
```

**Returns:**
```python
Message  # New Message instance
```

**Example:**
```python
msg_dict = {
    "id": "msg-123",
    "role": "user",
    "parts": [{"type": "text", "content": "Hello"}],
    "timestamp": "2023-01-01T00:00:00Z"
}
msg = Message.from_dict(msg_dict)
```

---

#### `user(text: str) -> Message` `classmethod` { #message-user }

Create a user message with text content (convenience method).

**Parameters:**
```python
text: str  # Message text content
```

**Returns:**
```python
Message  # New Message instance with role "user"
```

**Example:**
```python
msg = Message.user("What's the weather?")
print(msg.role)  # "user"
print(msg.parts[0].content)  # "What's the weather?"
```

---

#### `agent(text: str) -> Message` `classmethod` { #message-agent }

Create an agent message with text content (convenience method).

**Parameters:**
```python
text: str  # Message text content
```

**Returns:**
```python
Message  # New Message instance with role "agent"
```

**Example:**
```python
msg = Message.agent("It's sunny and 75°F.")
print(msg.role)  # "agent"
print(msg.parts[0].content)  # "It's sunny and 75°F."
```

---

#### `assistant(text: str) -> Message` `classmethod` { #message-assistant }

Create an assistant message with text content.

---

#### `infer(...) -> Message` `classmethod` { #message-infer }

Create a user message with an infer part.

**Parameters:**
- `prompt`: `str | None`
- `user`: `str | None`
- `output_schema`: `dict[str, Any] | None`
- `metadata`: `dict[str, Any] | None`

**Returns:**
```python
Message  # New Message instance with infer part
```

### Example

```python
from protolink.models import Message, Part

# Create messages using convenience methods
user_msg = Message.user("What's the weather?")
agent_msg = Message.agent("It's sunny and 75°F.")

# Create message with multiple parts
msg = Message(role="user")
msg.add_text("Here's an image:")
msg.add_part(Part(type="image", content=image_data))
```

---

## Part

```python
@dataclass
class Part:
    type: PartType
    content: Any
```

Atomic content unit within a message. Parts represent individual pieces of content like text, images, or files.

### Parameters

| Parameter | Type | Description |
|-----------|-----|-------------|
| `type` | `PartType` | Content type (e.g., 'text', 'image', 'file') |
| `content` | `Any` | The actual content data |

### Methods

#### `to_dict() -> dict[str, Any]`

Convert to dictionary.

**Returns:** Dictionary representation

#### `from_dict(data: dict[str, Any]) -> Part`

Create from dictionary.

**Parameters:**
- `data`: Dictionary data

**Returns:** New Part instance

#### `text(content: str) -> Part` (classmethod)

Create a text part.

**Parameters:**
- `content`: Text content

**Returns:** New Part instance with type "text"

#### `tool_call(...) -> Part` `classmethod`

Create a tool_call part.

#### `tool_output(...) -> Part` `classmethod`

Create a tool_output part.

#### `infer(...) -> Part` `classmethod`

Create an infer part.

#### `infer_output(...) -> Part` `classmethod`

Create an infer_output part.

#### `json(content: dict) -> Part` `classmethod`

Create a json part.

#### `error(...) -> Part` `classmethod`

Create an error part.

#### `status(...) -> Part` `classmethod`

Create a status part.

### Example

```python
from protolink.models import Part

# Create different types of parts
text_part = Part.text("Hello, world!")
tool_call = Part.tool_call(tool_name="get_weather", args={"location": "Athens"})
infer_part = Part.infer(prompt="Who are you?")
```

---

## Artifact

```python
@dataclass
class Artifact:
    id: str = field(default_factory=IDGenerator.generate_artifact_id)
    parts: list[Part] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)
```

Output produced by a task (v0.2.0+). Artifacts represent results from task execution - files, structured data, analysis results, etc.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `id` | `str` | `uuid4()` | Unique artifact identifier |
| `parts` | `list[Part]` | `[]` | Content parts of the artifact |
| `metadata` | `dict[str, Any]` | `{}` | Artifact metadata |
| `timestamp` | `str` | `utc now` | Creation timestamp |

### Methods

#### `add_part(part: Part) -> Artifact`

Add content part to artifact.

**Parameters:**
- `part`: Part to add

**Returns:** Self for method chaining

#### `add_text(text: str) -> Artifact`

Add text content (convenience method).

**Parameters:**
- `text`: Text content

**Returns:** Self for method chaining

#### `to_dict() -> dict[str, Any]`

Convert to dictionary.

**Returns:** Dictionary representation

#### `from_dict(data: dict[str, Any]) -> Artifact`

Create from dictionary.

**Parameters:**
- `data`: Dictionary data

**Returns:** New Artifact instance

### Example

```python
from protolink.models import Artifact, Part

# Create artifact with multiple parts
artifact = Artifact()
artifact.add_text("Analysis Results:")
artifact.add_part(Part.json({"results": [1, 2, 3]}))
artifact.add_part(Part(type="image", content=chart_image_data))

# Set metadata
artifact.metadata["type"] = "analysis_report"
artifact.metadata["version"] = "1.0"
```

---

---

## EndpointSpec

```python
@dataclass(frozen=True)
class EndpointSpec:
    name: str
    path: str
    method: HttpMethod
    handler: Callable[..., Awaitable]
    content_type: Literal["json", "html"] = "json"
    streaming: bool = False
    mode: Literal["request_response", "stream"] = "request_response"
    request_parser: Callable[[Any], Any] | None = None
    request_source: RequestSourceType = "none"
```

Defines the contract for a server endpoint. This model lives in `protolink.server.endpoint_handler` and bridges the gap between the server implementation (Agent/Registry) and the underlying transport.

### Parameters

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `name` | `str` | — | **Required.** Unique internal name for the endpoint |
| `path` | `str` | — | **Required.** URL path (e.g., `/tasks/`) |
| `method` | `HttpMethod` | — | **Required.** HTTP method (GET, POST, etc.) |
| `handler` | `Callable` | — | **Required.** Async function that handles the request |
| `content_type` | `str` | `"json"` | Response content type (`json` or `html`) |
| `streaming` | `bool` | `False` | Whether the endpoint handler returns a stream of events |
| `mode` | `str` | `"request_response"` | Interaction mode (`request_response` or `stream`) |
| `request_parser` | `Callable` | `None` | Optional function to parse raw request data |
| `request_source` | `RequestSourceType` | `"none"` | Source of request data (`body`, `query_params`, etc.) |

---

## LLMMessage

```python
@dataclass
class LLMMessage:
    role: LLMMessageRole
    content: str
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tool_calls: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
```

Canonical message format used internally across all LLM providers. Unlike the standard `Message` model used for agent-to-agent communication, `LLMMessage` is optimized for LLM context windows and provider-specific schemas.

### Methods

#### `to_dict() -> dict[str, Any]`
Convert the message to a JSON-serializable dictionary, preserving all fields (including metadata and tool calls).

#### `from_dict(data: dict[str, Any]) -> LLMMessage` `classmethod`
Create an `LLMMessage` instance from a dictionary.

---

## ConversationHistory

```python
class ConversationHistory:
    def __init__(self, system_prompt: str | None = None):
        self._messages: deque[LLMMessage] = deque()
```

Manages conversation state in a provider-agnostic way.

!!! info "Optimized Architecture"
    `ConversationHistory` uses a **`collections.deque`** to ensure that updating system prompts or truncating history remains highly performant ($O(1)$ prepends) even as the conversation grows.

### Methods

#### `to_list() -> list[dict[str, Any]]`
Convert the entire history into a list of full message dictionaries. Used for persistence.

#### `from_list(messages_data: list[dict[str, Any]]) -> ConversationHistory` `classmethod`
Restore a conversation history from a list of message dictionaries.

#### `add_user(content: str)`
Add a user message to history.

#### `add_assistant(content: str)`
Add an assistant message to history.

#### `add_system(content: str)`
Add a system message to history.

#### `reset_to_system(system_prompt: str)`
Wipes all history and sets a new system prompt.

#### `set_system(system_prompt: str)`
Updates the system prompt (at index 0) while preserving all subsequent conversation turns.
