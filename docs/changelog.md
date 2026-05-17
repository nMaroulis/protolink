
\# Changelog

!!! info "About this Changelog"
    All notable changes to the **Protolink** project will be documented in this file.

    The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
    and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Release Notes

### [v0.5.6] - 2026-05-17

# Flows Refactor & Upgrade

- **Semantic Context Injection**: Flows dynamically build instruction prompts based on their downstream topology. This prompt is injected into the `task.flow_state["prompt"]` for executing agents to utilize seamlessly. This way agents are aware of their downstream context and can format their output accordingly.
- **Graph**: Add Graph flow, which is a flow that is made up of nodes and edges. 
- **Pipeline**: Add Pipeline flow, which is a flow that is made up of steps. 
- **Parallel**: Add Parallel flow, which is a flow that is made up of branches. 
- **Router**: Add Router flow, which is a flow that is made up of a router. 
  
- Removed **Structured Agent**
- Better **State** Management
- **Flow Sync** Module
- 

**More:**

- **Agent Sync** Module
- **LLM Sync** Module
- **Agent Discovery TTL**

### [v0.5.5] - 2026-05-16

#### 🐞 NEW Feature - State (API Refactor)

- **State Management**: Refactored agent state management, specifically around conversation history persistence. The syntax has been simplyfied:

```python
agent = Agent(
    card=card,
    ...
    state=["conversation"],  # Session memory is not reset between tasks
)
```

NEW: **protolink.state** module. The State class manages:

- **Session memory** - Session memory is not reset between tasks
- **Conversation history** - Conversation history persistence
- **Tool call history** - Tool call history persistence
- **Flow state** - Flow state persistence

**DSA Optimization**:

- **Conversation History**: Use Message Double Ended Queue for O(1) append and pop operations.
- **Registry Storage**: Optimize agent pop operations to O(1)
and more... 


### [v0.5.4] - 2026-05-12

#### 🐞 Refactored

- **Agent Lifecycle**: Fixed issues with agent start/stop logic, specifically around event loop tasks and background threads. The syntax has been simplyfied:
- **Proper Thread Management**: Removed asyncio event loop and background threads for starting/stopping.

```python
agent.start()
agent.stop()
```

That's it. The `start()` method will start the agent in a background thread and will properly wait for all queues to empty. The `stop()` function will properly wait for all queues to empty, and gracefully shutdown the agent and background threads.

### [v0.5.3] - 2026-05-03

#### 🐞 Fixed

- **Tooling Schema**: Tool schema is now correctly inferred from the function signature and type hints. It is also correctly appended to the Agent Card prompt, so other agents are aware of available tools and schemas.

### [v0.5.2] - 2026-05-02

#### 🚀 Added

- **Logging Module**: Added explicit `file` logger (json) and `console` logger (color).
- Plug in Logging to the Agent using the `logger` argument. If none is provided, a default logger using the ConsoleLogger, so the IO is appended to the terminal.
- Added **context memory**:
  - "none" - No context memory.
  - "session" - Session based context memory. Agent remembers all messages exchanged during the current session with other agents.
Memory is configured in the agent using the `memory` argument. If none is provided, no memory is used.

### [v0.5.1] - 2026-04-28

#### 🚀 Added

- **Telemetry**: Add LangSmith and Langfuse telemetry implementations
- **BaseTelemetry**: Add base telemetry class
- **LangfuseTelemetry**: Langfuse telemetry implementation
- **LangsmithTelemetry**: Langsmith telemetry implementation
- **MultiTelemetry**: Multiplex multiple telemetry implementations.
- **Agent**: Plug in to the Agent using the `telemetry` argument. If none is provided, no telemetry is collected.

### [v0.5.0] - 2026-04-22

#### 🚀 Added

- **Flows**: Build deterministic execution paths out of the box (`Pipeline`, `Parallel`, `Router`, `Graph`).
- **StructuredAgent**: Wrap any complex flow to run autonomously as a generic, network-ready A2A agent.

### [v0.4.8] - 2026-04-19

TBA

### [v0.4.7] - 2026-02-08

#### 🚀 Added

- **LLM Inference Guardrails**:
  - Implemented robust guardrails for LLM inference.
  - Added agent calling for delegated inference.
  - Final result processing.
- NEW **GrokLLM**:
- Ticket Example
- Verbosity in Agent and Registry
and more...

### [v0.4.6] - 2026-02-05

#### 🚀 Added

- **LLM Automated Inference**:
  - Implemented robust tool calling capabilities.
  - Added agent calling for delegated inference.
  - Final result processing.
- **Agent Orchestration**:
  - Centralized handling for LLM inference, tool execution, and result aggregation.

#### 🔄 Changed

- **LLM API**: Refactored for better type safety and extensibility.
- **Agent Constructor**: Simplified initialization options.
- **Transport Factory**: Improved factory patterns for transport creation.

#### 🐞 Fixed

- **Agent Stability**: Resolved race conditions in agent message handling.
- **HTTP Backend**: Fixed issues with stream termination.

### [v0.4.5] - 2026-01-26

!!! abstract "Current Status"
    Work in progress features for the next release.

#### 🚀 Added

- **LLM Automated Inference**:
  - Implemented robust tool calling capabilities.
  - Added agent calling for delegated inference.
  - Final result processing.
- **Agent Orchestration**:
  - Centralized handling for LLM inference, tool execution, and result aggregation.

#### 🔄 Changed

- **LLM API**: Refactored for better type safety and extensibility.
- **Agent Constructor**: Simplified initialization options.
- **Transport Factory**: Improved factory patterns for transport creation.

#### 🐞 Fixed

- **Agent Stability**: Resolved race conditions in agent message handling.
- **HTTP Backend**: Fixed issues with stream termination.

## 🗺️ Roadmap

Currently working on **v0.4.8**

- Finalize LLM Inference Guardrails

### Upcoming Features

- [ ] **Agent Task Handling**: Finalise logic for robust task management.
- [ ] **Delegated Inference**: Logic for agent delegation and tool calling.
- [ ] **Transport Layer**: Add gRPC transport support.
- [ ] **Storage**: Add base classes and implementations (e.g., SQLite).
- [ ] **Observability**: Add OpenTelemetry support out-of-the-box.
- [x] **Integrations**: Finalise MCP adapter.
