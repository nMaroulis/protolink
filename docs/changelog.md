# Changelog

!!! info "About this Changelog"
    All notable changes to the **Protolink** project will be documented in this file.
    
    The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
    and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---
## Release Notes

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


Currently working on **v0.4.6**

- Finalize **LLM Automated Inference**:
    - Examine how to structure the tool calling logic.
    - Examine how to structure the agent delegation logic.
    - Examine how to structure the final result processing logic


### Upcoming Features
- [ ] **Agent Task Handling**: Finalise logic for robust task management.
- [ ] **Delegated Inference**: Logic for agent delegation and tool calling.
- [ ] **Transport Layer**: Add gRPC transport support.
- [ ] **Storage**: Add base classes and implementations (e.g., SQLite).
- [ ] **Observability**: Add OpenTelemetry support out-of-the-box.
- [x] **Integrations**: Finalise MCP adapter.
