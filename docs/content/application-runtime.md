# Embed an agent team in an application

An application can keep its agents registered for its entire lifespan while selecting models and supplying private
dependencies independently for each request. Use ordinary typed functions, `AgentGroup` for readiness and cleanup,
and `RunHandle` for events, evidence, results and cancellation.

The runnable [FastAPI example](https://github.com/nMaroulis/protolink/blob/main/examples/application_runtime.py)
declares two specialists and a coordinator. It uses offline mock providers, a native registry, local delegation,
blocking tools, isolated page selections and model snapshots, streamed events, cancellation, SQLite conversation
history and saved evidence. The mock consultations and answers are scripted; they demonstrate runtime behavior
without provider accounts.

The smaller [streaming example](https://github.com/nMaroulis/protolink/blob/main/examples/application_streams.py)
combines a lazy model factory, private dependencies, an approval adapter, SQLite reports, group admission,
answer/progress streams and reconnection in one offline script. Run `python examples/application_streams.py`.

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
| Stream display text and sanitized activity | `handle.answer_events()` and `handle.presentation_events()` |
| Reconnect to existing work | `group.get_run(run_id)` and `handle.events(after=sequence)` |
| Inspect root/child usage | `report.usage(scope="tree" \| "root" \| "children")` |
| Bound root requests and inspect capacity | `AgentGroup(limits=GroupLimits(...))` and `group.snapshot()` |
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

## Answer text and presentation events

```python
import asyncio

handle = coordinator.start_run("Consult the specialists", session_id="alice")


async def answer():
    text = ""
    async for update in handle.answer_events():
        text = text + update.content if update.type == "delta" else update.content
        render_answer(text, complete=update.type == "completed")


async def progress():
    async for update in handle.presentation_events():
        render_activity(update.type, update.status, update.name, update.action_id)


await asyncio.gather(answer(), progress())
result = await handle.result()
```

`AnswerEvent.content` appends text for `delta` and replaces it for `replacement`. Both remain provisional;
parsing corrections, tool transitions and completion hooks can revise the answer. Only `completed` carries the
authoritative successful answer. Cancellation, failure and an uncertain transport outcome never emit successful
completion. Inspect `result.status` and `result.error` after consumption.

The answer stream projects only the root task's text, including native-provider text and JSON-mode `final.content`.
It excludes child answers, tool arguments, action envelopes and recognized reasoning prefixes. Ambiguous protocol
prefixes remain buffered. Markdown, whitespace and Unicode are preserved unless the handle's explicit
`redaction_policy` changes them. Known `sensitive_values` are masked across chunk boundaries by holding back a
possible matching suffix. Structured results have no implicit text rendering.

`PresentationEvent` exposes typed model, tool, consultation, approval, action and run activity. Its fixed summaries,
display names, statuses, sequence and causal IDs avoid inspecting nested payloads. Prompts, reasoning, arguments,
results, policy reasons and diagnostic error text are omitted. Names remain untrusted text for the application to
render safely. Approval status describes permission, not evidence that an effect executed. Child activity retains
its own run/task IDs and its `parent_action_id` and `delegation_id` links.

`handle.events()` and `handle.chunks()` remain available for raw diagnostics. Raw `llm_chunk` fragments can contain
internal action JSON; do not send them directly to an answer view. `await handle.cancel(reason)` uses the native
control plane. Closing any subscriber leaves the shared execution active.

## Reconnect without submitting again

```python
from protolink import StreamGapError, collect_presentation_events

handle = group.get_run(run_id)
try:
    async for update in handle.presentation_events(after=last_sequence):
        send_activity(update)
        last_sequence = update.sequence
except StreamGapError:
    report = handle.report
    rebuild_activity(collect_presentation_events(report.events))
    last_sequence = report.events[-1].sequence if report.events else 0
```

Resume observation again from `last_sequence` after rebuilding. `events(after=N)` replays native events with sequence
greater than `N`, then follows live activity. Presentation updates retain this same cursor. Each subscriber advances
independently; disconnecting never resubmits work. `answer_events(after=N)` uses its **own** answer-update sequence,
while `AnswerEvent.source_sequence` links an update to a native event when available.

Set `AgentGroup(event_buffer_size=1024)` or `RunHandle.start(..., event_buffer_size=1024)` to bound the native replay
window. The default `None` retains the full replay sequence. Slow subscribers and stale reconnect cursors raise
`StreamGapError` with `after`, `first_available` and `latest`; gaps are never silently skipped. The full report and
safe answer-update history are retained separately, so a bounded replay window does **not** bound total report or
answer memory.

Lookup is process-local. Active handles are never evicted; `max_retained_runs=100` keeps up to 100 completed handles
by default. Unknown or evicted IDs raise `KeyError`. Saved reports remain available through `RunStore`, but reopening
storage does not recreate a live subscription. Apply application authorization to every run lookup and scope session,
run and request IDs to the caller.

## Usage across the run tree

```python
report = (await handle.result()).report
all_calls = report.usage()  # root and observed descendants
root_calls = report.usage(scope="root")
child_calls = report.usage(scope="children")
one_worker = report.usage(run_id=worker_run_id)
print(all_calls.reported.total_tokens, all_calls.estimated.total_tokens)
```

Owned and transported child calls preserve usage and correlation identities. Rollups deduplicate metric/lifecycle
copies and forwarded receipts; a consultation envelope does not add the child's usage again. `reported` contains
provider-only calls, while `estimated` contains calls with any estimated token count. `unknown_calls` counts observed
calls without usable usage. Missing fields remain `None`, including when any contributing call lacks that field.

`costs` groups known costs by currency **and** estimation flag; currencies are never added together.
`unpriced_calls` counts calls without price information. Empty or incomplete observations do not become zero usage
or free calls. These are observed totals: missing remote events cannot establish complete provider billing.

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

Optional admission applies to root submissions through `group.run()`:

```python
from protolink import AgentGroup, GroupLimits, Task

async with AgentGroup(
    [coordinator],
    limits=GroupLimits(max_concurrent_runs=4, max_queued_runs=64, queue_timeout=30),
    event_buffer_size=1024,
) as group:
    handle = group.run(coordinator, Task.create_infer(prompt="Read the dashboard"), request_id="alice:message-1")
    print(group.snapshot().to_dict())
    result = await handle.result()
```

Omitting `limits` leaves admission unlimited. `GroupLimits()` defaults to four active roots, 64 FIFO waiters and no
queue timeout; `max_queued_runs=0` rejects excess work immediately. A queue deadline runs from submission, including
time before the worker first runs. Queued work consumes no model/tool budget. Full queues and expired waiters finish
with `error.code` of `queue_full` or `queue_timeout`, before invoking application work. Queued cancellation is native.
Events `run.queued`, `run.admitted`, `run.rejected`, `run.expired` and `run.canceled` expose admission activity.
Delegated children share their root's slot; direct Agent calls and per-agent thread worker limits remain separate.

`group.run()` snapshots the accepted serialized task before it can wait. Optional `request_id` deduplicates within
this group: equivalent serialized semantic input and the same target return the original retained handle, including
failed or canceled work; different input raises `ValueError`. Generated task, message, artifact, run and tool/agent-call
identities and timestamps are excluded from comparison. Private dependencies and handle options are not fingerprinted.
Reuse the original semantic input when retrying an uncertain submission, and include any application configuration identity that must
distinguish requests in the task's public metadata.

Request IDs expire when their completed handles are evicted, and do not survive restarts or promise exactly-once
external side effects. Scope them to authenticated callers. A repeated ID observes existing work rather than changing
its private dependencies or controls.

`group.snapshot()` reports lifecycle state, ready owned agents, active roots, queue depth and retained handles.
Readiness means group transport/registration startup succeeded. It makes no provider request and does not report
provider availability or occupied thread worker slots.

Configure `state=["conversation"]` with `SQLiteStorage` for native per-session history and `SQLiteRunStore` for task
snapshots and reports. Use a separate storage namespace per agent. Application dependencies and frozen model choices
remain request-local and are not reconstructed from these stores.

The acceptance tests in
[`test_application_runtime.py`](https://github.com/nMaroulis/protolink/blob/main/tests/test_application_runtime.py)
exercise concurrent requests, frozen choices through later consultations, private credentials, streaming and
delegated evidence, cancellation during a blocking call, persisted sessions and shutdown.

## v0.8.4 scope decisions

The application integration proposals are assessed against existing execution primitives:

| # | Proposal | Decision |
| --- | --- | --- |
| 1 | Answer-only streaming | Implemented: root deltas, replacements and authoritative completion. |
| 2 | Presentation events | Implemented: typed allowlisted activity with native correlation IDs. |
| 3 | Reconnectable subscriptions | Implemented within a retained live process, with cursors and explicit gaps. |
| 4 | Delegated metrics | Implemented: preserved owned usage and deduplicated root/child rollups. |
| 5 | Group admission | Implemented: optional root concurrency, FIFO bounds, deadlines and cancellation. |
| 6 | Conversation presentation | Deferred: transcript and consultation display policy needs an application-facing history contract. |
| 7 | Idempotent submission | Implemented within a group retention window; no exactly-once side-effect guarantee. |
| 8 | Three tool-result views | Deferred: hooks and `expose_tool_results` already separate model observations from execution receipts; additional views need a classification contract. |
| 9 | Evidence-linked citations | Deferred: RAG citations and action/artifact IDs exist; a shared cross-delegation citation schema needs separate design. |
| 10 | Unified public errors | Deferred: existing typed subsystem errors and explicit outcomes remain; safe presentation summaries avoid exposing diagnostics. |
| 11 | Effective capabilities | Deferred: explicit/automatic tool protocol selection exists; uniform capability provenance is a separate API. |
| 12 | Private configuration snapshots | Reuse `request_context`, explicit inheritance and immutable application snapshots; dependencies remain local. |
| 13 | Multiple native tool calls | Reuse explicit batch rejection, parallel flows and subagents; never silently select one call. |
| 14 | Structured-output streaming | Deferred: provisional field updates need an authoritative schema-validation contract. |
| 15 | Unified continuation | Reuse `ApprovalBroker`, checkpoints, handoffs and `RunManager`; avoid duplicating continuation state. |
| 16 | Runtime diagnostics | Partial: group lifecycle/admission snapshot; provider probes and worker occupancy remain separate. |
| 17 | Stream testing helpers | Partial: offline contract tests cover fragmentation, Unicode, privacy, corrections, reconnects and cancellation; no new public toolkit. |
| 18 | Retention/export helpers | Deferred: stores already support query/delete; protected cleanup and export need explicit retention rules. |
| 19 | Tool contract diagnostics | Deferred: inferred schemas and docstrings remain authoritative; quality linting is separate development tooling. |
| 20 | Embedded-app example | Partial: the compact streaming script and existing full FastAPI example cover integration with focused runtime tests. |
