
# Changelog

!!! info "About this Changelog"
    All notable changes to the **Protolink** project will be documented in this file.

    The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
    and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

# Release Notes

## [v0.6.4] - 2026-07-01

### Added

- Added `QuietLogger`, a no-op `BaseLogger` implementation for agents and integrations that need the logging interface without emitting output.
- Added the ProtoLink ***Whitepaper***.
- Added task-local LLM **history scopes** for **concurrent agent execution**, including same-session locking for persistent conversation state.
- Added `RunStore`, `SQLiteRunStore`, `TaskRecord`, and `RunReportRecord` for durable task snapshots and run-report persistence.
- Added **registry** entry **liveness metadata**, optional **TTL** pruning, persistent registry **entry storage**, and `RegistryClient.heartbeat()`.
- Added **transport conformance** coverage for Runtime, HTTP, and WebSocket agent contracts.
- Added developer tooling commands for `doctor`, registry inspection, run listing/replay, and a local dashboard with registry health, HTTP agent ping, HTTP agent chat, run replay, and a disabled Studio preview.
- Added `examples/devtools_dashboard.py`, a provider-free dashboard demo with multiple registered agents, persisted run reports, and optional `--serve-live` HTTP mode for clickable **dashboard** ping/chat.
> To try it:
```bash
protolink doctor
python examples/devtools_dashboard.py --output-dir .protolink-devtools
protolink run replay dashboard_demo_1 --store .protolink-devtools/runs.db
protolink dashboard --store .protolink-devtools/runs.db --open
```

### Fixed

- Fixed `Agent.start(register=False)` so the lifecycle now honors the public `register` argument.
- Fixed RuntimeTransport async request-parser handling.
- Fixed WebSocket route registration, stale client-connection reuse, and task-stream closure semantics.

## [v0.6.3] - 2026-06-26

### Added

- **Context manifests and enforceable run budgets**
  - Added `ContextManifest`, `ContextItem`, and `build_context_manifest()` so applications can inspect estimated system, history, tool/delegation, user, total, and context-window usage before every LLM call.
  - Added `BudgetPolicy`, `BudgetEnforcer`, `BudgetDecision`, `BudgetUsage`, and `BudgetExceededError` to enforce `RunBudget` limits for steps, LLM calls, tool calls, runtime seconds, input tokens, and output tokens.
  - `LLM.infer()` now emits additive `context_prepared`, `llm_call_started`, `llm_call_completed`, `budget_warning`, and `budget_exceeded` events while preserving existing low-level LLM events.
  - `RunEvent` now promotes those events into stable `context.prepared`, `llm.call.started`, `llm.call.completed`, `budget.warning`, and `budget.exceeded` types for UI and golden-run consumers.
  - `LLMModelProfile` now accepts descriptive capability metadata such as `supports_tools`, `supports_streaming`, `supports_json_schema`, and `tokenizer` without becoming a live model catalog.
- **State inspection and state control reports**
  - Added `StateOperationRequest`, `StateStoreReport`, and `StateOperationResult` for typed describe, reset, and compact reports over agent state.
  - Added `Agent.describe_state()`, `Agent.reset_state()`, and `Agent.compact_state()` plus matching `AgentClient` request specs for `POST /state/describe`, `POST /state/reset`, and `POST /state/compact`.
  - State operations run through runtime policy capabilities (`state.describe`, `state.reset`, `state.compact`, and `llm.history.compact`) before reading or mutating state.
- **Run reports, replay, and redaction**
  - Added `RunReport`, `RunRecorder`, `RunReplay`, `assert_run_events()`, `assert_no_denied_actions()`, and `assert_budget_under()` for durable app-facing run summaries and golden-run integration tests.
  - Added `RedactionPolicy` and `DEFAULT_REDACTION_POLICY` so reports and local telemetry share one recursive secret-masking surface.
  - `RunEvent` now exposes optional `span_id`, `parent_span_id`, `action_id`, `parent_action_id`, and `delegation_id` fields for causal UI routes and replay tools.
