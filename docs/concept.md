# Concept

After reading this page you should have a good understanding of the core concepts and architecture of Protolink.

## Architecture Overview

Protolink is designed around **explicit separation of concerns**, **protocol agnosticism**, and **low boilerplate** for agent authors.  
At a high level, Protolink models an agent as a **logical actor** that communicates with other agents via well-defined client/server interfaces, backed by pluggable transports.

The core idea is simple:  

> Agents express intent. Clients and servers handle communication. Transports handle protocols.  

This separation keeps agent logic **clean, testable, and future-proof**.

---

# Core Concepts

Protolink is built from the following **core components**:

- **Agent** — business logic and orchestration  
- **Client** — outgoing communication  
- **Server** — incoming communication  
- **Transport** — protocol + runtime implementation  
- **Registry** — discovery and coordination  

Each layer has a **single responsibility** and a clear **dependency direction**.

---

# Agent

The **Agent** is the central abstraction in Protolink.  

It represents:

- Identity (via `AgentCard`)  
- Capabilities and skills  
- Task handling logic  
- Lifecycle orchestration  

The agent **does not perform networking** and **does not implement protocols**.

### Responsibilities

- Define how tasks are handled (`handle_task`)  
- Manage tools, skills, and optional LLMs  
- Coordinate startup and shutdown  
- Orchestrate client/server components  
- Register and discover peers via the registry  

### What the Agent Does Not Do

- Open sockets  
- Handle HTTP requests  
- Serialize messages  
- Know about protocols (HTTP, WS, local, etc.)  

This is **intentional and enforced by design**.

---

# Client / Server Layer

Between the agent and the transport, Protolink introduces an **explicit client/server layer**.  
This layer removes boilerplate from agent implementations while keeping responsibilities clear.

## AgentClient (Outgoing)

The `AgentClient` handles **agent-to-agent outgoing communication**.

### Responsibilities

- Sending tasks to other agents  
- Sending messages to other agents  
- Delegating all transport details  

The client exposes **intent-level methods only**.

Example interface (simplified):

```python
send_task(agent_url, task)
send_message(agent_url, message)
```

Key point: The client knows what it wants to send but does not know how it is sent.


## AgentServer (Incoming)

The `AgentServer` handles **incoming requests** for an agent.

### Responsibilities

- Wiring the agent’s task handler into the transport  
- Starting and stopping the server runtime  
- Enforcing lifecycle rules  

The server:

- Receives tasks via the transport  
- Delegates task execution to the agent  
- Never contains business logic  

---

## Transport Layer

The `AgentTransport` is the **lowest layer** in the system.  

It encapsulates:

- Network protocol (HTTP, WS, local, etc.)  
- Runtime concerns (ASGI, threads, event loops)  
- Serialization and deserialization  
- Request routing  

### Key Properties

- Protocol-agnostic  
- Swappable without touching agent logic  
- Reusable across agents  
- Shared by client and server  

> The transport is **never accessed directly by the agent**.

---

## Dependency Direction (Important)

The dependency graph is strictly **one-way**:

Agent
 ├── AgentClient
 │    └── AgentTransport
 └── AgentServer
      └── AgentTransport



**Key points:**

- The agent owns the client and server  
- The client and server own the transport  
- The agent never calls transport methods directly  

This guarantees:

- Clean abstractions  
- Easy testing  
- No protocol leakage into business logic  

---

## Registry

The registry enables **agent discovery and coordination**.  
Architecturally, it **mirrors the agent model**.

### Registry Components

- **Registry** — logical registry service  
- **RegistryClient** — outgoing discovery requests  
- **RegistryServer** — incoming registry API  
- **RegistryTransport** — protocol implementation  

### Registry Dependency Graph

Registry
 ├── RegistryClient
 │    └── RegistryTransport
 └── RegistryServer
      └── RegistryTransport



This symmetry is intentional and keeps the **mental model consistent** across the system.

### Registry Responsibilities

- Agent registration  
- Agent discovery  
- Heartbeat and expiry (liveness)  
- Filtering and metadata queries  

> Agents interact with the registry **only via the `RegistryClient`**.

---

## Agent Lifecycle

A typical agent lifecycle looks like this:

1. **Instantiation** with:  
   - `AgentCard`  
   - Transport  
   - Optional registry reference  

2. **Creation** of:  
   - `AgentClient`  
   - `AgentServer`  

3. **Startup**:  
   - Server runtime  
   - Registry registration  

4. **Runtime**: Agent runs autonomously  

5. **Shutdown**:  
   - Server stopped  
   - Registry unregistration  

> All of this happens with **minimal boilerplate** for the user.

---

## Autonomous Agents

Protolink supports **autonomous behavior** without external orchestration.

Agents can:

- Discover peers  
- Schedule tasks  
- Send tasks to other agents  
- React to incoming tasks  

This is done **inside the agent**, without manual wiring between agents.  
Agents behave like **independent actors**, not manually invoked objects.

---

## Why This Architecture

This design is intentionally:

- Protocol-agnostic  
- Low boilerplate  
- Explicit  
- Composable  
- Testable  

