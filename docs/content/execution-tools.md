# Execution, approvals, and recovery

These optional primitives let applications supply their own roles, workflows, policies, storage, credentials,
and UI while ProtoLink handles execution and lifecycle. They cover command execution, recoverable file changes,
approvals, delegated evidence, completion checks, and checkpoint inventory without adding base-package dependencies.

## Built-in execution tools

The [Built-in Tools](builtin-tools.md) catalog documents [command execution](builtin-tools.md#command-execution),
[shell and Git](builtin-tools.md#shell-and-git-tools), [user feedback](builtin-tools.md#user-questions-and-continuation),
and [filesystem access and recovery](builtin-tools.md#filesystem-access). Register those optional tools on any
Agent; this page explains the runtime facilities shared by built-in and application-defined tools.

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
and stops the agents in `agents`. It waits for transport/card readiness and successful configured registration, and
rolls back partially started resources if startup fails. Shutdown cancels runs submitted through the group and
stops owned resources in reverse order. Externally supplied agents, the client, and the registry are left running;
set `own_registry=True` to include the registry in the group's lifecycle. Ownership of an agent includes its server
and transport. Avoid sharing an owned transport with resources whose lifecycle is external to the group.

Configure each Agent normally, including its LLM, transport, policy, approval handler, credentials, and storage.
Transport-free agents use direct invocation; `runtime://` supports local discovery and delegation without sockets.
Network transports use their existing implementations. The group adds no global registry or orchestration roles.

For live model output, enable `capabilities={"streaming": True}` on the Agent card and inspect `event.payload.get("llm_event_type")`. `llm_chunk` carries incremental text in `event.payload["content"]`; `llm_final` carries the complete answer. JSON-action models stream raw JSON fragments, while native-tool models stream ordinary text and assemble tool calls separately. Continue to the terminal task status before treating the whole run as complete. See the [embedded streaming example](./llm.md#stream-into-your-application).

`RunHandle.start(agent_or_url, task, *, client=None, store=None, redaction_policy=None)` is also usable without a
group. URL targets require an existing `AgentClient`. The handle consumes the task once, even when only `result()`
is awaited. `events()` yields typed `RunEvent` objects, including history for later subscribers. `cancel(reason)`
uses native cancellation; cancellation of a waiter on `result()` does not cancel the underlying run.

`RunResult` exposes `status`, the normalized `task`, `output` (unwrapped tool result or final response), `report`,
and an optional structured `error`. Task statuses include `completed`, `failed`, `canceled`, and `input_required`.
If a remote stream closes without a terminal task, status is `uncertain`: the effect may already have occurred.
Task submission keeps response deduplication but disables automatic transport retries, including when a RetryPolicy
permits retries for other operations. The handle never retries or replays that operation. HTTP transports without
streaming return a final task and its
recorded native events; streaming transports provide live events. `handle.report` provides an interim or final
`RunReport`. Reports use an explicit `store` or the local Agent's existing `run_store` when configured.

### Delegated worker evidence

Model-driven delegation automatically includes worker events and execution receipts in the parent's stream,
`task.metadata["run_events"]`, and `RunReport`. Native peers advertising streaming on a capable transport deliver
events while the worker runs. A worker overriding only `handle_task()` is advertised without streaming so its
custom handler remains authoritative. Other peers and older `call_agent()` overrides contribute receipts from the returned task snapshot.
A2A peers contribute only the evidence present in their mapped task response.

Worker `event_id`, `run_id`, `task_id`, `agent_name`, and `action_id` stay intact. `parent_action_id` and
`delegation_id` link worker events to the calling action; existing links from nested delegation are preserved.
The parent stream assigns its own sequence numbers and retains `source_sequence`, `source_final`, and
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

Reopening durable storage is inspection only. Orphan pending requests become `uncertain` and cannot release an
action. Approval records carry `effect_state="unknown"`: approval itself cannot prove that an effect happened.
Consult execution receipts and the actual resource. Duplicate requests or reconnects never resume execution.

## Checkpoint inventory

The filesystem tools use checkpoints to record recoverable changes. See
[write recovery](builtin-tools.md#write-recovery) for configuration, mutation, conflict checks, and restoration.

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
signatures, individual parameters, returned fields, and errors.

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

`CompletionEvidence` supplies the typed `Task`, executed `ToolOutcome` records, artifacts, and `RunReport` to each
predicate. Predicates return `bool` or `ValidationResult`, synchronously or asynchronously. A check requires an
execution receipt by default; use explicit `action_ids` to bind it to particular operations. A proposed action,
preview, or approval alone produces `blocked / execution_evidence_missing`. Pure answer predicates may explicitly
set `require_execution=False`. Old inference receipts can prove execution while omitting private tool output;
predicates needing that output must use an available structured result or artifact.

For resource-dependent evidence, provide `revisions=(ResourceRevision(...),)` and
`read_revision=lambda resource_id: resource.read(resource_id).revision`. Versions are checked before and after
the predicate; changed resources yield `stale / resource_revision_changed`. `ValidationResult.is_current(revisions)`
allows an adapter to assess stored evidence later. A historical `passed` result is not a permanent assertion of freshness.

Validation emits `validation.completed`, appears in `RunReport.validations`, and participates in existing report
comparisons. Results distinguish `passed`, `failed`, `blocked`, and `stale`, with optional structured codes/messages.
Validation records its result without changing terminal task state or choosing a repair policy. Native runtime events
separate `action.requested`, `approval.required`, `approval.decided`, `action.approved`, `action.started`,
`action.completed`, and `validation.completed`. Policy-allowed actions proceed without a human approval event.

Use the existing `Graph`, `Pipeline`, and `Router` to choose your workflow:

```python
from protolink import Graph, Pipeline

graph = Graph(max_iterations=8, max_node_visits={"repair": 3})
# Add application nodes, conditions, and edges normally.
pipeline = Pipeline(application_steps, max_steps=5)
```

Graph retains its default 50-iteration bound; `max_node_visits` may be a per-node mapping or one limit for all nodes.
Pipeline optionally caps executed steps. Nested bounded flows share `RunBudget` counters and runtime limits;
workflow dispatches and ordinary agent/tool/model steps count toward `max_steps`. A limit raises `WorkflowLimitError`
or `BudgetExceededError`, records a structured blocker, and prevents the next dispatch. Cancellation stops traversal.
Workflow nodes use separate task identities while the enclosing task stays cancelable and retains its ID and partial
outputs. Denied, failed, canceled, or input-required work does not
silently become a new attempt. Limits on repair visits are independent of transport `RetryPolicy`; the runtime does
not retry denied actions or replay side effects after uncertain transport failures.

[`verified_workflow.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/verified_workflow.py)
shows application-defined acceptance with at most three attempts and no model provider.
It uses `RepeatUntil(ToolStep(agent, "measure"), check, max_attempts=3)`; checks receive
fresh execution receipts on each attempt. See [progressive control](progressive-control.md#deterministic-steps-and-bounded-acceptance)
for callable steps, bounded acceptance, and the explicit Graph alternative.

## Migration for an application such as ProtoAgent

| Application plumbing | ProtoLink replacement |
| --- | --- |
| Custom subprocess launch, pipe drains, timeout/cancellation handling | Register `process_tool()` and submit `Task.create_tool_call(...)`. |
| Per-agent startup/shutdown and partial-start rollback | `async with AgentGroup(owned, external_agents=external, ...)`. |
| Parsing several final stream shapes | `await handle.result()` and its normalized task/output/report. |
| Pending approval maps and decision futures | `ApprovalBroker`, with an authenticated adapter supplying `ApprovalScope`. |
| Saving original files and implementing restore conflict checks | `filesystem_tools(...)` with a dedicated `StorageCheckpointStore`. |
| Treating preview or approval as execution success | `CompletionValidator` over action receipts and current resource revisions. |
| Unbounded repair loops | Existing Graph/Pipeline with explicit visit/step limits. |

Keep roles, prompts, domain knowledge, task routing, configuration, credentials, user interface, and acceptance criteria
in the application. Existing `RunStore`/`SQLiteRunStore`, `RunRecorder`, `RunReport`, report assertions/comparisons,
`CapabilityPolicy`, task cancellation, transports, and per-agent LLM configuration remain the underlying facilities.
`RunReplay` remains read-only inspection. Full task suspension/resumption and conversation branching are outside this release.

Use existing `RedactionPolicy` when exporting approval requests, events, and reports. Environment values retain their
original keys so sensitive-key masking works. Output strings can contain arbitrary secrets: configure output fields
as sensitive or supply an application redaction policy where needed. Redaction does not mutate execution arguments or
lossless recovery storage, and the library does not automatically discover secrets embedded in command/output text.