- **Runnable integration examples**
  - Added provider-free `examples/v063_*.py` scripts covering context budgets, request-spec history compaction, state control endpoints, run reports/replay/redaction, and an abstract ProtoAgent-style policy mesh with tool capabilities and approval previews.

### Changed

- **Agent codebase reafctor with MixIns**: Agent is now the stable public facade, with behavior split into:
  - `engine.py`: task execution, streaming, LLM calls, delegation
  - `mixins.py`: lifecycle, control plane, communication, tools, config, serialization
  - `helpers.py`: state request normalization
  - `sync.py`: SyncAgent
  - `_typing.py`: internal structural typing support for mixins

- **LLM history compaction**: instead of having it as a tool which will just stress the model's context more, it's now a client/server spec, so it's called via an endpoint.
  - Kept the LLM-owned `HistoryCompactor` component with `recent`, `tokens`, and `summary` strategies plus structured before/after results.
  - `LLM.compact_history()` remains as a concise facade while compaction algorithms and isolated summary prompts live in the dedicated component.
  - Added `HistoryCompactionRequest`, `Agent.compact_history()`, and `AgentClient.COMPACT_HISTORY_REQUEST` (`POST /llm/history/compact`) so agents can compact persistent context through the same client/server spec pattern as other control endpoints.

## [v0.6.2] - 2026-06-24

### Added

- **Built-in LLM history compaction**
  - Added the LLM-owned `HistoryCompactor` component with `recent`, `tokens`, and `summary` strategies plus structured before/after results.
  - `LLM.compact_history()` remains as a concise facade while compaction algorithms, summaries, prompts, and tool construction live in the dedicated component.
  - Added the reserved `protolink_compact_history` runtime tool so agents can compact persistent context in response to explicit user requests.
  - Compaction preserves the leading system prompt and protected recent turns; summary generation is isolated and atomic on provider failures.
- Tests:
  - Added Starlette, FastAPI, and WebSocket regression coverage for nested `ToolOutput` stream payloads.

### Fixed

- **Nested transport payload serialization**
  - Starlette and FastAPI SSE backends now recursively normalize nested framework objects before encoding JSON-RPC event frames.
  - Delegated and tool-result events containing a `ToolOutput` dataclass in `content` or `metadata` no longer terminate the stream with `TypeError: Object of type ToolOutput is not JSON serializable`.
  - WebSocket streaming now uses the same shared recursive serializer for consistent event payloads across network transports.

### Changed

- Documented recursive JSON normalization and structured tool-result behavior in the transport and client streaming guides.

## [v0.6.1] - 2026-06-21

### Added

- **Live task cancellation**
  - Added `CancellationToken`, `TaskCancellationRequest`, and an active-task registry that separates serializable canceled state from process-local execution control.
  - Added direct and remote task-ID cancellation through `Agent.cancel_task()` and `AgentClient.cancel_task()` across HTTP, SSE JSON-RPC, WebSocket, and RuntimeTransport.
  - Default task, streaming, LLM, tool, and delegated-agent paths now propagate cancellation and produce a final `canceled` task state instead of a failure event.
  - Added `examples/task_cancellation.py` plus direct, streaming, runtime, and WebSocket cancellation coverage.

- **Runtime context and run events**
  - Added `RunContext`, `RunBudget`, `RunEvent`, `EventSink`, and `InMemoryEventSink` for typed run metadata, stable progress streams, and golden-run testing.
  - Default agent execution now normalizes runtime context into `task.metadata["run_context"]` while preserving legacy `session_id` and `trace_id` metadata.

