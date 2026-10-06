# Context management

Context management controls what the model sees on each inference step. An Agent can retain conversation history, read large tool results incrementally and keep recent exchanges within a configured context allowance. This is separate from durable execution: context preparation bounds model input, while execution checkpoints preserve unfinished operations and committed results.

```python
from protolink import Agent

agent = Agent(name="researcher", llm="mock", context_policy="auto")
print(agent.sync.invoke("Explain the evidence you find."))
```

`context_policy="auto"` enables deterministic preparation before every request in the default inference loop. Configure normal tools through `tools=`; a scoped `read_context_artifact` tool is installed automatically. The default Agent behavior remains opt-in. Context preparation does not introduce another action protocol or a separate orchestration loop.

## Configure the allowance

```python
from protolink import Agent, ContextPolicy

agent = Agent(
    name="researcher",
    llm="mock",
    context_policy=ContextPolicy(
        max_tokens=16_000,
        reserve_tokens=2_000,
        preserve_recent=2,
        tool_result_max_chars=4_000,
        max_artifacts=16,
        artifact_max_chars=200_000,
    ),
)
```

| Setting | Meaning | Default |
| --- | --- | --- |
| `max_tokens` | Total context ceiling, including reserved output | Model metrics profile's `context_window`, otherwise 32,000 |
| `reserve_tokens` | Space withheld from the prompt for model output | 2,048 |
| `preserve_recent` | Minimum recent user turns and recent marked tool observations retained | 2 |
| `tool_result_max_chars` | Maximum serialized result size before offloading; also the preview length | 6,000 |
| `max_artifacts` | Maximum retrievable observations in one scope; oldest entries are evicted | 32 |
| `artifact_max_chars` | Maximum retained JSON text per artifact; excess text is explicitly marked truncated | 1,000,000 |

Counts are estimates from ProtoLink's existing token estimator. Provider tokenization, image inputs and native tool-schema overhead can differ. Set a conservative ceiling and configure the provider's output limit separately: reserving tokens does not change its generation parameters. A `RunBudget` still limits aggregate calls, tokens, tools and runtime across the run; this policy controls the size of each prompt.

Before dispatch, preparation removes the oldest complete user turns until the estimated input fits `max_tokens - reserve_tokens`. The initial system instructions and protected recent turns remain. A user turn includes all subsequent messages up to the next user message, so pruning preserves native function-call/result associations.

When a long current turn still exceeds the allowance, the policy clears older marked tool observations in place. Their message roles, metadata and correlation fields remain and artifact references are retained where available. Recent observations and original user input remain protected. If that protected input still cannot fit, `ContextLimitError` stops execution before another model request. An error is preferable to silently dropping the current task or breaking a provider's message contract.

## Large observations and progressive retrieval

Successful tool results above the character threshold become a JSON preview with a `context_artifact` identifier, stored/original lengths and a truncation flag. The model can call:

```json
{
  "type": "tool_call",
  "tool": "read_context_artifact",
  "args": {"artifact_id": "the-returned-id", "offset": 0, "max_chars": 4000}
}
```

Retrieval returns a bounded text page, `next_offset` and an `untrusted_content` marker. Offsets count characters of the serialized JSON text; pages are not necessarily independently valid JSON. `max_chars` is limited to 20,000. Retrieval calls consume ordinary tool/step budgets and retrieved pages can themselves be cleared once they become older observations. The full external result remains in durable action receipts when durability is configured; observation preparation never rewrites that receipt.

Artifacts belong to the current Agent conversation session. Ordinary agents retain them in a bounded in-memory inventory of up to 128 sessions; those artifacts disappear when the application exits. Durable agents store them in the private execution checkpoint, allowing retrieval after a restart. Local subagents have their own scopes. An unknown, evicted or out-of-scope identifier produces an explicit error. Artifact identifiers do not grant cross-session access.

Keep artifact bounds appropriate for your workload: maximum retained text scales with artifact count and size and durable checkpoints serialize retained artifacts when saved. For larger corpora, use a configured knowledge source or application tool that retrieves original documents by page or query. Ephemeral retrieval results configured to stay out of history are not copied into persistent context artifacts.

## Explicit summary compaction

Automatic preparation makes no additional model call and does not invent a summary. Use the existing [history compaction API](llm.md#history-compaction) when your application needs a curated or model-generated summary. Its `recent`, `tokens` and `summary` strategies remain available. Summary quality is an application decision: retain unresolved questions, constraints, relevant evidence and resource references and verify those details against the source material.

The design follows the context-engineering principle of retaining relevant information and retrieving additional evidence incrementally. Anthropic describes compaction, structured notes and selective clearing of tool results in [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). ProtoLink implements deterministic pruning, observation clearing and scoped artifact retrieval; summary generation is an explicit operation.

## Hooks, events and serialization

[Before-model hooks](hooks.md) run before context preparation. Tool observation hooks run before oversized observations are offloaded. `context_compacted` events report estimated before/after sizes, removed messages, cleared observations and the prompt allowance; normal context manifests describe the prepared input.

The policy settings serialize with `Agent.to_dict()`. Live artifact contents are excluded from configuration exports and `from_dict()` recreates the scoped retrieval tool rather than restoring an executable placeholder. For durable applications, changing the policy changes the execution contract and prevents continuation of incompatible checkpoints. Custom adapters that override `infer()` must support these extension arguments explicitly; the default loop provides the integrated behavior.
