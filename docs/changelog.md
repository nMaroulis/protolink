
\# Changelog

!!! info "About this Changelog"
    All notable changes to the **Protolink** project will be documented in this file.

    The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
    and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Release Notes

### [v0.6.0] - TBD

NEW:

- **Task lifecycle enforcement**
  - `Task.state` now uses enforced `TaskState` transitions instead of acting as a loose label.
  - Added terminal-state awareness through `Task.is_terminal` for `completed`, `failed`, and `canceled` tasks.
  - Added lifecycle helpers: `Task.begin()`, `Task.require_input()`, and `Task.cancel()`.
  - Successful state transitions are recorded in `task.metadata["state_history"]`.
  - Direct task construction now normalizes serialized state values and rebuilds the last-item cache.

- **Agent-managed task states**
  - Default `Agent.execute_task()` now moves non-terminal tasks to `working`, finalizes successful runs as `completed`, marks error outputs and exceptions as `failed`, and supports `input-required` status outputs.
  - Streaming task handling now emits lifecycle-aware status updates and includes the final serialized task in final status event metadata.
  - `TaskLifecycle` now applies protocol-safe transition paths before completing, requiring input, failing, or canceling tasks.

- **LLM history serialization helper**
  - Added `protolink.llms.serialization.json_history_default()` for framework object serialization in LLM conversation history.
  - Base and Anthropic LLM history injection now serialize dataclasses, `to_dict()` objects, and `model_dump()` objects consistently.

- **First-run developer experience**
  - Added top-level exports for common primitives such as `Agent`, `AgentCard`, `Task`, `Tool`, `Pipeline`, `create_llm`, and local tracing utilities.
  - Added the `protolink init agent` CLI command with runnable `basic` and `tool` starter templates.

- **Local observability**
  - Added `LocalTraceTelemetry` and `LocalTraceRecorder` for in-memory and JSONL task trace replay.
  - Local traces now capture trace IDs, span hierarchy, LLM action events, retry counts, token estimates, model metadata, and redacted payloads.

- **Typed LLM action protocol**
  - Added typed `FinalAction`, `ToolCallAction`, `AgentCallAction`, and `LLMActionResult` models for the `infer()` execution loop.
  - Added provider-native action acquisition for OpenAI, Anthropic, Gemini, DeepSeek, Grok, Ollama, llama.cpp, LM Studio, and OpenAI-compatible servers where supported.
  - Added native streaming action acquisition through `call_action_stream()` so providers can stream text while buffering tool-call deltas into one validated runtime action.
  - Added provider-neutral tool schema builders and synthetic native delegation tools for agent calls.

Changed:

- `protolink.models` now exports `TaskState`.
- Task validation now accepts empty message, artifact, and metadata containers and validates `Task.state` as a `TaskState`.
- Flow execution no longer auto-wraps plain user messages without executable parts into inferred prompts.
- Telemetry hooks now accept optional LLM metadata and expose detailed inference-loop events through `on_llm_event()`.
- LLM prompt selection now separates JSON action prompts from native provider tool prompts, preventing native providers from seeing JSON tool-call instructions while keeping small/local models on the simple JSON protocol by default.
- Ollama, llama.cpp, LM Studio, and OpenAI-compatible local servers now use native tool calling only when `supports_tool_calling=True`; otherwise they retain the JSON fallback path.
- `.ruff_cache/` is now ignored by git.

Infer Loop Updates:
- The LLM no longer directly drives execution through fragile raw text.
- Every step converges into typed actions: FinalAction, ToolCallAction, AgentCallAction.
- Native providers like OpenAI/Anthropic/Gemini use real provider tool calling instead of being forced through prompt JSON.
- Small/local models still get the simpler JSON protocol, which is the right call for Ollama/Gemma-style reliability.
- Streaming now has a real action boundary through call_action_stream(), instead of pretending chunks are immediately executable.
- The loop has retries, parse failure limits, duplicate-action detection, tool argument correction, unknown-tool correction, and structured events for observability.

Fixed:

- Fixed delegated agent tool results crashing LLM history injection when the remote tool output is hydrated as a `ToolOutput` dataclass.
- Fixed task execution leaving tasks in non-terminal states after successful default agent execution.
- Fixed invalid direct lifecycle jumps such as `submitted -> completed` by requiring transition through `working`.

Docs:

- Updated README task semantics to describe `Task.state` and `metadata["state_history"]`.
- Added Agent documentation for default task lifecycle behavior and streaming status updates.
- Expanded model and transport docs for task lifecycle states, terminal states, transition history, and new task helper methods.
- Added CLI documentation and local trace telemetry documentation.
- Expanded LLM documentation for the typed `infer()` cycle, JSON vs native action modes, native streaming tool-call behavior, and provider support matrix.

Tests:

