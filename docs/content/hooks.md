# Lifecycle hooks

Lifecycle hooks let an application prepare model inputs, transform successful tool observations and validate a final answer while retaining ProtoLink's standard inference loop. They are executable application callbacks: use them for deterministic context selection, result normalization or completion checks. Capability policy continues to authorize actions and telemetry continues to observe them.

```python
from protolink import Agent, AgentHooks, FinalResponse


def check_answer(response: FinalResponse) -> None:
    if not isinstance(response.content, str) or not response.content.strip():
        raise ValueError("Expected a nonempty answer")


agent = Agent(
    name="helper",
    llm="mock",
    hooks=[AgentHooks(before_complete=check_answer)],
)
print(agent.sync.invoke("Write a short answer."))
```

Callbacks run in registration order and may be synchronous or asynchronous. They mutate the supplied object and return `None`. Exceptions and non-`None` return values stop execution visibly. The runtime does not swallow hook failures as optional observer errors.

## Extension points

| Stage | Callback input | Allowed change |
| --- | --- | --- |
| `before_model` | `ModelRequest(history, tools, context, step)` | Edit active history; remove tools from the step's available roster |
| `after_tool` | `ToolObservation(name, result, context, step)` | Transform a copied successful result before it enters model history |
| `before_complete` | `FinalResponse(content, context, step)` | Validate or replace the proposed final content |

`context` is a detached `RunContext` for inspection. Editing it does not modify permissions, shared usage or the runtime's authoritative context. `step` is the logical inference step, not an individual provider retry.

```python
from protolink import Agent, AgentHooks, ModelRequest, ToolObservation


def select_context(request: ModelRequest) -> None:
    # Remove this registered capability from this model step.
    request.tools.pop("delete_document", None)


async def normalize_observation(observation: ToolObservation) -> None:
    if observation.name == "search" and isinstance(observation.result, dict):
        observation.result = {"hits": observation.result.get("hits", [])}


agent = Agent(
    name="helper",
    llm="mock",
    hooks=[
        AgentHooks(
            before_model=select_context,
            after_tool=normalize_observation,
        )
    ],
)
```

A bare callable in `hooks=[callback]` is shorthand for a `before_model` callback. Prefer `AgentHooks` when configuring multiple stages so the lifecycle contract remains apparent.

## Ordering and execution guarantees

For a new model step, ProtoLink prepares the registered tool prompt, invokes `before_model`, rebuilds a filtered tool roster when needed, applies the optional [context policy](context-management.md), prepares the context manifest, enforces budgets and makes the model request. Before-model callbacks run once per logical step; provider retries reuse that prepared request. Mutate the supplied history; replacing the history object is rejected. Editing its initial compiled system message explicitly takes precedence over prompt regeneration, so callbacks doing that own the resulting prompt's descriptions; executable roster checks remain enforced.

Removing a tool affects both the advertised roster and executable dispatch for that step. Adding a new executable or replacing a registered tool through the callback is rejected. Configure tools on the Agent before starting work. A filtered roster is retained with a pending durable action so continuation cannot restore a tool excluded from that step. Tool filtering is an application control; use capability policy for the authoritative permission boundary.

After a successful authorized tool call, its durable receipt is committed before `after_tool` prepares the observation. The callback receives a copy: it can redact or normalize what the model sees without falsifying what executed. Failed tools do not produce a successful observation hook. An observation hook failure cannot undo an external effect; durable recovery reuses the committed receipt rather than executing the tool again.

For a final action, `before_complete` runs before the final event, output part and completion. The transformed answer is retained in conversation history. Validation applies to the complete response; already exposed raw streaming chunks cannot be recalled. If consumers require validated content, display the completed result after the hook succeeds.

Keep callbacks deterministic, idempotent and free of external side effects. Resume can repeat preparation at a checkpoint boundary and replay of a committed result can repeat observation preparation. Application side effects belong in registered tools with normal authorization and receipts. Hooks apply to the default inference loop; direct `call_tool()` invocations and custom orchestration handlers retain their own execution paths.

## Configuration and recovery

Callbacks are not executable configuration data. `Agent.to_dict()` records that hooks need reconnection; restore them explicitly:

```python
saved = agent.to_dict()
restored = Agent.from_dict(saved, llm="mock", hooks=agent.hooks)
```

Use a configured model object if it carries application-specific clients or callbacks. For durable runs, keep the hook roster stable and increment `execution_version` when callback behavior changes. Fingerprints detect the declared stages and policy configuration; they cannot verify arbitrary Python callback semantics.

Named lifecycle extension points are also described in [LangChain's middleware overview](https://docs.langchain.com/oss/python/langchain/middleware/overview). ProtoLink's callback types, ordering, receipt preservation and authorization boundaries are defined by the contract above.
