# Worker execution and continuation

An application can give an agent a small set of workers, display their progress as it happens, and decide when to continue unfinished work. ProtoLink 0.8.2 adds typed worker tool declarations and checkpointed work slices, forwards owned workers' live events, and lets prepared tools reject correctable requests before approval.

These features use the existing [local subagent](subagents.md), [runtime](runtime.md), and [durable execution](execution-tools.md#durable-execution) contracts. The application still chooses the workers, tool capabilities, budgets, permissions, and continuation policy.

| Need | Use | Result |
| --- | --- | --- |
| Reject an invalid operation before requesting approval | `ToolRejectedError` in a `PreparedTool` preparation function | Bounded model correction with no execution or approval for that proposal |
| Give the model a named, typed route to one worker | `parent.add_worker_tool(...)` | A tool-shaped declaration dispatched as native `agent.call` |
| Show progress while a worker is running | `parent.start_run(...).events()` | Existing child events in the parent's stream with their original identity |
| Return control after a bounded amount of inference | `yield_after_steps` with durable execution | An unfinished `TaskState.INPUT_REQUIRED` task with a `RunHandoff` |

The Python examples below run inside an async function or notebook with an active event loop. They use `MockLLM` to demonstrate exact model decisions offline; a provider-backed model makes its own choices from the same declarations.

The [runnable worker execution example](https://github.com/nMaroulis/protolink/blob/main/examples/worker_execution.py) combines typed delegation, live child activity, preparation correction, and explicit continuation with temporary checkpoints and no external services.

## Reject a prepared proposal before approval

A prepared tool separates three stages: describing the proposed operation, authorizing that exact operation, and executing it. Preparation can inspect application state and return a concrete `RunAction`. It must not commit the operation it describes.

Raise `ToolRejectedError` during preparation when the request is correctable and **this attempt made no changes or external effects**. For example, an identifier may no longer exist or a proposed replacement may match several locations. Include concise, structured feedback that helps the model make a better request:

```python
from protolink import Agent, RunAction, RunBudget, ToolRejectedError
from protolink.llms import MockLLM
from protolink.tools.prepared import PreparedTool

selected_checks = []


def select_check(check_id: str) -> str:
    """Select one available check for the plan."""
    raise AssertionError("This callable describes the signature only")


def prepare(arguments, context):
    if arguments["check_id"] not in {"lint", "tests"}:
        raise ToolRejectedError(
            code="unknown_check",
            message="That check is unavailable; nothing changed.",
            details={"valid_ids": ["lint", "tests"]},
            suggestion="Choose lint or tests.",
        )
    return RunAction(
        kind="tool.call",
        name="select_check",
        payload={"arguments": arguments},
    )


async def execute(execution):
    execution.check()
    check_id = execution.authorization.action.payload["arguments"]["check_id"]
    selected_checks.append(check_id)
    return f"Selected {check_id}."


llm = MockLLM(
    sequential_responses=[
        {"type": "tool_call", "tool": "select_check", "args": {"check_id": "typo"}},
        {"type": "tool_call", "tool": "select_check", "args": {"check_id": "lint"}},
        "Selected lint.",
    ]
)
llm.max_tool_corrections = 2
agent = Agent(
    name="planner",
    llm=llm,
    tools=[
        PreparedTool(
            select_check,
            prepare=prepare,
            execute=execute,
            capabilities=("plan.select",),
        )
    ],
    verbosity=0,
)
answer = await agent.invoke(
    "Select a check.",
    budget=RunBudget(max_steps=3, max_llm_calls=3, max_tool_calls=1),
)
assert answer == "Selected lint."
assert selected_checks == ["lint"]
```

The first proposal supplies a rejection observation to the same inference loop. The second proposal is prepared and authorized normally; only its executor consumes a tool call. A synchronous or asynchronous preparation function can use this contract, with either JSON actions or provider-native tool calling, including streaming inference.

If the tool requires approval, an invalid preparation never reaches the approval handler. A corrected proposal receives its own concrete action and normal policy decision. Rejected preparation emits `action.rejected` with `payload["metadata"]["phase"] == "preparation"` and an action ID matching its `action_rejection` receipt. It emits no execution-start or successful-result receipt for that proposal.

### Correction limits and stopping conditions

Within an inference loop, `llm.max_tool_corrections` is one allowance shared by tool name/schema errors, delegated request validation, and explicit no-change tool rejections. Its default is two corrections. A value of zero stops on the first rejection; exhausting the allowance raises `ToolCorrectionLimitError`. Successful actions do not replenish the allowance.

Preparation rejection does not charge a tool call, but the model turn that proposed it still consumes its step and model usage. Another proposal needs another model call. An executor that rejects after starting still consumes its tool call. Saved history, correction counts, and usage survive durable continuation.

Use ordinary exceptions for failures and `UncertainExecutionError` when an external effect may have happened. A permission denial, cancellation, exhausted hard budget, partial write, or uncertain network response must not become a correctable rejection. Direct application tool calls have no model correction loop; their rejection remains available through the existing task/error contract. See [tool rejection](tool.md#reject-a-request-the-model-can-correct) and [uncertain execution](execution-tools.md#crashes-and-unknown-outcomes).

## Expose a worker through a typed tool

Register the child as an owned local subagent, then expose the specific route you want the parent to offer:

```python
from protolink import Agent, RunBudget
from protolink.llms import MockLLM

researcher = Agent(
    name="researcher",
    llm=MockLLM(default_response="The fixture contains evidence E1."),
    verbosity=0,
)
parent = Agent(
    name="coordinator",
    subagents=[researcher],
    llm=MockLLM(
        sequential_responses=[
            {
                "type": "tool_call",
                "tool": "researcher",
                "args": {"task": "Find evidence in the fixture."},
            },
            "The worker found E1.",
        ]
    ),
    verbosity=0,
)
facade = parent.add_worker_tool(
    "researcher",
    description="Find supporting evidence in the supplied material.",
)
answer = await parent.invoke("Check the evidence.", budget=RunBudget(max_llm_calls=3))
assert answer == "The worker found E1."
```

The inference declaration accepts exactly `task: str`; the task must contain non-whitespace text. The model supplies the assignment, while the application fixes the target worker. The worker gets its own conversation and the delegated prompt. The parent receives the worker's returned result as an observation.

The facade resolves to the ordinary `agent_call` inference action before policy, dispatch, or checkpointing. It retains child ownership, inherited policies, shared run budgets, cancellation, approval, event lineage, and durable recovery. Its authorization action has kind `agent.call` and capability `agent.delegate`. The facade declaration itself consumes no extra tool call; model calls and actual tools used by the child consume the existing shared counters.

### Bind a worker's declared tool

Use `tool=` to expose one exact child tool with a copy of its declared input and output schemas:

```python
from protolink import Agent


def lookup(item_id: int) -> str:
    """Return an item from the local fixture."""
    return {1: "Evidence E1", 2: "Evidence E2"}[item_id]


catalog = Agent(name="catalog", tools=[lookup], verbosity=0)
parent = Agent(name="coordinator", subagents=[catalog], verbosity=0)
facade = parent.add_worker_tool("catalog", tool="lookup", name="lookup_evidence")

assert set(facade.input_schema["properties"]) == {"item_id"}
value = await parent.call_tool("lookup_evidence", item_id=1)
assert value == "Evidence E1"
```

The model sees `lookup_evidence(item_id: int)`. It cannot change the worker or child tool through routing arguments. This also supports a tools-only child without an LLM. A standalone `parent.call_tool()` creates a native parent task; the equivalent explicit entry point is `parent.run_task(Task.create_tool_call(...))`.

Within an already running task, use model-selected or native `agent_call` delegation. Calling the facade through `call_tool_in_context()` or nesting a standalone `call_tool()` inside active execution fails clearly. The returned facade is configuration metadata; calling `facade(...)` directly cannot execute the worker.

### Registration and configuration rules

```text
parent.add_worker_tool(worker, *, name=None, tool=None, description=None)
```

| Parameter | Contract |
| --- | --- |
| `worker` | Exact name of an already registered child in `parent.subagents` |
| `tool=None` | Expose inference with the `task` argument; the child must support inference |
| `tool="lookup"` | Bind that exact declared child tool and copy its argument/result schemas |
| `name=None` | Default to the worker name for inference or `<worker>_<tool>` for a child tool |
| `name="lookup_evidence"` | Set a provider-compatible alias: 1–64 characters, beginning with a letter or underscore, followed by letters, digits, underscores, or hyphens |
| `description=None` | Use the worker/tool description; supply a string to explain the application-specific purpose |

Registration executes no child work and rejects existing or reserved tool name collisions. Supply `name=` if the default alias is too long or unsuitable for the provider format. Changing or removing the registered child does not retarget an existing facade, including to a registry peer with the same name.

A live facade belongs to the parent that registered it. To expose the same worker on another parent, register a new facade there or reconnect serialized configuration rather than passing the live declaration between parents.

Agent configuration stores the binding rather than a Python closure. Reattach executable child instances with `Agent.from_dict(config, subagents=[child])`; the exact worker and tool must exist, and their declared schemas must still match. A changed binding changes the durable configuration fingerprint. This loads configuration; execution resumes through the owning root agent's durable API.

## Observe workers while they run

Use the parent's existing `RunHandle.events()` stream. Owned child events arrive while the child is working, before its final result returns:

```python
from protolink import Agent
from protolink.llms import MockLLM

researcher = Agent(
    name="researcher",
    llm=MockLLM(default_response="The fixture contains evidence E1."),
    verbosity=0,
)
parent = Agent(
    name="coordinator",
    subagents=[researcher],
    llm=MockLLM(
        sequential_responses=[
            {"type": "tool_call", "tool": "researcher", "args": {"task": "Find evidence."}},
            "The worker found E1.",
        ]
    ),
    verbosity=0,
)
parent.add_worker_tool("researcher")
handle = parent.start_run("Look up the supporting evidence.")
async for event in handle.events():
    print(event.agent_name, event.type, event.action_id)
    if event.type == "llm.stream" and event.payload.get("llm_event_type") == "llm_chunk":
        print(event.payload.get("content", ""), end="", flush=True)
result = await handle.result()
print(result.status, result.output)
```

The stream supports blocking delegation, nested owned children within the configured depth, and live background children created through `handle.spawn()`.

An event keeps its original `event_id`, `run_id`, `task_id`, and `agent_name`. `parent_action_id`, `delegation_id`, and parent metadata retain the delegation relationship. Group events by their run/agent identity when displaying parallel workers. Snapshot receipts and already forwarded live events are deduplicated.

Child final markers are forwarded with `final=False` and `metadata["source_final"]` recording their original marker. They describe that child's completion; the parent's final `task.status` closes the parent execution attempt. Ending the parent cancels and drains unfinished owned children. Cancellation remains cooperative around application operations.

Raw model fragments can contain JSON actions, tool arguments, or intermediate text. A UI should choose what to display for its users. A worker's text fragment is progress, while its task status and result determine its outcome. Remote unary/A2A calls retain their returned-evidence fallback; live remote fragments depend on negotiated native ProtoLink streaming.

See [local ownership and background work](subagents.md#optional-background-work) and [streaming controls](progressive-control.md#streaming-cancellation-and-reports). Durable execution supports blocking local delegation; background spawning is unavailable on durable parents.

## Return control after a work slice

Set `yield_after_steps` to bound how many inference model turns one execution attempt may take before returning control. Enable durable execution on that agent or its owning parent so the unfinished loop has a checkpoint to resume:

```python
from protolink import Agent, RunBudget, RunContext, RunHandoff, Task, TaskState
from protolink.llms import MockLLM


def inspect_section(section: str) -> str:
    """Read one section of the local fixture."""
    return f"Evidence from {section}."


agent = Agent(
    name="reviewer",
    llm=MockLLM(
        sequential_responses=[
            {"type": "tool_call", "tool": "inspect_section", "args": {"section": "intro"}},
            {"type": "tool_call", "tool": "inspect_section", "args": {"section": "method"}},
            {"type": "tool_call", "tool": "inspect_section", "args": {"section": "results"}},
            "Reviewed all three sections.",
        ]
    ),
    tools=[inspect_section],
    yield_after_steps=3,
    durability="runs.sqlite",
    verbosity=0,
)
context = RunContext(budget=RunBudget(max_steps=8, max_llm_calls=8, max_tool_calls=3))
task = await agent.run_task(Task.create_infer("Review the fixture.", context=context))
root_run_id = RunContext.from_task(task).run_id
handoff = RunHandoff.from_task(task)

assert task.state is TaskState.INPUT_REQUIRED
assert handoff is not None and handoff.steps == 3
assert handoff.usage.llm_calls == 3
print(handoff.to_dict())

# After the application decides that another slice is appropriate:
continued = await agent.resume_task(root_run_id)
assert continued.state is TaskState.COMPLETED
assert continued.get_output() == "Reviewed all three sections."
```

The first attempt saves the three tool observations and returns before a fourth model call. The explicit resume grants another slice and the model produces its final answer. No additional model call produces a handoff summary. A final answer produced within the current slice completes normally.

### Interpret the result

A handoff uses the existing task state `TaskState.INPUT_REQUIRED` and `metadata["interruption"]["kind"] == "yield"`. It reports unfinished work, not successful completion. Read it with `RunHandoff.from_task(task)` or `RunResult.handoff`:

| Field | Meaning |
| --- | --- |
| `run_id` | Durable run that yielded; this can identify a child when the root task exposes a child's pause |
| `reason` | `"step_slice"` for the configured cooperative boundary |
| `steps` | Cumulative model turns in the yielding inference loop |
| `usage` | Cumulative `BudgetUsage` shared by the run tree |
| `completed_action_ids` | IDs of succeeded operations recorded for that durable run; inspect the existing report and receipts for their evidence |

`to_dict()` and `from_dict()` serialize this progress metadata. The value carries no private conversation, tool-result body, or generated summary, and its completed action IDs do not certify the whole assignment. The application evaluates what remains and whether it merits another slice.

With the streaming API, inspect `result.status == "input-required"` and `result.handoff`. The current stream ends at that pause. `invoke()` and `resume()` raise `RunInterrupted` for a handoff; `run_task()` and `resume_task()` return the task for direct inspection.

### Resume through the owning root

Save the **root run ID** in your application's job record. To continue a yielded root or owned child, call `await root.resume_task(root_run_id)` after the application decides to proceed. If a child yielded, `handoff.run_id` identifies that child; it does not replace the root ID used to resume the tree.

Reopen the same execution store and reconstruct matching agent, tools, workers, and model configuration after a restart. Durable checkpoints restore the model history, pending state, prior observations, rejection allowance, deduplication history, counters, and completed action receipts. Reading the checkpoint or submitting the same paused task to `run_task()` leaves it paused. Each explicit resume grants one further bounded slice; ProtoLink does not schedule another attempt automatically.

For a `yield` interruption, resume without `answer`, `approved`, or a request ID. Approval and question interruptions still require their existing bound responses; a handoff does not approve a pending operation or answer a question. A saved operation awaiting a response resumes through its ordinary authorization boundary.

See [restart and resume](execution-tools.md#start-inspect-restart-resume), [configuration and storage](execution-tools.md#storage-and-application-changes), and [reconciling uncertain operations](execution-tools.md#crashes-and-unknown-outcomes).

### Keep a hard limit for the whole run

`yield_after_steps` counts model turns per slice. It does not interrupt a running tool, provide a wall-clock deadline, or reset any budget. A correction proposal and a final response each use a model turn. Children consume the root run's shared counters, so `handoff.usage.steps` can exceed one child's `handoff.steps`.

When slicing is enabled, `RunBudget.max_steps` supplies the total inference step bound if configured; otherwise the existing ten-step limit applies. Choose an explicit finite bound for work that may need more than ten total steps. Model, tool, token, runtime, and cancellation controls still apply across all slices. A slice boundary checks whether another model turn is permitted before offering continuation. Exhausting a hard limit stops the run; it does not grant another slice.

ProtoLink yields only at a checkpointed inference boundary between operations. It does not yield around an executing or uncertain action. A denial, cancellation, failed operation, uncertain effect, or hard-budget stop retains its existing outcome. This allows an application to approve useful continuation without treating a pause as a success or retrying an operation whose effects are unknown.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| An invalid prepared request still asks for approval | Put no-effect validation in `prepare`; raise `ToolRejectedError` before returning the action. An executor runs after authorization. |
| Corrections stop earlier than expected | Tool/schema/delegation rejections share `max_tool_corrections`, and every additional proposal still needs model budget. |
| Worker registration fails | Use the exact local child name and declared tool. Supply a valid, unoccupied `name=` if the default alias is unsuitable. |
| A worker facade fails after replacing a child | Rebuild the declaration for the intended roster. Existing bindings never silently select a replacement. |
| No worker chunks appear | Consume the parent's live `events()` stream; verify the child is owned and its provider emits fragments. Remote unary calls return evidence after completion. |
| A child completes but the parent is still running | Track each child's source identity. The parent may need its next inference turn or other children before completing. |
| Slicing fails before execution | Configure `durability` on the agent or its owning durable parent and use a positive integer `yield_after_steps`. |
| A yielded task appears successful in the UI | Inspect task state and `RunResult.handoff`; `input-required` with interruption kind `yield` is unfinished. |
| A yielded task does not continue | Reading state is passive. Explicitly call the owning root's `resume_task(root_run_id)` to grant another slice. |
| A run fails at the slice boundary | Inspect hard-budget, cancellation, policy, and execution errors. A cooperative pause cannot defer those stopping conditions. |
| Restart rejects the checkpoint | Restore matching configuration and worker schemas. Follow the existing durable configuration and uncertain-effect recovery rules. |

For application-specific verification of successful work, combine action receipts with a [completion validator](execution-tools.md#completion-evidence-and-bounded-workflows). A worker declaration chooses an execution route, live events expose progress, and a handoff offers the application a continuation decision; none of those substitutes for checking the assignment's actual result.
