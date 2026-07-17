# Flows

Structured Flows orchestrate the same A2A-derived `Task`, `Message`, `Part`, `Artifact`, and `AgentCard` primitives used by autonomous delegation. A flow is a deterministic `Flow.execute(Task) -> Task` state machine: it receives the current task, moves it through a known topology, and returns the enriched task at the end.

Flows are a ProtoLink runtime extension, not an A2A protocol operation. The important boundary is that deterministic orchestration does not escape into graph-private models: it continues to use the shared A2A-based task language.

Use flows when the shape of the process is known ahead of time. Instead of asking an LLM to decide the whole plan at runtime, you define the path in code: a sequential pipeline, a fan-out/fan-in review step, a controlled router, or a graph-shaped state machine with loops. The agents inside the flow can still use LLMs, tools, storage, and remote transports. The difference is that the orchestration itself is inspectable Python.

---

## 🧠 The Logic Behind Flows

In standard Protolink agent execution, an Agent receives a task, analyzes it using an LLM, and decides what to do next. It might call a tool, write a response, or delegate work to another Agent through an `agent_call`. That flexible mode is useful when the problem is open ended, but it can be too loose for workflows that must be repeatable, reviewable, or tied to a business process.

Flows move the topology out of the model and into code. A `Pipeline` always runs the same ordered steps. A `Parallel` flow always fans the same input out to the configured branches and merges the results. A `Graph` follows named edges and validates that destinations exist. A `Router` still lets a preceding agent choose a branch, but the available branch keys and destinations are fixed by the developer and recorded on the task for tracing.

:::tip[Why Structured Flows?]

**Structured Flows** are best for processes where the topology matters. They make the movement between agents explicit, while leaving each agent free to do its own specialized work.
They remove the LLM from the routing equation entirely (Agent Delegation). With a Flow, you, the developer, explicitly define the state machine. The task will move predictably from Agent A to Agent B, branching only on logical conditions you define in code.

:::

## What Happens To The Task?

In Protolink, a `Flow` expects a `Task` and returns a `Task`. A Task is essentially a container holding a history of interactions (Messages and Artifacts). When a Flow executes:

1. **Semantic Context Injection**: Before a deterministic next step, the flow builds a short prompt that describes the downstream target and stores it in `task.flow_state["prompt"]`.
2. **Execution**: The flow dispatches the task to the current target. The target can be a local `Agent`, a remote agent string, or another nested `Flow`.
3. **Agent Processing**: The executing agent can read the flow prompt automatically during inference. It appends messages, artifacts, metadata, or state transitions to the same logical task.
4. **Transition Bridge**: If one agent's previous output is not already an executable instruction, Protolink wraps that output into a new `Message.infer(...)` instruction before sending it to the next agent. This keeps direct agent-to-agent steps from silently no-oping on a plain text or artifact result.
5. **Traversal**: The flow moves to the next step and repeats until the topology reaches its terminal point.

`flow_state` is intentionally transient. `Pipeline` and `Graph` clear and rewrite it before each step so agents receive only the relevant downstream context. If you need durable business state, put it in task metadata, messages, artifacts, or storage rather than relying on `flow_state` to survive the whole workflow.

### 🧱 Deep Composability & Nesting

Protolink Flows are fully recursive. This means a step in a `Pipeline` can be another self-contained `Parallel` flow, or a `Graph` node can be a complete `Pipeline`. Nested flows receive the parent flow's client and registry when they have not been configured directly, so complex structures do not need repeated wiring at every level.


<div className="centered-media">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/flows.png" alt="Flows" width="100%" />
</div>


This lets you build hierarchical workflows out of small, reusable pieces. For example, a parent `Pipeline` can draft a response, run a `Parallel` review committee, route the reviewed output, and then finish with a final formatter.

:::info[Polymorphic Step Targets]

Every flow step, branch, route, or graph node supports three target types:

- **Local Agent Instance**: Executes directly in the same process through `agent.handle_task(task)`.
- **URL / Registry Name (string)**: Resolves an agent name through a registry, or dispatches directly to a URL such as `http://...`, `ws://...`, or `runtime://...`.
- **Flow Instance**: Executes a nested sub-flow by calling its own `execute(task)` method.

:::

When a string target is not already a URL, the flow needs a `Registry` or `RegistryClient` so it can discover the agent by name. Remote dispatch also needs an `AgentClient`; if the registry client exposes a transport, Protolink can infer the client from that registry.

---

## ⚙️ Execution

You can run every flow asynchronously with `.execute(task)`. This is the normal API for servers, async scripts, and agents that are already inside an event loop:

```python
from protolink.flows import Pipeline
from protolink.models import Message, Task

task = Task.create(Message.user("Research this topic and summarize it."))

pipeline = Pipeline(registry=registry)
pipeline.add_step("researcher").add_step("summarizer")

result = await pipeline.execute(task)
```

For scripts, CLI commands, and notebooks without async support, use the synchronous wrapper:

```python
result = pipeline.sync.execute(task)
```

