import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

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

`FlowTarget` accepts an `Agent | str | Flow`. A string can be a direct URL or a registry name.

### Constructors

`Flow` is abstract; construct one of its concrete subclasses in application code.

### Flow

<ApiReference kind="abstract class" path="protolink.flows.Flow" signature={`Flow(
    client: AgentClient | None = None,
    registry: Registry | RegistryClient | None = None,
)`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/base.py">
Base contract and shared dispatcher for deterministic workflows. It owns remote-client and registry wiring, the synchronous facade, semantic-context generation, target resolution, and nested-flow dependency propagation.

<ApiSection title="Parameters"><ApiFields ariaLabel="Flow constructor parameters">
  <ApiField name="client" type="AgentClient | None" defaultValue="None">Client used for string targets. When omitted, remote dispatch can infer one from a configured RegistryClient transport at execution time.</ApiField>
  <ApiField name="registry" type="Registry | RegistryClient | None" defaultValue="None">Discovery source for string targets that are names rather than direct HTTP, HTTPS, WS, WSS, or runtime URLs. A Registry contributes its client.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Attributes"><ApiFields ariaLabel="Flow attributes"><ApiField name="sync" type="SyncFlow">Blocking facade bound to this exact flow instance.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Abstract type">Instantiate <code>Pipeline</code>, <code>Parallel</code>, <code>Router</code>, or <code>Graph</code>. Subclasses implement only traversal; shared target execution stays in Flow.</ApiCallout>

</ApiReference>

### Pipeline

<ApiReference kind="class" path="protolink.flows.Pipeline" signature={`Pipeline(
    steps: list[FlowTarget] | None = None,
    client: AgentClient | None = None,
    registry: Registry | RegistryClient | None = None,
)`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/pipeline.py">
Execute an ordered sequence against one evolving Task. Before each step, Pipeline clears transient <code>flow_state</code> and compiles instructions for the known downstream target; the final step receives terminal-output guidance.

<ApiSection title="Parameters"><ApiFields ariaLabel="Pipeline constructor parameters">
  <ApiField name="steps" type="list[FlowTarget] | None" defaultValue="None">Initial ordered targets. The list is retained as <code>pipeline.steps</code>; <code>None</code> creates an empty pipeline.</ApiField>
  <ApiField name="client" type="AgentClient | None" defaultValue="None">Remote-dispatch client inherited by unconfigured nested flows.</ApiField>
  <ApiField name="registry" type="Registry | RegistryClient | None" defaultValue="None">Optional name-resolution source.</ApiField>
</ApiFields></ApiSection>

</ApiReference>

### Parallel

<ApiReference kind="class" path="protolink.flows.Parallel" signature={`Parallel(
    branches: list[FlowTarget],
    client: AgentClient | None = None,
    registry: Registry | RegistryClient | None = None,
)`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/parallel.py">
Fan one Task out to independently deep-copied branches, await every branch concurrently, then merge new messages, artifacts, and metadata back into the original Task in configured branch order.

<ApiSection title="Parameters"><ApiFields ariaLabel="Parallel constructor parameters">
  <ApiField name="branches" type="list[FlowTarget]" required>Concurrent local Agents, strings, or nested Flows. An empty list is valid and returns the original task without additions.</ApiField>
  <ApiField name="client" type="AgentClient | None" defaultValue="None">Remote branch client.</ApiField>
  <ApiField name="registry" type="Registry | RegistryClient | None" defaultValue="None">Optional name resolver.</ApiField>
</ApiFields></ApiSection>

<ApiCallout label="Failure and merge order"><code>asyncio.gather(..., return_exceptions=False)</code> propagates a branch exception and skips fan-in. Successful results merge in branch-list order, so a later branch wins metadata-key collisions.</ApiCallout>

</ApiReference>

### Router

<ApiReference kind="class" path="protolink.flows.Router" signature={`Router(
    routes: dict[str, FlowTarget],
    routing_prompt: str,
    client: AgentClient | None = None,
    registry: Registry | RegistryClient | None = None,
)`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/router.py">
Dispatch to one developer-approved target using a route decision already written by the preceding step. Router prefers structured route parts, accepts JSON-shaped decisions, and retains the historical text tag as a compatibility fallback.

<ApiSection title="Parameters"><ApiFields ariaLabel="Router constructor parameters">
  <ApiField name="routes" type="dict[str, FlowTarget]" required>Allowed decision keys mapped to targets. Router never guesses an unknown key.</ApiField>
  <ApiField name="routing_prompt" type="str" required>Criteria injected by a preceding Pipeline into that preceding Agent's prompt; Router itself does not make another model call.</ApiField>
  <ApiField name="client" type="AgentClient | None" defaultValue="None">Remote-route client.</ApiField>
  <ApiField name="registry" type="Registry | RegistryClient | None" defaultValue="None">Optional target-name resolver.</ApiField>
</ApiFields></ApiSection>

</ApiReference>

### Graph

<ApiReference kind="class" path="protolink.flows.Graph" signature={`Graph(
    client: AgentClient | None = None,
    registry: Registry | RegistryClient | None = None,
)`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/graph.py">
Create an initially empty named state machine. Nodes, edges, and entry point are added separately; <code>"__END__"</code> is reserved as the terminal destination.

<ApiSection title="Parameters"><ApiFields ariaLabel="Graph constructor parameters">
  <ApiField name="client" type="AgentClient | None" defaultValue="None">Remote-node client.</ApiField>
  <ApiField name="registry" type="Registry | RegistryClient | None" defaultValue="None">Optional node-name resolver.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Attributes"><ApiFields ariaLabel="Graph attributes">
  <ApiField name="nodes" type="dict[str, FlowTarget]">Named execution targets.</ApiField>
  <ApiField name="edges" type="dict[str, str]">One fixed destination per origin.</ApiField>
  <ApiField name="conditional_edges" type="dict[str, tuple[Callable, dict[str, str]]]">Condition function and route map per origin.</ApiField>
  <ApiField name="entry_point" type="str | None">First node, initially unset.</ApiField>
  <ApiField name="finish_point" type="str" defaultValue={'"__END__"'}>Reserved terminal sentinel.</ApiField>
</ApiFields></ApiSection>

</ApiReference>

### Public Methods

### Flow.execute

<ApiReference kind="abstract async method" path="protolink.flows.Flow.execute" signature={`async execute(task: Task) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/base.py">
Execute one concrete flow's topology against a Task.

<ApiSection title="Parameters"><ApiFields ariaLabel="Flow execute parameters"><ApiField name="task" type="Task" required>Mutable task passed through targets. Concrete flows return the same logical task, enriched by target outputs and flow metadata.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Flow execute return value"><ApiField name="task" type="Task">Final task after the topology terminates.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Local Agent dispatch">A local Agent target is called through <code>agent.handle_task(task)</code>, not <code>agent.run_task(task)</code>. Remote targets go through AgentClient. Applications needing the Agent live-cancellation/run-store wrapper for local steps should account for that distinction.</ApiCallout>

</ApiReference>

### Flow.sync.execute

<ApiReference kind="method" path="protolink.flows.SyncFlow.execute" signature={`execute(task: Task) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/base.py#L300-L310">
Blocking equivalent of the concrete flow's <code>execute()</code>, implemented with <code>asyncio.run()</code>.

<ApiSection title="Parameters"><ApiFields ariaLabel="synchronous flow execute parameters"><ApiField name="task" type="Task" required>Mutable task to pass through the concrete flow's topology. The wrapper forwards this exact object to the asynchronous implementation.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="synchronous flow execute return value"><ApiField name="task" type="Task">Final task after every selected target finishes and the topology terminates.</ApiField></ApiFields></ApiSection>

<ApiCallout label="Event loops">Do not call this wrapper inside an active event loop. Await <code>flow.execute(task)</code> there.</ApiCallout>

</ApiReference>

### Pipeline.add_step

<ApiReference kind="method" path="protolink.flows.Pipeline.add_step" signature={`add_step(step: FlowTarget) -> Pipeline`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/pipeline.py">
Append one target to <code>steps</code> and return this Pipeline for fluent chaining.

<ApiSection title="Parameters"><ApiFields ariaLabel="Pipeline add step parameters"><ApiField name="step" type="FlowTarget" required>Local Agent, direct URL or registry name, or nested Flow.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Pipeline add step return value"><ApiField name="pipeline" type="Pipeline">This same Pipeline instance, allowing calls such as <code>pipeline.add_step(a).add_step(b)</code>.</ApiField></ApiFields></ApiSection>

</ApiReference>

### Graph.add_node

<ApiReference kind="method" path="protolink.flows.Graph.add_node" signature={`add_node(
    node_name: str,
    target: FlowTarget,
) -> Graph`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/graph.py#L48-L61">
Add or replace a named target and return this Graph. The reserved terminal name cannot be used as a node.

<ApiSection title="Parameters"><ApiFields ariaLabel="Graph add node parameters">
  <ApiField name="node_name" type="str" required>Unique identifier used by edges and the entry point. Reusing an existing non-reserved name replaces that node's target.</ApiField>
  <ApiField name="target" type="FlowTarget" required>Local Agent, direct URL or registry name, or nested Flow executed when traversal reaches this node.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Graph add node return value"><ApiField name="graph" type="Graph">This same Graph instance for fluent construction.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Graph add node errors"><ApiField name="ValueError"><code>node_name == "__END__"</code>.</ApiField></ApiFields></ApiSection>

</ApiReference>

### Graph.add_edge

<ApiReference kind="method" path="protolink.flows.Graph.add_edge" signature={`add_edge(
    from_node: str,
    to_node: str,
) -> Graph`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/graph.py#L63-L83">
Assign a fixed outbound transition. Both nodes must already exist, except that the destination may be <code>"__END__"</code>.

<ApiSection title="Parameters"><ApiFields ariaLabel="Graph add edge parameters">
  <ApiField name="from_node" type="str" required>Existing origin node whose next transition should be deterministic.</ApiField>
  <ApiField name="to_node" type="str" required>Existing destination node, or the reserved <code>"__END__"</code> sentinel to terminate traversal.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Graph add edge return value"><ApiField name="graph" type="Graph">This same Graph instance for fluent construction.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Graph add edge errors"><ApiField name="ValueError">A node is missing or the origin already owns a conditional edge.</ApiField></ApiFields></ApiSection>

</ApiReference>

### Graph.add_conditional_edge

<ApiReference kind="method" path="protolink.flows.Graph.add_conditional_edge" signature={`add_conditional_edge(
    from_node: str,
    condition_fn: Callable[[Task], str],
    path_map: dict[str, str],
) -> Graph`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/graph.py#L85-L113">
Evaluate a synchronous Python function after the origin finishes and map its returned key to the next node.

<ApiSection title="Parameters"><ApiFields ariaLabel="Graph conditional edge parameters">
  <ApiField name="from_node" type="str" required>Existing origin node.</ApiField>
  <ApiField name="condition_fn" type="Callable[[Task], str]" required>Synchronous decision function. Async callables are not awaited.</ApiField>
  <ApiField name="path_map" type="dict[str, str]" required>Decision keys to existing nodes or <code>"__END__"</code>.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Graph conditional edge return value"><ApiField name="graph" type="Graph">This same Graph instance for fluent construction.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Graph conditional edge errors"><ApiField name="ValueError">An origin or destination is missing, the origin already owns a fixed edge, or execution later returns an unmapped key.</ApiField></ApiFields></ApiSection>

</ApiReference>

### Graph.set_entry_point

<ApiReference kind="method" path="protolink.flows.Graph.set_entry_point" signature={`set_entry_point(node_name: str) -> Graph`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/graph.py#L115-L126">
Select an existing node as the traversal start and return this Graph.

<ApiSection title="Parameters"><ApiFields ariaLabel="Graph set entry point parameters"><ApiField name="node_name" type="str" required>Name of an existing node that should execute first.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Graph set entry point return value"><ApiField name="graph" type="Graph">This same Graph instance for fluent construction.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Graph set entry point errors"><ApiField name="ValueError">No node with <code>node_name</code> has been added to the graph.</ApiField></ApiFields></ApiSection>

</ApiReference>

### Concrete execute behavior

Each concrete method implements the traversal described earlier on this page. Pipeline mutates sequentially; Parallel copies then merges; Router records and dispatches one decision; Graph traverses named edges with a hard limit of 50 executed nodes.

#### Pipeline.execute

<ApiReference kind="async method" path="protolink.flows.Pipeline.execute" signature={`async execute(
    task: Task,
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/pipeline.py#L56">
Run the task through <code>steps</code> in declaration order. Before each step, Pipeline clears transient flow state and injects context for the known downstream target; the last step receives terminal-output guidance.

<ApiSection title="Parameters"><ApiFields ariaLabel="Pipeline execute parameters"><ApiField name="task" type="Task" required>Initial task that every sequential step reads and enriches.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Pipeline execute return value"><ApiField name="task" type="Task">Fully processed task containing the accumulated messages, artifacts, metadata, and final flow context.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Pipeline execute errors"><ApiField name="ValueError | RuntimeError">Target resolution fails, a target type is invalid, or a remote target has no usable client.</ApiField><ApiField name="target error">Agent, nested-flow, registry, and transport exceptions propagate immediately; remaining steps are not executed.</ApiField></ApiFields></ApiSection>

</ApiReference>

#### Parallel.execute

<ApiReference kind="async method" path="protolink.flows.Parallel.execute" signature={`async execute(
    task: Task,
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/parallel.py#L47">
Deep-copy the input task for every branch, execute all branches concurrently, and merge only newly added messages and artifacts into the original task. Successful branch results are merged in configured order, regardless of completion order.

<ApiSection title="Parameters"><ApiFields ariaLabel="Parallel execute parameters"><ApiField name="task" type="Task" required>Source task copied independently for each configured branch.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Parallel execute return value"><ApiField name="task" type="Task">Original task enriched with deduplicated branch messages and artifacts plus merged metadata.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Parallel execute errors"><ApiField name="branch error">Any branch exception propagates through <code>asyncio.gather()</code>; fan-in is skipped instead of returning a partial merge.</ApiField></ApiFields></ApiSection>

</ApiReference>

#### Router.execute

<ApiReference kind="async method" path="protolink.flows.Router.execute" signature={`async execute(
    task: Task,
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/router.py#L128">
Read the route decision already produced by the preceding step, validate it against the configured route map, record the decision, and dispatch the task to exactly one developer-approved target.

<ApiSection title="Parameters"><ApiFields ariaLabel="Router execute parameters"><ApiField name="task" type="Task" required>Active task whose latest output contains a structured route part, JSON-shaped decision, or legacy route tag.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Router execute return value"><ApiField name="task" type="Task">Task returned by the selected route after the decision has been recorded.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Router execute errors"><ApiField name="ValueError">The decision is missing, malformed, or names a key absent from <code>routes</code>.</ApiField><ApiField name="target error">Resolution, nested-flow, Agent, registry, and transport failures from the selected route propagate.</ApiField></ApiFields></ApiSection>

</ApiReference>

#### Graph.execute

<ApiReference kind="async method" path="protolink.flows.Graph.execute" signature={`async execute(
    task: Task,
) -> Task`} source="https://github.com/nMaroulis/protolink/blob/main/protolink/flows/graph.py#L128">
Traverse from the configured entry point until the reserved <code>"__END__"</code> destination is reached. Fixed edges allow downstream context injection before a node runs; conditional edges select their destination from the node's resulting task.

<ApiSection title="Parameters"><ApiFields ariaLabel="Graph execute parameters"><ApiField name="task" type="Task" required>Initial task carried from node to node and passed to each condition function after its origin node finishes.</ApiField></ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Graph execute return value"><ApiField name="task" type="Task">Final enriched task after traversal reaches <code>"__END__"</code>.</ApiField></ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Graph execute errors"><ApiField name="ValueError">A conditional result has no destination in its path map, or shared target resolution rejects a target.</ApiField><ApiField name="RuntimeError">No entry point is configured, a remote target lacks a client, or traversal exceeds the 50-node safety limit.</ApiField><ApiField name="target error">Agent, nested-flow, registry, transport, and condition-function exceptions propagate.</ApiField></ApiFields></ApiSection>

</ApiReference>

## Practical Notes

- Keep long-lived workflow state in `Task.metadata`, messages, artifacts, or storage. Treat `task.flow_state` as short-lived execution context.
- Prefer structured `Part.route(...)` decisions for routers. Legacy `[ROUTE: key]` tags are supported, but structured parts are easier to test and replay.
- Use registry names for portable flows and explicit URLs when you want the topology to point at a concrete service.
- Keep branch metadata keys distinct in `Parallel` flows if multiple branches may write similar information.
- Test flows by asserting the final `Task`: message count, artifact IDs, metadata, route decisions, and terminal state are usually better assertions than checking only the final text.
