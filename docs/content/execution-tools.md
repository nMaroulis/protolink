# Execution, approvals, and recovery

Available in **0.7.0**. These optional, dependency-free primitives let applications supply their own roles,
workflows, policies, storage, credentials, and UI while ProtoLink handles execution and lifecycle. The `Agent`
constructor and ordinary tool and delegation contracts remain compatible with 0.6.9.

## Command execution

```python
import sys
from protolink import Agent, AgentCard, ApprovalDecision, CapabilityPolicy
from protolink.tools.builtins import process_tool


async def approve(request, context):
    # Present request.action.artifacts in your application's authenticated UI.
    approved = await application_ui.confirm(request.to_dict())
    return ApprovalDecision(approved=approved, request_id=request.request_id)


agent = Agent(
    AgentCard(name="commands", description="Command execution", url="runtime://commands"),
    policy=CapabilityPolicy({"process.execute": "require_approval"}),
    approval_handler=approve,
)
agent.add_tool(process_tool())
result = await agent.call_tool(
    "execute_command",
    argv=[sys.executable, "-c", "print('hello')"],
    cwd="/absolute/working/directory",
    env={},
    timeout_seconds=10,
    max_output_bytes=4096,
)
print(result.exit_code, result.stdout, result.truncated)
```

`application_ui` is application code. For a runnable, harmless approval callback, see
[`command_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/command_agent.py).
No LLM or server is required. Registration does not launch a process, and calling the prepared tool directly raises:
execution must pass through an Agent's authorization pipeline.

### Public interfaces

| Interface | Purpose |
| --- | --- |
| `process_tool(*, backend=None, max_timeout_seconds=300, max_output_bytes=1048576)` | Factory for the `execute_command` tool; factory limits are ceilings. |
| `execute_command(argv, cwd, env, timeout_seconds=60, max_output_bytes=65536)` | Tool arguments. `argv`, `cwd`, and `env` are required. |
| `ProcessSpec` | Exact argv, resolved cwd, environment mapping, timeout, and combined output-byte cap. |
| `ProcessResult` | `exit_code`, `stdout`, `stderr`, `truncated`, `timed_out`, `canceled`, `duration_seconds`, `budget_exceeded`. |
| `ExecutionBackend` | `boundary: str` and `async execute(spec, execution) -> ProcessResult`. |
| `LocalExecutionBackend` | The first-party host implementation. |
| `ProcessCancelledError` | Native `asyncio.CancelledError` subclass with a partial typed `.result`. |

Backend/result types are in `protolink.tools.builtins.process`. A future remote or container backend can implement this
protocol; ProtoLink does not implement those backends in this release. Backend implementations are trusted application
code and must honor the approved specification and live execution limits.

The local backend uses an argument array without an implicit shell. Environment inheritance is explicit: `env={}`
starts with no inherited environment variables; pass a deliberately selected mapping to allow others. Supply an
absolute executable, an explicit relative executable path, or a `PATH` entry in `env`. Preparation resolves the
executable and directory before presenting their exact values, limits, and execution boundary for authorization.
An explicitly requested shell executable can still interpret its own arguments.

**This is host execution, not a sandbox.** It does not restrict filesystem or network access. POSIX process groups
are killed and reaped on timeout, cancellation, and normal exit to clean up ordinary descendants. Descendants that
create their own session can escape group cleanup. Windows cleanup covers the immediate child only. These limits
bound wall time and captured output, not CPU, memory, disk writes, or arbitrary external effects.

Stdout and stderr are drained concurrently. Their combined retained/emitted output is capped in bytes; excess bytes
are discarded while pipes continue draining. Text uses UTF-8 replacement decoding. `process.output` events carry
`channel` and `text`; `process.finished` includes termination facts, including partial output on cancellation.
Task cancellation retains its native `canceled` lifecycle state. Nonzero exit codes and command timeouts are typed
results; an application completion predicate determines whether those outcomes satisfy its task.

Native task budgets are checked before launch, including time spent awaiting approval. Process time is also bounded
by the remaining runtime budget. Multiple direct calls with the same live `RunContext` share their tool budget;
serialization preserves configured limits, not live execution counters. Delegated tool dispatch counts against its
parent's tool budget and the recipient enforces inherited task limits. These are task-local limits, not a distributed
atomic accounting service for arbitrary parallel agent graphs.

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

## Filesystem changes and restoration

```python
from protolink import StorageCheckpointStore
from protolink.storage import SQLiteStorage
from protolink.tools.builtins import filesystem_tools

checkpoints = StorageCheckpointStore(SQLiteStorage("application.db", namespace="file-changes"))
for tool in filesystem_tools(roots=["/absolute/workspace"], checkpoints=checkpoints):
    agent.add_tool(tool)

change = await agent.call_tool("replace_file", path="/absolute/workspace/note.txt", content="new content\n")
preview = await agent.call_tool("preview_change", change_id=change["change_id"])
restored = await agent.call_tool("restore_change", change_id=change["change_id"])
```

Configure `filesystem.write` and `filesystem.restore` with `require_approval` for separately approved mutation and
restoration. Recovery preview uses `filesystem.read`. ProtoLink's backward-compatible default capability policy allows
actions, so installing a tool alone does not require a human approval. The runnable
[`recoverable_files.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/recoverable_files.py)
shows both successful restoration and a conflict.