The sync wrapper calls `asyncio.run()` internally, so do not use it from inside an already-running event loop. In async applications, always `await flow.execute(task)` directly.

---

## 🧩 Core Flow Patterns

All flow primitives share the same contract: they accept a `Task`, execute one or more `FlowTarget` objects, and return the updated `Task`. They differ only in how they choose the next target.

### 1. Pipeline (Sequential)

A pipeline runs a predefined list of agents in sequential order, passing the output of one agent as the input to the next.

```python
pipeline = Pipeline(registry=registry)
pipeline.add_step("researcher").add_step("summarizer")

await pipeline.execute(task)
```

Use a `Pipeline` when each step depends on the previous step's result: research then summarize, draft then edit, extract then validate, plan then execute. The order is stable, and before each step Protolink looks at the next step to generate the right `flow_state["prompt"]`.

If the next step is an agent, the prompt can include that agent's `AgentCard` so the current agent knows who will consume its output. If the next step is a `Router`, the prompt includes the available route keys and the routing instructions. If the next step is `Parallel`, the prompt describes all branch receivers so the current agent can produce an output useful to all of them.

:::tip[Fluid API]

Pipelines support a fluid API via the `.add_step()` method, allowing you to chain steps together dynamically during initialization.

:::

```python
pipeline = (
    Pipeline(registry=registry)
    .add_step("researcher")
    .add_step("fact_checker")
    .add_step("summarizer")
)
```

### 2. Parallel Execution

If multiple agents can act independently on the same task without needing each other's output, you can execute them concurrently. Their resulting parts are appended to the task outcome simultaneously.

:::warning[Semantic Fan-Out Context]

When a preceding agent passes its output to a `Parallel` flow, Protolink's Semantic Context Injection automatically informs the agent that it is broadcasting to a committee of concurrent receivers. The agent is fed the `AgentCards` for all parallel branches, allowing it to formulate a single comprehensive response optimized for *all* downstream consumers!

:::
:::info[Safe Fan-in]

Parallel execution uses **ID-based merging**. This ensures that the unified task only includes strictly new messages and artifacts from each branch, preventing duplicates even in complex nested structures.

:::

Under the hood, `Parallel` deep-copies the incoming task once per branch. Each branch gets an isolated task, so one branch cannot accidentally observe another branch's in-progress metadata or artifact changes. After all branches finish, Protolink merges newly created messages and artifacts back into the original task in branch order.

Metadata from each branch is also merged into the final task. If two branches write the same metadata key, the later branch in the configured branch list wins. For data that must never collide, prefer branch-specific metadata keys or artifacts.

```python
from protolink.flows import Parallel

# Executes Editor and Reviewer at the exact same time
parallel = Parallel(
    branches=["editor", "reviewer"], 
    registry=registry
)

task = Task.create(Message.user("Please analyze this draft."))
result = await parallel.execute(task)

for art in result.artifacts:
    print(f"- {art.parts[0].content}")
```

Parallel is most useful for independent review, scoring, enrichment, extraction, or validation steps. It is less useful when branch B needs the exact output of branch A; use a `Pipeline` for that.

### 3. Conditional Routing

A `Router` allows conditional branching based on **LLM decision-making** while keeping the actual branch transition explicit and inspectable. The Router injects your `routing_prompt` into the *preceding agent*, asking it to choose one of the named routes.

The preferred contract is a structured route part:

```python
from protolink.models import Message, Part

task.add_message(
    Message(
        role="agent",
        parts=[
            Part.text("This draft needs editing."),
            Part.route("editor", reason="needs polish"),
        ],
    )
)
```

`Part.route(...)` round-trips through normal task serialization, appears in traces, and gives tests an exact branch key to assert. The Router also accepts JSON-shaped decisions such as `{"route_key": "editor"}` and the older `[ROUTE: editor]` text tag as compatibility fallbacks.

The route key must match one of the keys in `routes`. If the preceding agent emits an unknown key, the router raises a `ValueError` instead of guessing. Every successful route decision is appended to `task.metadata["route_decisions"]`, which makes routing behavior easier to inspect in tests, traces, and replay tooling.

Use `Router` when the content of the task should choose the next branch but the allowed branches should remain controlled by the developer. If the branch decision should be pure Python logic instead of a model-generated route decision, use a `Graph` conditional edge.

```python
from protolink.flows import Router

router = Router(
    routes={
        "editor": "editor", 
        "quality": "quality"
    }, 
    routing_prompt="If the text is poorly written, choose 'editor'. If it is perfect, choose 'quality'.",
    registry=registry
)

# Place the router in a Pipeline:
pipeline = Pipeline(registry=registry)
pipeline.add_step("writer").add_step(router)

# The 'writer' agent will automatically receive the routing instructions and choose the path!
task = Task.create(Message.user("Write a very short poem."))
await pipeline.execute(task) 
```

In this example, the `writer` agent receives the routing instructions before it runs. The `Router` itself does not ask the model again; it reads the route decision already present on the task and dispatches to the mapped target.

