import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Models

ProtoLink's models are the transport-neutral vocabulary shared by agents, clients, servers, flows, storage, telemetry, registries, and LLM adapters. They describe who an agent is, how work moves through its lifecycle, what a message contains, and how those values cross process boundaries.

These are ProtoLink's ergonomic runtime forms of A2A's core agent primitives. The [A2A 1.0 adapter](a2a.md) maps the advertised subset to canonical wire models when interoperability is required; the classes on this page remain the native Python contract used inside ProtoLink.

<ApiSurface
  eyebrow="Protocol model layer"
  title="Core Data Models"
  path="protolink.models"
  description="The stable dataclass and protocol vocabulary shared by agents, clients, servers, transports, registries, LLM wrappers, and storage-aware runtime features."
  pills={[
    "A2A-derived cards and tasks",
    "Task lifecycle state",
    "Messages and parts",
    "Artifacts and endpoints",
    "LLM history contracts",
  ]}
  cards={[
    {
      title: "Identity",
      text: "Agent cards, capabilities, skills, roles, tags, security schemes, and advertised IO formats.",
      code: "AgentCard",
    },
    {
      title: "Work units",
      text: "Task state, messages, parts, artifacts, errors, metadata, and helper constructors for inference.",
      code: "Task",
    },
    {
      title: "Routes",
      text: "Endpoint specifications let servers declare paths once and transports bind them to a backend.",
      code: "EndpointSpec",
    },
    {
      title: "Context",
      text: "LLM messages, conversation history, compaction requests, and compaction reports.",
      code: "ConversationHistory",
    },
  ]}
/>

## Package overview

Most application-facing models can be imported from either `protolink` or `protolink.models`:

```python
from protolink import AgentCard, AgentInterface, AgentSkill
from protolink import Artifact, Message, Part, Task, TaskState
from protolink import HistoryCompactionRequest, HistoryCompactionResult
from protolink.models import EndpointSpec, RouteDecision
```

The source files are partitioned by runtime responsibility:

- `protolink.core.agent_card` owns identity, capabilities, skills, and additional interfaces.
- `protolink.core.task`, `message`, `part`, and `artifact` own the task envelope and its nested content.
- `protolink.server.endpoint_handler` owns transport-neutral server endpoint declarations.
- `protolink.llms.history` owns the provider-neutral LLM context representation.
- `protolink.llms.compaction` owns the request and result values used by direct, agent, and client compaction APIs.
- `protolink.models` is a convenience re-export layer. It intentionally gathers models from those focused modules rather than defining a second set of classes.

`AgentCapabilities`, `LLMMessage`, and `ConversationHistory` are lower-level implementation-facing types and are imported from their defining modules. They are documented here because they are important when customizing discovery cards or LLM state:

```python
from protolink.core.agent_card import AgentCapabilities
from protolink.llms.history import ConversationHistory, LLMMessage, LLMMessageRole
```

:::info[Serialization boundaries]

`to_dict()` methods return ordinary Python dictionaries suitable for ProtoLink's JSON boundaries, but they are not universal schema validators and generally do not deep-copy arbitrary metadata. Constructing a dataclass directly is intentionally permissive in several places; `from_dict()` performs the normalization required by that class's wire format.

:::

## Table of Contents