- **Runtime actions, policy, and approvals**
  - Added `RunAction`, structured artifact descriptors, `CapabilityPolicy`, `ActionAuthorizer`, and typed approval request/decision contracts.
  - Tools can declare extensible capabilities and attach preview artifacts; policy is enforced immediately before direct, model-selected, and delegated actions execute.
  - `RunEvent` now promotes action, policy, and approval activity into stable event types for application streams and golden-run tests.
  - Added `examples/runtime_policy_and_approvals.py`, a provider-free walkthrough of previews, approvals, normalized events, and denied side effects.

- **Optional LLM budget metrics**
  - Added `LLMModelProfile` and `LLM.configure_metrics()` for context-window and cost metadata without changing provider request payloads.
  - `LLM.infer()` now emits live `llm_context` and `llm_call_metrics` events when telemetry or an `event_callback` is attached.
  - Local traces now aggregate LLM call count, latency, token usage, context high-water marks, and estimated cost in LLM span metadata.
  - Added the optional `protolink[metrics]` extra for sharper token estimates with `tiktoken`; core installs still use a dependency-free estimate.

## [v0.6.0] - 2026-06-19

### Added

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

- **Structured route decisions**
  - Added `RouteDecision` plus `Part.route(...)` and `Part.decision(...)` for serializable, trace-visible flow routing.
  - `Router` now prefers structured route parts and JSON-shaped route decisions before falling back to legacy `[ROUTE: key]` text tags.
  - Legacy text-tag routing now records the chosen route as structured task metadata and a route part for replayability.

- **First-class tool JSON Schema**
  - Native `Tool` wrappers now infer full JSON Schema objects for inputs and outputs instead of flat parameter maps or return type strings.
  - Added nested schema preservation for Pydantic models, dataclasses, typed dictionaries, enums, arrays, objects, unions, and literals.
  - Added runtime validation/coercion for tool arguments before execution, including custom `BaseTool` implementations with JSON Schema input contracts.
  - Tool examples now flow into advertised `AgentSkill.examples`.

- **Docs**
  - Added an end-to-end runtime cancellation guide covering active registration, cooperative checkpoints, control-plane transport behavior, final events, and best-effort side-effect guarantees.
  - Updated README task semantics to describe `Task.state` and `metadata["state_history"]`.
  - Added Agent documentation for default task lifecycle behavior and streaming status updates.
  - Expanded model and transport docs for task lifecycle states, terminal states, transition history, and new task helper methods.
  - Added CLI documentation and local trace telemetry documentation.
  - Expanded LLM documentation for the typed `infer()` cycle, JSON vs native action modes, native streaming tool-call behavior, and provider support matrix.
  - Updated flow docs for structured route decisions and updated tool/model docs for first-class JSON Schema, Pydantic support, runtime validation, and skill examples.

- **Tests**
  - Added cancellation coverage for typed request round-trips, pre-canceled inference, interrupted async tools, final stream status, custom remote handlers, and WebSocket control channels.
  - Added lifecycle coverage for direct task construction, invalid transitions, `Task.complete()`, successful agent execution, and failed tool execution.
  - Added regression coverage for delegated `ToolOutput` serialization in the LLM inference loop.
  - Added coverage for top-level exports, CLI scaffolding, local trace capture, redaction, and retry metadata.
  - Added regression coverage for native action dispatch, native streaming action dispatch, provider tool-call normalization, streamed tool-call delta accumulation, and Ollama's opt-in native tool mode.
  - Added coverage for route decision part round-trips, structured Router branching, nested/Pydantic tool schema inference, runtime argument coercion, custom `BaseTool` schema validation, and AgentSkill examples.

### Changed

- `protolink.models` now exports `TaskState`.
- Task validation now accepts empty message, artifact, and metadata containers and validates `Task.state` as a `TaskState`.
- Flow execution no longer auto-wraps plain user messages without executable parts into inferred prompts.
- Flow transition bridging now ignores structured `route` and `decision` control parts when preparing downstream agent prompts.
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

### Fixed

- Fixed delegated agent tool results crashing LLM history injection when the remote tool output is hydrated as a `ToolOutput` dataclass.
- Fixed task execution leaving tasks in non-terminal states after successful default agent execution.
- Fixed invalid direct lifecycle jumps such as `submitted -> completed` by requiring transition through `working`.