| Tool | Preconditions and result |
| --- | --- |
| `create_file(path, content)` | Target must remain absent; creates UTF-8 bytes with mode `0600`. |
| `replace_file(path, content)` | Existing regular file must match the approved bytes, mode, identity, and parent directory. |
| `preview_change(change_id)` | Returns a restoration diff, current conflict flag, saved state, and uncertainty flag. |
| `restore_change(change_id)` | Requires a saved `applied` change and the exact expected postimage; restores bytes/mode or removes a created file. |

`filesystem_tools(*, roots, checkpoints, max_file_bytes=8388608)` returns four `PreparedTool` objects. All paths must be
absolute and beneath explicit roots; `..`, symlinks beneath roots, and nonregular files are rejected. Missing parent
directories are not created. Prepared diff artifacts are tied to the canonical target and preimage; both are checked
again after approval. Files are replaced atomically using a temporary file in the same directory, with fsync of
the file and parent directory. Creation atomically refuses a concurrently created target.

`FilesystemResource` implements the small `Resource` protocol: `read(resource_id)` and
`replace(expected_snapshot, data, mode)`. `ResourceRevision`, `ResourceSnapshot`, `ResourceChange`, `CheckpointStore`,
and `StorageCheckpointStore` live in `protolink.core.resources`. The filesystem implementation currently requires
POSIX descriptor-relative APIs and rejects Windows. Regular file bytes and mode bits are preserved; ownership,
ACLs, extended attributes, and timestamps are not restored. An OS sandbox is required to defend against hostile
concurrent filesystem manipulation; the final compare/rename is not a lock respected by arbitrary external writers.

Recovery information is persisted **before** mutation. Records correlate the resource with an action, task, and run;
states include `prepared`, `applied`, `restoring`, `restored`, `failed`, and `uncertain`. If an interrupted mutation
leaves a `prepared` or `restoring` record, inspection reports uncertainty. Failure to save the initial record prevents
mutation. Failure after a possible write leaves an uncertainty marker; no automatic replay or restoration occurs.
Restoration conflicts raise `ResourceConflictError`. Recovery of an uncertain operation requires application-led
inspection; this release deliberately does not guess whether its effect occurred.

Recovery storage is a dedicated namespace with one live writer. Keep it outside mutable allowed roots where practical.
It contains lossless original bytes, so protect it as application data. Resource recovery, conversation history, and
execution suspension/resumption are separate concepts. Multiple file writes are not an atomic transaction, and
arbitrary process/tool effects are not reversible.

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