- Added lifecycle coverage for direct task construction, invalid transitions, `Task.complete()`, successful agent execution, and failed tool execution.
- Added regression coverage for delegated `ToolOutput` serialization in the LLM inference loop.
- Added coverage for top-level exports, CLI scaffolding, local trace capture, redaction, and retry metadata.
- Added regression coverage for native action dispatch, native streaming action dispatch, provider tool-call normalization, streamed tool-call delta accumulation, and Ollama's opt-in native tool mode.

### [v0.5.8] - 2026-06-11

NEW:

- **SSE JSON-RPC streaming transport**
  - Added `SSEJSONRPCTransport` for `text/event-stream` task streams over HTTP.
  - Registered transport aliases: `"sse"`, `"json-rpc"`, and `"sse-json-rpc"`.
  - Starlette and FastAPI backends now serialize streaming endpoint events as JSON-RPC-style SSE envelopes.

- **Agent-level LLM streaming**
  - `Agent.handle_task_streaming()` now streams task status, LLM events, tool progress, artifacts, and completion.
  - `LLM.infer()` accepts `streaming=True` and an optional `event_callback` observer for chunks, tool calls, agent calls, parse errors, and final output.
  - `AgentClient.send_task_streaming()` now validates transport streaming support before subscribing.
  - `client.sync.send_task_streaming()` provides a blocking iterator for scripts and CLI interfaces.
  - Agent cards now reflect the selected transport's streaming capability for discovery and registry filtering.
  - `AgentCard.to_dict()` and `AgentCard.from_dict()` now preserve the `transport` field.

- **Local and OpenAI-compatible LLMs**
  - Added `OpenAICompatibleLLM` for servers exposing `/v1/chat/completions` and `/v1/models`.
  - Added `LMStudioLLM` for LM Studio's local OpenAI-compatible server.
  - Added provider keys `"lmstudio"` and `"openai-compatible"`.

Changed:

- Provider, server LLM, and transport exports are now lazy-loaded so optional SDKs are only required when the selected provider or transport needs them.
- `create_llm()` lazy factory entries now cover all documented providers, including Grok, Hugging Face, LM Studio, OpenAI-compatible servers, and Mock LLMs.
- Agent `verbosity=0` now suppresses transport server access logs more aggressively.
- Documentation updated for streaming, SSE JSON-RPC, LM Studio, OpenAI-compatible local servers, and the new client/server transport flow.

Tests:

- Added focused coverage for lazy mock LLM creation, SSE JSON-RPC event parsing, `AgentClient` streaming checks, sync streaming iteration, and agent LLM stream attachment.

### [v0.5.7] - 2026-06-07

NEW:

- Authentication now works with all transports (http, websocket)
  - Integrated to Agent. Now passable to agent as an argument 
    - `authenticator`: Optional Authenticator instance for verifying incoming requests to this agent.
    - `credentials`: Optional credentials string used for authenticating outgoing requests.

- **Import** / **Export** Agent from/to `yaml`
  - Agent can now serialize itself and save to yaml file
    - `to_yaml`: Saves the agent configuration to a YAML file
  - Agent can now load from yaml file
    - `from_yaml`: Loads the agent configuration from a YAML file

Bug Fixes:

None

### [v0.5.6] - 2026-05-17

# Flows Refactor & Upgrade

- **Semantic Context Injection**: Flows dynamically build instruction prompts based on their downstream topology. This prompt is injected into the `task.flow_state["prompt"]` for executing agents to utilize seamlessly. This way agents are aware of their downstream context and can format their output accordingly.
- Correct **Task** management. Added flow_state to Task, so that we provide additional context to the agents.
- **NEW Flow Examples** for each Use case (Graph, Pipeline, Parallel, Router).
- Removed **Structured Agent**
- Better **State** Management
- **Flow Sync** Module

**More:**

- **HUGE BUG fix**: Agent URL received from registry was wrong most of the time.
- **Agent Sync** Module
- **LLM Sync** Module
- **Added GuardRails**:
    - Added context for Agent ID and prevent agent from calling himself.
    - Removed self from fetched agents.
- **Agent Discovery TTL**
- **Mock LLM** for testing

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

Historical patch release.

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

The near-term roadmap focuses on hardening the runtime paths that production agent systems depend on most.

### Upcoming Features

- [x] **Agent Task Handling**: Enforced task lifecycle transitions and state history.
- [x] **Delegated Inference**: Typed tool and agent actions in the LLM inference loop.
- [x] **Storage**: In-memory and SQLite storage implementations.
- [x] **Observability**: Local trace replay plus Langfuse and LangSmith integrations.
- [x] **Integrations**: MCP adapter for external tool servers.
- [ ] **Transport Layer**: Add a production-ready gRPC transport implementation and factory registration.
- [ ] **State Modules**: Expand tool, task, and flow state modules beyond their current storage-backed extension points.
- [ ] **OpenTelemetry**: Add first-class OpenTelemetry export alongside the existing telemetry integrations.