### 4. Graph Flows (State Machines)

For creating highly complex deterministic workflows with loops, complex conditional branching, and a state-machine architecture, you can use the `Graph` flow.

```python
from protolink.flows import Graph

graph = Graph(registry=registry)

# 1. Add Nodes
graph.add_node("entry", "writer")
graph.add_node("process", "editor")
graph.add_node("final", "quality")

# 2. Add standard edges
graph.add_edge("entry", "process")

# 3. Add conditional routing edges
def review_logic(t: Task) -> str:
    return "approved" # Normally you'd inspect the task artifacts here

graph.add_conditional_edge(
    "process", 
    review_logic, 
    {"approved": "final", "rejected": "process"} # Loops back on rejection!
)

graph.add_edge("final", "__END__")
graph.set_entry_point("entry")

result = await graph.execute(task)
```

Graphs are useful when the workflow has named stages, loops, or code-defined branch logic. Each node is a normal `FlowTarget`, so it can be a local agent, a remote string target, or an entire nested flow. Edges come in two forms:

- `add_edge("a", "b")` creates a fixed transition from one node to the next.
- `add_conditional_edge("a", condition_fn, path_map)` evaluates `condition_fn(task)` after node `a` finishes and uses the returned key to choose a destination.

Graph validates that referenced nodes exist, requires an entry point, and uses the reserved `"__END__"` destination to terminate. A node can have either a fixed edge or a conditional edge, but not both. To protect against accidental infinite loops, graph execution stops with an error after 50 iterations.

For deterministic edges, Graph can inject downstream context just like Pipeline. For conditional edges, the next node is not known until after the current node executes, so Protolink clears the transient flow prompt before running that node.

## Choosing The Right Flow

| Need | Use |
| ---- | --- |
| Strict ordered stages | `Pipeline` |
| Independent work over the same input | `Parallel` |
| Model-assisted branch choice with fixed destinations | `Router` |
| Named state machine with loops or Python conditions | `Graph` |
| A reusable sub-workflow inside another workflow | Any `Flow` as a nested target |

## Flow API Reference

`FlowTarget` accepts an `Agent` ⎪ `str` ⎪ `Flow`. A string can be a direct URL or a registry name.

### Constructors

| Type | Parameters |
| ---- | ---------- |
| `Flow` | `client: AgentClient` ⎪ `None = None`, `registry: Registry` ⎪ `RegistryClient` ⎪ `None = None` |
| `Pipeline` | `steps: list[FlowTarget]` ⎪ `None = None`, `client: AgentClient` ⎪ `None = None`, `registry: Registry` ⎪ `RegistryClient` ⎪ `None = None` |
| `Parallel` | `branches: list[FlowTarget]`, `client: AgentClient` ⎪ `None = None`, `registry: Registry` ⎪ `RegistryClient` ⎪ `None = None` |
| `Router` | `routes: dict[str, FlowTarget]`, `routing_prompt: str`, `client: AgentClient` ⎪ `None = None`, `registry: Registry` ⎪ `RegistryClient` ⎪ `None = None` |
| `Graph` | `client: AgentClient` ⎪ `None = None`, `registry: Registry` ⎪ `RegistryClient` ⎪ `None = None` |

`Flow` is abstract; construct one of its concrete subclasses in application code.

### Public Methods

| Method | Signature and behavior |
| ------ | ---------------------- |
| `execute()` | `task: Task`<br />Returns `Task`. Asynchronously executes any flow; each concrete flow implements this contract. |
| `sync.execute()` | `task: Task`<br />Returns `Task`. Blocking wrapper around `execute()` for code without an active event loop. |
| `Pipeline.add_step()` | `step: FlowTarget`<br />Returns `Pipeline`. Appends one step and supports chaining. |
| `Graph.add_node()` | `node_name: str`, `target: FlowTarget`<br />Returns `Graph`. Adds a named execution target. |
| `Graph.add_edge()` | `from_node: str`, `to_node: str`<br />Returns `Graph`. Adds one deterministic edge; use `"__END__"` as the terminal destination. |
| `Graph.add_conditional_edge()` | `from_node: str`, `condition_fn: Callable[[Task], str]`, `path_map: dict[str, str]`<br />Returns `Graph`. Maps the condition function's result to a destination node. |
| `Graph.set_entry_point()` | `node_name: str`<br />Returns `Graph`. Selects the first graph node. |

## Practical Notes

- Keep long-lived workflow state in `Task.metadata`, messages, artifacts, or storage. Treat `task.flow_state` as short-lived execution context.
- Prefer structured `Part.route(...)` decisions for routers. Legacy `[ROUTE: key]` tags are supported, but structured parts are easier to test and replay.
- Use registry names for portable flows and explicit URLs when you want the topology to point at a concrete service.
- Keep branch metadata keys distinct in `Parallel` flows if multiple branches may write similar information.
- Test flows by asserting the final `Task`: message count, artifact IDs, metadata, route decisions, and terminal state are usually better assertions than checking only the final text.
