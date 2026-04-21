# Flows

Update **0.5.0** introduces **Structured Flows**, a new feature that allows you to define complex, structured workflows for your agents. Building on the core Agent-to-Agent (A2A) architecture, flows enable deterministic execution paths such as sequential pipelines, parallel execution, or complex graph structures.

Unlike standard Agents that might rely on LLMs to dynamically map out interactions and routing, flows mandate strict execution paths, ensuring consistent and predictable outcomes for multistep tasks.

---

## 🧠 The Logic Behind Flows

In standard Protolink (or many other LLM-based frameworks), an Agent receives a task, analyzes it using an LLM, and decides what to do next—whether that's calling a tool, writing some text, or delegating work to another Agent via an `agent_call`. While powerful and flexible, this "implicit routing" can sometimes be unpredictable, expensive, or hard to debug for rigid enterprise processes.

!!! success "Why Structured Flows?"
    **Structured Flows** solve this by removing the LLM from the routing equation entirely. With a Flow, you—the developer—explicitly define the state machine. The task will move predictably from Agent A to Agent B, branching only on logical conditions you define in code.

**Wait, what actually happens to the Task?**

In Protolink, a `Flow` expects a `Task` and returns a `Task`. A Task is essentially a container holding a history of interactions (Messages and Artifacts). When a Flow executes:

1. It sends the `Task` to the first Agent.
2. That Agent performs its logic (maybe running tools or inferring) and appends a new `Artifact` containing its output to the `Task`.
3. The Flow retrieves the updated `Task` and passes it to the next Agent in the sequence. 
4. This continues until the flow finishes, returning a highly-enriched `Task` full of intermediate artifacts.

---

## ⚙️ Execution Modes: Manual vs. Autonomous

One of the most important concepts to understand is **how** a flow actually runs. Protolink provides two distinct ways to execute your flows:

=== "Manual / Script-Based"

    You can define a Flow and run it programmatically in your Python script using its `.execute(task)` method. In this mode, the flow runs exactly once to completion and then your script continues.
    
    This is great for one-off tasks, background jobs, or testing.

=== "Autonomous (The StructuredAgent)"

    If you want your flow to act as an autonomous entity continuously listening for tasks on a network, you simply pass it to a `StructuredAgent`.
    
    !!! tip "The Power of StructuredAgent"
        A `StructuredAgent` is a built-in Protolink Agent that runs a `Flow` behind the scenes. This is extremely powerful because it packages an entire complex pipeline into a compliant A2A node! From the outside, other agents or clients don't even know it's a flow—they interact with the `StructuredAgent` exactly like any other agent.

---

## 🧩 Core Flow Patterns

All flows can optionally be instantiated with a `Registry` or `RegistryClient` so they can discover agents dynamically by their registered name instead of explicitly hardcoded URLs.

### 1. Pipeline (Sequential)

A pipeline runs a predefined list of agents in sequential order, passing the output of one agent as the input to the next.

```python
import asyncio
from protolink.discovery import Registry
from protolink.flows import Pipeline
from protolink.models import Task, Message

async def run_pipeline():
    registry = Registry(url="http://localhost:9020", transport="http")
    await registry.start()

    # Define a Pipeline
    pipeline = Pipeline(
        steps=["researcher", "summarizer"],  # Passes task through researcher, then summarizer
        registry=registry,
    )

    task = Task.create(Message.user("Research Protolink please."))

    # Manual / Script execution
    result = await pipeline.execute(task)
    print(result.get_last_part_content())
```

### 2. Parallel Execution

If multiple agents can act independently on the same task without needing each other's output, you can execute them concurrently. Their resulting parts are appended to the task outcome simultaneously.

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

### 3. Conditional Routing

A `Router` allows conditional branching. Based on a user-defined evaluator function you provide, the task is forwarded to a specific mapped agent.

```python
from protolink.flows import Router

# Evaluator returns the string key mapped to the next agent
def route_condition(t: Task) -> str:
    content = t.get_last_part_content()
    return "needs_edit" if "bad" in content.lower() else "good_to_go"

router = Router(
    routes={
        "needs_edit": "editor", 
        "good_to_go": "quality"
    }, 
    condition_fn=route_condition, 
    registry=registry
)

# This will route uniquely to the 'editor' agent based on evaluating the text
task = Task.create(Message.user("This is really bad."))
await router.execute(task) 
```

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
```

---

## 🏛️ Encapsulating within a StructuredAgent

As mentioned earlier, you can take any of the flows defined above (even the highly complex `Graph` state machine) and wrap them directly into a `StructuredAgent`.

!!! info "Seamless Interoperability"
    Once wrapped, your workflow is exposed as a single Agent endpoint. Other components in your system can offload work to this massive pipeline by just sending it a standard Protolink Task!

```python
from protolink.agents.builtins import StructuredAgent

# Wrap the Graph state machine inside an autonomous Agent!
structured_agent = StructuredAgent(
    card={"name": "graph_agent", "url": "http://localhost:8035"},
    flow=graph, # Pass any Flow (Pipeline, Parallel, Graph, Router, etc)
    transport="http",
    registry="http",
    registry_url="http://localhost:9030",
)

# Start listening on the network
await structured_agent.start()

# Now other agents or clients seamlessly interact with the flow:
client = AgentClient(transport="http", url="http://localhost:8036")
task = Task.create(Message.user("Write a blog post about Protolink."))
result = await client.send_task("http://localhost:8035", task)
```
