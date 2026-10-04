# Local subagents

Give an agent a few specialists. ProtoLink runs each specialist as an owned child with its own task and conversation, then returns its result to the parent. No server or registry is needed.

```python
from protolink import Agent

researcher = Agent(name="researcher", llm="mock", system_prompt="Find supporting evidence.")
assistant = Agent(name="assistant", llm="mock", subagents=[researcher])

answer = await assistant.invoke("Explain the evidence for this claim.")
```

`mock` is an offline model that returns a fixed answer by default. The runnable [subagents example](https://github.com/nMaroulis/protolink/blob/main/examples/subagents.py) scripts an actual delegation. Replace it with your chosen provider for model-selected work.

## What a child adds to delegation

The child is an ordinary `Agent`. Existing remote delegation still communicates with an independently managed peer. A local subagent adds ownership to that relationship:

| Behavior | Local subagent |
| --- | --- |
| Configuration | Supply an existing Agent in `subagents=[...]` |
| Context | Separate conversation; the parent sends the requested prompt or tool arguments |
| Lifecycle | Parent owns the child and cancels and drains unfinished work when it ends |
| Budgets | Children and grandchildren consume the root run's shared counters and active runtime |
| Policies | Parent and ancestor policies are evaluated alongside the child's policy; deny takes precedence |
| Evidence | Child run/task/action IDs and artifacts are retained; streamed events carry parent links |
| Limits | Bound total children, concurrent children and delegation depth |
| Recovery | Blocking local delegation participates in a durable parent's checkpoints |

Conversation separation does not isolate files, Python objects, credentials or the operating system. Agents use their configured tools and application resources.

Each child receives a fresh session ID for that run, even when it has conversation persistence configured. It receives the delegated prompt, its own instructions and tools, and inherited run controls. The parent receives its completed result and artifacts. ProtoLink does not copy the entire parent conversation into the child.

## The inference contract

The parent uses the existing action:

```json
{"type": "agent_call", "agent": "researcher", "action": "infer", "prompt": "Find supporting evidence."}
```

Delegating a known specialist tool also works:

```json
{"type": "agent_call", "agent": "calculator", "action": "tool_call", "tool": "add", "args": {"a": 2, "b": 3}}
```

The model still chooses one of `final`, `tool_call` or `agent_call`. ProtoLink advertises the configured specialist cards through the same prompt and provider-native delegation mechanisms. A blocking child call supplies an ordinary agent-result observation before the parent's next model call. There is no additional mandatory planning prompt or different action format.

Local names take precedence over registry peers with the same name. Local names must be unique, ignoring case, and different from the parent's name. Calls that create an ancestor cycle are rejected. Your local roster defines which specialists can be selected; existing discovery continues to expose remote peers when configured. Remote calls retain their existing transport lifecycle.

## More control

```python
from protolink import Agent, RunBudget, SubagentLimits

assistant = Agent(
    name="assistant",
    llm="mock",
    subagents=[researcher],
    subagent_limits=SubagentLimits(max_children=8, max_concurrency=4, max_depth=1),
)
result = await assistant.invoke("Research this topic", budget=RunBudget(max_llm_calls=20, max_tool_calls=10))
```

The defaults permit eight total children, four concurrent children, and direct children only. `max_children` counts every created child, including queued and completed work, across the run tree. Resuming a saved child does not create another child or consume another count. Depth one permits parent-to-child calls; increase `max_depth` for nested specialists. A nested call with no available concurrency slot fails with `SubagentLimitError` instead of waiting forever for its own ancestor's slot.

The root run's budget governs the tree. Worker policies can further restrict permissions; a child cannot relax an ancestor's decision. Tools must declare meaningful capabilities for capability policies to inspect them. Ordinary callables without capabilities remain subject to custom policies but supply no capability labels automatically.

## Optional background work

Blocking delegation is enough for many applications. A live application can start a child while its parent is working:

```python
run = assistant.start_run("Work on this topic")
child = await run.spawn("researcher", "Check this specific claim")
child_task = await child.result()
child_task.raise_for_status()
print(child_task.get_output())
parent_result = await run.result()
```

The parent must still be running when `spawn()` executes. `SubagentHandle` exposes `id`, `run_id`, `task`, `result()` and `cancel(reason)`. Cancelling a waiter on `result()` leaves the owned child running. Ending or cancelling its parent cancels queued and running children and awaits their cleanup. Cancellation is cooperative; a synchronous function or external operation may already have committed its effect.

To let the model manage concurrent work, opt in:

```python
assistant = Agent(
    name="assistant",
    llm="mock",
    subagents=[researcher],
    subagent_limits=SubagentLimits(background=True),
)
```

This registers three ordinary tools: `spawn_subagent(agent, prompt)`, `wait_subagent(child_id)` and `cancel_subagent(child_id)`. The spawn receipt contains the child ID; waiting returns its state, output and metadata. The parent must check that state before using the result. These tools use `tool_call` and add their usual tool descriptions to the prompt. The core action vocabulary stays the same.

Background children are live execution. A child with its own durable configuration must run under a durable parent; child checkpoints use the parent's execution store. Version 0.8.0 supports [durable execution](durable-execution.md) for blocking local delegation. Combining durable configuration with background model tools is rejected; `RunHandle.spawn()` is also unavailable on durable parents.

## Configuration and evidence

Use `agent.start_run()` for child events in the parent's stream and `RunReport`. Child events preserve their identity and carry `parent_action_id` and `delegation_id`; `metadata.parent_run_id` links the parent. A child's final event does not close the parent's stream. `Task.metadata.subagent_runs` records created child IDs for ordinary task calls too.

Agent dict/YAML configuration serializes roster names and limits. Reattach executable child instances with `Agent.from_dict(config, subagents=[researcher])`; names must match. The optional supervision tools are recreated from the limits, so closures are not serialized. This is configuration loading; it does not resume execution by itself.