## [v0.5.8] - 2026-06-11

### Added

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

- **Tests**
  - Added focused coverage for lazy mock LLM creation, SSE JSON-RPC event parsing, `AgentClient` streaming checks, sync streaming iteration, and agent LLM stream attachment.

### Changed

- Provider, server LLM, and transport exports are now lazy-loaded so optional SDKs are only required when the selected provider or transport needs them.
- `create_llm()` lazy factory entries now cover all documented providers, including Grok, Hugging Face, LM Studio, OpenAI-compatible servers, and Mock LLMs.
- Agent `verbosity=0` now suppresses transport server access logs more aggressively.
- Documentation updated for streaming, SSE JSON-RPC, LM Studio, OpenAI-compatible local servers, and the new client/server transport flow.


## [v0.5.7] - 2026-06-07

### Added

- Authentication now works with all transports (http, websocket)
  - Integrated to Agent. Now passable to agent as an argument 
    - `authenticator`: Optional Authenticator instance for verifying incoming requests to this agent.
    - `credentials`: Optional credentials string used for authenticating outgoing requests.

- **Import** / **Export** Agent from/to `yaml`
  - Agent can now serialize itself and save to yaml file
    - `to_yaml`: Saves the agent configuration to a YAML file
  - Agent can now load from yaml file
    - `from_yaml`: Loads the agent configuration from a YAML file


## [v0.5.6] - 2026-05-17

### Added

- **Flows Refactor & Upgrade**
  - **Semantic Context Injection**: Flows dynamically build instruction prompts based on their downstream topology. This prompt is injected into the `task.flow_state["prompt"]` for executing agents to utilize seamlessly. This way agents are aware of their downstream context and can format their output accordingly.
  - Correct **Task** management. Added flow_state to Task, so that we provide additional context to the agents.
  - **NEW Flow Examples** for each Use case (Graph, Pipeline, Parallel, Router).
  - Removed **Structured Agent**
  - Better **State** Management
  - **Flow Sync** Module

- **Other**
  - **Agent Sync** Module
  - **LLM Sync** Module
  - **Added GuardRails**:
      - Added context for Agent ID and prevent agent from calling himself.
      - Removed self from fetched agents.
  - **Agent Discovery TTL**
  - **Mock LLM** for testing

### Fixed

- **HUGE BUG fix**: Agent URL received from registry was wrong most of the time.

## [v0.5.5] - 2026-05-16

### Changed

**NEW Feature - State (API Refactor)**
- **State Management**: Refactored agent state management, specifically around conversation history persistence. The syntax has been simplyfied:

```python
agent = Agent(
    card=card,
    ...
    state=["conversation"],  # Session memory is not reset between tasks
)
```

### Added

- **protolink.state** module. The State class manages:
  - **Session memory** - Session memory is not reset between tasks
  - **Conversation history** - Conversation history persistence
  - **Tool call history** - Tool call history persistence
  - **Flow state** - Flow state persistence

- **DSA Optimization**:
  - **Conversation History**: Use Message Double Ended Queue for O(1) append and pop operations.
  - **Registry Storage**: Optimize agent pop operations to O(1)
  - and more... 


## [v0.5.4] - 2026-05-12

### Changed

- **Agent Lifecycle**: Fixed issues with agent start/stop logic, specifically around event loop tasks and background threads. The syntax has been simplyfied:
- **Proper Thread Management**: Removed asyncio event loop and background threads for starting/stopping.

```python
agent.start()
agent.stop()
```

That's it. The `start()` method will start the agent in a background thread and will properly wait for all queues to empty. The `stop()` function will properly wait for all queues to empty, and gracefully shutdown the agent and background threads.

## [v0.5.3] - 2026-05-03

### Fixed

