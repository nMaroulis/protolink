# Progressive control

Progressive control is a core design principle of ProtoLink: start with a small
call, configure the parts that need attention, and plug in your own components
through the same API. It applies to agent setup, execution, and deployment.

Identity, models, tools, transport, storage, and observability are independent
choices. A model string resolves to an LLM object; a transport alias resolves to a
transport instance. You can configure or replace either while keeping the rest
of the agent. Short and explicit forms share the same execution paths for
validation, policy, approvals, cancellation, and reporting.

Run the complete, provider-free walkthrough:

```bash
python examples/progressive_control.py
```

It needs only the base package. `--mcp` also starts the bundled MCP example server
and requires `protolink[mcp]`.

## Start with names and functions

```python
from protolink import Agent


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


agent = Agent(name="helper", llm="mock", tools=[add])
print(agent.sync.call_tool("add", a=2, b=3))  # 5
print(agent.sync.invoke("Hello"))
```

This example needs no provider credentials or server. The name creates an agent
card, `"mock"` selects the built-in offline model, and the typed function becomes
a tool. In async programs and notebooks use `await agent.invoke(...)` and
`await agent.call_tool(...)`. Blocking facades reject calls inside an active event
loop before creating a coroutine.

## Choose how much to configure

Use a shorthand for defaults, a configured object for specific options, or your
own implementation of the component's public interface. Choose independently
for each argument: `Agent(name="helper", llm=llm, transport=transport)` is just
as valid as an explicit card with `llm="gemini"`. Adding a transport does not
require changing tools; changing a model does not require changing task handling.

| Boundary | Start small | Add control |
| --- | --- | --- |
| Agent identity | `Agent(name="helper")` | Pass a card dictionary or an `AgentCard` with skills and capabilities |
| Transport | `Agent(name="helper", transport="http", url="http://127.0.0.1:8001")` | Pass `HTTPTransport(...)` with timeouts, TLS, and limits |
| Standalone client | `AgentClient("http")` | Pass a configured transport |
| Registry | `registry="http", registry_url=url` | Pass a `RegistryClient` or `Registry` |
| Model | `llm="gemini"` or `llm="ollama:qwen3:4b"` | Pass `GeminiLLM(...)`, `create_llm(...)`, or your own `LLM` |
| Tools | `tools=[function]` or `@agent.tool` | Supply a `Tool` with schemas, names, and capabilities |
| State | `state=["conversation"]` | Supply storage and a configured `State` |
| Knowledge | `create_knowledge("memory", sources=[...])` | Choose components or supply a retriever |
| Logs | `verbosity=0`, `1`, or `2` | Supply a logger; attach telemetry and a run store separately |
| Task creation | `Task.create_infer("Hello")` | Add run controls or compose messages and parts |
| Task reading | `task.get_output()` | Inspect `get_last_part()`, messages, artifacts, and state |
| Execution | `await agent.invoke("Hello")` | Use `start_run(...)` or `run_task(task)` |
| Flows | `await Pipeline([a, b]).invoke("Hello")` | Use `execute(task)` or a custom `Graph` |

### Agent cards and transports

A name is enough for a local agent. Network aliases require a URL with a matching
scheme and an explicit port; ProtoLink does not invent a listening address:

```python
from protolink import Agent, AgentCard

local = Agent(name="helper", llm="mock")  # runtime://helper identity, no transport
simple = Agent(name="helper", transport="http", url="http://127.0.0.1:8001")
```

For explicit identity metadata, pass a dictionary or a typed card:

```python
identity = {"name": "helper", "description": "A helpful agent", "url": "http://127.0.0.1:8001"}
card = AgentCard(**identity)

with_dict = Agent(card=identity, transport="http")
# Equivalent identity:
with_card = Agent(card=card, transport="http")
```

`transport="http"` creates an HTTP transport with defaults using `card.url`. To
configure the same boundary, create the transport and pass it to `Agent`:

```python
from protolink.transport import HTTPTransport, RetryPolicy, TransportConfig, TransportLimits

transport = HTTPTransport(
    url=card.url,
    timeout=30,
    config=TransportConfig(
        limits=TransportLimits(max_concurrent_requests=200),
        retry=RetryPolicy(max_attempts=3),
    ),
)
configured = Agent(card, transport=transport)
```

You can also use `Agent(name="helper", transport=transport)` to derive the card's
URL from the configured transport. An explicit `url=` can advertise a public
address while that transport binds locally, for example behind a reverse proxy.
Secure bind URLs require a configured transport with a `TLSConfig` containing a
certificate and key. Shorthand validates these settings before creating the LLM.

An explicit `card=` accepts an `AgentCard` or dictionary and cannot be combined
with `name=`, `description=`, or `url=`. Existing card-based construction keeps its
behavior. Construction does not start a server. HTTP needs `protolink[http]`;
`Agent(name="helper", transport="runtime")` enables communication within one
process. Use unique names for runtime endpoints. To add HTTP later to a name-only
agent, assign a configured `HTTPTransport(url="http://127.0.0.1:8001")` to
`agent.transport`; the automatically generated card URL follows it. An explicit
card URL stays under your control. Retries apply only to requests declared
idempotent. See [Transports](transport.md) for TLS and the other transport aliases.

### Clients and registries

The same transport choice is available to clients and registry servers:

```python
from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.transport import HTTPTransport

client = AgentClient("http")
configured_client = AgentClient(HTTPTransport(url="http://127.0.0.1:8000", timeout=30))

registry_url = "http://127.0.0.1:9000"
registry = Registry(transport="http", url=registry_url)
configured_registry = Registry(transport=HTTPTransport(url=registry_url, timeout=10))
```

Choose one registry server configuration when starting your application. For an
agent that connects to it, use the shorthand or pass the configured client:

```python
simple = Agent(card, transport="http", registry="http", registry_url=registry_url)

registry_client = RegistryClient(HTTPTransport(url=registry_url, timeout=10))
configured = Agent(card, transport="http", registry=registry_client)
# A Registry object also works: Agent(card, transport="http", registry=registry)
```

`RegistryClient` itself takes a concrete transport. Agent registration and server
startup happen through the normal lifecycle, such as `AgentGroup` below. Supplying
a registry client lets discovery use different transport settings from agent calls.

### Models

Start with a provider alias or `provider:model` string. Pass a provider instance
when you need to configure its credentials, model, or request parameters. For
Gemini, install `protolink[gemini]` and set `GEMINI_API_KEY`:

```python
from protolink import create_llm
from protolink.llms.api import GeminiLLM

simple = Agent(name="helper", llm="gemini")

llm = GeminiLLM(model_params={"temperature": 0.2})
configured = Agent(name="helper", llm=llm)
```

The configured object is used directly. You can also pass provider options through
`create_llm`, which returns the same concrete adapters, for example
`create_llm("ollama:qwen3:4b", base_url="http://127.0.0.1:11434")`.
`Agent(name="helper", llm="ollama:qwen3:4b")` uses the same factory with provider
defaults. Only the first colon separates the provider from the model, preserving
model tags and case. Existing `create_llm("ollama", model="qwen3:4b")` calls still
work; do not supply a model both inline and through `model=`.

Pass typed functions or configured tools through `Agent(name="helper", tools=[...])`
or register them later with `add_tools`. Both paths use the existing validation,
policy, and skill-registration behavior. Continue to execute through `invoke`,
`.sync`, and the task APIs.
See [LLMs](llm.md) for provider extras and implementing the `LLM` contract.
Provider construction or connection validation may contact the model service;
use `"mock"` or a configured `MockLLM` for an offline setup.

### Conversation state and storage

Enable conversation history with one option, then choose where it lives:

```python
from protolink.state import State
from protolink.storage import SQLiteStorage

simple = Agent(card, llm=create_llm("mock"), state=["conversation"])

storage = SQLiteStorage("agent-state.db", namespace="helper")
state = State(storage=storage, enabled=["conversation"])
configured = Agent(card, llm=create_llm("mock"), storage=storage, state=state)
```

The short form uses the agent's in-memory storage by default. You can also pass
`storage=storage, state=["conversation"]` to select persistence without constructing
`State`. Use the same `session_id` across calls that belong to one conversation.
This storage holds agent state; run reports use the separate `run_store` interface.

### Knowledge components

Start with the built-in local stack, replace selected components, or provide an
existing retriever:

```python
from protolink import create_knowledge
from protolink.rag import HashEmbedder, InMemoryVectorStore, RecursiveCharacterSplitter

knowledge = create_knowledge("memory", sources=["docs/content/"])
configured_knowledge = create_knowledge(
    "memory",
    sources=["docs/content/"],
    splitter=RecursiveCharacterSplitter(chunk_size=800, chunk_overlap=100),
    embedder=HashEmbedder(),
    store=InMemoryVectorStore(),
)
with_knowledge = Agent(card, llm=create_llm("mock"), knowledge=configured_knowledge)
```

Sources are indexed on first search, or explicitly with `await knowledge.ready()`.
For an application-owned index, pass a retriever through
`create_knowledge(retriever, name="manuals")` or directly as `Agent(..., knowledge=retriever)`.
Retrievers implement `async retrieve(query, *, k, where)`; managed loaders, splitting,
and ingestion remain optional. See [RAG](rag.md) for backend and retrieval controls.

### Logging and run persistence

Use verbosity for standard console logs; pass a logger for a different destination:

```python
from protolink.logging import FileLogger

simple = Agent(card, verbosity=0)
configured = Agent(card, logger=FileLogger("agent.json"))
```

A supplied logger owns its level and formatting. Add telemetry for tracing or
`run_store=SQLiteRunStore("runs.db")` for retained run reports independently of
console verbosity. [Runtime](runtime.md) covers those explicit interfaces.

## Create and read tasks

Use a task when you need state, messages, artifacts, or run controls alongside the
answer. The factories keep the common inputs positional and optional controls named:

```python
from protolink import Task, RunBudget

message_task = Task.create("Text for a custom handler")
infer_task = Task.create_infer("Summarize the plan", session_id="planning")
tool_task = Task.create_tool_call("add", {"a": 2, "b": 3}, budget=RunBudget(max_tool_calls=1))

result = await agent.run_task(tool_task)
print(result.raise_for_status().get_output())  # 5
print(result.get_last_part().as_tool_output().call_id)
```

`Task.create(text)` wraps `Message.user(text)`; it does not implicitly request an
LLM call. `create_infer` creates that instruction, and `create_tool_call` requests
a tool directly. Creation performs no execution. Existing keyword calls still work.
All three factories accept `session_id`, `budget`, and `context`, with copied controls
and explicit options overriding the supplied context. Omitted controls leave task
metadata empty. The inference factory's `metadata` still belongs to the infer part.

| Reader | Returns |
| --- | --- |
| `get_output(default=None)` | Latest answer content or the raw successful tool result |
| `get_last_part_content()` | Latest part content, including inputs and typed envelopes |
| `get_last_part()` | The `Part`, retaining its type and tool correlation/error fields |
| `get_last_item()` | The latest `Message` or `Artifact`, including its metadata |
| `messages`, `artifacts`, `state` | The complete task history and lifecycle status |

`get_output` examines only the final part of the latest item. It accepts inference
outputs, successful tool outputs, and text/JSON in agent or assistant messages and
`kind="result"` artifacts. An input, error, preview, diagnostic, unsupported part,
or empty item returns `default`; it never falls back to a stale answer. Falsey
answers, including `None`, are preserved. A sentinel default can distinguish an
absent answer from a tool that returned `None`.

