import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Telemetry

The Telemetry subsystem provides standard observable tracing to agent task execution, tool calling, and LLM inference. Protolink supports a non-invasive integration with external tracing services using Python's `contextvars`. This means it tracks nested traces, spans, and runs in the background without cluttering core execution method signatures.

Protolink includes a built-in local trace recorder and native integrations for **[Langfuse](https://langfuse.com/)** and **[LangSmith](https://www.langchain.com/langsmith)**.

<ApiSurface
  eyebrow="Observability module"
  title="Telemetry"
  path="protolink.telemetry"
  description="The tracing layer for task runs, tool calls, LLM spans, context usage, cost estimates, redacted local traces, and optional Langfuse or LangSmith export."
  pills={[
    "LocalTraceTelemetry",
    "Langfuse",
    "LangSmith",
    "LLM metrics",
    "RedactionPolicy",
  ]}
  cards={[
    {
      title: "Trace locally",
      text: "Record nested spans and replayable JSONL traces without requiring an external service.",
      code: "LocalTraceTelemetry",
    },
    {
      title: "Export",
      text: "Send compatible trace data to Langfuse or LangSmith when those optional integrations are installed.",
      code: "protolink[telemetry]",
    },
    {
      title: "Measure models",
      text: "Capture context pressure, latency, token usage, and estimated cost around LLM calls.",
      code: "llm_call_metrics",
    },
    {
      title: "Protect data",
      text: "Apply the shared redaction policy before common secrets are persisted or exported.",
      code: "RedactionPolicy",
    },
  ]}
/>

## How telemetry fits into execution

Telemetry is an `Agent` lifecycle boundary, not a replacement for runtime events or reports. When `agent.telemetry` is set, the Agent awaits coarse hooks around the task, each direct task-level tool call, and the complete `LLM.infer()` cycle. While inference is running, it also forwards provider-neutral loop events to `on_llm_event()`.

```text
on_task_start
├── on_tool_start → on_tool_end
└── on_llm_start
    ├── on_llm_event: context_prepared
    ├── on_llm_event: llm_call_metrics
    ├── on_llm_event: tool_start → tool_result | tool_error
    ├── on_llm_event: agent_call_start → agent_call_result | agent_call_error
    └── on_llm_end
on_task_end
```

The exact middle events depend on the action loop. A simple inference can emit context, call, response, action, and final events; multi-step inference can add streamed chunks, retries, tool operations, delegated-agent operations, budget decisions, and more. `LocalTraceTelemetry` retains those detailed events. The hosted backends currently inherit the base no-op implementation of `on_llm_event()`, so Langfuse and LangSmith receive the coarse task, LLM, and explicit tool lifecycle only.

Telemetry is non-authoritative when attached to an Agent. The runtime catches hook exceptions, logs the first failure for each hook name, and continues with the task, LLM, or tool result unchanged. This isolation applies to unary and streaming task lifecycles. Calling a telemetry implementation's hook directly still follows that implementation's own exception contract.

:::info[Telemetry versus runtime reporting]

Use telemetry for detailed traces, span hierarchy, observability export, and local debugging. Use `RunEvent`, `RunRecorder`, and `RunReport` from the [Runtime](runtime.md) layer for the stable application-facing event envelope, durable run summaries, replay, and regression assertions. An application can use both surfaces on the same Agent.

:::

:::note[Direct LLM calls]

Attaching telemetry to an Agent instruments calls made through that Agent. A direct `llm.infer()` call does not discover an Agent's telemetry object; pass an `event_callback` when you need its live provider-neutral events outside Agent execution.

:::

## Installation

Telemetry dependencies are handled as optional plugins. To use a telemetry integration, you must install its corresponding library:

```bash
# Install telemetry with langfuse and langsmith
uv add "protolink[telemetry]"

# Or install telemetry with just langfuse
uv add langfuse
# Or install telemetry with just langsmith
uv add langsmith

# Optional: improve local token estimates for LLM metrics
uv add "protolink[metrics]"
```

## Setup & Usage

To enable observability, instantiate your preferred telemetry tracker and inject it into your `Agent`. Tasks executed by this agent will now automatically trace their internal states and synchronize with your observability platform.

### Local Trace Example

`LocalTraceTelemetry` records task traces in memory and can append replayable JSONL records to disk. It captures trace IDs, parent-child spans, model metadata, token estimates, raw inference-loop events, retry counts, and redacted payloads without requiring an external service.

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, Task

telemetry = LocalTraceTelemetry(path="traces.jsonl")

agent = Agent(
    card=AgentCard(
        name="local_observer",
        description="A locally traced agent",
        url="runtime://local-observer",
    ),
    telemetry=telemetry,
)

@agent.tool(name="add", description="Add two integers")
async def add(a: int, b: int) -> int:
    return a + b

result = await agent.handle_task(Task.create_tool_call(tool_name="add", args={"a": 2, "b": 3}))
records = telemetry.recorder.replay()
```

:::tip[View traces in Devtools]

Open the persisted telemetry file as a timeline and span waterfall:

```bash
protolink dashboard --traces traces.jsonl --open
```

:::

`--telemetry` is an alias for `--traces`, and the dashboard Telemetry view also accepts a JSONL file selected locally in the browser. It pages recent task records, rolls a bounded summary window through older history, and loads detail payloads lazily rather than reading the entire file into the initial page. See [Developer Tools](devtools.md#telemetry-jsonl) for shared `trace_id` grouping, scan and detail safeguards, partial-line handling, and local-data security guidance.

### LLM Metrics and Context Usage

When an agent has both an LLM and telemetry, Protolink records live context and budget metadata for every model call inside `LLM.infer()`. This includes the pre-call context manifest, latency, token usage, context-window pressure, and estimated cost. Provider-reported usage is used when available; otherwise Protolink estimates usage without requiring extra dependencies.

```python
from protolink import Agent, AgentCard, LLMModelProfile, LocalTraceTelemetry, Task, create_llm

telemetry = LocalTraceTelemetry(path="traces.jsonl")
llm = create_llm(
    "openai-compatible",
    model="my-model",
    metrics_profile=LLMModelProfile(
        context_window=128_000,
        input_cost_per_million=1.0,   # example value; use your provider's current pricing
        output_cost_per_million=5.0,  # example value; use your provider's current pricing
    ),
)

agent = Agent(
    card=AgentCard(name="budgeted", description="Observed LLM agent", url="runtime://budgeted"),
    llm=llm,
    telemetry=telemetry,
)

result = await agent.handle_task(Task.create_infer(prompt="Plan the next release"))
trace = telemetry.recorder.replay()[-1]
llm_span = next(span for span in trace["spans"] if span["kind"] == "llm")
print(llm_span["metadata"]["llm_metrics"])
```

The same data is emitted live as `context_prepared`, `llm_context`, and `llm_call_metrics` events through `event_callback`, so terminal apps can render a status line such as context used, call latency, and session cost while the agent is still running.

Local trace telemetry and runtime reports share the same default `RedactionPolicy`, so common secret-bearing fields such as API keys, tokens, passwords, authorization headers, and credentials are masked consistently before data is persisted.

:::note[Cost estimates]

Protolink does not ship a fixed provider pricing catalog. Prices and context windows are application-owned metadata passed through `LLMModelProfile`, which keeps the core package stable and avoids stale billing assumptions.

:::
### Langfuse Example

The `LangfuseTelemetry` tracks tasks as traces, and LLM/Tool executions as spans/generations.

```python
import os
from protolink.telemetry import LangfuseTelemetry
from protolink.agents.base import Agent

# Ensure environment variables are set:
# os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
# os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
# os.environ["LANGFUSE_HOST"] = "https://cloud.langfuse.com"

# Initialize tracking
telemetry_tracker = LangfuseTelemetry()

# Inject into an agent
agent = Agent(
    card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"},
    telemetry=telemetry_tracker
)
```

### LangSmith Example

The `LangSmithTelemetry` uses the `RunTree` API to track tasks hierarchically.

```python
import os
from protolink.telemetry import LangSmithTelemetry
from protolink.agents.base import Agent

# Ensure environment variables are set:
# os.environ["LANGCHAIN_API_KEY"] = "lsv2_pt_..."
# os.environ["LANGCHAIN_PROJECT"] = "my-protolink-project"

# Initialize tracking
telemetry_tracker = LangSmithTelemetry()

# Inject into an agent
agent = Agent(
    card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"},
    telemetry=telemetry_tracker
)
```

## Multiplexing Telemetry

If you want to broadcast telemetry events to multiple trackers simultaneously, you can use the `MultiTelemetry` class:

```python
from protolink.telemetry import LangfuseTelemetry, LangSmithTelemetry, MultiTelemetry
from protolink.agents.base import Agent

# Initialize tracking
langfuse_tracker = LangfuseTelemetry()
langsmith_tracker = LangSmithTelemetry()
multi_tracker = MultiTelemetry([langfuse_tracker, langsmith_tracker])

# Inject into an agent
agent = Agent(
    card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"},
    telemetry=multi_tracker
)
```

`MultiTelemetry` awaits trackers sequentially in list order. It does not isolate failures or run trackers concurrently: if a custom tracker raises, later trackers do not receive that hook and the exception reaches the Agent. The built-in Langfuse and LangSmith lifecycle methods catch provider-operation failures and log warnings, but constructor and dependency errors still propagate.

## Setting Telemetry Dynamically

You can also change or assign a telemetry tracker after agent initialization using the `.telemetry` property:

```python
agent = Agent(card={"name": "ObserverAgent", "description": "Observed agent", "url": "runtime://observer"})

# Later in your code...
agent.telemetry = LangfuseTelemetry()
```

The setter accepts a `Telemetry` instance or `None` and performs no runtime validation. Change it between tasks whenever possible. Replacing a tracker during an active task can give the new tracker an end hook without its matching start hook, while the previous tracker keeps unfinished provider context.

## Creating Custom Telemetry Implementations

If you wish to integrate with a different observability platform (e.g., Datadog, Prometheus, Arize Phoenix), subclass `Telemetry` and implement its six abstract asynchronous hooks. Override `on_llm_event()` only when the backend also needs detailed inference-loop events; the base implementation deliberately returns `None`.

```python
from typing import Any
from protolink.models import Task, Part
from protolink.telemetry.base import Telemetry

class MyCustomTelemetry(Telemetry):
    async def on_task_start(self, task: Task, agent_name: str) -> Any:
        pass
        
    async def on_task_end(self, task: Task, result: Task, agent_name: str) -> Any:
        pass
        
    async def on_llm_start(
        self,
        prompt: str,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        pass
        
    async def on_llm_end(self, response: Part) -> Any:
        pass
        
    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        pass
        
    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
        pass

    async def on_llm_event(self, event: dict[str, Any]) -> Any:
        pass
```

Hooks are awaited inline by the Agent. A custom implementation should therefore avoid blocking I/O in the event loop, maintain per-task state with `contextvars` or another concurrency-safe mechanism, and decide explicitly whether export failures should propagate or be converted into warnings. Return values are permitted by the abstract contract but are ignored by the current Agent runtime.

## Example Code

Here is a complete example demonstrating telemetry tracking with an `Agent` using Langfuse:

```python
import asyncio

from protolink import Agent, AgentCard, Task, create_llm
from protolink.telemetry import LangfuseTelemetry


async def main() -> None:
    # OPENAI_API_KEY and the Langfuse environment variables must be set.
    llm = create_llm("openai", model="gpt-4o-mini")
    telemetry = LangfuseTelemetry()

    agent = Agent(
        card=AgentCard(
            name="HelperAgent",
            description="Observed helper",
            url="runtime://helper",
        ),
        llm=llm,
        telemetry=telemetry,
    )

    result = await agent.handle_task(
        Task.create_infer(prompt="Give me one concise release-planning tip.")
    )
    print(result.get_last_part_content())


asyncio.run(main())
```

---

## Telemetry API reference

The package-level public surface is:

```python
from protolink.telemetry import (
    LangfuseTelemetry,
    LangSmithTelemetry,
    LocalTraceRecorder,
    LocalTraceTelemetry,
    MultiTelemetry,
    Telemetry,
    TraceEvent,
    TraceRecord,
    TraceSpan,
)
```

`LocalTraceRecorder` and `LocalTraceTelemetry` are also available from the top-level `protolink` package. The hosted providers, multiplexer, abstract contract, and trace dataclasses are imported from `protolink.telemetry`.

### Telemetry

<ApiReference
  kind="abstract class"
  path="protolink.telemetry.Telemetry"
  signature={`class Telemetry()`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L7"
>

Define the asynchronous lifecycle contract shared by every telemetry backend. The class stores no state and supplies no constructor arguments. Concrete implementations decide how to preserve task-local hierarchy, serialize values, export data, and handle backend failures.

<ApiSection title="Abstract methods">
  <ApiFields ariaLabel="Telemetry abstract methods">
    <ApiField name="on_task_start" type="async method" required>
      Begin task-level telemetry before the Agent executes the task.
    </ApiField>
    <ApiField name="on_task_end" type="async method" required>
      Finalize task-level telemetry with the Task returned by execution, or with the original Task on the Agent's exception path.
    </ApiField>
    <ApiField name="on_llm_start" type="async method" required>
      Begin the span or run that surrounds one complete <code>LLM.infer()</code> operation.
    </ApiField>
    <ApiField name="on_llm_end" type="async method" required>
      Finalize that LLM operation after inference returns a response Part.
    </ApiField>
    <ApiField name="on_tool_start" type="async method" required>
      Begin an explicit task-level tool operation.
    </ApiField>
    <ApiField name="on_tool_end" type="async method" required>
      Finalize an explicit task-level tool operation with either a result or an error string.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Concrete extension hook">
  <ApiFields ariaLabel="Telemetry concrete extension hook">
    <ApiField name="on_llm_event" type="async method">
      Optional detailed inference-event hook. Its base implementation is a no-op returning <code>None</code>, so older or coarse-grained providers remain instantiable without implementing it.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Telemetry construction errors">
    <ApiField name="TypeError">
      Instantiating <code>Telemetry</code> directly, or instantiating a subclass that has not implemented all six abstract methods, fails through Python's ABC machinery.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Inline execution">
  Agent awaits every hook in its execution path; hook return values are currently ignored. The abstract return type is <code>Any</code> so providers may return context for direct callers, but implementations that perform slow synchronous export work can delay the task.
</ApiCallout>

</ApiReference>

## Local tracing API

The local backend is dependency-free. One `LocalTraceTelemetry` instance manages lifecycle state; its `LocalTraceRecorder` owns completed records in memory and, optionally, appends them to JSONL. `TraceRecord`, `TraceSpan`, and `TraceEvent` are the structured objects retained in memory.

### default_redactor

<ApiReference
  kind="function"
  path="protolink.telemetry.local.default_redactor"
  signature={`default_redactor(
    value: Any,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L94"
>

Best-effort normalize common runtime values and recursively mask fields recognized by the shared `DEFAULT_REDACTION_POLICY`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="default_redactor parameters">
    <ApiField name="value" type="Any" required>
      Nested runtime value. Objects with <code>to_dict()</code>, dataclass instances, mappings, lists, tuples, and sets receive special handling; ordinary non-JSON-native leaves fall back to <code>str(value)</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="default_redactor return">
    <ApiField name="redacted" type="Any">
      Best-effort normalized value with case-insensitive secret fields masked. Default sensitive names include API key, authorization, client secret, credentials, password, secret, and token variants, including common suffixed forms.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="default_redactor errors">
    <ApiField name="serialization or user-object error">
      Exceptions raised by an object's custom <code>to_dict()</code> or dataclass conversion are not caught.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Import path">
  This helper is public in <code>protolink.telemetry.local</code> but is not re-exported by <code>protolink.telemetry</code>. Most applications configure redaction through <code>LocalTraceTelemetry(redactor=...)</code> instead of calling it directly.
</ApiCallout>

<ApiCallout label="Custom serializer boundary">
  A custom <code>to_dict()</code> result or a dataclass field is not passed through a second complete normalization cycle. If it contains an unsupported leaf object, later JSONL encoding can still raise <code>TypeError</code>.
</ApiCallout>

</ApiReference>

### LocalTraceTelemetry

<ApiReference
  kind="class"
  path="protolink.telemetry.LocalTraceTelemetry"
  signature={`LocalTraceTelemetry(
    recorder: LocalTraceRecorder | None = None,
    *,
    path: str | Path | None = None,
    redactor: Callable[[Any], Any] | None = None,
    capture_payloads: bool = True,
    max_traces: int = 1000,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L266"
>

Record one replayable local trace per completed Agent task. Task, LLM, explicit tool, and inference-selected child operations are connected through IDs stored in `contextvars`, so concurrent async task contexts do not need trace objects passed through every runtime call.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LocalTraceTelemetry constructor parameters">
    <ApiField name="recorder" type="LocalTraceRecorder | None" defaultValue="None">
      Existing recorder to use. Supplying one is useful for sharing completed trace storage across agents or tests. Because the implementation selects it with <code>recorder or LocalTraceRecorder(...)</code>, a custom recorder with false truthiness is replaced rather than retained.
    </ApiField>
    <ApiField name="path" type="str | Path | None" defaultValue="None">
      JSONL destination used only when the constructor creates its own recorder. It is ignored when a truthy <code>recorder</code> is supplied. Parent directories are created on the first completed trace.
    </ApiField>
    <ApiField name="redactor" type="Callable[[Any], Any] | None" defaultValue="None">
      Application-specific transformation applied after default normalization and secret masking at explicit capture points: span inputs and outputs, event payloads, span metadata, and context or budget mappings. Generated trace status and metric-rollup fields are assigned directly.
    </ApiField>
    <ApiField name="capture_payloads" type="bool" defaultValue="True">
      When true, retain span inputs and outputs plus event payloads. When false, those values become <code>None</code> or an empty mapping; span and trace metadata, event types, timing, IDs, statuses, and metrics are still recorded.
    </ApiField>
    <ApiField name="max_traces" type="int" defaultValue="1000">
      In-memory retention limit passed to the automatically created recorder. Positive values keep only the newest records. Zero and negative values disable truncation, not recording.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="LocalTraceTelemetry attributes">
    <ApiField name="recorder" type="LocalTraceRecorder">
      Recorder receiving a trace when <code>on_task_end()</code> completes.
    </ApiField>
    <ApiField name="redactor" type="Callable[[Any], Any] | None">
      Exact custom callable supplied at construction.
    </ApiField>
    <ApiField name="capture_payloads" type="bool">
      Current payload-capture switch. It is a normal mutable attribute, so applications can change it, although changing it during a task can produce a mixed-detail trace.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LocalTraceTelemetry constructor errors">
    <ApiField name="constructor error">
      The constructor performs no explicit validation. Most path, redactor, serialization, and persistence errors occur later in lifecycle hooks and propagate to the Agent.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Redaction order">
  Default redaction always runs first. A custom redactor can remove more data, but it receives already masked values and cannot recover secrets. Its return value is not normalized again, so returning a non-JSON-serializable object can make JSONL persistence fail.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import LocalTraceRecorder, LocalTraceTelemetry

shared = LocalTraceRecorder(path="var/traces.jsonl", max_traces=250)
telemetry = LocalTraceTelemetry(
    recorder=shared,
    capture_payloads=True,
    redactor=lambda value: value,
)
```

</ApiSection>

</ApiReference>

### LocalTraceTelemetry lifecycle methods

<ApiReference
  kind="async methods"
  path="protolink.telemetry.LocalTraceTelemetry lifecycle"
  signature={`async on_task_start(task: Task, agent_name: str) -> Any
async on_task_end(task: Task, result: Task, agent_name: str) -> Any
async on_llm_start(
    prompt: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any
async on_llm_end(response: Part) -> Any
async on_tool_start(tool_name: str, args: dict[str, Any]) -> Any
async on_tool_end(
    tool_name: str,
    result: Any,
    error: str | None = None,
) -> Any
async on_llm_event(event: dict[str, Any]) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L486"
>

Implement the complete telemetry contract and translate it into a local trace hierarchy. All seven methods return `None` implicitly; lifecycle state is held in the current context and the finished `TraceRecord` is committed through the recorder.

<ApiSection title="Task lifecycle">
  <ApiFields ariaLabel="LocalTraceTelemetry task lifecycle">
    <ApiField name="on_task_start">
      Reuse a truthy <code>task.metadata["trace_id"]</code> or generate a UUID, write it back to the Task, create a running <code>TraceRecord</code>, reset the context-local span stack, and open a root <code>kind="task"</code> span containing the serialized task.
    </ApiField>
    <ApiField name="on_task_end">
      If no trace is active, return without action. Otherwise close the nearest active task span, derive error state only from <code>result.metadata["error"]</code>, set final-state and retry metadata, append the record through the recorder, and clear local context.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="LLM lifecycle">
  <ApiFields ariaLabel="LocalTraceTelemetry LLM lifecycle">
    <ApiField name="on_llm_start">
      Open one <code>kind="llm"</code> span named <code>"LLM Call"</code>. Metadata includes the model, any supplied cost field, prompt character count, a four-character token estimate, and the caller metadata merged afterward.
    </ApiField>
    <ApiField name="on_llm_end">
      Close the nearest active LLM span, capture response content, and add output character count plus the same local token estimate.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Explicit tool lifecycle">
  <ApiFields ariaLabel="LocalTraceTelemetry tool lifecycle">
    <ApiField name="on_tool_start">
      Open a <code>kind="tool"</code> child span with the requested arguments and metadata identifying <code>source="task"</code>.
    </ApiField>
    <ApiField name="on_tool_end">
      Close the nearest active tool span. A truthy error marks it <code>status="error"</code> and stores the message; otherwise status remains <code>"ok"</code>, even when the result is <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Detailed inference events">
  <ApiFields ariaLabel="LocalTraceTelemetry inference event handling">
    <ApiField name="context_prepared">
      Store a mapping-valued <code>manifest</code> in the current span's <code>context_manifest</code> metadata, then append the chronological event.
    </ApiField>
    <ApiField name="llm_context">
      Store a mapping-valued <code>context</code> in the current span metadata, then append the event.
    </ApiField>
    <ApiField name="budget_warning | budget_exceeded">
      Append a mapping-valued <code>decision</code> to trace-level <code>budget_decisions</code>, then append the event.
    </ApiField>
    <ApiField name="llm_call_metrics">
      Aggregate call count, latency, usage, estimated-call count, context pressure, window size, cost, and currency into both the current span and the trace before appending the event.
    </ApiField>
    <ApiField name="tool_start">
      Open a nested <code>kind="tool"</code> span with <code>source="llm_loop"</code>, tool name, step, and arguments.
    </ApiField>
    <ApiField name="tool_result | tool_error">
      Append the event once, close the nearest tool span, attach result/name/step, and mark an error from <code>message</code> for <code>tool_error</code>.
    </ApiField>
    <ApiField name="agent_call_start">
      Open a nested <code>kind="agent_call"</code> span containing agent, action, step, and payload.
    </ApiField>
    <ApiField name="agent_call_result | agent_call_error">
      Append the event once and close the nearest delegated-agent span, using <code>message</code> as its error when appropriate.
    </ApiField>
    <ApiField name="llm_parse_error">
      Set trace retry count to the maximum of its existing value and the event's <code>retry_count</code>, falling back to <code>parse_failures</code>.
    </ApiField>
    <ApiField name="llm_retry">
      Increment trace retry count by one.
    </ApiField>
    <ApiField name="other event types">
      Preserve the full redacted event chronologically. A missing <code>type</code> is normalized to <code>"llm_event"</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Fallback behavior">
  <ApiFields ariaLabel="LocalTraceTelemetry fallback behavior">
    <ApiField name="no active trace">
      LLM, tool, and event hooks return without recording anything.
    </ApiField>
    <ApiField name="no matching active span">
      Span-closing calls return without error. Events still attach to the trace and to the current span when one exists.
    </ApiField>
    <ApiField name="token usage unavailable">
      Prompt and response estimates use <code>max(1, len(str(value)) // 4)</code> for non-empty content and zero for empty content. This tracer-level estimate does not use <code>tiktoken</code>; provider-normalized metrics can separately carry richer usage.
    </ApiField>
    <ApiField name="non-numeric metrics">
      Values that cannot be converted with <code>float()</code> are skipped during aggregation rather than raising.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LocalTraceTelemetry lifecycle errors">
    <ApiField name="redactor error">
      Exceptions from the custom redactor propagate when the hook is called directly. Agent catches and logs them at its observability boundary.
    </ApiField>
    <ApiField name="serialization or filesystem error">
      Task/result conversion, malformed metric values used by explicit integer conversion, directory creation, JSON encoding, and file writes may propagate from a direct hook call. Task-end cleanup runs in <code>finally</code>, so the active local trace frame is still cleared when recording fails; Agent execution also isolates that failure.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Unfinished child spans">
  If inference raises, Agent does not call <code>on_llm_end()</code>. The subsequent task-end hook closes the root task span by kind but does not synthesize an end time or error for the still-open LLM child span, so replay can contain a child with <code>ended_at=None</code>.
</ApiCallout>

</ApiReference>

## Base lifecycle method reference

### Telemetry.on_task_start

<ApiReference
  kind="abstract async method"
  path="protolink.telemetry.Telemetry.on_task_start"
  signature={`async on_task_start(
    task: Task,
    agent_name: str,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L16"
>

Receive control immediately before an Agent begins executing a task. Implementations normally allocate a root trace or run and bind it to the current async context.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_task_start parameters">
    <ApiField name="task" type="Task" required>
      The live mutable Task about to execute. A backend may inspect its ID, state, parts, metadata, and attached run context. Mutating it affects the task seen by the runtime; <code>LocalTraceTelemetry</code> intentionally adds or reuses <code>task.metadata["trace_id"]</code>.
    </ApiField>
    <ApiField name="agent_name" type="str" required>
      The current Agent card's name. It is not independently normalized or validated by the hook contract.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_task_start return">
    <ApiField name="context" type="Any">
      Optional backend-specific context. The current Agent discards this value, so built-in implementations return <code>None</code> implicitly and retain state with <code>contextvars</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="on_task_start errors">
    <ApiField name="implementation error">
      A direct call can propagate an implementation error. Agent invokes the hook through its best-effort telemetry boundary, logs the first failure for this hook name, and continues task execution.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Telemetry.on_task_end

<ApiReference
  kind="abstract async method"
  path="protolink.telemetry.Telemetry.on_task_end"
  signature={`async on_task_end(
    task: Task,
    result: Task,
    agent_name: str,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L29"
>

Finalize the active task trace after execution. On the normal path, `result` is the Task returned by `execute_task()`. When execution raises, Agent invokes the hook with the original task as both `task` and `result`, then re-raises the execution exception.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_task_end parameters">
    <ApiField name="task" type="Task" required>
      Original task object passed to <code>Agent.handle_task()</code>.
    </ApiField>
    <ApiField name="result" type="Task" required>
      Completed Task on success. On the current exception path this is the original Task, which may not contain an <code>error</code> metadata field.
    </ApiField>
    <ApiField name="agent_name" type="str" required>
      Name of the Agent that handled the task.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_task_end return">
    <ApiField name="context" type="Any">
      Optional provider value; ignored by Agent. Built-in backends return <code>None</code> implicitly.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Failure-path detail">
  A backend cannot infer every execution exception from <code>result.metadata</code>. In particular, the local backend marks a trace as failed only when that metadata contains a truthy <code>error</code> value. A raised execution error without that metadata can therefore produce a locally recorded trace whose status is <code>"ok"</code>.
</ApiCallout>

<ApiCallout label="Hook failure isolation">
  Agent calls this hook once from its task-finalization boundary. A hook failure is logged and does not replace the task result or the execution exception already in flight.
</ApiCallout>

</ApiReference>

### Telemetry.on_llm_start

<ApiReference
  kind="abstract async method"
  path="protolink.telemetry.Telemetry.on_llm_start"
  signature={`async on_llm_start(
    prompt: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L43"
>

Begin observability around one complete `LLM.infer()` cycle. This is broader than one provider request: a single inference can call the model repeatedly while resolving tools, delegated agents, parse retries, and the final answer.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_llm_start parameters">
    <ApiField name="prompt" type="str" required>
      User inference prompt extracted from the Task's infer Part. It is the query supplied to <code>LLM.infer()</code>, not the fully compiled provider conversation or system prompt.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Best available model identifier, selected from the LLM's <code>model_name</code> or <code>model</code> attribute. It is <code>None</code> when neither exists.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional provider context. Agent currently passes <code>agent_name</code>, <code>task_id</code>, <code>trace_id</code>, <code>provider</code>, and <code>model_type</code>. Direct callers may pass a different mapping.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_llm_start return">
    <ApiField name="context" type="Any">
      Optional provider generation/span context; ignored by Agent.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="No matching end on inference failure">
  Agent calls <code>on_llm_end()</code> only after <code>LLM.infer()</code> returns. If inference raises, the task-end hook still runs, but an implementation must decide whether and how to close an unfinished LLM span.
</ApiCallout>

<ApiCallout label="Start-hook failure">
  If this hook raises through Agent, the runtime logs the failure and still starts inference. The failure does not suppress the matching end-hook attempt after a successful infer result.
</ApiCallout>

</ApiReference>

### Telemetry.on_llm_end

<ApiReference
  kind="abstract async method"
  path="protolink.telemetry.Telemetry.on_llm_end"
  signature={`async on_llm_end(
    response: Part,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L63"
>

Finish the active LLM operation after the controlled inference loop has produced its final Part.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_llm_end parameters">
    <ApiField name="response" type="Part" required>
      Final Part returned by <code>LLM.infer()</code>. Hosted providers extract <code>response.content</code>; the local backend stores and estimates tokens from the same content.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_llm_end return">
    <ApiField name="context" type="Any">
      Optional backend value; ignored by Agent. Built-ins return <code>None</code> implicitly.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Telemetry.on_tool_start

<ApiReference
  kind="abstract async method"
  path="protolink.telemetry.Telemetry.on_tool_start"
  signature={`async on_tool_start(
    tool_name: str,
    args: dict[str, Any],
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L75"
>

Begin a span for a tool call executed from an explicit task `tool_call` Part. Tools chosen inside the LLM action loop are surfaced instead through `on_llm_event()` as `tool_start` events.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_tool_start parameters">
    <ApiField name="tool_name" type="str" required>
      Registered tool name resolved by Agent.
    </ApiField>
    <ApiField name="args" type="dict[str, Any]" required>
      Requested keyword arguments before runtime policy authorization. A policy or approval handler can subsequently modify the actual arguments passed to the tool.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_tool_start return">
    <ApiField name="context" type="Any">
      Optional provider span context; ignored by Agent.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Missing tools">
  Agent resolves the tool before invoking this hook. An unknown tool returns an error Part without producing <code>on_tool_start()</code> or <code>on_tool_end()</code>.
</ApiCallout>

<ApiCallout label="Start-hook errors">
  Agent isolates this observer failure and continues through policy authorization and tool execution. Direct hook calls can still propagate according to the implementation.
</ApiCallout>

</ApiReference>

### Telemetry.on_tool_end

<ApiReference
  kind="abstract async method"
  path="protolink.telemetry.Telemetry.on_tool_end"
  signature={`async on_tool_end(
    tool_name: str,
    result: Any,
    error: str | None = None,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L88"
>

Finish an explicit task-level tool span. Agent sends the returned value on success; policy failures, cancellation, and tool exceptions are represented by `result=None` plus a string error.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_tool_end parameters">
    <ApiField name="tool_name" type="str" required>
      Registered tool name associated with the active operation.
    </ApiField>
    <ApiField name="result" type="Any" required>
      Tool return value on success. Agent supplies <code>None</code> on its caught error paths, so a successful tool that legitimately returns <code>None</code> is distinguished by the separate <code>error</code> argument.
    </ApiField>
    <ApiField name="error" type="str | None" defaultValue="None">
      String form of the failure, or <code>None</code> for success.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_tool_end return">
    <ApiField name="context" type="Any">
      Optional backend value; ignored by Agent.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="End-hook errors">
  Agent logs and isolates this observer failure. A successful tool result remains successful, a tool error keeps its original error, and the hook is not called a second time merely because telemetry export failed.
</ApiCallout>

</ApiReference>

### Telemetry.on_llm_event

<ApiReference
  kind="async method"
  path="protolink.telemetry.Telemetry.on_llm_event"
  signature={`async on_llm_event(
    event: dict[str, Any],
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/base.py#L102"
>

Receive a provider-neutral event emitted while `LLM.infer()` is running. This optional high-detail hook carries context manifests, model-call metrics, chunks, actions, retries, tools, delegated agents, budget decisions, and final outputs without expanding the coarse lifecycle signature.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="on_llm_event parameters">
    <ApiField name="event" type="dict[str, Any]" required>
      Event mapping whose <code>type</code> key selects its schema. Consumers should tolerate unknown event types and additive fields because providers and inference paths emit different detail.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="on_llm_event return">
    <ApiField name="None" type="None">
      The base implementation returns <code>None</code>. Agent ignores return values from overrides.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Hosted-provider behavior">
  <code>LangfuseTelemetry</code> and <code>LangSmithTelemetry</code> do not override this method in the current implementation. Use <code>MultiTelemetry</code> with a local or custom detailed tracker when you need hosted coarse traces and complete local inference events together.
</ApiCallout>

<ApiCallout label="Observer failure">
  Agent isolates telemetry-hook exceptions. For direct <code>LLM.infer(event_callback=...)</code> usage, the inference loop logs the first callback exception and disables that callback for the rest of the infer call.
</ApiCallout>

</ApiReference>

## Local recorder API

### LocalTraceRecorder

<ApiReference
  kind="class"
  path="protolink.telemetry.LocalTraceRecorder"
  signature={`LocalTraceRecorder(
    path: str | Path | None = None,
    *,
    max_traces: int = 1000,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L193"
>

Retain completed `TraceRecord` objects in process and optionally append one serialized record per line to a JSONL file.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LocalTraceRecorder constructor parameters">
    <ApiField name="path" type="str | Path | None" defaultValue="None">
      Optional JSONL file. Truthy values are converted to <code>Path(path).expanduser()</code>; <code>None</code> and other falsey values such as an empty string disable file persistence.
    </ApiField>
    <ApiField name="max_traces" type="int" defaultValue="1000">
      Positive in-memory retention limit. After each append, only the newest <code>max_traces</code> objects remain. Zero or a negative value keeps every trace.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="LocalTraceRecorder attributes">
    <ApiField name="path" type="Path | None">
      Expanded destination or <code>None</code>.
    </ApiField>
    <ApiField name="max_traces" type="int">
      Mutable retention value consulted on each subsequent <code>record()</code>.
    </ApiField>
    <ApiField name="traces" type="list[TraceRecord]">
      Live retained record objects in completion order. This list is public and mutable; use <code>replay()</code> when callers need serialized dictionaries.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Memory and disk retention are independent">
  The retention limit affects only <code>traces</code>. JSONL is append-only: truncating memory or calling <code>clear()</code> never removes lines already written to disk.
</ApiCallout>

</ApiReference>

### LocalTraceRecorder.record

<ApiReference
  kind="method"
  path="protolink.telemetry.LocalTraceRecorder.record"
  signature={`record(
    trace: TraceRecord,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L214"
>

Append a completed trace to memory, enforce the positive retention limit, and then append its dictionary representation to the configured JSONL destination.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LocalTraceRecorder record parameters">
    <ApiField name="trace" type="TraceRecord" required>
      Record object retained by identity in memory. The recorder performs no runtime type check; file persistence later expects a callable <code>to_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LocalTraceRecorder record return">
    <ApiField name="None" type="None">
      The method mutates recorder state and has no value return.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LocalTraceRecorder record errors">
    <ApiField name="AttributeError">
      File persistence is enabled and the supplied object has no suitable <code>to_dict()</code>.
    </ApiField>
    <ApiField name="TypeError">
      The serialized mapping still contains a value rejected by <code>json.dumps()</code>.
    </ApiField>
    <ApiField name="OSError">
      Parent-directory creation or append-mode UTF-8 writing fails.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Mutation before persistence">
  The trace is appended to memory before the file is opened. If JSON serialization or writing fails, the exception propagates but the in-memory trace remains recorded.
</ApiCallout>

</ApiReference>

### LocalTraceRecorder.replay

<ApiReference
  kind="method"
  path="protolink.telemetry.LocalTraceRecorder.replay"
  signature={`replay(
    trace_id: str | None = None,
) -> list[dict[str, Any]]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L235"
>

Serialize retained in-memory traces for inspection, tests, or a replay UI. This method does not read the JSONL file.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LocalTraceRecorder replay parameters">
    <ApiField name="trace_id" type="str | None" defaultValue="None">
      Exact trace-ID filter. Omit it to return every retained record in completion order. An unknown ID produces an empty list.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LocalTraceRecorder replay return">
    <ApiField name="records" type="list[dict[str, Any]]">
      Fresh dictionary serialization for each matching <code>TraceRecord</code>, including computed durations and nested serialized spans/events.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LocalTraceRecorder replay errors">
    <ApiField name="timestamp or serialization error">
      Malformed timestamps or manually inserted objects that violate the trace dataclass expectations can fail during <code>to_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### LocalTraceRecorder.clear

<ApiReference
  kind="method"
  path="protolink.telemetry.LocalTraceRecorder.clear"
  signature={`clear() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L231"
>

Remove every in-memory `TraceRecord` from the recorder.

<ApiSection title="Returns">
  <ApiFields ariaLabel="LocalTraceRecorder clear return">
    <ApiField name="None" type="None">
      The existing list is cleared in place.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="JSONL is preserved">
  This method deliberately does not truncate, replace, or delete the configured file. Use filesystem retention under explicit application control.
</ApiCallout>

</ApiReference>

### LocalTraceRecorder.load_jsonl

<ApiReference
  kind="class method"
  path="protolink.telemetry.LocalTraceRecorder.load_jsonl"
  signature={`load_jsonl(
    path: str | Path,
) -> list[dict[str, Any]]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L247"
>

Read an existing JSONL trace file without constructing a recorder or mutating in-memory state.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LocalTraceRecorder load_jsonl parameters">
    <ApiField name="path" type="str | Path" required>
      File path converted with <code>Path(path).expanduser()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="LocalTraceRecorder load_jsonl return">
    <ApiField name="records" type="list[dict[str, Any]]">
      Decoded non-empty lines in file order. A missing path returns an empty list. Blank or whitespace-only lines are skipped.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LocalTraceRecorder load_jsonl errors">
    <ApiField name="json.JSONDecodeError">
      Any non-empty malformed JSON line aborts the entire load; partial results are not returned.
    </ApiField>
    <ApiField name="OSError | UnicodeError">
      The path cannot be opened/read as UTF-8.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="No schema reconstruction">
  Each line is returned exactly as <code>json.loads()</code> decodes it. The method does not validate trace keys and does not reconstruct <code>TraceRecord</code>, <code>TraceSpan</code>, or <code>TraceEvent</code> instances.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import LocalTraceRecorder

records = LocalTraceRecorder.load_jsonl("~/protolink/traces.jsonl")
failed = [record for record in records if record.get("status") == "error"]
```

</ApiSection>

</ApiReference>

## Local trace data model

### TraceEvent

<ApiReference
  kind="dataclass"
  path="protolink.telemetry.TraceEvent"
  signature={`TraceEvent(
    type: str,
    timestamp: str = field(default_factory=_utc_now),
    span_id: str | None = None,
    payload: dict[str, Any] = field(default_factory=dict),
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L104"
>

Represent one point-in-time inference event. Events live in the trace-wide chronological list and, when a span is active, in that span's event list as well.

<ApiSection title="Fields">
  <ApiFields ariaLabel="TraceEvent fields">
    <ApiField name="type" type="str" required>
      Event discriminator such as <code>"context_prepared"</code>, <code>"llm_call_metrics"</code>, <code>"tool_result"</code>, or an application-defined value.
    </ApiField>
    <ApiField name="timestamp" type="str" defaultValue="current UTC ISO-8601 time">
      Serialized timestamp generated with timezone-aware <code>datetime.now(timezone.utc).isoformat()</code> when omitted.
    </ApiField>
    <ApiField name="span_id" type="str | None" defaultValue="None">
      ID of the active span when the event was recorded, or <code>None</code> when it belongs only to the trace.
    </ApiField>
    <ApiField name="payload" type="dict[str, Any]" defaultValue="{}">
      Event data created with a per-instance default factory. Local telemetry redacts it before construction; direct construction performs no validation or redaction.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Runtime validation">
  Dataclass annotations are not enforced at runtime. Direct callers can construct inconsistent values; downstream serialization and replay code assumes the documented shapes.
</ApiCallout>

</ApiReference>

### TraceEvent.to_dict

<ApiReference
  kind="method"
  path="protolink.telemetry.TraceEvent.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L118"
>

Convert the event with `dataclasses.asdict()`.

<ApiSection title="Returns">
  <ApiFields ariaLabel="TraceEvent to_dict return">
    <ApiField name="event" type="dict[str, Any]">
      Deep dataclass conversion containing <code>type</code>, <code>timestamp</code>, <code>span_id</code>, and <code>payload</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="JSON compatibility">
  Values captured through <code>LocalTraceTelemetry</code> are normalized before reaching the event. A manually constructed payload is only converted by <code>asdict()</code>; it is not independently redacted or guaranteed JSON-serializable.
</ApiCallout>

</ApiReference>

### TraceSpan

<ApiReference
  kind="dataclass"
  path="protolink.telemetry.TraceSpan"
  signature={`TraceSpan(
    id: str,
    trace_id: str,
    name: str,
    kind: str,
    parent_id: str | None = None,
    started_at: str = field(default_factory=_utc_now),
    ended_at: str | None = None,
    status: str = "ok",
    input: Any | None = None,
    output: Any | None = None,
    error: str | None = None,
    metadata: dict[str, Any] = field(default_factory=dict),
    events: list[TraceEvent] = field(default_factory=list),
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L123"
>

Represent one timed operation inside a local trace. The built-in tracer uses `kind` values `task`, `llm`, `tool`, and `agent_call`; parent IDs encode hierarchy while the record stores spans in a flat list.

<ApiSection title="Identity and hierarchy">
  <ApiFields ariaLabel="TraceSpan identity fields">
    <ApiField name="id" type="str" required>
      Unique span ID. Local telemetry generates a UUID.
    </ApiField>
    <ApiField name="trace_id" type="str" required>
      Owning trace ID.
    </ApiField>
    <ApiField name="name" type="str" required>
      Human-readable operation name such as <code>"LLM Call"</code> or <code>"Tool: add"</code>.
    </ApiField>
    <ApiField name="kind" type="str" required>
      Machine-readable operation category. Direct construction is not restricted to built-in values.
    </ApiField>
    <ApiField name="parent_id" type="str | None" defaultValue="None">
      Parent span ID. The root task span has no parent.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Timing and outcome">
  <ApiFields ariaLabel="TraceSpan timing and outcome fields">
    <ApiField name="started_at" type="str" defaultValue="current UTC ISO-8601 time">
      Start timestamp.
    </ApiField>
    <ApiField name="ended_at" type="str | None" defaultValue="None">
      End timestamp. It remains <code>None</code> for an open or abandoned span.
    </ApiField>
    <ApiField name="status" type="str" defaultValue={'"ok"'}>
      Outcome label. Local telemetry changes it to <code>"error"</code> only when ending the span with a truthy error string.
    </ApiField>
    <ApiField name="error" type="str | None" defaultValue="None">
      Captured error message.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Captured data">
  <ApiFields ariaLabel="TraceSpan captured data fields">
    <ApiField name="input" type="Any | None" defaultValue="None">
      Redacted operation input when payload capture is enabled.
    </ApiField>
    <ApiField name="output" type="Any | None" defaultValue="None">
      Redacted operation output once closed and when payload capture is enabled.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Redacted identifiers, source, steps, context manifests, and metric rollups. The default is per instance.
    </ApiField>
    <ApiField name="events" type="list[TraceEvent]" defaultValue="[]">
      Detailed events observed while this span was active. The default is per instance.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### TraceSpan.duration_ms and TraceSpan.to_dict

<ApiReference
  kind="property and method"
  path="protolink.telemetry.TraceSpan inspection"
  signature={`duration_ms: float | None
to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L146"
>

Inspect elapsed time and serialize the complete span.

<ApiSection title="Returns">
  <ApiFields ariaLabel="TraceSpan inspection returns">
    <ApiField name="duration_ms" type="float | None">
      <code>None</code> while <code>ended_at</code> is absent. Otherwise parse both ISO timestamps, subtract them, convert to milliseconds, and round to three decimal places.
    </ApiField>
    <ApiField name="to_dict()" type="dict[str, Any]">
      All dataclass fields plus computed <code>duration_ms</code>, with each child event serialized through <code>TraceEvent.to_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="TraceSpan inspection errors">
    <ApiField name="ValueError">
      A non-empty timestamp is not accepted by <code>datetime.fromisoformat()</code>.
    </ApiField>
    <ApiField name="AttributeError">
      A manually inserted item in <code>events</code> does not provide <code>to_dict()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="No monotonicity validation">
  The dataclass does not verify that <code>ended_at</code> is later than <code>started_at</code>; directly supplied timestamps can therefore produce a negative duration.
</ApiCallout>

</ApiReference>

### TraceRecord

<ApiReference
  kind="dataclass"
  path="protolink.telemetry.TraceRecord"
  signature={`TraceRecord(
    trace_id: str,
    task_id: str,
    agent_name: str,
    started_at: str = field(default_factory=_utc_now),
    ended_at: str | None = None,
    status: str = "running",
    metadata: dict[str, Any] = field(default_factory=dict),
    spans: list[TraceSpan] = field(default_factory=list),
    events: list[TraceEvent] = field(default_factory=list),
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L159"
>

Represent the top-level replay artifact for one task. The local backend retains a flat span list with parent IDs and a trace-wide chronological event list.

<ApiSection title="Identity">
  <ApiFields ariaLabel="TraceRecord identity fields">
    <ApiField name="trace_id" type="str" required>
      Trace correlation ID, normally reused from or written into task metadata.
    </ApiField>
    <ApiField name="task_id" type="str" required>
      Source Task ID.
    </ApiField>
    <ApiField name="agent_name" type="str" required>
      Agent name supplied to the task-start hook.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Timing and status">
  <ApiFields ariaLabel="TraceRecord timing and status fields">
    <ApiField name="started_at" type="str" defaultValue="current UTC ISO-8601 time">
      Trace creation time.
    </ApiField>
    <ApiField name="ended_at" type="str | None" defaultValue="None">
      Completion time assigned by <code>LocalTraceTelemetry.on_task_end()</code>.
    </ApiField>
    <ApiField name="status" type="str" defaultValue={'"running"'}>
      Starts as <code>"running"</code>; the local task-end hook sets <code>"error"</code> when result metadata contains a truthy error and <code>"ok"</code> otherwise.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Contents">
  <ApiFields ariaLabel="TraceRecord content fields">
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Agent/task state, final state, retry count, budget decisions, and trace-level metric rollups.
    </ApiField>
    <ApiField name="spans" type="list[TraceSpan]" defaultValue="[]">
      Flat operation list in start order.
    </ApiField>
    <ApiField name="events" type="list[TraceEvent]" defaultValue="[]">
      Chronological detailed inference events. Events associated with active spans also appear within the corresponding span.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### TraceRecord.duration_ms and TraceRecord.to_dict

<ApiReference
  kind="property and method"
  path="protolink.telemetry.TraceRecord inspection"
  signature={`duration_ms: float | None
to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/local.py#L179"
>

Inspect total elapsed task time and serialize a replayable trace dictionary.

<ApiSection title="Returns">
  <ApiFields ariaLabel="TraceRecord inspection returns">
    <ApiField name="duration_ms" type="float | None">
      <code>None</code> until <code>ended_at</code> is set; otherwise elapsed milliseconds rounded to three decimals.
    </ApiField>
    <ApiField name="to_dict()" type="dict[str, Any]">
      All trace fields plus computed duration, recursively serialized spans, and serialized trace-level events.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="TraceRecord inspection errors">
    <ApiField name="ValueError | AttributeError">
      Invalid timestamps or manually inserted span/event objects that do not satisfy the documented interface.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Intentional event duplication">
  An event recorded while a span is active is referenced by both <code>TraceRecord.events</code> and <code>TraceSpan.events</code>. Serialization emits it in both views so consumers can choose chronological replay or span-local inspection.
</ApiCallout>

</ApiReference>

## Hosted telemetry providers

The hosted adapters import their SDKs lazily when constructed. Importing `protolink.telemetry` therefore does not itself require Langfuse or LangSmith. Both adapters isolate async task state with `contextvars`, catch ordinary provider-operation exceptions inside lifecycle hooks, and log warnings so export outages normally do not stop Agent work.

### LangfuseTelemetry

<ApiReference
  kind="class"
  path="protolink.telemetry.LangfuseTelemetry"
  signature={`LangfuseTelemetry(
    public_key: str | None = None,
    secret_key: str | None = None,
    host: str | None = None,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/langfuse_telemetry.py#L18"
>

Create a Langfuse client and map Agent tasks to traces, complete inference cycles to generations, and explicit task-level tool calls to spans.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LangfuseTelemetry constructor parameters">
    <ApiField name="public_key" type="str | None" defaultValue="None">
      Langfuse public key. A truthy explicit value wins; otherwise the constructor reads <code>LANGFUSE_PUBLIC_KEY</code>.
    </ApiField>
    <ApiField name="secret_key" type="str | None" defaultValue="None">
      Langfuse secret key. A truthy explicit value wins; otherwise the constructor reads <code>LANGFUSE_SECRET_KEY</code>.
    </ApiField>
    <ApiField name="host" type="str | None" defaultValue="None">
      Langfuse endpoint. Resolution is a truthy explicit value, then <code>LANGFUSE_HOST</code>, then <code>"https://cloud.langfuse.com"</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="LangfuseTelemetry attributes">
    <ApiField name="langfuse" type="langfuse.Langfuse">
      SDK client constructed immediately with the resolved credentials and host.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LangfuseTelemetry constructor errors">
    <ApiField name="ImportError">
      The optional <code>langfuse</code> library is unavailable. Install <code>langfuse</code> directly or install <code>protolink[telemetry]</code>.
    </ApiField>
    <ApiField name="Langfuse client error">
      Credential, host, configuration, or SDK-construction failures propagate from the constructor.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Falsey explicit values">
  Resolution uses Python's <code>or</code>. An empty explicit key or host does not override the environment/default; it falls through to the next source.
</ApiCallout>

</ApiReference>

### LangfuseTelemetry lifecycle methods

<ApiReference
  kind="async methods"
  path="protolink.telemetry.LangfuseTelemetry lifecycle"
  signature={`async on_task_start(task: Task, agent_name: str) -> Any
async on_task_end(task: Task, result: Task, agent_name: str) -> Any
async on_llm_start(
    prompt: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any
async on_llm_end(response: Part) -> Any
async on_tool_start(tool_name: str, args: dict[str, Any]) -> Any
async on_tool_end(
    tool_name: str,
    result: Any,
    error: str | None = None,
) -> Any
async on_llm_event(event: dict[str, Any]) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/langfuse_telemetry.py#L46"
>

Translate the shared lifecycle into the Langfuse trace API. The six overridden methods return `None` implicitly. `on_llm_event()` is inherited from `Telemetry` and returns `None` without exporting its event.

<ApiSection title="Task mapping">
  <ApiFields ariaLabel="Langfuse task mapping">
    <ApiField name="on_task_start">
      Call <code>langfuse.trace()</code> with a <code>"Task: "</code>-prefixed agent name, the Task ID as the Langfuse trace ID, and agent-name metadata. It does not send the full task as trace input.
    </ApiField>
    <ApiField name="on_task_end">
      If a trace exists, update its output with <code>result.to_dict()</code>, flush the client, and clear the current trace in a <code>finally</code> block. The original <code>task</code> and <code>agent_name</code> parameters are not otherwise used.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="LLM mapping">
  <ApiFields ariaLabel="Langfuse LLM mapping">
    <ApiField name="on_llm_start">
      If a trace exists, create a generation named <code>"LLM Call"</code> containing model, raw prompt input, and the supplied metadata. An empty or absent metadata mapping is sent as <code>None</code>.
    </ApiField>
    <ApiField name="on_llm_end">
      If a generation exists, end it with <code>response.content</code>; objects without that attribute fall back to <code>str(response)</code>. Clear the current generation even when ending it fails.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Tool mapping">
  <ApiFields ariaLabel="Langfuse tool mapping">
    <ApiField name="on_tool_start">
      If a trace exists, create a span with a <code>"Tool: "</code>-prefixed tool name and the arguments as input.
    </ApiField>
    <ApiField name="on_tool_end">
      End the active span with <code>output=result</code> when <code>error</code> is falsey. A truthy error instead ends it with level <code>"ERROR"</code> and <code>status_message=error</code>. Clear the current span afterward.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Fallback and errors">
  <ApiFields ariaLabel="Langfuse lifecycle fallback behavior">
    <ApiField name="missing parent context">
      LLM/tool starts and all matching ends return silently when their required trace, generation, or span is absent.
    </ApiField>
    <ApiField name="provider operation failure">
      Every overridden hook catches <code>Exception</code> around SDK calls and logs a warning. End hooks still clear their corresponding context variable.
    </ApiField>
    <ApiField name="detailed inference events">
      The inherited no-op hook does not forward <code>context_prepared</code>, per-call metrics, retries, LLM-loop tools, delegation, or budget events.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Trace correlation">
  Langfuse uses <code>task.id</code> as its trace ID. It does not read the separate <code>task.metadata["trace_id"]</code> used by <code>LocalTraceTelemetry</code>, although that value is included in Agent-supplied LLM metadata when another tracker has already attached it.
</ApiCallout>

</ApiReference>

### LangSmithTelemetry

<ApiReference
  kind="class"
  path="protolink.telemetry.LangSmithTelemetry"
  signature={`LangSmithTelemetry(
    api_key: str | None = None,
    project_name: str | None = None,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/langsmith_telemetry.py#L18"
>

Create a LangSmith client and represent task execution as a root `RunTree` with child LLM and explicit tool runs.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="LangSmithTelemetry constructor parameters">
    <ApiField name="api_key" type="str | None" defaultValue="None">
      LangSmith API key. A truthy explicit value wins; otherwise the constructor reads <code>LANGCHAIN_API_KEY</code>.
    </ApiField>
    <ApiField name="project_name" type="str | None" defaultValue="None">
      Run project. Resolution is a truthy explicit value, then <code>LANGCHAIN_PROJECT</code>, then <code>"default"</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="LangSmithTelemetry attributes">
    <ApiField name="client" type="langsmith.Client">
      SDK client constructed immediately with the resolved API key.
    </ApiField>
    <ApiField name="project_name" type="str">
      Resolved project used for every root run.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="LangSmithTelemetry constructor errors">
    <ApiField name="ImportError">
      The optional <code>langsmith</code> package is unavailable. Install it directly or install <code>protolink[telemetry]</code>.
    </ApiField>
    <ApiField name="LangSmith client error">
      SDK client construction and configuration errors propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Falsey explicit values">
  As with Langfuse, empty explicit values fall through to environment/default values because resolution uses <code>or</code>.
</ApiCallout>

</ApiReference>

### LangSmithTelemetry lifecycle methods

<ApiReference
  kind="async methods"
  path="protolink.telemetry.LangSmithTelemetry lifecycle"
  signature={`async on_task_start(task: Task, agent_name: str) -> Any
async on_task_end(task: Task, result: Task, agent_name: str) -> Any
async on_llm_start(
    prompt: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any
async on_llm_end(response: Part) -> Any
async on_tool_start(tool_name: str, args: dict[str, Any]) -> Any
async on_tool_end(
    tool_name: str,
    result: Any,
    error: str | None = None,
) -> Any
async on_llm_event(event: dict[str, Any]) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/langsmith_telemetry.py#L42"
>

Translate the common hooks into root and child LangSmith runs. The six overrides return `None` implicitly; detailed `on_llm_event()` values are ignored by the inherited base implementation.

<ApiSection title="Task mapping">
  <ApiFields ariaLabel="LangSmith task mapping">
    <ApiField name="on_task_start">
      Construct a <code>RunTree</code> with a <code>"Task: "</code>-prefixed agent name, <code>run_type="chain"</code>, the configured project, a task-ID input mapping, agent-name metadata, and the shared client; post it and retain it as the current root.
    </ApiField>
    <ApiField name="on_task_end">
      End the active root with <code>result.to_dict()</code> as outputs, patch it to LangSmith, and clear context in <code>finally</code>. The output is passed directly rather than wrapped under a named key.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="LLM mapping">
  <ApiFields ariaLabel="LangSmith LLM mapping">
    <ApiField name="on_llm_start">
      Create and post an <code>llm</code> child named <code>"LLM Call"</code> with prompt, model, and metadata in its inputs.
    </ApiField>
    <ApiField name="on_llm_end">
      End the active child with response content under the <code>response</code> output key, patch it, and clear context. Objects without <code>content</code> are stringified.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Tool mapping">
  <ApiFields ariaLabel="LangSmith tool mapping">
    <ApiField name="on_tool_start">
      Create and post a <code>tool</code> child with a <code>"Tool: "</code>-prefixed tool name and the argument mapping as inputs.
    </ApiField>
    <ApiField name="on_tool_end">
      End with <code>error=error</code> for a truthy error, otherwise put the value under the <code>result</code> output key; patch and clear the current child.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Fallback and errors">
  <ApiFields ariaLabel="LangSmith lifecycle fallback behavior">
    <ApiField name="missing parent context">
      Child starts and end hooks return silently when no corresponding current run exists.
    </ApiField>
    <ApiField name="provider operation failure">
      SDK construction/post/end/patch calls inside hook bodies catch <code>Exception</code> and log a warning. End hooks clear context even after an error.
    </ApiField>
    <ApiField name="dependency re-check">
      <code>on_task_start()</code> resolves <code>RunTree</code> through the lazy dependency helper before entering its SDK-operation <code>try</code> block. In the unusual case that the package becomes unavailable after construction, that <code>ImportError</code> propagates.
    </ApiField>
    <ApiField name="detailed inference events">
      Context, metric, retry, budget, LLM-loop tool, and delegation events are not exported by the inherited no-op hook.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Multiplexer API

### MultiTelemetry

<ApiReference
  kind="class"
  path="protolink.telemetry.MultiTelemetry"
  signature={`MultiTelemetry(
    trackers: list[Telemetry],
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/multiplexer.py#L7"
>

Broadcast every telemetry hook to multiple trackers. This lets one Agent retain detailed local traces while also exporting the coarse lifecycle to one or more hosted systems.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MultiTelemetry constructor parameters">
    <ApiField name="trackers" type="list[Telemetry]" required>
      Ordered tracker list retained by reference. No copy, element validation, or non-empty check is performed; later list mutations affect future broadcasts.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="MultiTelemetry attributes">
    <ApiField name="trackers" type="list[Telemetry]">
      Exact supplied list.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Useful ordering">
  Put <code>LocalTraceTelemetry</code> first when preserving an event locally is more important than reaching a later external exporter. This does not make delivery transactional, but it determines which trackers have already received a hook if a later tracker raises.
</ApiCallout>

</ApiReference>

### MultiTelemetry lifecycle methods

<ApiReference
  kind="async methods"
  path="protolink.telemetry.MultiTelemetry lifecycle"
  signature={`async on_task_start(task: Task, agent_name: str) -> Any
async on_task_end(task: Task, result: Task, agent_name: str) -> Any
async on_llm_start(
    prompt: str,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any
async on_llm_end(response: Part) -> Any
async on_tool_start(tool_name: str, args: dict[str, Any]) -> Any
async on_tool_end(
    tool_name: str,
    result: Any,
    error: str | None = None,
) -> Any
async on_llm_event(event: dict[str, Any]) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/telemetry/multiplexer.py#L22"
>

Forward each hook, with the same arguments, to every tracker in list order.

<ApiSection title="Task hook parameters">
  <ApiFields ariaLabel="MultiTelemetry task lifecycle parameters">
    <ApiField name="task" type="Task" required>
      Live task passed unchanged to each task-start or task-end hook.
    </ApiField>
    <ApiField name="result" type="Task" required>
      Task result passed unchanged to each task-end hook.
    </ApiField>
    <ApiField name="agent_name" type="str" required>
      Agent name passed unchanged to each task hook.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="LLM hook parameters">
  <ApiFields ariaLabel="MultiTelemetry LLM lifecycle parameters">
    <ApiField name="prompt" type="str" required>
      Inference prompt passed unchanged to each LLM-start hook.
    </ApiField>
    <ApiField name="model" type="str | None" defaultValue="None">
      Optional model identifier passed unchanged to each LLM-start hook.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional mapping passed by reference to each LLM-start hook. A tracker
      that mutates it changes what later trackers observe.
    </ApiField>
    <ApiField name="response" type="Part" required>
      Final inference Part passed unchanged to each LLM-end hook.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Tool hook parameters">
  <ApiFields ariaLabel="MultiTelemetry tool lifecycle parameters">
    <ApiField name="tool_name" type="str" required>
      Tool name passed unchanged to each explicit tool hook.
    </ApiField>
    <ApiField name="args" type="dict[str, Any]" required>
      Mutable argument mapping passed by reference to each tool-start hook.
    </ApiField>
    <ApiField name="result" type="Any" required>
      Tool return value passed unchanged to each tool-end hook.
    </ApiField>
    <ApiField name="error" type="str | None" defaultValue="None">
      Optional failure text passed unchanged to each tool-end hook.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Detailed-event parameter">
  <ApiFields ariaLabel="MultiTelemetry detailed event parameter">
    <ApiField name="event" type="dict[str, Any]" required>
      Event mapping passed by reference to each detailed-event hook. A tracker
      that mutates it changes what later trackers observe.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="MultiTelemetry lifecycle return">
    <ApiField name="None" type="None">
      Tracker return values are discarded; after every await succeeds, the multiplexer returns <code>None</code> implicitly.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="MultiTelemetry lifecycle errors">
    <ApiField name="tracker error">
      Any exception propagates immediately. The failing tracker stops iteration, later trackers miss that hook, and no rollback is attempted for earlier trackers.
    </ApiField>
    <ApiField name="AttributeError">
      A list element does not implement the invoked hook.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Sequential fan-out">
  Trackers are awaited one at a time, not with <code>asyncio.gather()</code>. Ordering is deterministic, but total hook latency includes every tracker's latency. An empty list is valid and makes every hook a no-op.
</ApiCallout>

<ApiSection title="Examples">

```python
from protolink import LocalTraceTelemetry
from protolink.telemetry import LangfuseTelemetry, MultiTelemetry

telemetry = MultiTelemetry(
    [
        LocalTraceTelemetry(path="traces.jsonl"),
        LangfuseTelemetry(),
    ]
)
```

</ApiSection>

</ApiReference>
