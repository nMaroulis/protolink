# Execution, approvals and recovery

ProtoLink's execution substrate governs action dispatch and task lifecycle. Capability policies and approval requirements authorize prepared actions; typed events and execution receipts record their outcomes. Durable checkpoints preserve inference-loop state and pending requests so an application can suspend execution and resume after a restart.

These optional primitives let applications supply their own roles, workflows, policies, storage, credentials,
and UI while ProtoLink handles execution and lifecycle. They cover command execution, recoverable file changes,
approvals, delegated evidence, completion checks and checkpoint inventory without adding base-package dependencies.

```python
from protolink import Agent, RunInterrupted
from protolink.tools import ask_user_tool

agent = Agent(name="helper", tools=[ask_user_tool()], durability="runs.sqlite")
try:
    agent.sync.call_tool("ask_user", question="Which export format should I use?")
except RunInterrupted as pause:
    print(pause.run_id, pause.interruption.request_id)
```

This offline example saves a pending question and returns control to your application. Reopen the same database and agent configuration, then supply the answer with `agent.sync.resume(run_id, request_id=request_id, answer="CSV")`. The [complete restart example](https://github.com/nMaroulis/protolink/blob/main/examples/durable_execution.py) runs approval, input and continuation in separate processes.

| Application need | Configure or use | Execution behavior |
| --- | --- | --- |
| Bound work or stream progress | `RunBudget` and `start_run()` | Limits, cancellation, events and reports |
| Decide which operations are permitted | `policy=CapabilityPolicy(...)` | Allow, deny or require approval before dispatch |
| Ask for approval while the process stays alive | `approval_handler=ApprovalBroker(...)` | A live adapter resolves a waiting request |
| Pause, exit and resume later | `durability="runs.sqlite"` | Persist execution checkpoints and resume through `resume()` |
| Undo a recoverable file change | Filesystem tools with `StorageCheckpointStore` | Save original bytes and check conflicts before restoration |
| Supervise local specialists | `subagents=[specialist]` | Owned children with shared budgets and inherited policies |
| Verify that work succeeded | `CompletionValidator` | Check execution receipts and current resource evidence |

Conversation [state](state.md) stores memory between turns; diagnostic [run storage](storage.md) stores reports for inspection. Execution checkpoints preserve the unfinished operation itself. [Local subagents](subagents.md) can participate in durable runs through blocking delegation.

## Built-in execution tools

The [Built-in Tools](builtin-tools.md) catalog documents [command execution](builtin-tools.md#command-execution),
[shell and Git](builtin-tools.md#shell-and-git-tools), [user feedback](builtin-tools.md#user-questions-and-continuation),
and [filesystem access and recovery](builtin-tools.md#filesystem-access). Register those optional tools on any
Agent; this page explains the runtime facilities shared by built-in and application-defined tools.

## Durable execution

Configure a checkpoint file to let an agent pause for approval or an answer, exit the application, and continue after a restart.

```python
from protolink import Agent
from protolink.tools import ask_user_tool

agent = Agent(name="assistant", tools=[ask_user_tool()], durability="runs.sqlite")
```

For a known operation, use `call_tool()` without a model, as below. Add your model through `llm=` and use `invoke()` to let it select tools; `run_task()` and `start_run()` expose the full task and run controls. The runnable [durable execution example](https://github.com/nMaroulis/protolink/blob/main/examples/durable_execution.py) demonstrates approval, a question, and continuation across three separate application processes, using an offline scripted model.

### Start, inspect, restart, resume

Convenience calls such as `invoke()` and `call_tool()` raise `RunInterrupted` when work needs a durable response. Its `task` retains completed outputs and the pending request:

```python
from protolink import RunInterrupted

try:
    answer = await agent.call_tool("ask_user", question="Which export format should I use?")
except RunInterrupted as pause:
    run_id = pause.run_id
    pending = pause.interruption
    print(pending.kind, pending.request_id, pending.request)
    # Persist the root run ID in your application's job record and show the request.
```

Recreate the same agent and tools after restarting, open the same checkpoint file, and supply the pending request ID:

```python
agent = Agent(name="assistant", tools=[ask_user_tool()], durability="runs.sqlite")
answer = await agent.resume(run_id, request_id=pending.request_id, answer="CSV")
```

For this direct tool call, the result is the structured `ask_user` response. During inference, the same response becomes a tool observation and the model continues from its saved conversation.

An application obtains the current pending request from its own saved job record or the store:

```python
checkpoint = agent.durability.get(run_id)
pending = checkpoint.data["interruption"]
answer = await agent.resume(run_id, request_id=pending["request_id"], answer="CSV")
```

`answer=None` means the user declined; it selects no default. Nonblank text is required otherwise. Another pause raises another `RunInterrupted`. The synchronous equivalents are `agent.sync.invoke()`, `agent.sync.resume()` and `agent.sync.resume_task()`.

Use `resume_task()` to receive the full `Task` instead of raising on a new wait. A paused task has state `TaskState.INPUT_REQUIRED` and `metadata["interruption"]`. `run_task()` also returns that state directly. `start_run()` ends its current stream with the paused task; the application later invokes a separate resume operation. Its run handle represents that execution attempt and does not automatically wait for a future response.

| Call | When to use it | Result |
| --- | --- | --- |
| `resume(run_id, request_id=..., answer="CSV")` | Answer the current question | Final content, or `RunInterrupted` for a later wait |
| `resume(run_id, request_id=..., approved=True)` | Approve the current prepared operation | Final content, or a later interruption |
| `resume_task(run_id, ...)` | Inspect state and metadata directly | The complete `Task`, including `INPUT_REQUIRED` |
| `resume(run_id)` | Continue a safe saved boundary or read a completed result | Stored output, normal continuation, or the existing interruption |
| `reconcile(run_id, action_id, result=...)` | Record an externally verified uncertain outcome | No dispatch; commits the supplied result receipt |

Supply either `answer` or `approved` for a response, together with the current `request_id`. An optional `fingerprint` binds a displayed request to its saved preview. Async methods use `await`; the blocking facade exposes `sync.resume()` and `sync.resume_task()`. `reconcile()` is synchronous.

### Approval before execution

Declare capabilities on effectful tools and configure your policy:

```python
from protolink import Agent, CapabilityPolicy, RunInterrupted
from protolink.tools import Tool


def publish(text: str) -> str:
    """Publish text through the application's service."""
    return application_service.publish(text)


agent = Agent(
    name="publisher",
    llm="mock",
    tools=[Tool.from_callable(publish, capabilities=["content.publish"])],
    policy=CapabilityPolicy({"content.publish": "require_approval"}),
    durability="runs.sqlite",
)

try:
    await agent.call_tool("publish", text="Reviewed announcement")
except RunInterrupted as pause:
    # Your application presents pause.interruption.request and authenticates its approver.
    request = pause.interruption
    result = await agent.resume(
        pause.run_id,
        request_id=request.request_id,
        fingerprint=request.fingerprint,
        approved=True,
    )
```

`application_service` represents your application's integration. Direct `call_tool()` creates a checkpointed task when durability is enabled. Reject with `approved=False`; the action does not execute, and the run fails with its policy denial.

The stored request includes the exact prepared action, preview artifacts and policy decision. A committed result retains its original authorization and is reused without requesting approval for an effect that already finished. Resume checks the request ID and optional displayed fingerprint, prepares the action again, compares its payload and resource preconditions with the saved action, and evaluates current policies before dispatch. A changed resource or execution contract fails closed. Approval of an old preview cannot authorize a newly prepared operation. Prepared tools must still verify external resource preconditions immediately before effects.

With durability enabled, approval requirements and `ask_user_tool()` use checkpointed interruptions. Live `approval_handler` and user-input callbacks are used for agents without durability. Durable waits do not keep a coroutine or terminal input open. The existing `ApprovalBroker` continues to support live approval adapters and persisted inspection; it is a separate facility from execution checkpoints.

A response authorizes only its pending request. Request IDs, run IDs and fingerprints correlate work; they are not credentials. Applications authenticate responders and authorize access to the relevant job before calling these APIs.

### What is checkpointed

| State | Purpose |
| --- | --- |
| Original task instructions and output cursor | Skip completed task parts |
| Conversation and pending typed model action | Continue the same inference step after a pause |
| Prepared action and stable action ID | Bind permission to the operation actually requested |
| Committed action results | Reuse a completed result without invoking its tool again |
| Root budget usage | Preserve model, tool and step counters across resumes and local children |
| Local child task IDs and checkpoints | Continue blocking delegation through the parent |
| Pending requests and responses | Reject stale or mismatched responses |
| Execution contract fingerprint and schema version | Reject incompatible application changes |

The default prompts and action vocabulary remain the same: `final`, `tool_call`, `agent_call`. Resuming a pending action does not ask the model to choose it again. Once a result is available, the usual observation enters the saved conversation and the ordinary loop continues. A crash during a model request may require another model call; its reserved budget remains counted. This recovery is about execution boundaries, rather than reproducing model token streams.

Counters and child counts are reserved before work. A crash can leave capacity reserved for an attempt that did not start; recovery does not grant that capacity back automatically. Shared root counters are committed before child progress can depend on them.

Suspension time does not consume the active runtime budget. Active time committed before the pause is restored. Time between the last checkpoint and an abrupt crash cannot be reconstructed exactly; completed counters and receipts are the durable record.

### Crashes and unknown outcomes

ProtoLink persists an execution intent before dispatching a tool and a result receipt after it returns. The recovery behavior depends on the last committed boundary:

| Boundary at interruption | Recovery |
| --- | --- |
| Before dispatch | Continue the saved action under current policy |
| Waiting for approval/input | Return the same pending request or apply its matching response |
| Result receipt committed | Reuse the result and continue; do not repeat the tool |
| Tool started, result receipt missing | Raise `UncertainExecutionError`; require reconciliation |
| Completed run | Return the stored output |
| Failed/canceled run with no unresolved action | Reject resume; create a new run if appropriate |

A database checkpoint cannot provide exactly-once effects in an unrelated external system. If a service committed a write and the process stopped before saving its receipt, ProtoLink cannot infer that outcome. It refuses to invoke that operation again automatically.

Ensure the old worker and its operation have stopped, then inspect the external system using the saved action ID, service receipt or your own idempotency key. When you have verified the outcome, trusted application code records it:

```python
checkpoint = agent.durability.get(run_id)
unresolved = next(
    entry for entry in checkpoint.data["actions"].values() if entry["state"] in {"executing", "uncertain"}
)
# Obtain verified_result from the external system first.
agent.reconcile(run_id, unresolved["action"]["action_id"], result=verified_result)
answer = await agent.resume(run_id)
```

`reconcile()` performs no external operation and invents no rollback. Its result becomes the receipt observed by the original loop. If an effect did not occur, your application may resolve the saved operation to an explicit no-effect result and begin separately authorized new work. External APIs with idempotency support can use `ToolExecution.authorization.action.action_id` in a prepared tool's execution hook.

An uncertain child can be reconciled through the configured root agent using the **child run ID** and action ID. Then resume the **root run ID**. An interruption originating in a child exposes that child's ID in `RunInterruption.run_id`; `RunInterrupted.run_id` always identifies the parent invocation to resume.

### Storage and application changes

A path creates `SQLiteDurableStore` using Python's standard library. For control over ownership leases:

```python
from protolink import SQLiteDurableStore

store = SQLiteDurableStore("runs.sqlite", lease_seconds=300)
agent = Agent(name="assistant", llm="mock", durability=store, execution_version="workflow-3")
```

Each run has a fenced owner token. A second active worker receives `RunBusyError`. A dead process on the same host can be reclaimed immediately; other abandoned ownership expires at the configured lease interval. Checkpoint writes renew the lease. Set the interval longer than your longest operation and anticipated event-loop stalls. A worker that loses ownership cannot commit state after a replacement acquires the run. An unresolved execution intent still prevents a replacement from repeating the effect.

Use SQLite for local application recovery on a persistent file, preferably an absolute path. New files are created with owner-only permissions on POSIX systems. Give each task a distinct run ID; a stored run ID cannot be reused for a different task. This implementation supplies no distributed scheduler, cross-host process termination or external-system transaction. A custom `DurableStore` implements `get`, `acquire`, `save` and `release`; it must preserve atomic acquisition and reject writes by stale owner tokens.

Checkpoints contain the actual conversation, tool results, previews, task metadata and responses. Store them as private application data with appropriate access and retention. They are distinct from redacted diagnostic `RunStore` reports and ordinary conversation `Storage`. Exporting a report or using `state=["conversation"]` does not make execution resumable.

Recreate tools, providers, policies and application services before resuming. The fingerprint covers the agent's model/settings, instructions, tool descriptions/schemas/capabilities and local roster/limits. Set a new `execution_version` whenever tool implementations, external resource bindings or dependencies change. Python function bodies and arbitrary client objects are not serialized or hashed. A mismatch raises `CheckpointMismatchError`; execution checkpoints are not migrated automatically.

Agent dict/YAML serialization retains SQLite path, lease interval, execution version and child descriptors. Custom stores and executable children require explicit reattachment. Configuration loading and execution resume are separate operations.

### Supported execution boundaries

Durable execution checkpoints the default Agent task handler and `LLM.infer` loop, registered tool dispatch, and blocking configured local children. Both JSON action providers and provider-native action adapters use these boundaries. Tool outputs must be representable by ProtoLink's JSON serializer; a result that cannot be committed leaves the effect uncertain. Durable dispatch returns that JSON representation on both initial execution and receipt replay. Objects with `to_dict()` or Pydantic serialization become mappings, tuples become lists, and datetimes become strings. Ordinary live tools retain their original return types.

Custom `handle_task` or `LLM.infer` overrides and automatic eager RAG modes (`retrieval="always"` or `"required"`) are rejected for durable runs. On-demand knowledge tools remain available with `retrieval="auto"`. Background children and remote peer delegation are live features; durable runs reject remote delegation rather than silently resubmitting a transported side effect.

Arbitrary internal steps inside a Python tool are one operation from the checkpoint's perspective. Tools that need several independently recoverable effects should expose those operations separately to the default loop, or implement their own idempotent external workflow. Direct application flows and private event-loop/SDK state are not captured automatically. Cancellation remains cooperative and cannot undo an effect that already committed.

### Manage stopped runs

`RunManager` reconnects an application's durable agents and provides bounded inventory, inspection, continuation, cancellation and verified-outcome reconciliation. Its controls use the same leases, configuration checks and prepared-action checks as `Agent.resume_task()`. A run ID selects a record; it does not authorize access to that record.

```python
from protolink import Agent, RunManager
from protolink.tools import ask_user_tool


def application():
    return Agent(
        name="helper",
        llm="mock",
        tools=[ask_user_tool()],
        durability="runs.sqlite",
    )


manager = RunManager(application())
print(manager.list(status="input-required"))
# In async application code, answer an inspected request:
# await manager.resume(run_id, request_id=request_id,
#                      fingerprint=fingerprint, answer="CSV")
```

`manager.inspect(run_id)` returns redacted status, interruption, usage and uncertain-action metadata. Inventory contains configured root-agent records; blocking child continuation remains part of the parent's resume path. `SQLiteDurableStore.list(status=None, agent_name=None, limit=20)` reads up to 1,000 private checkpoints without acquiring a lease. Other stores may implement that optional inventory API without changing the four-method `DurableStore` contract.

`manager.resume()` returns a redacted task and refreshed run metadata, including any subsequent interruption. `manager.reconcile(run_id, action_id, result=verified_result)` commits an outcome already verified in the external system. `manager.cancel(run_id)` fences a stopped checkpoint and marks it canceled; it refuses active leases and unresolved executing/uncertain actions. It does not cancel a currently running process, reverse effects or invent a result. Use the live run handle to cancel active work, and inspect/reconcile uncertain effects before offline cancellation.

The [CLI](cli.md#durable-run-controls) and [dashboard](devtools.md#durable-run-controls) accept a trusted `module:function` factory returning an Agent, an iterable of Agents or a RunManager. The factory has no arguments and is selected by the operator at startup; importing it executes application code. Browsers cannot replace the factory or reconnect executable callbacks through JSON. Management projections apply `RedactionPolicy`; private execution checkpoints remain in their separate store. Network applications should authenticate users and scope the configured roster before exposing these methods.

## Embedded groups and run handles

```python
from protolink import AgentGroup, Task

async with AgentGroup([agent]) as group:
    handle = group.run(
        "commands",
        Task.create_tool_call(
            tool_name="execute_command",
            args={"argv": ["/absolute/executable"], "cwd": "/absolute/directory", "env": {}},
        ),
    )
    async for event in handle.events():
        render(event)  # Application presentation.
        if application_wants_to_stop():
            await handle.cancel("User stopped the run")
    result = await handle.result()
    print(result.status, result.output)
    report = result.report
```

The runnable [`embedded_group.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/embedded_group.py)
cancels a harmless process after its first output.

`AgentGroup(agents, *, external_agents=(), registry=None, own_registry=False, client=None, startup_timeout=10)` starts
and stops the agents in `agents`. It waits for transport/card readiness and successful configured registration and
rolls back partially started resources if startup fails. Shutdown cancels runs submitted through the group and
stops owned resources in reverse order. Externally supplied agents, the client and the registry are left running;
set `own_registry=True` to include the registry in the group's lifecycle. Ownership of an agent includes its server
and transport. Avoid sharing an owned transport with resources whose lifecycle is external to the group.

Configure each Agent normally, including its LLM, transport, policy, approval handler, credentials and storage.
Transport-free agents use direct invocation; `runtime://` supports local discovery and delegation without sockets.
Network transports use their existing implementations. The group adds no global registry or orchestration roles.

For live model output, enable `capabilities={"streaming": True}` on the Agent card and inspect `event.payload.get("llm_event_type")`. `llm_chunk` carries incremental text in `event.payload["content"]`; `llm_final` carries the complete answer. JSON-action models stream raw JSON fragments, while native-tool models stream ordinary text and assemble tool calls separately. Continue to the terminal task status before treating the whole run as complete. See the [embedded streaming example](./llm.md#stream-into-your-application).

`RunHandle.start(agent_or_url, task, *, client=None, store=None, redaction_policy=None)` is also usable without a
group. URL targets require an existing `AgentClient`. The handle consumes the task once, even when only `result()`
is awaited. `events()` yields typed `RunEvent` objects, including history for later subscribers. `cancel(reason)`
uses native cancellation; cancellation of a waiter on `result()` does not cancel the underlying run.

`RunResult` exposes `status`, the normalized `task`, `output` (unwrapped tool result or final response), `report`,
and an optional structured `error`. Task statuses include `completed`, `failed`, `canceled` and `input_required`.
If a remote stream closes without a terminal task, status is `uncertain`: the effect may already have occurred.
Task submission keeps response deduplication but disables automatic transport retries, including when a RetryPolicy
permits retries for other operations. The handle never retries or replays that operation. HTTP transports without
streaming return a final task and its
recorded native events; streaming transports provide live events. `handle.report` provides an interim or final
`RunReport`. Reports use an explicit `store` or the local Agent's existing `run_store` when configured.

### Delegated worker evidence

Model-driven delegation automatically includes worker events and execution receipts in the parent's stream,
`task.metadata["run_events"]` and `RunReport`. Native peers advertising streaming on a capable transport deliver
events while the worker runs. A worker overriding only `handle_task()` is advertised without streaming so its
custom handler remains authoritative. Other peers and older `call_agent()` overrides contribute receipts from the returned task snapshot.
A2A peers contribute only the evidence present in their mapped task response.

Worker `event_id`, `run_id`, `task_id`, `agent_name` and `action_id` stay intact. `parent_action_id` and
`delegation_id` link worker events to the calling action; existing links from nested delegation are preserved.
The parent stream assigns its own sequence numbers and retains `source_sequence`, `source_final` and
`parent_run_id` in envelope metadata. Forwarded child events have `final=False`; the original payload is unchanged.
Only the parent's terminal task status closes the parent run. Returned artifacts are also retained on the parent.

Streamed events and final snapshot receipts are deduplicated by event ID. Failed and canceled workers retain
observed evidence. A disconnected stream or missing terminal task fails the delegation with unknown remote effects
and is never resubmitted. `CompletionValidator` can inspect executed worker outcomes directly from the parent;
an `agent.call` receipt by itself does not count as a tool execution.

## Approval adapters and reconnects

```python
from protolink import ApprovalBroker, ApprovalDecision, ApprovalScope
from protolink.storage import SQLiteStorage

broker = ApprovalBroker(
    storage=SQLiteStorage("application.db", namespace="approvals"),
    timeout_seconds=120,
)
# Supply approval_handler=broker when constructing the Agent.
# Derive this scope from the authenticated caller, never from untrusted UI data.
scope = ApprovalScope(frozenset({authorized_run_id}))
for pending in broker.pending(scope):
    show_approval(pending.request.to_dict(), pending.fingerprint)

resolution = broker.resolve(
    ApprovalDecision(approved=True, request_id=displayed_request_id),
    scope=scope,
    fingerprint=displayed_fingerprint,
)
```

[`approval_adapter.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/approval_adapter.py)
shows a separate adapter coroutine consuming `broker.events(scope)` while the Agent waits.

`ApprovalBroker` implements the existing `ApprovalHandler`. Each pending request has a stable request ID and a
fingerprint of the complete prepared `RunAction`, including artifacts. Decisions with mismatched request IDs or
changed prepared actions cannot authorize execution. The broker handles multiple pending requests independently.

`resolve()` returns an `ApprovalResolution` with one of `approved`, `denied`, `duplicate`, `already_resolved`, `stale`,
`expired`, or `unknown`. Repeating the identical decision is a harmless duplicate; a different decision for a resolved
request returns `already_resolved`. Unknown and out-of-scope IDs both return `unknown`. A fingerprint is correlation
data, not a credential. The application authenticates callers and constructs the allowed scope server-side.

Task cancellation unblocks the wait and marks the request canceled. `records(scope)` returns detached snapshots;
`pending(scope)` returns outstanding requests; each `events(scope)` subscription yields pending snapshots and later
resolution records. Close unused subscriptions. Reconnecting to the same broker preserves pending waits. One live
broker owns its Storage namespace on one event loop; it is not a distributed multi-writer approval service.

Reopening the broker's approval storage is inspection only. Orphan pending requests become `uncertain` and cannot release an
action. Approval records carry `effect_state="unknown"`: approval itself cannot prove that an effect happened.
Consult execution receipts and the actual resource. Duplicate requests or reconnects never resume execution.

## Checkpoint inventory

The filesystem tools use checkpoints to record recoverable changes. See
[write recovery](builtin-tools.md#write-recovery) for configuration, mutation, conflict checks and restoration.

```python
recent = checkpoints.list_changes(limit=20)
uncertain = checkpoints.list_changes(state="uncertain", resource_id="/absolute/workspace/note.txt")
run_changes = checkpoints.list_changes(run_id=run_id, task_id=task_id, limit=20, offset=20)
```

`list_changes(*, limit=100, offset=0, state=None, resource_id=None, run_id=None, task_id=None)` returns detached
`ResourceChange` records, most recently inserted first. Filters match exactly and combine with AND; pagination
applies after filtering. Negative limits or offsets raise `ValueError`; a zero limit returns an empty list.
Updating or restoring a record does not move it. Run/task filters identify the original write, with restoration
identifiers available on each result. The Storage adapter loads its dedicated namespace once per query.

Inventory does not inspect files, alter states, or resume work. Results contain original recovery bytes and need
the same protection as `get(change_id)`. Use a redacted presentation copy for a UI; preserve the protected record
for restoration. Existing custom checkpoint stores need to implement `list_changes()` to expose inventory.

See the [checkpoint storage API reference](./storage.md#checkpoint-recovery-records) for the constructor, method
signatures, individual parameters, returned fields and errors.

## Completion evidence and bounded workflows

```python
from protolink import CompletionCheck, CompletionValidator, RunReport

validator = CompletionValidator(
    [
        CompletionCheck(
            "command succeeded",
            lambda evidence: evidence.outcomes[-1].result["exit_code"] == 0,
            action_ids=(executed_action_id,),
        )
    ]
)
checks = await validator.validate(final_task, report=final_report)
assert all(check.passed for check in checks)
updated_report = RunReport.from_task(final_task)
```

`CompletionEvidence` supplies the typed `Task`, executed `ToolOutcome` records, artifacts and `RunReport` to each
predicate. Predicates return `bool` or `ValidationResult`, synchronously or asynchronously. A check requires an
execution receipt by default; use explicit `action_ids` to bind it to particular operations. A proposed action,
preview, or approval alone produces `blocked / execution_evidence_missing`. Pure answer predicates may explicitly
set `require_execution=False`. Old inference receipts can prove execution while omitting private tool output;
predicates needing that output must use an available structured result or artifact.

For resource-dependent evidence, provide `revisions=(ResourceRevision(...),)` and
`read_revision=lambda resource_id: resource.read(resource_id).revision`. Versions are checked before and after
the predicate; changed resources yield `stale / resource_revision_changed`. `ValidationResult.is_current(revisions)`
allows an adapter to assess stored evidence later. A historical `passed` result is not a permanent assertion of freshness.

Validation emits `validation.completed`, appears in `RunReport.validations` and participates in existing report
comparisons. Results distinguish `passed`, `failed`, `blocked` and `stale`, with optional structured codes/messages.
Validation records its result without changing terminal task state or choosing a repair policy. Native runtime events
separate `action.requested`, `approval.required`, `approval.decided`, `action.approved`, `action.started`,
`action.completed` and `validation.completed`. Policy-allowed actions proceed without a human approval event.

Use the existing `Graph`, `Pipeline` and `Router` to choose your workflow:

```python
from protolink import Graph, Pipeline

graph = Graph(max_iterations=8, max_node_visits={"repair": 3})
# Add application nodes, conditions and edges normally.
pipeline = Pipeline(application_steps, max_steps=5)
```

Graph retains its default 50-iteration bound; `max_node_visits` may be a per-node mapping or one limit for all nodes.
Pipeline optionally caps executed steps. Nested bounded flows share `RunBudget` counters and runtime limits;
workflow dispatches and ordinary agent/tool/model steps count toward `max_steps`. A limit raises `WorkflowLimitError`
or `BudgetExceededError`, records a structured blocker and prevents the next dispatch. Cancellation stops traversal.
Workflow nodes use separate task identities while the enclosing task stays cancelable and retains its ID and partial
outputs. Denied, failed, canceled, or input-required work does not
silently become a new attempt. Limits on repair visits are independent of transport `RetryPolicy`; the runtime does
not retry denied actions or replay side effects after uncertain transport failures.

[`verified_workflow.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/verified_workflow.py)
shows application-defined acceptance with at most three attempts and no model provider.
It uses `RepeatUntil(ToolStep(agent, "measure"), check, max_attempts=3)`; checks receive
fresh execution receipts on each attempt. See [progressive control](progressive-control.md#deterministic-steps-and-bounded-acceptance)
for callable steps, bounded acceptance and the explicit Graph alternative.

## Plug into an existing application

| Application plumbing | ProtoLink replacement |
| --- | --- |
| Custom subprocess launch, pipe drains, timeout/cancellation handling | Register `process_tool()` and submit `Task.create_tool_call(...)`. |
| Per-agent startup/shutdown and partial-start rollback | `async with AgentGroup(owned, external_agents=external, ...)`. |
| Parsing several final stream shapes | `await handle.result()` and its normalized task/output/report. |
| Restartable approval/input waits and saved execution progress | Configure `durability` and use `resume()` with the pending request ID. |
| Pending approval maps and decision futures | `ApprovalBroker`, with an authenticated adapter supplying `ApprovalScope`. |
| Saving original files and implementing restore conflict checks | `filesystem_tools(...)` with a dedicated `StorageCheckpointStore`. |
| Treating preview or approval as execution success | `CompletionValidator` over action receipts and current resource revisions. |
| Unbounded repair loops | Existing Graph/Pipeline with explicit visit/step limits. |

Keep roles, prompts, domain knowledge, task routing, configuration, credentials, user interface and acceptance criteria
in the application. Existing `RunStore`/`SQLiteRunStore`, `RunRecorder`, `RunReport`, report assertions/comparisons,
`CapabilityPolicy`, task cancellation, transports and per-agent LLM configuration remain the underlying facilities.
`RunReplay` remains read-only inspection. Use execution checkpoints for default-loop suspension and restart. Conversation branching and arbitrary Python continuation require application-defined handling.

Use existing `RedactionPolicy` when exporting approval requests, events and reports. Environment values retain their
original keys so sensitive-key masking works. Output strings can contain arbitrary secrets: configure output fields
as sensitive or supply an application redaction policy where needed. Redaction does not mutate execution arguments or
lossless recovery storage and the library does not automatically discover secrets embedded in command/output text.