- **Tooling Schema**: Tool schema is now correctly inferred from the function signature and type hints. It is also correctly appended to the Agent Card prompt, so other agents are aware of available tools and schemas.

## [v0.5.2] - 2026-05-02

### Added

- **Logging Module**: Added explicit `file` logger (json) and `console` logger (color).
- Plug in Logging to the Agent using the `logger` argument. If none is provided, a default logger using the ConsoleLogger, so the IO is appended to the terminal.
- Added **context memory**:
  - "none" - No context memory.
  - "session" - Session based context memory. Agent remembers all messages exchanged during the current session with other agents.
Memory is configured in the agent using the `memory` argument. If none is provided, no memory is used.

## [v0.5.1] - 2026-04-28

### Added

- **Telemetry**: Add LangSmith and Langfuse telemetry implementations
- **BaseTelemetry**: Add base telemetry class
- **LangfuseTelemetry**: Langfuse telemetry implementation
- **LangsmithTelemetry**: Langsmith telemetry implementation
- **MultiTelemetry**: Multiplex multiple telemetry implementations.
- **Agent**: Plug in to the Agent using the `telemetry` argument. If none is provided, no telemetry is collected.

## [v0.5.0] - 2026-04-22

### Added

- **Flows**: Build deterministic execution paths out of the box (`Pipeline`, `Parallel`, `Router`, `Graph`).
- **StructuredAgent**: Wrap any complex flow to run autonomously as a generic, network-ready A2A agent.

## [v0.4.8] - 2026-04-19

Historical patch release.

## [v0.4.7] - 2026-02-08

### Added

- **LLM Inference Guardrails**:
  - Implemented robust guardrails for LLM inference.
  - Added agent calling for delegated inference.
  - Final result processing.
- NEW **GrokLLM**:
- Ticket Example
- Verbosity in Agent and Registry
and more...

## [v0.4.6] - 2026-02-05

### Added

- **LLM Automated Inference**:
  - Implemented robust tool calling capabilities.
  - Added agent calling for delegated inference.
  - Final result processing.
- **Agent Orchestration**:
  - Centralized handling for LLM inference, tool execution, and result aggregation.

### Changed

- **LLM API**: Refactored for better type safety and extensibility.
- **Agent Constructor**: Simplified initialization options.
- **Transport Factory**: Improved factory patterns for transport creation.

### Fixed

- **Agent Stability**: Resolved race conditions in agent message handling.
- **HTTP Backend**: Fixed issues with stream termination.

## [v0.4.5] - 2026-01-26

### Added

- **LLM Automated Inference**:
  - Implemented robust tool calling capabilities.
  - Added agent calling for delegated inference.
  - Final result processing.
- **Agent Orchestration**:
  - Centralized handling for LLM inference, tool execution, and result aggregation.

### Changed

- **LLM API**: Refactored for better type safety and extensibility.
- **Agent Constructor**: Simplified initialization options.
- **Transport Factory**: Improved factory patterns for transport creation.

### Fixed

- **Agent Stability**: Resolved race conditions in agent message handling.
- **HTTP Backend**: Fixed issues with stream termination.

## < [v0.4.4]

Changelog starts after this version.


# Roadmap

The near-term roadmap focuses on hardening the runtime paths that production agent systems depend on most.

## Upcoming Features

- [x] **Agent Task Handling**: Enforced task lifecycle transitions and state history.
- [x] **Delegated Inference**: Typed tool and agent actions in the LLM inference loop.
- [x] **Storage**: In-memory and SQLite storage implementations.
- [x] **Observability**: Local trace replay plus Langfuse and LangSmith integrations.
- [x] **Integrations**: MCP adapter for external tool servers.
- [ ] **Transport Layer**: Add a production-ready **gRPC** transport implementation and factory registration.
- [ ] **State Modules**: Expand tool, task, and flow state modules beyond their current storage-backed extension points.
- [ ] **OpenTelemetry**: Add first-class OpenTelemetry export alongside the existing telemetry integrations.