Reading neither waits for completion nor raises for task state. Chain
`raise_for_status()` to reject failed/canceled tasks and inspect `state` when you
require completion. Tool error details remain on `get_last_part().as_tool_output().error`.

For multiple parts or custom messages, use the explicit constructors:

```python
from protolink import Message, Part

task = Task.create(Message(role="user", parts=[Part.text("Review these values"), Part.json({"values": [2, 3]})]))
```

`Task.infer(...)` and `Task.tool_call(...)` remain **part factories**; the corresponding
`create_*` methods create complete tasks. See [Models](models.md#task-create) for the
factory parameters and reader contracts.

## Add run controls

`invoke`, `ask`, `start_run`, `Flow.invoke`, and peer inference accept `budget` and
`context`. The blocking equivalents accept the same controls where available.

```python
from protolink import RunBudget, RunContext

answer = await agent.invoke(
    "Summarize the release plan",
    session_id="planning",
    budget=RunBudget(max_llm_calls=3, max_tool_calls=5, max_runtime_seconds=30),
)

context = RunContext(
    session_id="planning",
    trace_id="release-0.7.4",
    permissions={"filesystem.write": "deny"},
)
answer = await agent.invoke("Review the plan", context=context)
```

Explicit `session_id` and `budget` override those fields in the supplied context.
Contexts and budgets are copied before use. Without an explicit session or context
session, prompt invocations retain the existing `invocation_session_id` partition;
`ask` retains `ask_session_id`. Set distinct session IDs for independent conversations.
Per-run permissions still cannot weaken the receiving agent's policy.

The complete task path remains available:

```python
from protolink import Task

task = Task.create_infer(prompt="Review the plan")
context.attach_to_task(task)
result = await agent.run_task(task)
result.raise_for_status()
# Equivalent setup: Task.create_infer("Review the plan", context=context)
```

`invoke` returns final part content; `call_tool` returns the raw tool value. Falsey
values such as `0`, `False`, and empty collections remain intact. `invoke`, `ask`,
`Flow.invoke`, and peer convenience calls raise `TaskExecutionError` for returned
failed/canceled tasks. `run_task` and `Flow.execute` retain returned states for
inspection; provider, policy, and handler exceptions still propagate. Inspect the
full task when your application handles `input-required` or other incomplete states.

## Streaming, cancellation, and reports

```python
handle = agent.start_run("Explain the plan", budget=RunBudget(max_llm_calls=2))
async for chunk in handle.chunks():
    print(chunk, end="", flush=True)
result = await handle.result()
print(result.status, result.output, result.report)
```

`start_run(prompt_or_task, *, session_id=None, budget=None, context=None, store=None,
redaction_policy=None)` requires an active asyncio loop and starts one local task
stream without starting a server. It returns the existing `RunHandle`.

- `chunks()` yields **raw model fragments**. JSON-action models stream JSON, including
  action envelopes. These fragments are not necessarily user-facing answer text.
- `events()` yields all normalized `RunEvent` objects, including tools and task status.
- `result()` returns `RunResult(status, task, output, report, error)`; inspect the status
  and error. It does not have `invoke`'s raise-on-failure behavior.
- `report` provides the current snapshot, then the final report.
- `await handle.cancel(reason)` requests cancellation. Leaving either iterator does
  not cancel the run; multiple consumers observe the same execution.

Passing a configured `Task` preserves its context unless you explicitly override
controls. Report persistence defaults to the agent's `run_store`; `store` selects
another store, and `redaction_policy` controls captured data. Direct local streams
need no card capability flag; remote subscriptions still follow the advertised
streaming capability and transport support. Use `RunHandle.start(...)` for remote
handles or `RunRecorder` when adapting your own event source.

## Register collections and MCP tools

An ordinary typed function provides an inferred name, description, and schemas.
Pass a configured `Tool` when you need explicit metadata or capability requirements:

```python
from protolink import Tool

agent.add_tool(add)
configured_tool = Tool.from_callable(
    add, name="sum_numbers", description="Add two whole numbers", capabilities=["math.add"]
)
agent.add_tool(configured_tool)
```

`@agent.tool` is the decorator form of native registration. Explicit tools still run
through normal argument validation and policy checks when called through the agent.

`agent.add_tools(iterable)` accepts native tools and ordinary typed functions,
including the lists returned by built-in tool factories. It applies `add_tool`'s
existing replacement rules in order. If an item fails, earlier items remain registered.
Registration never executes a tool.

```python
from protolink.tools import calculator, document_tools

agent.add_tools([calculator(), *document_tools(roots=["docs/"])])
```

MCP discovery has a dedicated async path, usable inside notebooks and applications:

```python
import sys

registered = await agent.add_mcp(
    command=sys.executable,
    args=["examples/mcp/mcp_server.py"],
    include=["add"],
    prefix="math_",
)
print(await agent.call_tool("math_add", a=2, b=3))
```

`add_mcp(adapter=None, *, transport=None, command=None, args=None, url=None, headers=None, include=None,
prefix="")` accepts either a configured `MCPToolAdapter`, stdio command/arguments,
or an HTTP URL/headers. Set `transport="streamable_http"` for Streamable HTTP;
an omitted transport with a URL retains legacy SSE behavior. `include` contains original server names; `prefix` only changes
local registration names. Unknown selections, duplicate discovered names, or existing
local names fail before registration. An empty selection registers nothing.

Discovery contacts the server and may start its process, but invokes no tool. Sessions
open and close per request unless you pass an adapter inside its `session()` context.
Use `agent.sync.add_mcp(...)` in blocking scripts. For lower-level control, use
`await adapter.list_tools_async()` or `await adapter.get_tools_async()`; the existing
blocking adapter methods remain available. Install the optional `mcp` extra first.

```python
from protolink.tools.adapters import MCPToolAdapter

adapter = MCPToolAdapter("streamable_http", url="https://example.com/mcp")
async with adapter.session():
    await agent.add_mcp(adapter, include=["search"], prefix="remote_")
    result = await agent.call_tool("remote_search", query="agent protocols")
```

Single plain text results return strings. Rich results are dictionaries with MCP
fields such as `content`, `structuredContent`, and `_meta`; for structured output,
read `result["structuredContent"]`. MCP tool failures raise `MCPToolError` on direct
calls and become failed tool outputs through task execution. See [MCP tools](tool.md#mcp-tools).

## Call a peer

```python
peer = caller.peer("calculator")  # caller has a registry and transport
print(await peer.call_tool("add", a=2, b=3))
answer = await peer.invoke("Explain the calculation", session_id="planning")
```

`agent.peer(target, *, protocol="auto")` binds an `AgentCard`, URL, or registry name.
It uses the agent's existing transport, credentials, registry, and outbound protocol
selection. Binding performs no I/O. A registry name resolves afresh on each call and
must match exactly one agent; zero or multiple matches raise `ValueError`.

A standalone client can bind a peer too:

```python
from protolink.client import AgentClient

peer = AgentClient("http").peer("http://127.0.0.1:8001")
answer = peer.sync.invoke("Hello")
```

`client.peer(target, *, registry=None, protocol="auto")` accepts a `RegistryClient`
when resolving names. Peers expose `invoke`, `invoke_typed`, `call_tool`, and `run_task`,
plus matching `.sync` methods. Tool keyword arguments belong exclusively to the tool;
use `run_task` with an explicit context for controlled tool tasks.

Peers submit once and preserve normal transport errors. `call_tool` requires a native
ProtoLink peer and a tool-output response. A2A-only peers support inference translation,
not ProtoLink tool tasks or native budget/permission controls. Existing `call_agent`,
`send_task`, and `send_infer_task` remain available for full task handling.

## Compose local flows before adding services

```python
from protolink import Pipeline

flow = Pipeline([researcher, summarizer])
answer = await flow.invoke("Prepare release notes", budget=RunBudget(max_llm_calls=2))
```

Local agent instances require no registry, port, or startup sequence. `flow.sync.invoke`
is the blocking equivalent; `flow.execute(task)` retains the complete task contract.
The convenience result is final part content, including `ToolOutput` for a tool step.

For agents that communicate through transports, the existing `AgentGroup` owns startup,
readiness, and cleanup:

```python
from protolink import AgentGroup

async with AgentGroup([calculator, caller], registry=registry, own_registry=True):
    result = await caller.peer("calculator").call_tool("add", a=2, b=3)
```

Each agent retains its configured transport. Omit `own_registry=True` when the
application owns the registry lifecycle.

## Deterministic steps and bounded acceptance

`Step(handler)` adapts a sync or async `Task -> Task` function without subclassing:

```python
from protolink import Pipeline, Step


def label(task):
    return task.complete(f"Reviewed: {task.get_last_part_content()}")


flow = Pipeline([researcher, Step(label)])
```

`ToolStep(agent, tool_name, args=None, *, client=None, registry=None)` appends a tool
instruction and executes it through the receiving agent. `args` is a mapping or a
synchronous function receiving the current task and returning a mapping. Local Agent
instances and remote URLs/names use the same dispatch rules as other flow steps.

```python
from protolink import CompletionCheck, RepeatUntil, ToolStep

workflow = RepeatUntil(
    ToolStep(sensor, "measure"),
    CompletionCheck("minimum", lambda evidence: evidence.outcomes[-1].result >= 5),
    max_attempts=3,
)
result = await workflow.execute(Task.create_infer(prompt="Find an acceptable sample"))
```

`RepeatUntil(step, checks, *, max_attempts, client=None, registry=None)` accepts one
`CompletionCheck` or a nonempty sequence. `max_attempts` is a positive total attempt
count. Checks receive the current attempt's execution receipts and the accumulated
task; all attempts and validation events remain in the report. Default completion
checks require actual execution evidence. Set `require_execution=False` explicitly
for pure answer checks.

Failed acceptance permits another attempt; execution exceptions and failed, canceled,
or input-required tasks stop immediately. Exhaustion raises `WorkflowLimitError`
and records a blocker. Local attempts share the workflow budget, and repetition can
repeat side effects. Use `Graph` when you need custom routing or repair topology.

## Typed responses and explicit repair

```python
from pydantic import BaseModel


class ReleasePlan(BaseModel):
    version: str
    steps: list[str]


plan = await agent.invoke_typed("Prepare a release plan", ReleasePlan)
print(plan.version)
```

`invoke_typed(message, response_model, *, max_attempts=1, session_id=None, budget=None,
context=None)` adds the type's JSON schema to the prompt, executes through the normal
task lifecycle, then validates the answer with Pydantic `TypeAdapter`. Pydantic models,
dataclasses, and other supported Python types work. Pydantic's normal coercion rules
apply; choose strict fields/types when your contract requires them. JSON strings,
JSON values, and a single enclosing `json` code fence are accepted. No prose extraction
or provider-specific schema guarantee is implied.

Set `max_attempts=2` to explicitly permit one corrective inference following a
validation failure. Feedback includes the original request/schema, previous answer,
and validation errors. This can execute tools again. Execution failures, transport
errors, and incomplete tasks never trigger repair. One local workflow budget covers
all attempts; remote peers receive serialized limits but do not share atomic counters
across submissions. The local wall-clock budget still bounds the overall remote call.

`StructuredResponseError` exposes `.task`, `.attempts`, and `.validation_error` when
validation cannot succeed; the validation error is `None` for missing/incomplete
responses. These errors preserve task evidence. The same interface is available through
`agent.sync.invoke_typed`, `peer.invoke_typed`, and `peer.sync.invoke_typed`.