- [Messages and content](#messages-and-content)
  - [Message](#message)
  - [Part](#part)
  - [RouteDecision](#routedecision)
  - [Artifact](#artifact)
- [Agent identity](#agent-identity)
  - [AgentCard](#agentcard)
  - [AgentCapabilities](#agentcapabilities)
  - [AgentSkill](#agentskill)
  - [AgentInterface](#agentinterface)
- [Tasks and lifecycle](#tasks-and-lifecycle)
  - [Task](#task)
  - [TaskState](#taskstate)
- [Server endpoints](#server-endpoints)
  - [EndpointSpec](#endpointspec)
- [LLM context models](#llm-context-models)
  - [LLMMessage](#llmmessage)
  - [ConversationHistory](#conversationhistory)
  - [HistoryCompactionRequest](#historycompactionrequest)
  - [HistoryCompactionResult](#historycompactionresult)

---

## Messages and content

Messages are the ordered communication units inside a task. Each message contains one or more `Part` values so plain text, structured control requests, tool calls, routes, errors, and media can share the same envelope. Artifacts use the same part model for durable outputs.

### Message

<ApiReference
  kind="dataclass"
  path="protolink.Message"
  signature={`class Message(
    id: str = generate_message_id(),
    role: MessageRoleType = "user",
    parts: list[Part] = [],
    timestamp: str = utc_now(),
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L11"
>

One unit of communication between a user, agent, assistant model, or system layer. The message envelope supplies identity, sender role, and creation time; ordered `Part` values carry the actual text, structured data, control request, or result.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message constructor parameters">
    <ApiField name="id" type="str" defaultValue="generate_message_id()">
      Unique message identifier. The default generator creates a <code>msg_</code>-prefixed timestamp plus a random suffix.
    </ApiField>
    <ApiField name="role" type="MessageRoleType" defaultValue={'"user"'}>
      Sender role: <code>user</code>, <code>agent</code>, <code>assistant</code>, or <code>system</code>. The literal annotation is not enforced at direct dataclass construction, so use the convenience constructors when possible.
    </ApiField>
    <ApiField name="parts" type="list[Part]" defaultValue="[]">
      Ordered message content. A fresh list is created for each default instance; a list supplied by the caller is stored directly.
    </ApiField>
    <ApiField name="timestamp" type="str" defaultValue="utc_now()">
      ISO 8601 UTC creation time used when comparing messages with artifacts for a task's last-item cache.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Message versus LLMMessage">
  <code>Message</code> is the agent/task protocol envelope and may contain heterogeneous parts. <code>LLMMessage</code> is the provider-neutral context entry used by LLM adapters and always carries a text content field.
</ApiCallout>

</ApiReference>

#### Message.add_text {#message-add-text}

<ApiReference
  kind="method"
  path="protolink.Message.add_text"
  signature={`add_text(
    text: str,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L26"
>

Append plain text by constructing `Part.text(text)`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message add_text parameters">
    <ApiField name="text" type="str" required>
      Text content to append. The method stores the string as-is and does not trim, normalize, or reject an empty value.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message add_text return value">
    <ApiField name="self" type="Message">
      The mutated message for method chaining.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Side effect">
  Appends one new part to <code>parts</code>. The message identifier, role, and timestamp remain unchanged.
</ApiCallout>

</ApiReference>

#### Message.add_part {#message-add-part}

<ApiReference
  kind="method"
  path="protolink.Message.add_part"
  signature={`add_part(
    part: Part,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L31"
>

Append an existing part to the message. Use this for structured JSON, media, tool calls, inference requests, route decisions, and custom part types.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message add_part parameters">
    <ApiField name="part" type="Part" required>
      Content part to append. No runtime type check or defensive copy is performed.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message add_part return value">
    <ApiField name="self" type="Message">
      The mutated message.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Message.to_dict {#message-to-dict}

<ApiReference
  kind="method"
  path="protolink.Message.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L36"
>

Serialize the message and each nested part into the native task wire shape.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing <code>id</code>, <code>role</code>, serialized <code>parts</code>, and <code>timestamp</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Content conversion">
  Each part controls conversion of its own content. Dataclass-backed tool and route content becomes a dictionary; arbitrary custom content is returned as supplied and must already be compatible with the eventual encoder.
</ApiCallout>

</ApiReference>

#### Message.from_dict {#message-from-dict}

<ApiReference
  kind="classmethod"
  path="protolink.Message.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L45"
>

Create a message from native serialized data and hydrate every nested part.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Message mapping. Missing identifier, role, parts, or timestamp receive the same defaults as direct construction.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message from_dict return value">
    <ApiField name="message" type="Message">
      A new message whose nested tool calls, tool outputs, and route decisions are normalized by <code>Part.from_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Message from_dict errors">
    <ApiField name="KeyError, TypeError, or ValueError">
      Propagated from malformed nested part payloads. The message mapping itself has no mandatory keys because defaults are available for every constructor field.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
message = Message.from_dict(
    {
        "id": "msg-123",
        "role": "user",
        "parts": [{"type": "text", "content": "Hello"}],
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
)
```

</ApiSection>

</ApiReference>

#### Message.user {#message-user}

<ApiReference
  kind="classmethod"
  path="protolink.Message.user"
  signature={`user(
    text: str,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L56"
>

Create a user-role message containing one text part. This is the normal constructor for human or calling-client input.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message user parameters">
    <ApiField name="text" type="str" required>
      User text stored in a new <code>Part(type="text", ...)</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message user return value">
    <ApiField name="message" type="Message">
      New message with role <code>user</code>, a generated identifier and timestamp, and one text part.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Message.agent {#message-agent}

<ApiReference
  kind="classmethod"
  path="protolink.Message.agent"
  signature={`agent(
    text: str,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L61"
>

Create an agent-role message containing one text part. Task convenience methods such as `Task.complete()` use this constructor for final responses.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message agent parameters">
    <ApiField name="text" type="str" required>
      Agent response text.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message agent return value">
    <ApiField name="message" type="Message">
      New message with role <code>agent</code> and one text part.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Message.assistant {#message-assistant}

<ApiReference
  kind="classmethod"
  path="protolink.Message.assistant"
  signature={`assistant(
    text: str,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L66"
>

Create an assistant-role message containing one text part. Use this role when preserving the distinction between an LLM assistant response and the broader agent runtime identity.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message assistant parameters">
    <ApiField name="text" type="str" required>
      Assistant response text.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message assistant return value">
    <ApiField name="message" type="Message">
      New message with role <code>assistant</code> and one text part.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Message.route

<ApiReference
  kind="classmethod"
  path="protolink.Message.route"
  signature={`route(
    route_key: str,
    *,
    reason: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L71"
>

Create an agent-role message containing one structured route decision. Routers can inspect the typed decision instead of parsing fragile text labels.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message route parameters">
    <ApiField name="route_key" type="str" required>
      Key expected by the receiving router's route map.
    </ApiField>
    <ApiField name="reason" type="str | None" defaultValue="None">
      Optional human-readable explanation for observability or debugging.
    </ApiField>
    <ApiField name="confidence" type="float | None" defaultValue="None">
      Optional confidence score. The model does not clamp or validate the documented zero-to-one range.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Additional serializable decision context. <code>None</code> and an empty dictionary both become a fresh empty mapping.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message route return value">
    <ApiField name="message" type="Message">
      New agent message containing <code>Part.route(...)</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Message.infer {#message-infer}

<ApiReference
  kind="classmethod"
  path="protolink.Message.infer"
  signature={`infer(
    *,
    prompt: str | None = None,
    user: str | None = None,
    output_schema: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L93"
>

Create a user-role message containing one `infer` control part. When an agent executes the enclosing task, the part requests an LLM inference rather than representing ordinary display text.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message infer parameters">
    <ApiField name="prompt" type="str | None" defaultValue="None">
      Main model instruction included when supplied.
    </ApiField>
    <ApiField name="user" type="str | None" defaultValue="None">
      Optional user context carried inside the control payload.
    </ApiField>
    <ApiField name="output_schema" type="dict[str, Any] | None" defaultValue="None">
      Optional schema for a structured response.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional operation metadata, distinct from message and task metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message infer return value">
    <ApiField name="message" type="Message">
      New user message containing exactly one infer part. Values that are <code>None</code> are omitted from the part content.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Message.tool_call

<ApiReference
  kind="classmethod"
  path="protolink.Message.tool_call"
  signature={`tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    call_id: str | None = None,
) -> Message`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/message.py#L111"
>

Create a user-role message containing one typed tool invocation. The receiving agent resolves and executes the tool when processing the task.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Message tool_call parameters">
    <ApiField name="tool_name" type="str" required>
      Canonical registered tool name.
    </ApiField>
    <ApiField name="args" type="dict[str, Any] | None" defaultValue="None">
      Tool arguments. <code>None</code> becomes an empty mapping.
    </ApiField>
    <ApiField name="call_id" type="str | None" defaultValue="None">
      Optional correlation identifier used to match a later <code>tool_output</code>. A generated identifier is used when omitted.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Message tool_call return value">
    <ApiField name="message" type="Message">
      New user message containing exactly one tool-call part.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

<ApiSection title="Message examples">

```python
from protolink import Message, Part

user_message = Message.user("What's the weather?")
agent_message = Message.agent("It's sunny and 24°C.")

multi_part = (
    Message(role="user")
    .add_text("Analyze this payload:")
    .add_part(Part.json({"city": "Athens"}))
)

route_message = Message.route(
    "quality",
    reason="Draft is ready for review",
    confidence=0.92,
)
```

</ApiSection>

### Part

<ApiReference
  kind="dataclass"
  path="protolink.Part"
  signature={`class Part(
    type: PartType,
    content: Any,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L64"
>

Atomic content unit within a message or artifact. The `type` is the dispatch key; `content` may be text, JSON-compatible data, media, a typed tool-call value, a typed tool output, or a route decision.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part constructor parameters">
    <ApiField name="type" type="PartType" required>
      Content category such as <code>text</code>, <code>json</code>, <code>tool_call</code>, <code>tool_output</code>, <code>infer</code>, <code>route</code>, <code>error</code>, or a supported media type. Direct construction does not runtime-check the literal.
    </ApiField>
    <ApiField name="content" type="Any" required>
      Payload interpreted according to <code>type</code>. Direct construction preserves it unchanged; <code>from_dict()</code> hydrates selected structured part types into dataclasses.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Prefer factories for structured parts">
  Use <code>tool_call()</code>, <code>tool_output()</code>, <code>route()</code>, and <code>decision()</code> to obtain typed content with generated IDs and normalized metadata. A direct <code>Part(type="tool_call", content=dict(...))</code> remains dictionary-backed until explicitly converted.
</ApiCallout>

</ApiReference>

#### Part.to_dict

<ApiReference
  kind="method"
  path="protolink.Part.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L116"
>

Serialize a part into its two-field native representation.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing <code>type</code> and <code>content</code>. Dataclass content, including tool calls, tool outputs, and route decisions, is recursively converted with <code>dataclasses.asdict()</code>; other content is returned unchanged.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="JSON compatibility">
  The method does not encode bytes, arbitrary objects, or custom mappings. A part can be valid in memory while still requiring a transport-specific encoder.
</ApiCallout>

</ApiReference>

#### Part.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.Part.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L124"
>

Rehydrate a serialized part. Tool-call, tool-output, route, and decision dictionaries become their typed dataclass representations; all other content remains as supplied.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Mapping with a required <code>type</code> and optional <code>content</code>. Missing content becomes <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part from_dict return value">
    <ApiField name="part" type="Part">
      New part with normalized structured content where supported.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Part from_dict errors">
    <ApiField name="KeyError">
      Raised when <code>type</code> is absent, or when a serialized tool call does not provide its required <code>tool_name</code>.
    </ApiField>
    <ApiField name="ValueError">
      Raised when route or decision content lacks <code>route_key</code> and its accepted compatibility aliases <code>route</code> and <code>key</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Generated correlation IDs">
  A serialized tool call or output without <code>call_id</code> receives a newly generated identifier during hydration. Supply the original ID when correlation must survive a round trip.
</ApiCallout>

</ApiReference>

#### Part.as_tool_call

<ApiReference
  kind="method"
  path="protolink.Part.as_tool_call"
  signature={`as_tool_call() -> ToolCall`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L131"
>

Validate that the part represents a tool call and return a typed `ToolCall` view of its content.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part as_tool_call return value">
    <ApiField name="tool_call" type="ToolCall">
      Existing typed content, or a newly hydrated value when the content is a dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Part as_tool_call errors">
    <ApiField name="ValueError">
      Raised when <code>type</code> is not <code>tool_call</code>.
    </ApiField>
    <ApiField name="TypeError">
      Raised when the type is correct but content is neither <code>ToolCall</code> nor a dictionary.
    </ApiField>
    <ApiField name="KeyError">
      Raised when dictionary content lacks <code>tool_name</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="No in-place conversion">
  When content is dictionary-backed, this method returns a hydrated object but does not assign it back to <code>part.content</code>.
</ApiCallout>

</ApiReference>

#### Part.as_tool_output

<ApiReference
  kind="method"
  path="protolink.Part.as_tool_output"
  signature={`as_tool_output() -> ToolOutput`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L140"
>

Validate that the part represents a tool result and return a typed `ToolOutput` view.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part as_tool_output return value">
    <ApiField name="tool_output" type="ToolOutput">
      Existing typed output or a newly hydrated view of dictionary content.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Part as_tool_output errors">
    <ApiField name="ValueError">
      Raised when <code>type</code> is not <code>tool_output</code>.
    </ApiField>
    <ApiField name="TypeError">
      Raised when content has an unsupported runtime type.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.as_route_decision

<ApiReference
  kind="method"
  path="protolink.Part.as_route_decision"
  signature={`as_route_decision() -> RouteDecision`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L149"
>

Read a typed route decision from either a `route` or `decision` part.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part as_route_decision return value">
    <ApiField name="decision" type="RouteDecision">
      Existing typed decision or a hydrated view of dictionary content.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Part as_route_decision errors">
    <ApiField name="ValueError">
      Raised for any part type other than <code>route</code> or <code>decision</code>, or when dictionary content lacks a route key.
    </ApiField>
    <ApiField name="TypeError">
      Raised when content is neither a <code>RouteDecision</code> nor a dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.text

<ApiReference
  kind="classmethod"
  path="protolink.Part.text"
  signature={`text(
    content: str,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L158"
>

Create a plain-text part.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part text parameters">
    <ApiField name="content" type="str" required>
      Text payload preserved exactly as supplied.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part text return value">
    <ApiField name="part" type="Part">
      New part with type <code>text</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.json

<ApiReference
  kind="classmethod"
  path="protolink.Part.json"
  signature={`json(
    content: dict,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L163"
>

Create a structured JSON part. The method labels the mapping but does not serialize or copy it.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part json parameters">
    <ApiField name="content" type="dict" required>
      Mapping to store as the part content. Nested values must be serializable by the eventual transport.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part json return value">
    <ApiField name="part" type="Part">
      New part with type <code>json</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.error

<ApiReference
  kind="classmethod"
  path="protolink.Part.error"
  signature={`error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L167"
>

Create a structured error part suitable for task failure detection and client display.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part error parameters">
    <ApiField name="code" type="str" required>
      Stable machine-readable error identifier.
    </ApiField>
    <ApiField name="message" type="str" required>
      Human-readable failure explanation.
    </ApiField>
    <ApiField name="retryable" type="bool" defaultValue="False">
      Advisory flag indicating whether repeating the operation may succeed. It does not schedule a retry.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part error return value">
    <ApiField name="part" type="Part">
      Error part whose content contains <code>code</code>, <code>message</code>, and <code>retryable</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.status

<ApiReference
  kind="classmethod"
  path="protolink.Part.status"
  signature={`status(
    state: str,
    message: str | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L178"
>

Create a structured status part. Agent lifecycle handling can use status content to communicate progress or request additional input.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part status parameters">
    <ApiField name="state" type="str" required>
      Application or runtime status label. This helper does not coerce the value to <code>TaskState</code>.
    </ApiField>
    <ApiField name="message" type="str | None" defaultValue="None">
      Optional human-readable status detail. The key remains present with a <code>null</code> value when omitted.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part status return value">
    <ApiField name="part" type="Part">
      Status part containing <code>state</code> and <code>message</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.route

<ApiReference
  kind="classmethod"
  path="protolink.Part.route"
  signature={`route(
    route_key: str,
    *,
    reason: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L185"
>

Create a structured flow-routing part backed by `RouteDecision`. Routers prefer this typed control value over extracting route names from prose.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part route parameters">
    <ApiField name="route_key" type="str" required>
      Destination key in the receiving router's route map.
    </ApiField>
    <ApiField name="reason" type="str | None" defaultValue="None">
      Optional explanation for the selection.
    </ApiField>
    <ApiField name="confidence" type="float | None" defaultValue="None">
      Optional confidence score. No numeric range validation is performed.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Additional serializable context; falsy values become a fresh empty dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part route return value">
    <ApiField name="part" type="Part">
      Part with type <code>route</code> and typed <code>RouteDecision</code> content.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.decision

<ApiReference
  kind="classmethod"
  path="protolink.Part.decision"
  signature={`decision(
    route_key: str,
    *,
    reason: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L205"
>

Create a structured decision part with the same `RouteDecision` content as `route()`. Use the distinct type when an application wants to label a branching decision without calling it a route.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part decision parameters">
    <ApiField name="route_key" type="str" required>
      Selected branch or decision key.
    </ApiField>
    <ApiField name="reason" type="str | None" defaultValue="None">
      Optional human-readable rationale.
    </ApiField>
    <ApiField name="confidence" type="float | None" defaultValue="None">
      Optional unvalidated confidence value.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional additional decision context.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part decision return value">
    <ApiField name="part" type="Part">
      Part with type <code>decision</code> and typed route-decision content.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.tool_call

<ApiReference
  kind="classmethod"
  path="protolink.Part.tool_call"
  signature={`tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    call_id: str | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L229"
>

Create a standardized tool or capability invocation. The typed content keeps the tool name, arguments, and correlation identifier together through task serialization.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part tool_call parameters">
    <ApiField name="tool_name" type="str" required>
      Canonical name resolved by the receiving agent's tool registry.
    </ApiField>
    <ApiField name="args" type="dict[str, Any] | None" defaultValue="None">
      Arguments passed to the tool. <code>None</code> and other falsy mappings become a new empty dictionary.
    </ApiField>
    <ApiField name="call_id" type="str | None" defaultValue="None">
      Correlation identifier used by the corresponding tool output. A generated <code>tool_call_</code>-prefixed ID is retained when this value is <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part tool_call return value">
    <ApiField name="part" type="Part">
      Part with type <code>tool_call</code> and a typed <code>ToolCall</code> content object.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Resolution timing">
  Creating the part does not verify that the named tool exists or validate its arguments. Those checks happen when an agent executes the call.
</ApiCallout>

</ApiReference>

#### Part.tool_output

<ApiReference
  kind="classmethod"
  path="protolink.Part.tool_output"
  signature={`tool_output(
    *,
    call_id: str | None = None,
    result: Any | None = None,
    error: dict | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L267"
>

Create the success or failure result for an earlier tool call.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part tool_output parameters">
    <ApiField name="call_id" type="str | None" defaultValue="None">
      Identifier of the originating call. If omitted, a new <code>tool_output_</code>-prefixed ID is generated; that generated value will not correlate with an earlier call unless the caller records it explicitly.
    </ApiField>
    <ApiField name="result" type="Any | None" defaultValue="None">
      Successful result payload. ProtoLink does not enforce mutual exclusivity with <code>error</code>.
    </ApiField>
    <ApiField name="error" type="dict | None" defaultValue="None">
      Structured error payload for a failed invocation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part tool_output return value">
    <ApiField name="part" type="Part">
      Part with type <code>tool_output</code> and typed <code>ToolOutput</code> content.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.infer

<ApiReference
  kind="classmethod"
  path="protolink.Part.infer"
  signature={`infer(
    *,
    prompt: str | None = None,
    user: str | None = None,
    output_schema: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L305"
>

Create a control part instructing an agent to invoke its configured LLM. This is the low-level value wrapped by `Message.infer()` and `Task.create_infer()`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part infer parameters">
    <ApiField name="prompt" type="str | None" defaultValue="None">
      Model instruction.
    </ApiField>
    <ApiField name="user" type="str | None" defaultValue="None">
      Optional user identity or context.
    </ApiField>
    <ApiField name="output_schema" type="dict[str, Any] | None" defaultValue="None">
      Optional structured-output schema.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional operation metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part infer return value">
    <ApiField name="part" type="Part">
      Part with type <code>infer</code>. Every argument whose value is <code>None</code> is removed from the content dictionary; empty strings and empty mappings remain.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Part.infer_output

<ApiReference
  kind="classmethod"
  path="protolink.Part.infer_output"
  signature={`infer_output(
    *,
    content: str | dict[str, Any],
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L343"
>

Wrap the result of an LLM inference operation in a dedicated output part.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Part infer_output parameters">
    <ApiField name="content" type="str | dict[str, Any]" required>
      Unstructured response text or a structured result mapping. The value is stored without copying or schema validation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Part infer_output return value">
    <ApiField name="part" type="Part">
      Part with type <code>infer_output</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

<ApiSection title="Part examples">

```python
from protolink import Part

text_part = Part.text("Hello, world!")
json_part = Part.json({"status": "ready"})

tool_call = Part.tool_call(
    tool_name="get_weather",
    args={"location": "Athens"},
)
tool_result = Part.tool_output(
    call_id=tool_call.as_tool_call().call_id,
    result={"temperature": 24},
)

infer_part = Part.infer(prompt="Summarize the weather.")
route_part = Part.route("quality", reason="Ready for review")
```

</ApiSection>

### RouteDecision

<ApiReference
  kind="dataclass"
  path="protolink.models.RouteDecision"
  signature={`class RouteDecision(
    route_key: str,
    reason: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] = {},
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/part.py#L46"
>

Typed content carried by `route` and `decision` parts. Keeping the selected key separate from explanatory text lets `Router` branch deterministically while retaining rationale, confidence, and application context for observability.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RouteDecision constructor parameters">
    <ApiField name="route_key" type="str" required>
      Selected key in the receiving router's route map. The model stores the value without confirming that a matching route exists.
    </ApiField>
    <ApiField name="reason" type="str | None" defaultValue="None">
      Optional human-readable rationale for logs, traces, or review.
    </ApiField>
    <ApiField name="confidence" type="float | None" defaultValue="None">
      Optional confidence score. Although zero to one is the intended semantic range, this dataclass does not enforce it.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Additional serializable routing context. Each default instance receives an independent mapping.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Normal construction">
  Applications usually call <code>Part.route()</code>, <code>Part.decision()</code>, or <code>Message.route()</code>. Those helpers wrap this value with the appropriate part and message type.
</ApiCallout>

</ApiReference>

### Artifact

<ApiReference
  kind="dataclass"
  path="protolink.Artifact"
  signature={`class Artifact(
    id: str = generate_artifact_id(),
    parts: list[Part] = [],
    metadata: dict[str, Any] = {},
    timestamp: str = utc_now(),
    kind: str = "result",
    name: str | None = None,
    uri: str | None = None,
    media_type: str | None = None,
    action_id: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/artifact.py#L10"
>

Structured output or preview produced during a run. Artifacts carry the same flexible parts as messages while adding durable descriptors for resources, diagnostics, previews, and action-related results.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Artifact constructor parameters">
    <ApiField name="id" type="str" defaultValue="generate_artifact_id()">
      Unique artifact identifier generated with an <code>art_</code> prefix by default.
    </ApiField>
    <ApiField name="parts" type="list[Part]" defaultValue="[]">
      Ordered output content, such as text, JSON, media, tool output, or an inference result.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Extensible application metadata. The model imposes no reserved schema.
    </ApiField>
    <ApiField name="timestamp" type="str" defaultValue="utc_now()">
      ISO 8601 UTC creation time used by task last-item ordering.
    </ApiField>
    <ApiField name="kind" type="str" defaultValue={'"result"'}>
      Application-defined category such as <code>result</code>, <code>preview</code>, or <code>diagnostic</code>. It remains a free string so domains can extend the taxonomy.
    </ApiField>
    <ApiField name="name" type="str | None" defaultValue="None">
      Optional display name or represented resource name.
    </ApiField>
    <ApiField name="uri" type="str | None" defaultValue="None">
      Optional URI identifying the represented resource.
    </ApiField>
    <ApiField name="media_type" type="str | None" defaultValue="None">
      Optional MIME type describing the artifact as a whole. Individual parts may still carry heterogeneous content.
    </ApiField>
    <ApiField name="action_id" type="str | None" defaultValue="None">
      Optional identifier of the <code>RunAction</code> that produced or proposes this artifact.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Descriptor semantics">
  Optional descriptors are informational and are not cross-validated. For example, setting <code>media_type</code> does not transform parts or verify that their content matches the MIME type.
</ApiCallout>

</ApiReference>

#### Artifact.add_part

<ApiReference
  kind="method"
  path="protolink.Artifact.add_part"
  signature={`add_part(
    part: Part,
) -> Artifact`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/artifact.py#L43"
>

Append an existing content part to the artifact.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Artifact add_part parameters">
    <ApiField name="part" type="Part" required>
      Part to append. It is stored by reference without validation or copying.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Artifact add_part return value">
    <ApiField name="self" type="Artifact">
      The mutated artifact for chaining.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Artifact.add_text

<ApiReference
  kind="method"
  path="protolink.Artifact.add_text"
  signature={`add_text(
    text: str,
) -> Artifact`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/artifact.py#L48"
>

Append a plain-text part to the artifact.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Artifact add_text parameters">
    <ApiField name="text" type="str" required>
      Text wrapped by <code>Part.text()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Artifact add_text return value">
    <ApiField name="self" type="Artifact">
      The mutated artifact.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Artifact.for_action

<ApiReference
  kind="method"
  path="protolink.Artifact.for_action"
  signature={`for_action(
    action_id: str,
) -> Artifact`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/artifact.py#L53"
>

Associate the artifact with a runtime action. This is useful when a preview is created before the final `RunAction` identifier is known.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Artifact for_action parameters">
    <ApiField name="action_id" type="str" required>
      Identifier assigned directly to the artifact. It is not checked against an action registry.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Artifact for_action return value">
    <ApiField name="self" type="Artifact">
      The same artifact after mutation.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Artifact.to_dict

<ApiReference
  kind="method"
  path="protolink.Artifact.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/artifact.py#L69"
>

Serialize all artifact fields and nested parts into the native dictionary representation.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Artifact to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing every descriptor key, including optional keys whose values are <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Copy semantics">
  Parts are converted recursively. The metadata mapping and non-dataclass part contents are not deep-copied.
</ApiCallout>

</ApiReference>

#### Artifact.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.Artifact.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> Artifact`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/artifact.py#L83"
>

Create an artifact from serialized data while remaining compatible with payloads emitted before structured descriptor fields were added.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Artifact from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Artifact mapping. Missing identifiers and timestamps are generated, missing or falsy <code>kind</code> becomes <code>result</code>, and missing metadata becomes a fresh empty dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Artifact from_dict return value">
    <ApiField name="artifact" type="Artifact">
      New artifact with hydrated parts. Non-<code>None</code> values for <code>name</code>, <code>uri</code>, <code>media_type</code>, and <code>action_id</code> are converted with <code>str()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Artifact from_dict errors">
    <ApiField name="KeyError, TypeError, or ValueError">
      Propagated from malformed nested parts or from values that cannot be converted to the expected container shape.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink import Artifact, Part

artifact = (
    Artifact(
        kind="diagnostic",
        name="analysis report",
        media_type="application/json",
    )
    .add_text("Analysis results:")
    .add_part(Part.json({"results": [1, 2, 3]}))
    .for_action("action_42")
)

artifact.metadata["version"] = "1.0"
```

</ApiSection>

</ApiReference>

---

## Agent identity

Discovery starts with an `AgentCard`. The card identifies one logical agent, describes the work it can perform, and advertises how peers can reach it. Capabilities are coarse feature flags; skills provide task-level schemas and examples; interfaces describe alternate endpoints for the same identity.

### AgentCard

<ApiReference
  kind="dataclass"
  path="protolink.AgentCard"
  signature={`class AgentCard(
    name: str,
    description: str,
    url: str,
    transport: TransportType = "http",
    version: str = "1.0.0",
    protocol_version: str = protolink_version,
    capabilities: AgentCapabilities = AgentCapabilities(),
    skills: list[AgentSkill] = [],
    input_formats: list[MimeType] = ["text/plain"],
    output_formats: list[MimeType] = ["text/plain"],
    security_schemes: dict[SecuritySchemeType, dict[str, Any]] | None = {},
    role: AgentRoleType = "worker",
    tags: list[str] = [],
    interfaces: list[AgentInterface] = [],
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L132"
>

Agent identity and capability declaration used by ProtoLink discovery, registration, delegation prompts, and server metadata. The primary `url` and `transport` describe the normal route; `interfaces` advertises additional routes to the same logical agent.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentCard constructor parameters">
    <ApiField name="name" type="str" required>
      Stable human-readable identity used by registries, delegation prompts, logs, and agent lookup. <code>from_dict()</code> rejects an absent, empty, or otherwise falsy name, although direct dataclass construction does not repeat that validation.
    </ApiField>
    <ApiField name="description" type="str" required>
      Clear explanation of the agent's purpose and when another agent should delegate work to it. This text is included in <code>get_prompt_format()</code>, so operational descriptions are more useful than marketing copy.
    </ApiField>
    <ApiField name="url" type="str" required>
      Primary service endpoint. ProtoLink stores the value as supplied; URL syntax and reachability are validated later by the selected transport rather than by the dataclass.
    </ApiField>
    <ApiField name="transport" type="TransportType" defaultValue={'"http"'}>
      Registered transport for the primary URL. Supported annotations include <code>http</code>, <code>websocket</code>, <code>sse</code>, <code>json-rpc</code>, <code>sse-json-rpc</code>, <code>grpc</code>, and <code>runtime</code>. Runtime construction does not independently validate the literal.
    </ApiField>
    <ApiField name="version" type="str" defaultValue={'"1.0.0"'}>
      Application-defined version of the agent implementation. It lets clients distinguish behavior changes independently from the protocol version.
    </ApiField>
    <ApiField name="protocol_version" type="str" defaultValue="protolink_version">
      ProtoLink native-card protocol version. The default is resolved from the installed package version when the module is imported. A2A adapters own their interface version separately.
    </ApiField>
    <ApiField name="capabilities" type="AgentCapabilities | Mapping[str, Any]" defaultValue="AgentCapabilities()">
      Coarse features and limits advertised by the agent. A mapping is normalized into <code>AgentCapabilities</code> during <code>__post_init__</code>; missing mapping keys receive dataclass defaults. Any other object raises <code>TypeError</code>.
    </ApiField>
    <ApiField name="skills" type="list[AgentSkill]" defaultValue="[]">
      Specific operations available for discovery and delegation. Each skill can carry input and output JSON Schemas plus examples. Unlike <code>capabilities</code>, raw skill mappings are not normalized by direct construction; use <code>AgentSkill</code> objects or <code>AgentCard.from_dict()</code>.
    </ApiField>
    <ApiField name="input_formats" type="list[MimeType]" defaultValue={'["text/plain"]'}>
      MIME types accepted by the agent's normal task interface. Each card receives an independent list from the default factory.
    </ApiField>
    <ApiField name="output_formats" type="list[MimeType]" defaultValue={'["text/plain"]'}>
      MIME types the agent may return. This is discovery metadata, not automatic response transcoding.
    </ApiField>
    <ApiField name="security_schemes" type="dict[SecuritySchemeType, dict[str, Any]] | None" defaultValue="{}">
      Named authentication scheme declarations used by discovery consumers. ProtoLink preserves the mapping as supplied and does not validate the nested OpenAPI-style scheme definition here. <code>None</code> is accepted and serialized as <code>null</code>.
    </ApiField>
    <ApiField name="role" type="AgentRoleType" defaultValue={'"worker"'}>
      Native runtime responsibility such as a worker or orchestrator. This field is available in memory, but the current native <code>to_dict()</code> and <code>from_dict()</code> paths do not serialize or restore it.
    </ApiField>
    <ApiField name="tags" type="list[str]" defaultValue="[]">
      Discovery labels such as <code>finance</code>, <code>travel</code>, or <code>math</code>. Tags are serialized verbatim and are suitable for registry-side filtering.
    </ApiField>
    <ApiField name="interfaces" type="list[AgentInterface | Mapping[str, Any]]" defaultValue="[]">
      Additional URLs and transports for the same identity. Mappings are normalized through <code>AgentInterface.from_dict()</code>. They serialize under <code>additionalInterfaces</code>, which is distinct from the A2A 1.0 adapter's canonical <code>supportedInterfaces</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="AgentCard attributes">
    <ApiField name="capabilities" type="AgentCapabilities">
      Always normalized to an <code>AgentCapabilities</code> instance after successful initialization.
    </ApiField>
    <ApiField name="interfaces" type="list[AgentInterface]">
      Always normalized to interface objects after successful initialization. Invalid members raise <code>TypeError</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Independent defaults">
  Lists, dictionaries, capabilities, and interfaces use dataclass default factories. Instances do not share their mutable default containers even though the concise signature displays familiar empty values.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import AgentCard, AgentInterface, AgentSkill
from protolink.core.agent_card import AgentCapabilities

card = AgentCard(
    name="weather_agent",
    description="Provides current conditions and short-range forecasts.",
    url="https://api.example.com/weather",
    version="1.2.0",
    input_formats=["text/plain", "application/json"],
    output_formats=["text/plain", "application/json", "text/markdown"],
    capabilities=AgentCapabilities(
        streaming=True,
        tool_calling=True,
        max_concurrency=5,
    ),
    skills=[
        AgentSkill(
            id="forecast",
            description="Forecast weather for a supplied location.",
        )
    ],
    interfaces=[
        AgentInterface(
            url="grpcs://api.example.com:9443",
            transport="grpc",
        )
    ],
)
```

</ApiSection>

</ApiReference>

#### AgentCard.to_dict

<ApiReference
  kind="method"
  path="protolink.AgentCard.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L185"
>

Serialize the card into ProtoLink's native discovery-card dictionary. Nested capabilities and skills become dictionaries, field names that belong to the wire contract use camel case, and additional interfaces are omitted when the list is empty.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentCard to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      A new outer dictionary containing <code>protocolVersion</code>, <code>inputFormats</code>, <code>outputFormats</code>, <code>securitySchemes</code>, and optionally <code>additionalInterfaces</code>. Capability and skill dataclasses are recursively converted with <code>dataclasses.asdict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Native card behavior">
  The current serializer does not include <code>role</code>. It also returns the original tags, format lists, and security mapping rather than deep-copying those containers. The A2A 1.0 adapter uses a separate canonical serializer.
</ApiCallout>

<ApiSection title="Examples">

```python
payload = card.to_dict()

print(payload["name"])                  # "weather_agent"
print(payload["protocolVersion"])       # installed ProtoLink version
print(payload["additionalInterfaces"])  # serialized alternate route
```

</ApiSection>

</ApiReference>

#### AgentCard.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.AgentCard.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> AgentCard`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L209"
>

Construct an `AgentCard` from the native discovery dictionary. This is the validated and normalizing path for data received from JSON, a registry, or another transport boundary.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentCard from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Native card mapping. <code>name</code>, <code>description</code>, and <code>url</code> must be present and truthy. Capabilities and skills are read from nested mappings; wire-facing names such as <code>protocolVersion</code> and <code>securitySchemes</code> are converted to Python attribute names.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentCard from_dict return value">
    <ApiField name="card" type="AgentCard">
      A new card with normalized <code>AgentCapabilities</code>, <code>AgentSkill</code>, and <code>AgentInterface</code> values.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="AgentCard from_dict errors">
    <ApiField name="ValueError">
      Raised when any mandatory identity field is absent or falsy, or when nested dataclass values cannot be constructed.
    </ApiField>
    <ApiField name="TypeError">
      Raised when nested values have incompatible shapes or interface members cannot be normalized.
    </ApiField>
    <ApiField name="KeyError">
      Raised by malformed interface mappings that do not contain their required <code>url</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Accepted interface keys">
  Additional interfaces are read from <code>interfaces</code> first and then <code>additionalInterfaces</code>. The former is accepted for compatibility; <code>to_dict()</code> emits the latter.
</ApiCallout>

<ApiSection title="Examples">

```python
data = {
    "name": "weather_agent",
    "description": "Weather service",
    "url": "https://api.example.com/weather",
    "capabilities": {"streaming": True},
    "additionalInterfaces": [
        {
            "url": "grpcs://api.example.com:9443",
            "transport": "grpc",
        }
    ],
}

card = AgentCard.from_dict(data)
```

</ApiSection>

</ApiReference>

#### AgentCard.get_prompt_format

<ApiReference
  kind="method"
  path="protolink.AgentCard.get_prompt_format"
  signature={`get_prompt_format() -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L260"
>

Generate a structured, human-readable description for an LLM system prompt. The output explains the agent's identity and, when skills are present, embeds each skill's name, description, schemas, and examples so another model can decide whether to delegate work.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentCard get_prompt_format return value">
    <ApiField name="prompt_text" type="str">
      A multi-line prompt fragment containing the card name and description plus a <code>tools</code> block for every advertised skill.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Prompt representation">
  This method is intended for model context, not machine parsing or wire serialization. Use <code>to_dict()</code> when stable field names and JSON-compatible structure matter.
</ApiCallout>

</ApiReference>

### AgentCapabilities

<ApiReference
  kind="dataclass"
  path="protolink.core.agent_card.AgentCapabilities"
  signature={`class AgentCapabilities(
    streaming: bool = False,
    push_notifications: bool = False,
    state_transition_history: bool = False,
    delegation: bool = True,
    has_llm: bool = False,
    max_concurrency: int = 1,
    message_batching: bool = False,
    tool_calling: bool = False,
    multi_step_reasoning: bool = False,
    timeout_support: bool = False,
    rag: bool = False,
    code_execution: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L15"
>

Coarse capability and capacity declaration carried by an `AgentCard`. These values help peers choose an interaction mode; they do not themselves enable streaming, tools, delegation, or execution infrastructure.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentCapabilities constructor parameters">
    <ApiField name="streaming" type="bool" defaultValue="False">
      Advertises that the agent can produce task events through a streaming-capable transport. The selected transport must also support streaming.
    </ApiField>
    <ApiField name="push_notifications" type="bool" defaultValue="False">
      Advertises webhook or other push delivery for task updates. The flag is descriptive and does not configure a callback endpoint.
    </ApiField>
    <ApiField name="state_transition_history" type="bool" defaultValue="False">
      Indicates that detailed task lifecycle transitions can be provided to clients.
    </ApiField>
    <ApiField name="delegation" type="bool" defaultValue="True">
      Indicates that the agent may delegate work to other agents. It defaults to enabled in ProtoLink's native runtime profile.
    </ApiField>
    <ApiField name="has_llm" type="bool" defaultValue="False">
      Declares that an LLM is part of the agent's processing path. This does not expose the provider or model identifier.
    </ApiField>
    <ApiField name="max_concurrency" type="int" defaultValue="1">
      Advertised maximum simultaneous task capacity. No positivity validator runs in this dataclass; runtime schedulers decide how to enforce the declared value.
    </ApiField>
    <ApiField name="message_batching" type="bool" defaultValue="False">
      Indicates support for processing multiple messages as one request.
    </ApiField>
    <ApiField name="tool_calling" type="bool" defaultValue="False">
      Indicates that the agent can invoke registered tools or external APIs.
    </ApiField>
    <ApiField name="multi_step_reasoning" type="bool" defaultValue="False">
      Advertises a multi-step reasoning or planning path.
    </ApiField>
    <ApiField name="timeout_support" type="bool" defaultValue="False">
      Indicates that task or operation timeouts are understood by the agent.
    </ApiField>
    <ApiField name="rag" type="bool" defaultValue="False">
      Advertises retrieval-augmented generation support.
    </ApiField>
    <ApiField name="code_execution" type="bool" defaultValue="False">
      Advertises access to a code-execution facility. This flag is not a security boundary; the actual sandbox and policy must be configured separately.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Import path">
  <code>AgentCapabilities</code> is used by the public <code>AgentCard</code>, but it is not currently re-exported from <code>protolink</code> or <code>protolink.models</code>. Import it from <code>protolink.core.agent_card</code>.
</ApiCallout>

</ApiReference>

#### AgentCapabilities.as_dict

<ApiReference
  kind="method"
  path="protolink.core.agent_card.AgentCapabilities.as_dict"
  signature={`as_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L47"
>

Convert every capability field into a plain dictionary using `dataclasses.asdict()`.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentCapabilities as_dict return value">
    <ApiField name="capabilities" type="dict[str, Any]">
      A new flat dictionary containing enabled and disabled booleans plus <code>max_concurrency</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### AgentCapabilities.enabled

<ApiReference
  kind="method"
  path="protolink.core.agent_card.AgentCapabilities.enabled"
  signature={`enabled() -> list[str]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L51"
>

Produce a compact display list of truthy boolean capabilities and positive integer capacities.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentCapabilities enabled return value">
    <ApiField name="names" type="list[str]">
      Boolean fields appear by name. Positive integer fields appear as <code>"field: value"</code>; consequently the default profile includes <code>delegation</code> and <code>max_concurrency: 1</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
from protolink.core.agent_card import AgentCapabilities

capabilities = AgentCapabilities(streaming=True, max_concurrency=5)

print(capabilities.enabled())
# ["streaming", "delegation", "max_concurrency: 5"]
```

</ApiSection>

</ApiReference>

### AgentSkill

<ApiReference
  kind="dataclass"
  path="protolink.AgentSkill"
  signature={`class AgentSkill(
    id: str,
    description: str = "",
    input_schema: dict[str, Any] = {},
    output_schema: dict[str, Any] = {},
    tags: list[str] = [],
    examples: list[Any] = [],
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L63"
>

Task-level capability advertised by an agent. A skill combines a stable identifier with enough schema and example information for humans, registries, and delegating models to understand how to call it.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentSkill constructor parameters">
    <ApiField name="id" type="str" required>
      Human-readable operation identifier such as <code>weather_forecast</code>. The dataclass does not enforce uniqueness; cards and registries are responsible for avoiding ambiguous identifiers.
    </ApiField>
    <ApiField name="description" type="str" defaultValue={'""'}>
      Detailed explanation of what the skill does, when to use it, and any important boundaries. It is included in delegation prompt material.
    </ApiField>
    <ApiField name="input_schema" type="dict[str, Any]" defaultValue="{}">
      JSON Schema describing the accepted input payload. ProtoLink stores the mapping but does not validate that it is a complete or valid JSON Schema at construction time.
    </ApiField>
    <ApiField name="output_schema" type="dict[str, Any]" defaultValue="{}">
      JSON Schema describing the successful result payload.
    </ApiField>
    <ApiField name="tags" type="list[str]" defaultValue="[]">
      Search and categorization labels scoped to this skill.
    </ApiField>
    <ApiField name="examples" type="list[Any]" defaultValue="[]">
      Representative inputs, outputs, or usage scenarios. Values may be strings or structured JSON-compatible objects.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="None normalization">
  If <code>tags</code>, <code>examples</code>, <code>input_schema</code>, or <code>output_schema</code> is explicitly passed as <code>None</code>, <code>__post_init__</code> replaces it with a fresh empty list or dictionary. The identifier and description are not otherwise validated.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import AgentSkill

skill = AgentSkill(
    id="weather_forecast",
    description="Return a forecast for a named location.",
    input_schema={
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "additionalProperties": True,
    },
    tags=["weather", "forecast", "location"],
    examples=[
        {"location": "New York"},
        {"location": "London"},
    ],
)
```

</ApiSection>

</ApiReference>

### AgentInterface

<ApiReference
  kind="frozen dataclass"
  path="protolink.AgentInterface"
  signature={`class AgentInterface(
    url: str,
    transport: TransportType,
    protocol_version: str = protolink_version,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L95"
>

Additional endpoint exposed by the same logical agent. The primary route remains `AgentCard.url` plus `AgentCard.transport`; use an interface only when one agent is genuinely reachable over another URL, transport, or protocol version.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentInterface constructor parameters">
    <ApiField name="url" type="str" required>
      Absolute endpoint for the alternate interface. Syntax is preserved as supplied.
    </ApiField>
    <ApiField name="transport" type="TransportType" required>
      Registered transport name for this endpoint. Unlike <code>from_dict()</code>, direct construction requires the argument explicitly.
    </ApiField>
    <ApiField name="protocol_version" type="str" defaultValue="protolink_version">
      Protocol version served specifically by this endpoint.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Immutable value">
  The dataclass is frozen and slot-backed. Assigning to an interface field after construction raises <code>dataclasses.FrozenInstanceError</code>.
</ApiCallout>

</ApiReference>

#### AgentInterface.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.AgentInterface.from_dict"
  signature={`from_dict(
    data: Mapping[str, Any],
) -> AgentInterface`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L112"
>

Normalize an alternate-interface mapping from the native card wire format.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="AgentInterface from_dict parameters">
    <ApiField name="data" type="Mapping[str, Any]" required>
      Mapping containing <code>url</code> and optionally <code>transport</code> and <code>protocolVersion</code>. The URL and protocol version are converted with <code>str()</code>; transport is preserved.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentInterface from_dict return value">
    <ApiField name="interface" type="AgentInterface">
      A new immutable interface. Missing transport defaults to <code>http</code>; missing protocol version defaults to the installed ProtoLink version.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="AgentInterface from_dict errors">
    <ApiField name="KeyError">
      Raised when the required <code>url</code> key is absent.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### AgentInterface.to_dict

<ApiReference
  kind="method"
  path="protolink.AgentInterface.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/agent_card.py#L121"
>

Serialize the interface using the field names expected inside `AgentCard.additionalInterfaces`.

<ApiSection title="Returns">
  <ApiFields ariaLabel="AgentInterface to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing <code>url</code>, <code>transport</code>, and camel-cased <code>protocolVersion</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Type aliases used by AgentCard

#### MimeType

`MimeType` enumerates the media types used by `input_formats` and `output_formats`. The annotation helps static checking and documentation; values are not runtime-validated by `AgentCard`.

| Category | MIME types |
|----------|------------|
| **Text** | `text/plain`, `text/markdown`, `text/html` |
| **Structured data** | `application/json` |
| **Images** | `image/png`, `image/jpeg`, `image/webp` |
| **Audio** | `audio/wav`, `audio/mpeg`, `audio/ogg` |
| **Video** | `video/mp4`, `video/webm` |
| **Documents** | `application/pdf` |

#### SecuritySchemeType

`SecuritySchemeType` enumerates the supported top-level security scheme categories. The nested configuration remains an application-supplied mapping.

| Category | Security schemes |
|----------|------------------|
| **API key** | `apiKey` |
| **HTTP** (bearer/basic/digest) | `http` |
| **OAuth 2.0** | `oauth2` |
| **Certificates** | `mutualTLS` |
| **OIDC auto-discovery** | `openIdConnect` |

---

## Tasks and lifecycle

A `Task` is the durable unit of work exchanged between agents. Messages record the conversation and control inputs, artifacts record produced outputs, and `TaskState` enforces how the work moves from submission to a terminal result.

### Task

<ApiReference
  kind="dataclass"
  path="protolink.Task"
  signature={`class Task(
    id: str = generate_task_id(),
    state: TaskState = TaskState.SUBMITTED,
    messages: list[Message] = [],
    artifacts: list[Artifact] = [],
    metadata: dict[str, Any] = {},
    flow_state: dict[str, Any] = {},
    created_at: str = utc_now(),
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L63"
>

State container for one agentic work unit. The model combines lifecycle state, chronological communication, produced artifacts, extensible metadata, and flow-local state. It also caches the most recently added message or artifact for constant-time access.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task constructor parameters">
    <ApiField name="id" type="str" defaultValue="generate_task_id()">
      Unique task identifier. The default generator produces a <code>task_</code>-prefixed timestamp and random suffix. Supply an existing identifier when rehydrating or correlating work across systems.
    </ApiField>
    <ApiField name="state" type="TaskState | str" defaultValue="TaskState.SUBMITTED">
      Current lifecycle state. During <code>__post_init__</code>, strings are converted with <code>TaskState(value)</code>, so only exact enum values such as <code>working</code> or <code>input-required</code> succeed.
    </ApiField>
    <ApiField name="messages" type="list[Message]" defaultValue="[]">
      Ordered communication and control messages associated with the task. The constructor stores the supplied list and builds the last-item cache from its final element.
    </ApiField>
    <ApiField name="artifacts" type="list[Artifact]" defaultValue="[]">
      Ordered outputs, previews, diagnostics, and resources produced during the run.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Extensible task metadata. Lifecycle helpers add <code>state_history</code>, <code>error</code>, or <code>cancel_reason</code> entries here.
    </ApiField>
    <ApiField name="flow_state" type="dict[str, Any]" defaultValue="{}">
      Flow and orchestration context carried with the task independently from general metadata.
    </ApiField>
    <ApiField name="created_at" type="str" defaultValue="utc_now()">
      ISO 8601 UTC timestamp captured at construction time.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="Task attributes">
    <ApiField name="is_terminal" type="bool">
      Read-only property that is true for <code>COMPLETED</code>, <code>CANCELED</code>, and <code>FAILED</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Last-item cache">
  Use <code>add_message()</code> and <code>add_artifact()</code> after construction. Mutating <code>messages</code> or <code>artifacts</code> directly does not refresh the private cache used by <code>get_last_item()</code> and <code>get_last_part_content()</code>.
</ApiCallout>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task constructor errors">
    <ApiField name="ValueError">
      Raised when a string state is not one of the exact <code>TaskState</code> values.
    </ApiField>
    <ApiField name="TypeError">
      Raised when <code>state</code> is neither a <code>TaskState</code> nor a string.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Task lifecycle

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

`completed`, `failed`, and `canceled` are terminal states. Once a task reaches one of them, it cannot transition further. `UNKNOWN` is primarily a compatibility state; the current transition graph permits it to move to any enum value.

Every successful state change is recorded in `task.metadata["state_history"]` when that key is a list:

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

:::tip[Performance]

`add_message()`, `add_artifact()`, `update_state()`, and cached last-item lookup are constant-time operations. Serialization remains proportional to the number of nested messages and artifacts.

:::

#### Task.add_message {#task-add-message}

<ApiReference
  kind="method"
  path="protolink.Task.add_message"
  signature={`add_message(
    message: Message,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L132"
>

Append a message to the task and make it the cached most recent item.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task add_message parameters">
    <ApiField name="message" type="Message" required>
      Communication or control message to append. The method does not perform an <code>isinstance</code> check, so callers should supply a real <code>Message</code> to preserve serialization and helper behavior.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task add_message return value">
    <ApiField name="self" type="Task">
      The same task instance, allowing fluent construction.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Side effect">
  Mutates <code>messages</code> and replaces the cached last item, but does not change task state or timestamps.
</ApiCallout>

<ApiSection title="Examples">

```python
task.add_message(Message.user("What's the weather?"))
task.add_message(Message.agent("It's sunny."))
```

</ApiSection>

</ApiReference>

#### Task.add_artifact {#task-add-artifact}

<ApiReference
  kind="method"
  path="protolink.Task.add_artifact"
  signature={`add_artifact(
    artifact: Artifact,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L141"
>

Append a durable output artifact and make it the cached most recent item.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task add_artifact parameters">
    <ApiField name="artifact" type="Artifact" required>
      Result, preview, diagnostic, or resource produced by the task.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task add_artifact return value">
    <ApiField name="self" type="Task">
      The mutated task for chaining.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Side effect">
  Mutates <code>artifacts</code> and the last-item cache. It does not automatically complete the task.
</ApiCallout>

<ApiSection title="Examples">

```python
artifact = Artifact().add_text("Weather analysis complete")
task.add_artifact(artifact)
```

</ApiSection>

</ApiReference>

#### Task.update_state {#task-update-state}

<ApiReference
  kind="method"
  path="protolink.Task.update_state"
  signature={`update_state(
    state: TaskState | str,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L150"
>

Move the task through the enforced lifecycle graph. Repeating the current state is a no-op; a successful change is recorded in `metadata["state_history"]`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task update_state parameters">
    <ApiField name="state" type="TaskState | str" required>
      Destination state as an enum or exact serialized value. The method validates the transition from the task's current state before mutating it.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task update_state return value">
    <ApiField name="self" type="Task">
      The same task after a valid transition or repeated-state no-op.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task update_state errors">
    <ApiField name="ValueError">
      Raised for an unknown string value or a transition not present in the lifecycle graph. State and history remain unchanged when the graph check fails.
    </ApiField>
    <ApiField name="TypeError">
      Raised when the destination is neither an enum nor a string.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="History behavior">
  If <code>metadata["state_history"]</code> already exists but is not a list, the state still changes and the transition record is silently skipped.
</ApiCallout>

<ApiSection title="Examples">

```python
task.update_state(TaskState.WORKING)
task.update_state(TaskState.COMPLETED)

task = Task.create(Message.user("hello"))
task.update_state(TaskState.COMPLETED)
# ValueError: Invalid task state transition: submitted -> completed
```

</ApiSection>

</ApiReference>

#### Task.begin {#task-begin}

<ApiReference
  kind="method"
  path="protolink.Task.begin"
  signature={`begin() -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L172"
>

Mark the task as actively being processed. This is exactly `update_state(TaskState.WORKING)` and therefore follows the same transition rules and history behavior.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task begin return value">
    <ApiField name="self" type="Task">
      The task in <code>WORKING</code> state.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task begin errors">
    <ApiField name="ValueError">
      Raised when the current state cannot transition to <code>WORKING</code>, including terminal states.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Task.require_input {#task-require-input}

<ApiReference
  kind="method"
  path="protolink.Task.require_input"
  signature={`require_input(
    message: Message | None = None,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L176"
>

Move the task to `INPUT_REQUIRED` and optionally append a message explaining what information is missing. A submitted task first moves through `WORKING`, which preserves a valid and observable lifecycle.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task require_input parameters">
    <ApiField name="message" type="Message | None" defaultValue="None">
      Optional prompt or status message appended after the state reaches <code>INPUT_REQUIRED</code>. Falsy values are ignored.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task require_input return value">
    <ApiField name="self" type="Task">
      The task in <code>INPUT_REQUIRED</code> state.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task require_input errors">
    <ApiField name="ValueError">
      Raised when the current lifecycle state cannot reach <code>WORKING</code> or <code>INPUT_REQUIRED</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Repeated requests">
  Calling this method while already in <code>INPUT_REQUIRED</code> records two new transitions: back to <code>WORKING</code>, then to <code>INPUT_REQUIRED</code>.
</ApiCallout>

</ApiReference>

#### Task.complete {#task-complete}

<ApiReference
  kind="method"
  path="protolink.Task.complete"
  signature={`complete(
    response_text: str,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L189"
>

Finish the task successfully and append the final text as an agent message. Submitted or input-required tasks first move through `WORKING`, so the convenience method can be used without manually creating the intermediate state.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task complete parameters">
    <ApiField name="response_text" type="str" required>
      Final response content. It is wrapped with <code>Message.agent()</code> after the state becomes <code>COMPLETED</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task complete return value">
    <ApiField name="self" type="Task">
      The completed task with the response message as its cached last item.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task complete errors">
    <ApiField name="ValueError">
      Raised when the current state cannot transition through <code>WORKING</code> to <code>COMPLETED</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
task.complete("The weather is sunny and 24°C.")

print(task.state)  # TaskState.COMPLETED
print(task.get_last_part_content())  # "The weather is sunny and 24°C."
```

</ApiSection>

</ApiReference>

#### Task.fail {#task-fail}

<ApiReference
  kind="method"
  path="protolink.Task.fail"
  signature={`fail(
    error_message: str,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L204"
>

Move the task to `FAILED` and store a human-readable error in task metadata.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task fail parameters">
    <ApiField name="error_message" type="str" required>
      Failure explanation stored at <code>metadata["error"]</code>. The method does not append an error part or response message.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task fail return value">
    <ApiField name="self" type="Task">
      The failed task.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task fail errors">
    <ApiField name="ValueError">
      Raised if the current state cannot transition to <code>FAILED</code>. The error metadata is written only after a successful transition.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Task.cancel {#task-cancel}

<ApiReference
  kind="method"
  path="protolink.Task.cancel"
  signature={`cancel(
    reason: str | None = None,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L213"
>

Move the task model to `CANCELED` and optionally retain a reason. This updates lifecycle data only; it does not interrupt an operation that is currently executing.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task cancel parameters">
    <ApiField name="reason" type="str | None" defaultValue="None">
      Optional explanation stored at <code>metadata["cancel_reason"]</code>. Empty strings are treated as absent and are not stored.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task cancel return value">
    <ApiField name="self" type="Task">
      The canceled task.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task cancel errors">
    <ApiField name="ValueError">
      Raised when the current state cannot transition to <code>CANCELED</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Running work">
  To interrupt active execution, use <code>await agent.cancel_task(task.id, reason=...)</code> or <code>await client.cancel_task(agent_url, task.id, reason=...)</code>. See [runtime cancellation](runtime.md#canceling-running-tasks).
</ApiCallout>

</ApiReference>

#### Task.to_dict {#task-to-dict}

<ApiReference
  kind="method"
  path="protolink.Task.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L220"
>

Serialize a task and all nested messages and artifacts into the native transport shape.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      New outer dictionary containing the string state value, serialized nested objects, metadata, flow state, identifier, and creation timestamp.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Copy semantics">
  Nested messages and artifacts are converted recursively. The task's <code>metadata</code> and <code>flow_state</code> mappings are attached directly rather than deep-copied.
</ApiCallout>

</ApiReference>

#### Task.from_dict {#task-from-dict}

<ApiReference
  kind="classmethod"
  path="protolink.Task.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L235"
>

Rehydrate a task from native serialized data, including nested `Message`, `Part`, and `Artifact` instances. Construction also rebuilds the cached last item by comparing the final message and artifact timestamps.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Task mapping. Missing fields receive constructor defaults; nested message and artifact lists are normalized by their respective <code>from_dict()</code> methods.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task from_dict return value">
    <ApiField name="task" type="Task">
      A new task with enum state, hydrated nested content, and a reconstructed last-item cache.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Task from_dict errors">
    <ApiField name="ValueError">
      Raised when the serialized state is not a valid <code>TaskState</code> value or nested data fails value conversion.
    </ApiField>
    <ApiField name="KeyError or TypeError">
      Propagated from malformed nested part, message, or artifact payloads.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
task = Task.from_dict(
    {
        "state": "working",
        "messages": [],
        "artifacts": [],
    }
)

print(task.state)  # TaskState.WORKING
```

</ApiSection>

</ApiReference>

#### Task.create {#task-create}

<ApiReference
  kind="classmethod"
  path="protolink.Task.create"
  signature={`create(
    message: Message,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L256"
>

Create a submitted task with one initial message and initialize the last-item cache without a second scan.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task create parameters">
    <ApiField name="message" type="Message" required>
      Initial user, agent, infer, tool-call, or other message.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task create return value">
    <ApiField name="task" type="Task">
      New <code>SUBMITTED</code> task whose <code>messages</code> contains exactly the supplied message.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
task = Task.create(Message.user("Analyze this data"))

print(len(task.messages))  # 1
print(task.state)          # TaskState.SUBMITTED
```

</ApiSection>

</ApiReference>

#### Task.create_infer {#task-create-infer}

<ApiReference
  kind="classmethod"
  path="protolink.Task.create_infer"
  signature={`create_infer(
    *,
    prompt: str | None = None,
    user: str | None = None,
    output_schema: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L266"
>

Create a submitted task containing one user-role message with an `infer` part. Agents interpret that part as a request to invoke their configured LLM.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task create_infer parameters">
    <ApiField name="prompt" type="str | None" defaultValue="None">
      Main inference instruction. Omitted values are removed from the part payload rather than serialized as <code>null</code>.
    </ApiField>
    <ApiField name="user" type="str | None" defaultValue="None">
      Optional user identity or user-specific context passed inside the infer payload. It does not change the enclosing message role.
    </ApiField>
    <ApiField name="output_schema" type="dict[str, Any] | None" defaultValue="None">
      Optional structured-output schema that the receiving agent may use when configuring inference.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Additional infer-operation metadata stored inside the part, separate from <code>Task.metadata</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task create_infer return value">
    <ApiField name="task" type="Task">
      A new submitted task initialized through <code>Message.infer()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Empty payload">
  All arguments are optional. Calling <code>Task.create_infer()</code> with no values still creates a valid <code>infer</code> part whose content is an empty dictionary.
</ApiCallout>

<ApiSection title="Examples">

```python
task = Task.create_infer(
    prompt="Extract the invoice total.",
    output_schema={
        "type": "object",
        "properties": {"total": {"type": "number"}},
        "required": ["total"],
    },
)
```

</ApiSection>

</ApiReference>

#### Task.create_tool_call

<ApiReference
  kind="classmethod"
  path="protolink.Task.create_tool_call"
  signature={`create_tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    call_id: str | None = None,
) -> Task`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L288"
>

Create a submitted task containing one user-role `tool_call` message. This is the direct task-level entry point for asking an agent to execute a registered tool without first asking its LLM to select one.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task create_tool_call parameters">
    <ApiField name="tool_name" type="str" required>
      Registered tool or capability name to invoke. Resolution happens when the receiving agent executes the task.
    </ApiField>
    <ApiField name="args" type="dict[str, Any] | None" defaultValue="None">
      Keyword arguments for the tool. <code>None</code> and an empty dictionary both become a new empty argument mapping.
    </ApiField>
    <ApiField name="call_id" type="str | None" defaultValue="None">
      Optional correlation identifier. If omitted, <code>Part.tool_call()</code> generates a <code>tool_call_</code>-prefixed identifier.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task create_tool_call return value">
    <ApiField name="task" type="Task">
      New submitted task containing the generated tool-call message.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
task = Task.create_tool_call(
    tool_name="get_weather",
    args={"location": "Athens"},
)
```

</ApiSection>

</ApiReference>

#### Task.get_last_item

<ApiReference
  kind="method"
  path="protolink.Task.get_last_item"
  signature={`get_last_item() -> Message | Artifact | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L308"
>

Return the message or artifact most recently cached by task construction, deserialization, `add_message()`, or `add_artifact()`.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task get_last_item return value">
    <ApiField name="item" type="Message | Artifact | None">
      Cached object, or <code>None</code> when the task has no messages or artifacts. For a task initialized with both lists, their final items are compared by timestamp.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Complexity">
  Lookup is O(1). The method does not rescan the lists, which is why direct list mutation can leave the result stale.
</ApiCallout>

</ApiReference>

#### Task.tool_call

<ApiReference
  kind="staticmethod"
  path="protolink.Task.tool_call"
  signature={`tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    call_id: str | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L316"
>

Create a standalone `tool_call` part. This is a convenience alias for `Part.tool_call()`; it does not create or mutate a task.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task tool_call parameters">
    <ApiField name="tool_name" type="str" required>
      Tool or capability identifier.
    </ApiField>
    <ApiField name="args" type="dict[str, Any] | None" defaultValue="None">
      Tool arguments; falsy values become an empty dictionary.
    </ApiField>
    <ApiField name="call_id" type="str | None" defaultValue="None">
      Optional correlation identifier, otherwise generated automatically.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task tool_call return value">
    <ApiField name="part" type="Part">
      Typed tool-call part suitable for a message or task.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Task.infer

<ApiReference
  kind="staticmethod"
  path="protolink.Task.infer"
  signature={`infer(
    *,
    prompt: str | None = None,
    user: str | None = None,
    output_schema: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Part`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L334"
>

Create a standalone `infer` part without constructing a message or task. This delegates directly to `Part.infer()`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Task infer parameters">
    <ApiField name="prompt" type="str | None" defaultValue="None">
      Model instruction included only when non-<code>None</code>.
    </ApiField>
    <ApiField name="user" type="str | None" defaultValue="None">
      Optional user context included only when non-<code>None</code>.
    </ApiField>
    <ApiField name="output_schema" type="dict[str, Any] | None" defaultValue="None">
      Optional structured-output schema.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional infer-operation metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task infer return value">
    <ApiField name="part" type="Part">
      Part with type <code>infer</code> and a dictionary containing only supplied values.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### Task.get_last_part_content

<ApiReference
  kind="method"
  path="protolink.Task.get_last_part_content"
  signature={`get_last_part_content() -> Any | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L359"
>

Read the content of the final part on the cached most recent message or artifact. This is the concise result accessor used throughout examples and transport conformance tests.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Task get_last_part_content return value">
    <ApiField name="content" type="Any | None">
      The final part's content, or <code>None</code> when there is no cached item or that item has no parts. Typed content such as <code>ToolOutput</code> is returned as the object, not automatically unwrapped to its result.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

<ApiSection title="Task example">

```python
from protolink import Message, Task

task = Task.create(Message.user("What's the weather in New York?"))

task.begin()
task.complete("It's 22°C and sunny in New York.")

print(task.is_terminal)             # True
print(task.get_last_part_content()) # "It's 22°C and sunny in New York."
```

</ApiSection>

### TaskState

<ApiReference
  kind="enum"
  path="protolink.TaskState"
  signature={`class TaskState(Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/core/task.py#L12"
>

Enumeration of task lifecycle states. In-memory tasks hold enum members; `Task.to_dict()` serializes their string values.

<ApiSection title="Values">

| Value | Meaning |
|-------|---------|
| `SUBMITTED` | Task has been accepted but processing has not started. |
| `WORKING` | Agent is actively processing the task. |
| `INPUT_REQUIRED` | Agent cannot continue without additional input. |
| `COMPLETED` | Task finished successfully. |
| `CANCELED` | Task was canceled before successful completion. |
| `FAILED` | Task ended because of an error. |
| `UNKNOWN` | Compatibility state used when lifecycle status is not known. |

</ApiSection>

<ApiCallout label="Terminal states">
  <code>COMPLETED</code>, <code>CANCELED</code>, and <code>FAILED</code> intentionally have no outgoing transitions.
</ApiCallout>

</ApiReference>

---

## Server endpoints

ProtoLink servers declare behavior through transport-neutral endpoint specifications. HTTP, WebSocket, gRPC, runtime-memory, and backend adapters consume the same declaration and decide how to bind a path, parse input, invoke the handler, and serialize its result.

### EndpointSpec

<ApiReference
  kind="frozen dataclass"
  path="protolink.models.EndpointSpec"
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

Transport-agnostic declaration of one server endpoint. Server implementations assemble these values; transport backends use them to register routes and adapt raw requests without coupling agent or registry logic to FastAPI, Starlette, WebSocket, gRPC, or runtime-memory APIs.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="EndpointSpec constructor parameters">
    <ApiField name="name" type="str" required>
      Unique internal endpoint name used by transport routing tables and diagnostics. The dataclass does not enforce uniqueness; the server or backend that registers the collection is responsible for collisions.
    </ApiField>
    <ApiField name="path" type="str" required>
      Route path such as <code>/tasks/</code>. The transport backend interprets path syntax and route parameters.
    </ApiField>
    <ApiField name="method" type="HttpMethod" required>
      HTTP-style method: <code>GET</code>, <code>POST</code>, <code>DELETE</code>, <code>PUT</code>, or <code>PATCH</code>. Non-HTTP transports use the value as part of the common routing contract.
    </ApiField>
    <ApiField name="handler" type="Callable[..., Any]" required>
      Sync function, async function, or streaming callable invoked by the transport. Its expected argument depends on <code>request_source</code> and the optional parser; its return value is normalized by the selected backend.
    </ApiField>
    <ApiField name="content_type" type={'"json" | "html"'} defaultValue={'"json"'}>
      Response rendering mode. HTTP backends return an HTML response only for <code>html</code>; otherwise they use their JSON normalization path.
    </ApiField>
    <ApiField name="streaming" type="bool" defaultValue="False">
      Compatibility flag indicating that the handler returns an async stream of events.
    </ApiField>
    <ApiField name="mode" type={'"request_response" | "stream"'} defaultValue={'"request_response"'}>
      Explicit interaction mode. Current transports generally treat <code>mode="stream"</code> or <code>streaming=True</code> as a streaming declaration.
    </ApiField>
    <ApiField name="request_parser" type="Callable[[Any], Any] | None" defaultValue="None">
      Optional normalizer or validator applied to the selected raw request value before handler invocation. Parser exceptions propagate through the backend's normal error path.
    </ApiField>
    <ApiField name="request_source" type="RequestSourceType" defaultValue={'"none"'}>
      Selects the handler input: <code>none</code>, <code>body</code>, <code>query_params</code>, <code>form</code>, <code>headers</code>, <code>path_params</code>, or a transport-neutral <code>request</code> view.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Declaration, not validation">
  The frozen dataclass stores the values but does not verify path syntax, method literals, handler callability, or consistency between <code>streaming</code> and <code>mode</code>. Registration and request handling expose incompatible declarations.
</ApiCallout>

<ApiCallout label="Immutable specification">
  Endpoint specifications are frozen after construction. Create a replacement value when route behavior changes instead of mutating one registered with a transport.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink.models import EndpointSpec

async def create_task(task):
    return await agent.execute_task(task)

endpoint = EndpointSpec(
    name="create_task",
    path="/tasks/",
    method="POST",
    handler=create_task,
    request_source="body",
)
```

For a stream, declare the interaction explicitly:

```python
stream_endpoint = EndpointSpec(
    name="stream_task",
    path="/tasks/stream",
    method="POST",
    handler=agent.run_task_streaming,
    request_source="body",
    streaming=True,
    mode="stream",
)
```

</ApiSection>

</ApiReference>

---

## LLM context models

Agent protocol messages and LLM context have different jobs. `Message` and `Part` represent task-level communication; `LLMMessage` and `ConversationHistory` represent the compact, provider-neutral sequence translated into OpenAI, Anthropic, Gemini, local-server, or other model requests.

History compaction is a control-plane operation. `HistoryCompactionRequest` carries the requested strategy across direct Agent and client/server APIs, while `HistoryCompactionResult` reports exactly what changed.

### LLMMessage

<ApiReference
  kind="slot dataclass"
  path="protolink.llms.history.LLMMessage"
  signature={`class LLMMessage(
    role: LLMMessageRole,
    content: str,
    name: str | None = None,
    metadata: dict[str, Any] = {},
    id: str = uuid4(),
    created_at: datetime = datetime.now(timezone.utc),
    tool_calls: dict[str, Any] = {},
    tool_name: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L20"
>

Canonical context entry used internally across all LLM providers. It keeps the provider-neutral role and text content alongside tracing metadata and optional provider-specific tool-call information.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLMMessage constructor parameters">
    <ApiField name="role" type="LLMMessageRole" required>
      One of <code>SYSTEM</code>, <code>USER</code>, <code>ASSISTANT</code>, or <code>TOOL</code>. Direct construction expects an enum because <code>to_dict()</code> accesses <code>role.value</code>; use <code>from_dict()</code> to coerce serialized strings.
    </ApiField>
    <ApiField name="content" type="str" required>
      Provider-neutral textual content. Tool-call metadata may be stored separately, but content is still required by the dataclass.
    </ApiField>
    <ApiField name="name" type="str | None" defaultValue="None">
      Optional function or tool name exposed by simplified provider message conversion.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Framework or application metadata retained by full-history serialization. It is not included in the simplified <code>ConversationHistory.messages</code> provider view.
    </ApiField>
    <ApiField name="id" type="str" defaultValue="uuid4()">
      UUID string used for tracing and persistence.
    </ApiField>
    <ApiField name="created_at" type="datetime" defaultValue="datetime.now(timezone.utc)">
      Timezone-aware UTC creation time. Full serialization converts it to ISO 8601.
    </ApiField>
    <ApiField name="tool_calls" type="dict[str, Any]" defaultValue="{}">
      Provider-specific tool-call payload retained for adapters and complete persistence.
    </ApiField>
    <ApiField name="tool_name" type="str | None" defaultValue="None">
      Additional provider-specific tool name field. This is distinct from <code>name</code> and is preserved only by full serialization.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Import path">
  <code>LLMMessage</code> and <code>LLMMessageRole</code> are lower-level LLM context types, not top-level ProtoLink exports. Import them from <code>protolink.llms.history</code>.
</ApiCallout>

</ApiReference>

#### LLMMessage.to_dict

<ApiReference
  kind="method"
  path="protolink.llms.history.LLMMessage.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L40"
>

Serialize every canonical message field for persistence, compaction, copying, or telemetry.

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLMMessage to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing the string role, content, names, metadata, identifier, ISO timestamp, and tool-call payload.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Shallow containers">
  The outer dictionary is new, but <code>metadata</code> and <code>tool_calls</code> are returned by reference rather than deep-copied.
</ApiCallout>

</ApiReference>

#### LLMMessage.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.llms.history.LLMMessage.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> LLMMessage`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L53"
>

Rehydrate a full serialized context message. This is the canonical path used by history copy, replacement, and persistence.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LLMMessage from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Mapping with required <code>role</code> and <code>content</code>. Optional metadata, tracing, and tool fields receive constructor defaults.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LLMMessage from_dict return value">
    <ApiField name="message" type="LLMMessage">
      New slot-backed message with an enum role and a parsed <code>datetime</code> when <code>created_at</code> is present.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LLMMessage from_dict errors">
    <ApiField name="KeyError">
      Raised when <code>role</code> or <code>content</code> is absent.
    </ApiField>
    <ApiField name="ValueError">
      Raised for an unknown role value or invalid ISO timestamp.
    </ApiField>
    <ApiField name="TypeError">
      Raised when a present timestamp has a value that <code>datetime.fromisoformat()</code> cannot consume.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### ConversationHistory

<ApiReference
  kind="class"
  path="protolink.llms.history.ConversationHistory"
  signature={`class ConversationHistory(
    system_prompt: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L70"
>

Provider-agnostic conversation container backed by `collections.deque`. It provides fast appends and system-message prepends while keeping a complete serialization format for state persistence and a simplified format for model adapters.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory constructor parameters">
    <ApiField name="system_prompt" type="str | None" defaultValue="None">
      Optional first system instruction. A message is created only when the value is truthy, so <code>None</code> and an empty string both produce an initially empty history.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes and protocols">
  <ApiFields ariaLabel="ConversationHistory attributes">
    <ApiField name="messages" type="list[dict[str, Any]]">
      Read-only property returning a newly built simplified list with role, content, and optional name. It deliberately omits metadata, IDs, timestamps, tool calls, and <code>tool_name</code>.
    </ApiField>
    <ApiField name="len(history)" type="int">
      Number of canonical messages currently stored.
    </ApiField>
    <ApiField name="iter(history)" type="Iterable[LLMMessage]">
      Iterates the live deque in chronological order.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Import path">
  Import this lower-level model from <code>protolink.llms.history</code>. Most direct users encounter it through <code>llm.history</code> or <code>llm.use_history()</code>.
</ApiCallout>

<ApiCallout label="Two serialization views">
  Use <code>history.messages</code> for simple provider input and <code>history.to_list()</code> for persistence, copying, or compaction. The latter preserves every <code>LLMMessage</code> field.
</ApiCallout>

</ApiReference>

#### ConversationHistory.add_system

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.add_system"
  signature={`add_system(
    content: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L103"
>

Append a system-role message to the end of history.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory add_system parameters">
    <ApiField name="content" type="str" required>
      System instruction stored in a newly generated <code>LLMMessage</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Append semantics">
  This method does not enforce that a system message is first or unique. Use <code>set_system()</code> to create or replace the leading system instruction, or <code>reset_to_system()</code> to discard all other history.
</ApiCallout>

</ApiReference>

#### ConversationHistory.add_user

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.add_user"
  signature={`add_user(
    content: str,
    **metadata: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L115"
>

Append a user-role context message.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory add_user parameters">
    <ApiField name="content" type="str" required>
      User text sent to provider adapters.
    </ApiField>
    <ApiField name="**metadata" type="Any">
      Keyword metadata retained in full history. Passing <code>{'metadata={"key": "value"}'}</code> creates a nested key named <code>metadata</code>; pass <code>key="value"</code> when a flat metadata entry is intended.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### ConversationHistory.add_assistant

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.add_assistant"
  signature={`add_assistant(
    content: str,
    **metadata: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L128"
>

Append an assistant-role context message, optionally retaining framework metadata for persistence and telemetry.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory add_assistant parameters">
    <ApiField name="content" type="str" required>
      Assistant response text.
    </ApiField>
    <ApiField name="**metadata" type="Any">
      Arbitrary keyword metadata stored on the canonical message.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### ConversationHistory.add_tool

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.add_tool"
  signature={`add_tool(
    content: str,
    tool_name: str,
    **metadata: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L141"
>

Append a tool-role response. The tool name is stored in `LLMMessage.name` so simplified provider conversion includes it.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory add_tool parameters">
    <ApiField name="content" type="str" required>
      Tool response represented as text.
    </ApiField>
    <ApiField name="tool_name" type="str" required>
      Name of the tool that produced the response.
    </ApiField>
    <ApiField name="**metadata" type="Any">
      Additional canonical-message metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### ConversationHistory.add_raw

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.add_raw"
  signature={`add_raw(
    message: dict[str, Any],
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L160"
>

Append a message from a simplified provider-style mapping.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory add_raw parameters">
    <ApiField name="message" type="dict[str, Any]" required>
      Mapping with required <code>role</code>, optional <code>content</code>, and optional <code>tool_calls</code>. Missing content becomes an empty string.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="ConversationHistory add_raw errors">
    <ApiField name="KeyError">
      Raised when <code>role</code> is absent.
    </ApiField>
    <ApiField name="ValueError">
      Raised when the role string is not a valid <code>LLMMessageRole</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Lossy ingestion">
  This helper copies only role, content, and tool calls. Input keys such as name, metadata, ID, creation time, and tool name are ignored. Use <code>replace()</code> or <code>from_list()</code> with full message dictionaries when every canonical field must survive.
</ApiCallout>

</ApiReference>

#### ConversationHistory.reset_to_system

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.reset_to_system"
  signature={`reset_to_system(
    content: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L173"
>

Discard every message and replace the history with one new system message.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory reset_to_system parameters">
    <ApiField name="content" type="str" required>
      New system prompt. Unlike constructor initialization, an empty string is still stored as a system message.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Destructive mutation">
  The history object's identity remains stable, but all previous message objects become unreachable from it.
</ApiCallout>

</ApiReference>

#### ConversationHistory.set_system

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.set_system"
  signature={`set_system(
    content: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L186"
>

Set the leading system instruction while preserving later conversation turns. If the first item is already a system message it is replaced; otherwise a new system message is prepended in constant time.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory set_system parameters">
    <ApiField name="content" type="str" required>
      New system prompt, including an empty string if that is explicitly desired.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Replacement identity">
  Replacing an existing system message creates a new <code>LLMMessage</code>, so its ID, creation time, metadata, and provider-specific fields are reset.
</ApiCallout>

</ApiReference>

#### ConversationHistory.messages_raw

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.messages_raw"
  signature={`messages_raw() -> list[LLMMessage]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L211"
>

Return a shallow list snapshot of the canonical message objects.

<ApiSection title="Returns">
  <ApiFields ariaLabel="ConversationHistory messages_raw return value">
    <ApiField name="messages" type="list[LLMMessage]">
      New list in chronological order. The contained <code>LLMMessage</code> objects are shared with the history, so mutating one changes the canonical entry.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### ConversationHistory.to_list

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.to_list"
  signature={`to_list() -> list[dict[str, Any]]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L232"
>

Serialize the complete history for persistence, copying, or a lossless transformation.

<ApiSection title="Returns">
  <ApiFields ariaLabel="ConversationHistory to_list return value">
    <ApiField name="messages" type="list[dict[str, Any]]">
      Chronological full-message dictionaries produced by <code>LLMMessage.to_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Full versus provider view">
  Unlike the <code>messages</code> property, this method preserves metadata, tracing IDs, timestamps, tool calls, and tool names.
</ApiCallout>

</ApiReference>

#### ConversationHistory.copy

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.copy"
  signature={`copy() -> ConversationHistory`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L239"
>

Create an independent history by round-tripping every canonical message through full serialization.

<ApiSection title="Returns">
  <ApiFields ariaLabel="ConversationHistory copy return value">
    <ApiField name="history" type="ConversationHistory">
      New history object with newly constructed <code>LLMMessage</code> instances that preserve all serialized fields.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Container depth">
  Message objects and their top-level dictionaries are recreated. Arbitrary nested objects inside metadata or tool-call mappings may still be shared because the message serializer is not a general deep-copy routine.
</ApiCallout>

</ApiReference>

#### ConversationHistory.replace

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.replace"
  signature={`replace(
    messages_data: Iterable[dict[str, Any]],
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L251"
>

Replace every canonical message while preserving the `ConversationHistory` object's identity. History compaction uses this behavior so LLMs, agents, and state modules can keep existing references to the same history container.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory replace parameters">
    <ApiField name="messages_data" type="Iterable[dict[str, Any]]" required>
      Full chronological message dictionaries, normally from <code>to_list()</code>. The iterable is consumed once and each item is rehydrated through <code>LLMMessage.from_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="ConversationHistory replace errors">
    <ApiField name="KeyError or ValueError">
      Propagated from the first malformed serialized message. The new deque is built before assignment, so the existing history remains intact if hydration fails.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### ConversationHistory.from_list

<ApiReference
  kind="classmethod"
  path="protolink.llms.history.ConversationHistory.from_list"
  signature={`from_list(
    messages_data: list[dict[str, Any]],
) -> ConversationHistory`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L267"
>

Restore a new conversation from full serialized messages.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory from_list parameters">
    <ApiField name="messages_data" type="list[dict[str, Any]]" required>
      Chronological full-message dictionaries.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="ConversationHistory from_list return value">
    <ApiField name="history" type="ConversationHistory">
      New history with one canonical <code>LLMMessage</code> per dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="ConversationHistory from_list errors">
    <ApiField name="KeyError or ValueError">
      Propagated from malformed role, content, or timestamp fields.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### ConversationHistory.truncate

<ApiReference
  kind="method"
  path="protolink.llms.history.ConversationHistory.truncate"
  signature={`truncate(
    max_messages: int,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/history.py#L287"
>

Trim older history while preserving the first stored message and the newest suffix. The low-level operation mutates the live deque in place and is intended for histories whose first message is the system prompt.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConversationHistory truncate parameters">
    <ApiField name="max_messages" type="int" required>
      Maximum retained message count, including the protected first item. Values below two are rejected. When the history is already within the limit, no mutation occurs.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="ConversationHistory truncate errors">
    <ApiField name="ValueError">
      Raised when <code>max_messages</code> is less than two.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Current first-message behavior">
  The implementation protects the first stored message without checking its role. If a history has no leading system message, its first user or assistant message is retained as though it were the system prompt.
</ApiCallout>

<ApiCallout label="Prefer structured compaction">
  For explicit recent-message limits, token budgets, summaries, and before/after reports, use [`LLM.compact_history()`](llm.md#history-compaction).
</ApiCallout>

</ApiReference>

<ApiSection title="History examples">

```python
from protolink.llms.history import ConversationHistory

history = ConversationHistory("You are a concise support assistant.")
history.add_user("My account is locked.", customer_id="customer-42")
history.add_assistant("I can help you recover access.")
history.add_tool(
    '{"recovery_email_sent": true}',
    tool_name="send_recovery_email",
)

persisted = history.to_list()
restored = ConversationHistory.from_list(persisted)

# Update the prompt without discarding the conversation.
restored.set_system("You are a concise, security-aware support assistant.")
```

</ApiSection>

### HistoryCompactionRequest

<ApiReference
  kind="frozen dataclass"
  path="protolink.HistoryCompactionRequest"
  signature={`class HistoryCompactionRequest(
    strategy: Literal["recent", "tokens", "summary"] = "recent",
    max_messages: int = 20,
    max_tokens: int = 4000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/compaction.py#L27"
>

Transport-neutral control payload used by `Agent.compact_history()` and `AgentClient.compact_history()`. It requests context maintenance without creating a task part, adding text to model history, or exposing compaction as an LLM tool.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HistoryCompactionRequest constructor parameters">
    <ApiField name="strategy" type={'"recent" | "tokens" | "summary"'} defaultValue={'"recent"'}>
      Compaction algorithm. <code>recent</code> keeps a bounded newest suffix, <code>tokens</code> keeps a newest suffix under a soft estimated-token ceiling, and <code>summary</code> replaces older turns with one generated summary.
    </ApiField>
    <ApiField name="max_messages" type="int" defaultValue="20">
      Retained-message limit for the <code>recent</code> strategy, including a leading system message when one exists.
    </ApiField>
    <ApiField name="max_tokens" type="int" defaultValue="4000">
      Estimated-token ceiling for the <code>tokens</code> strategy. Protected system and recent messages can make the result exceed this soft ceiling.
    </ApiField>
    <ApiField name="preserve_recent" type="int" defaultValue="6">
      Number of newest non-system messages protected verbatim by <code>tokens</code> and <code>summary</code>.
    </ApiField>
    <ApiField name="summary_max_tokens" type="int" defaultValue="512">
      Requested approximate maximum length of a generated summary.
    </ApiField>
    <ApiField name="session_id" type="str | None" defaultValue="None">
      Optional persistent conversation session to load, compact, and save when the agent uses conversation state.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Application metadata for logs or future control policy. The compactor itself ignores it.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Validation timing">
  Direct dataclass construction does not validate strategy names or numeric limits. <code>from_dict()</code> validates the strategy and normalizes numeric fields; the compactor validates strategy-specific limits when the operation runs.
</ApiCallout>

<ApiCallout label="Control plane">
  This immutable value is not shown to the model and does not consume prompt tokens.
</ApiCallout>

</ApiReference>

#### HistoryCompactionRequest.to_dict

<ApiReference
  kind="method"
  path="protolink.HistoryCompactionRequest.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/compaction.py#L56"
>

Serialize the complete request for a transport body.

<ApiSection title="Returns">
  <ApiFields ariaLabel="HistoryCompactionRequest to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing all request fields. When the instance's metadata is <code>None</code>, the serialized value is normalized to an empty dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Frozen does not mean deeply immutable">
  The request fields cannot be reassigned, but a metadata dictionary supplied by the caller remains mutable.
</ApiCallout>

</ApiReference>

#### HistoryCompactionRequest.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.HistoryCompactionRequest.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> HistoryCompactionRequest`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/compaction.py#L63"
>

Normalize a JSON-compatible compaction request received through the control plane.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HistoryCompactionRequest from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Request mapping. Missing values receive dataclass defaults. Numeric fields are converted with <code>int()</code>, non-<code>None</code> session IDs with <code>str()</code>, and metadata with <code>dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="HistoryCompactionRequest from_dict return value">
    <ApiField name="request" type="HistoryCompactionRequest">
      New immutable request. Missing or falsy metadata is normalized to a fresh empty dictionary rather than <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="HistoryCompactionRequest from_dict errors">
    <ApiField name="ValueError">
      Raised when strategy is not <code>recent</code>, <code>tokens</code>, or <code>summary</code>, or when a numeric value cannot be converted to an integer.
    </ApiField>
    <ApiField name="TypeError">
      Raised when numeric or metadata values have incompatible runtime shapes.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Range checks">
  Integer conversion is not range validation. Negative or otherwise invalid limits are rejected later by the compaction operation.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import HistoryCompactionRequest

request = HistoryCompactionRequest(
    strategy="tokens",
    max_tokens=8_000,
    preserve_recent=6,
    session_id="customer-42",
    metadata={"reason": "context pressure"},
)
```

</ApiSection>

</ApiReference>

### HistoryCompactionResult

<ApiReference
  kind="frozen dataclass"
  path="protolink.HistoryCompactionResult"
  signature={`class HistoryCompactionResult(
    strategy: Literal["recent", "tokens", "summary"],
    before_messages: int,
    after_messages: int,
    removed_messages: int,
    before_tokens: int,
    after_tokens: int,
    summary_created: bool = False,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/compaction.py#L82"
>

Structured report returned after direct LLM compaction, Agent control-plane compaction, or the equivalent client request. It records both message-count and estimated-token effects without requiring callers to diff histories manually.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HistoryCompactionResult constructor parameters">
    <ApiField name="strategy" type={'"recent" | "tokens" | "summary"'} required>
      Strategy used for this attempt.
    </ApiField>
    <ApiField name="before_messages" type="int" required>
      Canonical message count before compaction.
    </ApiField>
    <ApiField name="after_messages" type="int" required>
      Canonical message count after compaction.
    </ApiField>
    <ApiField name="removed_messages" type="int" required>
      Number of source messages removed. Summary replacement reports the number of older source messages represented by the summary.
    </ApiField>
    <ApiField name="before_tokens" type="int" required>
      Provider-neutral estimated token count before compaction.
    </ApiField>
    <ApiField name="after_tokens" type="int" required>
      Estimated token count after compaction.
    </ApiField>
    <ApiField name="summary_created" type="bool" defaultValue="False">
      Whether summary compaction successfully inserted a generated summary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="HistoryCompactionResult attributes">
    <ApiField name="changed" type="bool">
      Computed property that is true when at least one source message was removed or a summary was created.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Observational value">
  The result is immutable and does not retain the history itself. Counts are supplied by the compactor; direct constructor calls do not validate their consistency or non-negativity.
</ApiCallout>

</ApiReference>

#### HistoryCompactionResult.to_dict

<ApiReference
  kind="method"
  path="protolink.HistoryCompactionResult.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/compaction.py#L98"
>

Serialize the compaction report for task results, telemetry, logging, or a client response.

<ApiSection title="Returns">
  <ApiFields ariaLabel="HistoryCompactionResult to_dict return value">
    <ApiField name="data" type="dict[str, Any]">
      Dictionary containing every dataclass field plus the computed <code>changed</code> property.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### HistoryCompactionResult.from_dict

<ApiReference
  kind="classmethod"
  path="protolink.HistoryCompactionResult.from_dict"
  signature={`from_dict(
    data: dict[str, Any],
) -> HistoryCompactionResult`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/llms/compaction.py#L102"
>

Create a compaction report from a JSON-compatible response.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="HistoryCompactionResult from_dict parameters">
    <ApiField name="data" type="dict[str, Any]" required>
      Result mapping. Missing strategy defaults to <code>recent</code>; missing counts default to zero; missing summary status defaults to false. An incoming <code>changed</code> key is ignored because the property is recomputed.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="HistoryCompactionResult from_dict return value">
    <ApiField name="result" type="HistoryCompactionResult">
      New immutable report with integer-normalized counts and a Boolean-normalized summary flag.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="HistoryCompactionResult from_dict errors">
    <ApiField name="ValueError or TypeError">
      Raised when a count cannot be converted with <code>int()</code>. Strategy values and relationships between counts are not validated here.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Examples">

```python
report = llm.compact_history(
    "summary",
    preserve_recent=8,
    summary_max_tokens=600,
)

if report.changed:
    print(
        f"Compacted {report.before_messages} messages "
        f"to {report.after_messages}"
    )

print(report.to_dict())
```

</ApiSection>

</ApiReference>

## See also

- [LLMs](llm.md) — inference, history ownership, and compaction behavior.
- [Agents](agent.md) — task execution and lifecycle integration.
- [Flows](flows.md) — structured route decisions and task propagation.
- [State](state.md) — conversation and task persistence.
- [Transport](transport.md) — endpoint binding and model serialization across backends.
