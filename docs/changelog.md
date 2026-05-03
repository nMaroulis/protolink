# Changelog

!!! info "About this Changelog"
    All notable changes to the **Protolink** project will be documented in this file.

    The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
    and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---
## Release Notes

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
