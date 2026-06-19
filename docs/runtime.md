# Runtime

Protolink's runtime primitives provide a stable execution layer above the core A2A-style `Task`, `Message`, `Part`, and `Artifact` models. They are intentionally generic: the same contracts work for local CLIs, workflow engines, support assistants, research systems, browser agents, data tools, and any other agent application.

The runtime layer does not replace transports, telemetry, storage, or structured flows. It gives them shared execution metadata and a normalized event stream.

## Runtime Context

`RunContext` is the typed execution envelope for a task run. It replaces ad hoc metadata keys such as `task.metadata["session_id"]`, `trace_id`, `workspace`, or `parent_agent` with one serializable object stored under `task.metadata["run_context"]`.

```python
from protolink import RunBudget, RunContext, Task

task = Task.create_infer(prompt="Summarize the latest report")

context = RunContext(
    run_id="run_123",
    session_id="session_abc",
    trace_id="trace_abc",
    workspace_uri="file:///workspace",
    agent_chain=["gateway"],
    permissions={"fs.read": {"paths": ["file:///workspace"]}},
    budget=RunBudget(max_steps=8, max_llm_calls=4),
)

context.attach_to_task(task)
```

The default `Agent` runtime calls `RunContext.ensure_task_context()` before normal execution, streaming execution, and outbound agent calls. Existing callers can keep setting `task.metadata["session_id"]`; Protolink upgrades that legacy metadata into a typed context and mirrors common keys back for compatibility.

### Fields

| Field | Description |
|------|-------------|
| `run_id` | Stable identifier for one logical execution run. |
| `session_id` | Conversation or application session shared across runs. |
| `trace_id` | Observability trace identifier, also used by local telemetry. |
| `workspace_uri` | Generic run boundary such as a folder, dataset, browser profile, account, or ticket collection. |
| `parent_run_id` | Parent run for nested agent or tool execution. |
| `agent_chain` | Ordered list of agents that have handled the run. |
| `permissions` | Domain-neutral permission grants or policy metadata. |
| `budget` | Optional `RunBudget` limits such as max steps, model calls, tool calls, runtime seconds, and token budgets. |
| `canceled` | Whether the run has been canceled. |
| `metadata` | Application metadata that should travel with the run. |

!!! note "Policy enforcement"
    In this phase, permissions and budgets are typed runtime metadata. A later policy layer can enforce them before side effects, but applications can already render and inspect the same fields today.

## Run Events

Existing stream events such as `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`, and `TaskLLMStreamEvent` remain the transport-compatible event objects. `RunEvent` is the normalized application-facing envelope for those events.

```python
from protolink import InMemoryEventSink, RunContext

sink = InMemoryEventSink()

async for task_event in agent.handle_task_streaming(task):
    await sink.emit_task_event(task_event, context=RunContext.from_task(task))

events = sink.to_list()
```

Each `RunEvent` includes:

| Field | Description |
|------|-------------|
| `version` | Stable run-event envelope version. |
| `type` | Normalized event type such as `task.status`, `task.artifact`, `task.progress`, `task.error`, or `llm.stream`. |
| `run_id` | Logical run identifier from `RunContext`. |
| `task_id` | Task correlated with the event. |
| `agent_name` | Agent that emitted or handled the event. |
| `sequence` | Monotonic event sequence assigned by the sink. |
| `step` | Optional LLM or runtime step. |
| `severity` | `info`, `warning`, or `error` for renderers and logs. |
| `summary` | Short progress text for CLIs, UIs, and logs. |
| `payload` | Full original task-event payload. |
| `final` | Whether the source event marks a final boundary. |

`RunEvent.from_task_event(event)` can also recover context from the final task payload when the event includes a serialized task.

## Event Sinks

`EventSink` is the protocol for consumers of normalized `RunEvent` objects. `InMemoryEventSink` is the built-in implementation for tests, local apps, and replay tooling.

```python
from protolink import InMemoryEventSink, RunEvent

sink = InMemoryEventSink()
await sink.emit(RunEvent(type="task.progress", summary="Halfway done"))

assert sink.to_list()[0]["sequence"] == 1
```

Applications can implement their own sinks for terminal rendering, WebSocket fanout, database persistence, or custom observability systems without changing agent execution code.

## Golden Run Tests

Golden-run tests use deterministic model/tool fixtures and assert the normalized runtime contract. They are useful for application integrations because they lock down the event and artifact sequence without depending on live model providers.

```python
from protolink import Agent, AgentCard, InMemoryEventSink, RunContext, Task, create_llm

llm = create_llm("mock", default_response="done")
agent = Agent(
    AgentCard(name="tester", description="Golden test agent", url="runtime://tester"),
    llm=llm,
    verbosity=0,
)

task = Task.create_infer(prompt="Produce a result")
RunContext(run_id="run_golden", session_id="session_golden").attach_to_task(task)

sink = InMemoryEventSink()
async for event in agent.handle_task_streaming(task):
    await sink.emit_task_event(event, context=RunContext.from_task(task))

snapshot = [
    {
        "sequence": item["sequence"],
        "type": item["type"],
        "summary": item["summary"],
        "final": item["final"],
    }
    for item in sink.to_list()
]
```

Use this style for runtime compatibility tests: assert the stable event envelope, task state, final artifacts, and context propagation. Keep volatile fields such as timestamps, UUIDs, and artifact IDs out of the golden snapshot unless the test explicitly controls them.

## Relationship To Telemetry

Runtime events and telemetry serve different layers:

- `RunEvent` is for live application progress, terminal rendering, stream snapshots, and runtime assertions.
- `LocalTraceTelemetry` is for replayable traces, spans, metrics, redacted payloads, and observability backends.

Both share the same `run_id`, `trace_id`, `task_id`, and agent metadata through `RunContext`, so a local UI can show live progress while telemetry records the detailed trace behind it.
