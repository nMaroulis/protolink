# Embed an agent team in an application

An application can keep its agents registered for its entire lifespan while selecting models and supplying private
dependencies independently for each request. Use ordinary typed functions, `AgentGroup` for readiness and cleanup,
and `RunHandle` for events, evidence, results and cancellation.

The runnable [FastAPI example](https://github.com/nMaroulis/protolink/blob/main/examples/application_runtime.py)
declares two specialists and a coordinator. It uses offline mock providers, a native registry, local delegation,
blocking tools, isolated page selections and model snapshots, streamed events, cancellation, SQLite conversation
history and saved evidence. The mock consultations and answers are scripted; they demonstrate runtime behavior
without provider accounts.

```bash
pip install 'protolink[http]'
python examples/application_runtime.py
# Or serve the same application from the repository root:
uvicorn examples.application_runtime:create_app --factory
```

Serving it writes `application.sqlite` in the current directory. The offline demonstration uses a temporary database.
Post `{"session_id":"alice","page":"overview"}` to `/runs` for a newline-delimited stream of native events.
The `X-Run-ID` response header identifies the run; `DELETE /runs/{run_id}` cancels active work and
`GET /runs/{run_id}/evidence` reads saved tool evidence. Session IDs identify conversations and must be scoped
to the authenticated user by the surrounding application.

## What belongs in ProtoLink

| Application need | Native API |
| --- | --- |
| Run a blocking Python tool without blocking asyncio | `Agent(sync_execution="thread", max_sync_workers=4)` |
| Override one tool's execution policy | `@agent.tool(sync_execution="inline")` or `Tool.from_callable(...)` |
| Supply private per-request dependencies | `request_context(values, inherit=...)` and `current_request_context()` |
| Choose a model for each persistent agent's request | `Agent(llm_factory=...)` |
| Inspect tools without wrapping them | `result.tool_evidence`, `report.tool_evidence`, `handle.tool_evidence()` |
| Consume activity, consultations and final output | `handle.events()` and `await handle.result()` |
| Start a registered team, await readiness and shut it down | `async with AgentGroup(...)` |
| Preserve conversations and execution reports | `SQLiteStorage` and `SQLiteRunStore` |

Registry discovery, hooks, streaming, live cancellation, correlated delegation and session persistence already
exist. These APIs use the same execution loop, policies, budgets, events and receipts. Domain services, credential
storage, page instructions and UI persistence belong to the application.

## Blocking tools

```python
import time
from protolink import Agent


def lookup(record_id: int) -> dict:
    """Look up a record using a blocking client."""
    time.sleep(0.2)
    return {"id": record_id}


agent = Agent(name="reader", tools=[lookup], sync_execution="thread", max_sync_workers=4)
record = await agent.call_tool("lookup", record_id=12)
```

`sync_execution` defaults to `"inline"` for compatibility. Opt into `"thread"` for blocking functions. Native
async tools are awaited directly in either mode. A tool's explicit `sync_execution` overrides its executing agent's
default; an unset override inherits the default. Registration preserves the original callable's signature,
annotations and docstring. No background wrapper or tool-schema parameter is needed.

The same dispatcher handles direct calls, explicit tool tasks, model-selected tools and delegated child tools.
Authorization, argument validation and tool budgets run before execution. Worker threads receive copied Python
context variables, including private request dependencies. The worker limit belongs to the executing agent;
specialists have their own limits. Waiting for capacity does not block the event loop.

Cancellation stops the await promptly. Python cannot forcibly terminate a running thread or undo its side effects.
The worker retains its capacity slot until the function actually finishes, and its late return cannot become a
successful observation after cancellation. Use a cooperative API or an isolated process when work itself must stop.
Threaded results that completed and were recorded before cancellation retain their existing completion receipts.

Synchronous provider requests and model factories also run off the event loop. Existing async and streaming provider
adapters retain their normal protocols. Native SDK streaming adapters share the same admission bound while keeping
one worker for opening, reading and closing a stream. A shared local llama.cpp model serializes evaluations because
its native model state is mutable. Automatic tool-capability metadata discovery also runs off the event loop.

## Private request context and frozen model choices

`RunContext` remains the **serialized** envelope for sessions, tracing, permissions and budgets. Private Python
values belong in a separate request scope:

```python
from types import MappingProxyType
from protolink import Agent, create_llm, current_request_context, request_context


def read_selected_page() -> dict:
    """Read the application's validated selection."""
    private = current_request_context()
    return private["service"].read(private["page"])


reader = Agent(
    name="reader",
    tools=[read_selected_page],
    sync_execution="thread",
    llm_factory=lambda: create_llm(current_request_context()["models"]["reader"]),
)

# Freeze the whole team's settings when accepting the request, before queuing.
snapshot = MappingProxyType(dict(application_model_settings))
with request_context(
    {"models": snapshot, "service": page_service, "page": validated_page}, inherit=("models", "service", "page")
):
    handle = reader.start_run("Read the selected page", session_id="alice")
result = await handle.result()
```

`request_context(values, *, inherit=())` copies the outer mapping and exposes it read-only. Nested values are ordinary
Python objects, so freeze or copy nested settings yourself. Entering a scope replaces the current mapping and leaving
it restores the previous scope. Concurrent asyncio tasks and their workers remain isolated. A run handle captures the
scope when it starts, so the request handler may leave the scope before consuming its events.

Only keys listed in `inherit` reach **local owned subagents**. Each generation retains that same allowlist.
The default inherits no keys. Dependencies are never added automatically to prompts, tool schemas, task serialization,
events, conversation history or configuration exports. A tool can deliberately return application data; ordinary
result and history rules then apply to that returned data.

Private dependencies do not cross transport boundaries, including `runtime://`, which simulates serialization.
Resolve credentials and services in the receiving application's request scope. Use `subagents=[...]` when local
specialists should inherit selected private dependencies. They can also be registered for normal discovery, as in
the example. Private scopes are live process-local values and must be re-established when resuming persisted work.

`llm_factory` is a zero-argument synchronous or async callable returning an `LLM` or a supported model specification
accepted by `create_llm`. Choose either `llm` or `llm_factory`. It runs lazily once for an inference-bearing task;
constructing agents, registering them and starting the application do not call the factory. Explicit tool-only tasks
do not need a model. A factory may use the private scope to pick a different provider/model for every specialist.

The resolved provider is bound to that execution without changing shared `agent.llm`. Native tool calling, streaming,
usage reporting and conversation state continue through ProtoLink's inference loop. Return an independent provider
instance when its SDK or custom state is not safe to share. Freezing the team's configuration at acceptance ensures
that later consultations use the same choices even if application settings change while a request is queued.
Serialized agent configuration records that a factory must be reconnected; pass `llm_factory=...` to `Agent.from_dict`.

## Inspect completed tool evidence

```python
from protolink import Agent

agent = Agent(name="reader", llm="mock", expose_tool_results=True)
handle = agent.start_run("Use the available tools")

# Optional live subscription; this consumes the existing run stream once.
async for evidence in handle.tool_evidence():
    print(evidence.tool_name, evidence.outcome, evidence.result)

result = await handle.result()
for evidence in result.tool_evidence:
    print(evidence.arguments, evidence.action_id, evidence.duration_seconds)
```

`ToolEvidence` is a view over existing `RunEvent` records, not an additional execution log. `RunReport.tool_evidence`
and `RunResult.tool_evidence` return tuples; `RunHandle.tool_evidence()` replays observed terminals and subscribes to
new ones. `collect_tool_evidence(events)` supports existing event collectors. None of these execute or retry tools.

Each record has:

- `tool_name`, validated `arguments`, `result`, `result_omitted` and optional `error`.
- `outcome`: `completed`, `rejected`, `failed` or `canceled`. Policy denials are rejected requests.
- `agent_name`, `task_id`, `run_id`, `action_id`, `parent_action_id` and `delegation_id`.
- `started_at`, `finished_at` and `duration_seconds`; start/duration are unknown if no start event was observed.
- `to_dict()` for rendering or JSON output.

Pre-validation rejections may have no validated arguments or start timestamp. Forwarded live events and final task
snapshots produce one observation per action. Child tool evidence retains the child's IDs and its delegation links;
the coordinator's consultation envelope is not counted again as a tool execution. A disconnected transport can end
with an uncertain run and no terminal action receipt; absence of evidence is not proof that a side effect failed.

Inference results remain private by default. Set `expose_tool_results=True` **on the executing agent** to include its
ordinary tool results in public events, receipts and reports. This exposes the actual JSON-safe return value before
`after_tool` hooks or context policies transform model history; redact sensitive values in the tool's returned data
when enabling it. Knowledge passages still use their existing sanitized
statistics. `result_omitted=True` distinguishes an unavailable/private result from a tool that returned `None`.
Direct explicit tool calls already expose their returned output. Configure redaction on handles/stores when needed.

## One event stream

```python
handle = coordinator.start_run("Consult the specialists", session_id="alice")
async for event in handle.events():
    if event.payload.get("llm_event_type") == "llm_final" and event.task_id == handle.task.id:
        render_answer(event.payload["content"])
    elif event.type.startswith("action."):
        render_activity(event)
    elif event.type == "llm.call.completed":
        details = event.payload.get("metadata", {})
        render_model(details.get("provider"), details.get("model"), details.get("metrics"))
result = await handle.result()
```

`handle.events()` carries answer events, action lifecycle, consultations, errors, cancellation and the terminal task.
Child events preserve their IDs and delegation links; only the root terminal task closes the parent run. Inspect
`result.status` and `result.error` after the iterator ends. `await handle.cancel(reason)` uses the native cancellation
control plane. Leaving an event iterator alone does not cancel a shared run.

`llm_chunk` and `handle.chunks()` contain **raw provider fragments**, which can be internal JSON actions rather than
user-facing text. Use the root `llm_final` content for a complete answer. The example filters raw chunks from its
application stream and streams typed progress and completed answers. Keep diagnostic action JSON and any provider
reasoning separate from the answer area.

`llm.call.started` and `llm.call.completed` identify the resolved provider and model. Completed-call metrics distinguish
provider-reported usage from token estimates with `usage.source` and `usage.estimated`; estimates are not actual usage.
Missing metrics or cost are unknown. Do not turn missing values into zero or invent pricing for an unsupported model.

## Async lifecycle and persistence

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from protolink import AgentGroup


@asynccontextmanager
async def lifespan(app):
    async with AgentGroup([reader, analyst, coordinator], registry=registry, own_registry=True) as group:
        app.state.group = group
        yield


app = FastAPI(lifespan=lifespan)
```

`AgentGroup.start()` awaits transport and registration readiness and rolls back partial startup failure. Exiting the
context cancels group-started runs and stops owned agents/transports and the owned registry in reverse order.
Use `group.run(agent_or_name, task)` for runs the group must drain. Supplied external agents, the optional client
and a registry with `own_registry=False` remain application-owned. No thread wrappers around start/stop are needed.
Already running Python tool threads still follow the cancellation limitation described above.

Configure `state=["conversation"]` with `SQLiteStorage` for native per-session history and `SQLiteRunStore` for task
snapshots and reports. Use a separate storage namespace per agent. Application dependencies and frozen model choices
remain request-local and are not reconstructed from these stores.

The acceptance tests in
[`test_application_runtime.py`](https://github.com/nMaroulis/protolink/blob/main/tests/test_application_runtime.py)
exercise concurrent requests, frozen choices through later consultations, private credentials, streaming and
delegated evidence, cancellation during a blocking call, persisted sessions and shutdown.
