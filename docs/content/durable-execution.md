# Durable execution

Configure a checkpoint file to let an agent pause for approval or an answer, exit the application, and continue after a restart.

```python
from protolink import Agent
from protolink.tools import ask_user_tool

agent = Agent(name="assistant", llm="mock", tools=[ask_user_tool()], durability="runs.sqlite")
```

Use the usual `invoke()`, `run_task()` or `start_run()` methods. A real model can call `ask_user` through its normal tool interface. The runnable [durable execution example](https://github.com/nMaroulis/protolink/blob/main/examples/durable_execution.py) demonstrates approval, a question, and continuation across three separate application processes, using an offline scripted model.

## Start, inspect, restart, resume

`invoke()` raises `RunInterrupted` when work needs a durable response. Its `task` retains completed outputs and the pending request:

```python
from protolink import RunInterrupted

try:
    answer = await agent.invoke("Ask which format I want, then continue.")
except RunInterrupted as pause:
    run_id = pause.run_id
    pending = pause.interruption
    print(pending.kind, pending.request_id, pending.request)
    # Persist the root run ID in your application's job record and show the request.
```

Recreate the same agent and tools after restarting, open the same checkpoint file, and supply the pending request ID:

```python
agent = Agent(name="assistant", llm="mock", tools=[ask_user_tool()], durability="runs.sqlite")
answer = await agent.resume(run_id, request_id=pending.request_id, answer="CSV")
```

An application obtains the current pending request from its own saved job record or the store:

```python
checkpoint = agent.durability.get(run_id)
pending = checkpoint.data["interruption"]
answer = await agent.resume(run_id, request_id=pending["request_id"], answer="CSV")
```

`answer=None` means the user declined; it selects no default. Nonblank text is required otherwise. Another pause raises another `RunInterrupted`. The synchronous equivalents are `agent.sync.invoke()`, `agent.sync.resume()` and `agent.sync.resume_task()`.

Use `resume_task()` to receive the full `Task` instead of raising on a new wait. A paused task has state `TaskState.INPUT_REQUIRED` and `metadata["interruption"]`. `run_task()` also returns that state directly. `start_run()` ends its current stream with the paused task; the application later invokes a separate resume operation. Its run handle represents that execution attempt and does not automatically wait for a future response.

## Approval before execution

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

## What is checkpointed

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

## Crashes and unknown outcomes

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

## Storage and application changes

A path creates `SQLiteDurableStore` using Python's standard library. For control over ownership leases:

```python
from protolink import SQLiteDurableStore

store = SQLiteDurableStore("runs.sqlite", lease_seconds=300)
agent = Agent(name="assistant", llm="mock", durability=store, execution_version="workflow-3")
```

Each run has a fenced owner token. A second active worker receives `RunBusyError`. A dead process on the same host can be reclaimed immediately; other abandoned ownership expires at the configured lease interval. Checkpoint writes renew the lease. Set the interval longer than your longest operation and anticipated event-loop stalls. A worker that loses ownership cannot commit state after a replacement acquires the run. An unresolved execution intent still prevents a replacement from repeating the effect.

Use SQLite for local application recovery on a persistent file, preferably an absolute path. New files are created with owner-only permissions on POSIX systems. Give each task a distinct run ID; a stored run ID cannot be reused for a different task. This implementation supplies no distributed scheduler, cross-host process termination or external-system transaction. A custom `DurableStore` implements `get`, `acquire`, `save` and `release`; it must preserve atomic acquisition and reject writes by stale owner tokens.

Checkpoints contain the actual conversation, tool results, previews, task metadata and responses. Store them as private application data with appropriate access and retention. They are distinct from redacted diagnostic `RunStore` reports and ordinary conversation `Storage`. Exporting a report or using `state=["conversation"]` does not make execution resumable.

Recreate tools, providers, policies and application services before resuming. The fingerprint covers the agent's model/settings, instructions, tool descriptions/schemas/capabilities and local roster/limits. Set a new `execution_version` whenever tool implementations, external resource bindings or dependencies change. Python function bodies and arbitrary client objects are not serialized or hashed. A mismatch raises `CheckpointMismatchError`; version 0.8.0 has no automatic migration of execution checkpoints.

Agent dict/YAML serialization retains SQLite path, lease interval, execution version and child descriptors. Custom stores and executable children require explicit reattachment. Configuration loading and execution resume are separate operations.

## Supported execution boundaries

Version 0.8.0 checkpoints the default Agent task handler and `LLM.infer` loop, registered tool dispatch, and blocking configured local children. Both JSON action providers and provider-native action adapters use these boundaries. Tool outputs must be representable by ProtoLink's JSON serializer; a result that cannot be committed leaves the effect uncertain. Durable dispatch returns that JSON representation on both initial execution and receipt replay. Objects with `to_dict()` or Pydantic serialization become mappings, tuples become lists, and datetimes become strings. Ordinary live tools retain their original return types.

Custom `handle_task` or `LLM.infer` overrides and automatic eager RAG modes (`retrieval="always"` or `"required"`) are rejected for durable runs. On-demand knowledge tools remain available with `retrieval="auto"`. Background children and remote peer delegation are live features; durable runs reject remote delegation rather than silently resubmitting a transported side effect.

Arbitrary internal steps inside a Python tool are one operation from the checkpoint's perspective. Tools that need several independently recoverable effects should expose those operations separately to the default loop, or implement their own idempotent external workflow. Direct application flows and private event-loop/SDK state are not captured automatically. Cancellation remains cooperative and cannot undo an effect that already committed.