It draws inspiration from:

- Actor models  
- Ports & adapters (hexagonal architecture)  
- Distributed systems design  
- Google A2A concepts (agent cards, tasks, discovery)  

Most importantly:

> The agent stays simple, and complexity is pushed down into infrastructure layers.

---

## Summary

- Agents **express intent**  
- Clients and servers **handle directionality**  
- Transports **handle protocols**  
- Registries **handle coordination**  
- Dependencies flow **one way**  
- Boilerplate is **minimized by design**  

This architecture makes it easy to:

- Add new transports  
- Scale from local to distributed  
- Swap protocols  
- Keep agent logic clean and focused

---

# Design Principles

Protolink’s architecture is guided by a small number of **explicit design principles**.  
These principles explain *why* the system looks the way it does and help contributors extend it coherently.

---

## 1. Intent Over Mechanism

Agents express **what they want to do**, never **how it is done**.

- Agents send tasks  
- Agents receive tasks  
- Agents discover peers  

They do **not**:
- Open sockets  
- Serialize payloads  
- Know transport details  

This allows:
- Clean agent logic  
- Easier testing  
- Transport substitution without rewrites  

---

## 2. Directional Communication Is Explicit

Outgoing and incoming communication are **separate concerns**.

That is why Protolink has:
- `AgentClient` for outgoing requests  
- `AgentServer` for incoming requests  

This avoids:
- Bidirectional “god objects”  
- Hidden side effects  
- Transport leakage into agents  

---

## 3. Transport Is a Boundary, Not a Feature

Transports are infrastructure.

They are:
- Swappable  
- Replaceable  
- Reusable  
- Shared between client and server  

Agents should never depend on:
- HTTP  
- ASGI  
- WebSockets  
- Threads  
- Event loops  

This keeps the system future-proof.

---

## 4. Registry Mirrors Agent Architecture

The registry is not “special”.

It follows the **same architectural rules** as agents:

- Logical registry object  
- Client for outgoing calls  
- Server for incoming calls  
- Transport underneath  

This symmetry:
- Reduces cognitive load  
- Improves maintainability  
- Makes distributed registries natural  

---

## 5. Minimal Boilerplate, Explicit Control

Protolink aims to reduce boilerplate **without hiding control**.

- Defaults are sensible  
- Explicit overrides are possible  
- No magic global state  
- No hidden background threads  

You always know:
- What is running  
- What is registered  
- What is communicating  

---

# Agent ↔ Agent Sequence Diagram

This section describes the **runtime flow** when one agent sends a task to another.

---

## Scenario

Agent A wants to send a task to Agent B.

Both agents are already running and registered.

---

## Sequence

1. Agent A creates a `Task`  
2. Agent A calls `send_task_to(agent_b_url, task)`  
3. `AgentClient` forwards the task to its transport  
4. Transport sends the request to Agent B’s server endpoint  
5. Agent B’s transport receives the request  
6. `AgentServer` invokes Agent B’s `handle_task`  
7. Agent B processes the task  
8. The result task is returned through the same path  
9. Agent A receives the completed task  

---

## Responsibility Breakdown

- Agent: defines *what* to do  
- Client: defines *direction*  
- Server: defines *entry point*  
- Transport: defines *mechanism*  

No layer violates its responsibility.

---

# Registry Interaction Sequence

This section explains how discovery works at runtime.

---

## Agent Startup

1. Agent starts its server  
2. Agent creates a `RegistryClient`  
3. Agent registers its `AgentCard`  
4. Registry stores the agent metadata  
5. Optional heartbeat begins  

---

## Discovery

1. Agent requests discovery via `RegistryClient`  
2. Registry applies filters  
3. Registry returns matching `AgentCard`s  
4. Agent decides what to do next  

The registry **never pushes behavior** to agents.

---

# Comparison With Raw Google A2A

Protolink is inspired by Google’s A2A spec, but intentionally diverges in structure.

---

## What Is Preserved

- Agent Cards  
- Task-based communication  
- Explicit discovery  
- Stateless requests  
- Protocol neutrality  

---

## What Is Improved

### 1. Central Agent Abstraction

In Protolink, the agent is the **primary unit**, not a loose collection of endpoints.

This:
- Improves composability  
- Makes agents easier to reason about  
- Encourages reusable agent logic  

---

### 2. Explicit Client / Server Split

Google A2A often conflates:
- Sending  
- Receiving  
- Hosting  

Protolink separates them cleanly, which:
- Improves testability  
- Clarifies ownership  
- Reduces hidden coupling  

---

### 3. Registry as a First-Class Component

Instead of being an afterthought, the registry is:
- Structured  
- Extensible  
- Transport-agnostic  
- Distributed-ready  

---

### 4. Lower Boilerplate for Users

A typical Protolink agent requires:
- One subclass  
- One `handle_task` method  
- One transport  

Everything else is handled by composition.

---

# Mental Model Summary

If you remember only one thing:

> **Agents think. Clients talk. Servers listen. Transports move bytes. Registries coordinate.**

Each layer is small, focused, and replaceable.

That is the entire philosophy.
