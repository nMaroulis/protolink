import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Changelog

:::info[About this Changelog]

All notable changes to the **Protolink** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

:::

:::tip[Update Protolink]

Upgrade to the latest published release before following the notes below.
<Tabs groupId="package-manager">
<TabItem value="pip" label="pip" default>
```bash title="Terminal"
pip install --upgrade protolink
```
</TabItem>
<TabItem value="uv" label="uv">
```bash title="Terminal"
uv add --upgrade protolink
```

</TabItem>
</Tabs>

:::
---

# Release Notes

## [0.6.8] - Unreleased

### Added

- Added the infer-loop benchmark for correctness, reliability, timing, baseline comparisons, and CSV/JSON results.

## [0.6.7] - 2026-07-28

:::note Latest release

This patch release hardens the controlled inference path from task admission through provider calls, tool execution,
delegation, streaming finalization, and observability. It keeps the portable JSON action protocol as the default for
local and smaller models while making malformed-output recovery, prompt metadata, budgets, retries, and task lifecycle
behavior more deterministic. Adds vLLM client support natively. Fixes Local Telemetry. Also adds the AI Courtroom Example.

:::

### Added

- Added `AgentClient.send_infer_task()` and its `client.sync` counterpart. The helper requires a query and agent URL,
  creates the request with `Task.create_infer()`, supports optional user context, output schema, inference metadata, and
  native/A2A protocol selection, then returns the complete task from `send_task()`.
- Added task-scoped budget accounting across every executable part in one task. Multiple `infer` parts, explicit
  `tool_call` parts, and physical provider retry attempts now consume one cumulative `BudgetEnforcer`; inline nested
  tasks receive an isolated budget scope.
- Added `BudgetEnforcer.check_next_step()` and the optional advanced-runtime
  `LLM.infer(..., budget_enforcer=...)` integration point for callers that need to share accounting across several
  inference invocations.
- Added structured physical-attempt metadata to LLM lifecycle events. Transient retries report the failed and next
  attempt, delay, exception type, and message; completed calls report total attempts and current budget usage.
- Added durable `Artifact(kind="action_result")` receipts for model-selected tools and delegated-agent calls. Receipts
  carry the runtime `action_id`, inference source/kind/step metadata, and completion status without copying internal
  tool or delegation results into client-visible task data. A later model failure, cancellation, or budget boundary no
  longer hides a side effect that already completed, while private conversation history retains the full observation.
- Added focused regression coverage for pre-cancellation, external coroutine cancellation, abandoned streams,
  task-wide budgets, legacy override signatures, telemetry failures, provider retries, invalid tool arguments,
  deterministic prompts, strict JSON extraction, Anthropic action handling, and parallel native tool calls.
- Added vLLM client `VLLMLLM`, which inherits `OpenAICompatibleLLM`.
- Added validated `create_llm(..., max_parse_failures=N)` runtime configuration. The limit is kept separate from
  provider model parameters, so ProtoLink retry controls are never forwarded to Ollama, OpenAI, or compatible servers
  as generation options.

### Changed

- Provider retries now count each actual request against LLM-call and input-token budgets. Provider runtime is checked
  again after every request, including a final model call. Completed tool and delegated-agent side effects are recorded
  before cancellation or runtime limits stop the next step, rather than being retroactively reported as if they never
  ran. A streaming provider call may retry only before any output chunk has been exposed to a consumer.
- Transient-error classification now recognizes common direct and response-wrapped provider status fields, numeric
  string statuses, provider exception names, HTTP 429/529/5xx messages, timeouts, overloads, and connection failures.
- Model-proposed tool arguments are validated and conservatively coerced before authorization, budget consumption, or
  execution. Invalid arguments remain recoverable model feedback; a `TypeError` raised inside tool business logic is
  treated as an execution failure rather than an argument mistake.
- Duplicate-action protection now records only successful tool and Agent side effects, hashes bounded canonical
  signatures, includes the complete delegated prompt, and never suppresses a repeated final answer.
- Portable JSON prompts now use valid single-brace examples, deterministic JSON tool/Agent metadata, explicit
  capabilities, and clear instructions that metadata is untrusted data. Parse-repair examples advertise only actions
  available in the current run, keeping correction prompts concise for smaller models.
- Embedded JSON recovery now performs a linear, quote- and escape-aware scan and accepts exactly one valid top-level
  object. Ambiguous multiple objects are rejected; raw-response and parsed-payload diagnostics use deterministic,
  bounded head-and-tail previews while preserving field-level validation errors.
- Prompt-fallback parsing now conservatively normalizes common small-model response drift: structured
  `FinalAction.content` values are serialized losslessly, and a direct application object can become final content only
  when it contains no ProtoLink action-envelope fields. Full JSON fences, complete leading reasoning wrappers, and
  trailing commas receive syntax-only recovery; ambiguous objects, incomplete reasoning wrappers, and action-shaped
  payloads with missing or unknown types still fail validation.
- Action-parse retries now preserve the decoded outer action type as structured error context and return
  capability-aware correction feedback. Malformed or unavailable tool and Agent calls are explained explicitly, while
  retry examples include only actions that the current inference can dispatch.
- Agent discovery is now a best-effort delegation affordance: a Registry outage no longer prevents otherwise-local
  inference. Discovered ancestors are removed from the prompt, model-originated direct URL delegation is rejected, and
  delegation cycles are stopped before dispatch.
- Agent and direct-inference telemetry observers are non-authoritative. Hook/export failures are logged and isolated so
  they cannot change a successful model or tool result; streaming tasks now receive the same task start/end telemetry
  boundary as unary tasks.
- Anthropic action parsing and the shared streamed Chat Completions normalizer reject ambiguous parallel tool calls
  instead of merging fragments. The synthetic delegation tool names `protolink_call_agent` and
  `protolink_call_agent_tool` are reserved and cannot be shadowed by a local tool.

### Fixed

- Fixed pre-canceled `RunContext` values so task, LLM, tool, and streaming paths stop before mutating history or
  starting work.
- Fixed failed unary tasks so their failed snapshots are persisted before the original exception is re-raised.
- Fixed multi-part tasks so each completed output is attached and snapshotted immediately. A later part failure keeps
  the earlier output visible instead of losing all partial progress.
- Fixed cancellation during post-tool telemetry so an already-returned explicit tool result is attached exactly once,
  persisted, and correlated through `completed_after_cancellation` metadata before cancellation completes.
- Fixed external `asyncio` cancellation so task state and snapshots are updated while the cancellation still
  propagates to the caller; protocol-requested cancellation continues to return the canceled task/event contract.
- Fixed early streaming-consumer closure so an unfinished task is marked canceled and persisted instead of remaining
  orphaned in `working` state.
- Fixed Anthropic requests so system instructions come from the task-local `ConversationHistory`, multiple system
  entries are preserved, streamed `partial_json` arguments take precedence over an initial empty input object, and
  parallel `tool_use` blocks fail explicitly.
- Fixed prompt serialization for quotes, newlines, booleans, nested schemas, unordered tools/skills, and legacy Python
  type metadata.
- Fixed failed conversation turns so they remain isolated by default, while a failed turn with a completed
  `action_result` receipt retains the matching observation for safe resume and retry behavior.
- Fixed non-JSON/circular action results so history receives a bounded serialization fallback rather than losing the
  observation after an external side effect has completed.
- Fixed streamed tool/delegation result events so client-visible metadata keeps correlation but omits private internal
  result data. A failing external event observer is disabled without disabling runtime-owned action receipts.
- Fixed internal receipt callbacks so they do not implicitly activate optional call-metrics/token-estimation work on
  otherwise unobserved Agent inference.
- Fixed delegated task handling so only a remote `completed` task with a real output produces a successful
  `agent_call_result`; failed, canceled, input-required, non-terminal, and empty completions are propagated explicitly.
  Full-task and response-only transports are both accepted by distinguishing returned output from the outbound request
  by stable item ID.
- Fixed partial-history persistence failures so they are logged without replacing an active budget, cancellation, or
  execution exception after a completed side effect.
- Fixed repeated small-model/Ollama parse failures when an otherwise-valid final action placed the requested
  application object directly in `content` instead of encoding it as a string.
- Fixed Registry discovery for both serialized and in-process `AgentCard` responses.
- Fixed nested local telemetry so parent and child task traces are both preserved.

### Compatibility Notes

- No provider or model integration was removed. JSON action mode remains the default compatibility path for Ollama,
  llama.cpp, LM Studio, and generic OpenAI-compatible backends, and correction prompts are smaller when tools or
  delegation are unavailable.
- The new budget parameters are optional. Agent preserves custom pre-0.6.7 `call_llm()`, `call_llm_stream()`,
  `execute_tool()`, and `LLM.infer()` override signatures; the shared enforcer is passed to an `infer()` override only
  when that callable declares the keyword or accepts `**kwargs`.
- Budget limits now apply cumulatively to a complete task and to physical retry attempts. A multi-part or retrying task
  that previously reset counters between calls can therefore stop earlier when it reaches its configured limit.
- Model-produced Agent targets must be Registry-advertised names, not URLs. Anthropic and streamed Chat Completions
  paths reject multiple tool actions in one inference step, and portable responses containing multiple valid JSON
  objects are now rejected as ambiguous.
- Cancellation remains best effort for synchronous provider/tool code and already-issued external side effects. The
  runtime cannot forcibly interrupt synchronous work running on the event-loop thread. If a tool or delegation has
  already returned, ProtoLink preserves its result and stops subsequent work at the next execution boundary.

## [0.6.6] - 2026-07-17

:::note Release summary

This release adds normalized run-report regression diffing, a small opt-in built-in tool set, and an explicit
description of ProtoLink's A2A architecture without replacing its small Python runtime API.
`AgentCard`, `Task`, `Message`, `Part`, and `Artifact` remain ProtoLink's ergonomic runtime primitives.
An HTTP agent can now opt into a separate, versioned A2A 1.0 inbound and outbound translation boundary with
`Agent(..., a2a=True)`. The default `False` preserves existing ProtoLink clients, native endpoints, transports
and `handle_task(Task)` implementations.

:::

### Added

- **Normalized run-report regression diffing**
  - Added `RunReportDiff`, `RunReportDifference`, `RunReportDiffConfig`, `RunReportTolerance`, `ALL_RUN_REPORT_SECTIONS`, `normalize_run_report()`, `diff_run_reports()`, and `assert_run_matches()` for comparing baseline and candidate reports. Regression suites normally record final reports, but the helpers do not require a particular task lifecycle state.
  - Comparisons normalize known ProtoLink runtime-envelope identifiers, timestamps, and sequence counters while preserving repeated identifier relationships, report structured path-level changes, and support configurable ignored paths and numeric tolerances without mutating the source reports. Application-owned payloads and report metadata remain exact by default.
  - Added `protolink run diff BASELINE CANDIDATE --store runs.db [--json]` for offline comparison of two stored reports. The command exits `0` for a match, `1` for behavioral changes, and `2` when either report is missing.
  - Text and JSON CLI diff output apply the default redaction policy to compared values. The core `RunReportDiff.to_dict()` API remains raw unless the caller supplies a redaction policy.
  - Added the provider-free `examples/run_regression_diff.py` walkthrough for pinning a baseline, detecting a changed result, and using the assertion helper in tests.
- **Opt-in dependency-free built-in tools**
  - Added `web_search()`, `fetch_url()`, `calculator()`, and `current_datetime()` factories, exported from `protolink.tools` and registered explicitly with `agent.add_tool(factory())`.
  - `web_search` selects `engine="brave"` by default, documented keyless English Wikipedia search with `engine="wikipedia"`, or keyless best-effort DuckDuckGo HTML search with `engine="duckduckgo"`. All three use the same bounded normalized result contract with no silent provider fallback. Brave reads `BRAVE_SEARCH_API_KEY` only at invocation; DuckDuckGo challenge and markup-drift responses fail explicitly, while recognized sponsored entries are retained and labeled.
  - Added `examples/builtin_web_search.py`, an offline-safe CLI walkthrough that registers the tool through an Agent policy, defaults to the reliable keyless Wikipedia engine, and exposes engine, freshness, and result-count controls.
  - The web tools declare `network.read`; URL fetch rejects non-public targets and bounds redirects, response types, and content size. Search and fetched content remain untrusted external data, and applications can restrict the allow-by-default policy with `CapabilityPolicy`.
  - Agent dict/YAML round-trips preserve built-in tool identities and first-party `CapabilityPolicy` rules without serializing executable custom policies, approval callbacks, or the Brave API key.
- **Opt-in A2A 1.0 HTTP interoperability**
  - `Agent(..., transport="http", a2a=True)` now exposes `GET /.well-known/agent-card.json` and `POST /` while retaining every native endpoint. The flag defaults to `False`, is available through the read-only `agent.a2a` property, and round-trips through dict/YAML configuration.
  - The adapter implements `SendMessage`, `GetTask`, `ListTasks`, and `CancelTask`, with standard card, task, message, part, artifact, security, timestamp, version, content-type, and error translation for its advertised scope.
  - Blocking and non-blocking execution, filtering, pagination, cancellation, and authenticated principal/tenant task isolation reuse the existing `handle_task(Task)` execution path.
  - The process-local task index retains at most 1,024 tasks for one hour, prunes expired or oldest inactive work first, and never evicts an active operation to admit a new task.
- **Outbound A2A 1.0 translation**
  - `AgentClient(..., a2a=True)`, `Agent.call_agent()`, and their synchronous facades can discover and call A2A 1.0 JSON-RPC peers without an `a2a-sdk` runtime dependency.
  - `protocol="auto"` prefers the native ProtoLink contract and selects A2A for an A2A-only peer. `protocol="protolink"` goes directly to the native route; `protocol="a2a"` skips the native-vs-A2A choice but still discovers and validates the standard Agent Card and compatible JSON-RPC interface.
  - Advertised A2A interfaces must share the discovered Agent Card's origin by default. The compact `Agent` facade always keeps that secure policy; `a2a_allow_cross_origin=True` remains an explicit `AgentClient` trust override for controlled split-origin deployments.
  - Outbound calls reuse the configured HTTP transport's authentication, TLS, limits, pooling, metrics, and request headers. `SendMessage` is non-idempotent and is not retried automatically.
  - ProtoLink preserves the caller's local task ID while retaining the remote A2A task ID, context, state, timestamp, and agent URL for continuation and cancellation. The protocol-selection cache is bounded to 1,024 peers for five minutes, and local-to-remote task-ID mappings are bounded to 1,024 entries for one hour.
  - Cancellation reason and metadata translate through A2A `CancelTask`. A blocking outbound call cannot be canceled until its response reveals the server-assigned task ID; `"auto"` never guesses by sending a local ID to the native cancellation route.
  - `send_message()` raises for an artifact-only A2A result so callers use `send_task()` and retain the full task artifacts.
- **Execution-aware message translation**
  - Inbound A2A user text remains a ProtoLink `Part(type="text")` for custom handlers. The default Agent engine recognizes `task.metadata["a2a_inbound"]` and treats that text as an inference request when an LLM is configured. Outbound ProtoLink `infer` prompts become standard A2A text.
  - Standard text, data, raw/file, URI, message, artifact, and task-state forms translate directly. ProtoLink-specific tool-call, flow, runtime-context, and control-plane semantics remain native-only contracts.
- **A2A verification harness**
  - Added a provider-free test agent, focused adapter tests, and a manually dispatched workflow pinned to the official A2A TCK commit documented in [A2A Core and 1.0 Compatibility](a2a.md).
  - The current unmodified JSON-RPC MUST run reports `67 passed, 1 failed, 167 skipped, 30 deselected`. The remaining failure is the documented upstream `CORE-SEND-003` metadata defect, so this release does not claim a complete TCK pass.

### Changed

- Reworked the README around ProtoLink's lightweight, A2A-first, pluggable-agent design, with a provider-free one-agent quickstart, progressive configuration, local and small-model support, structured flows, and the CLI dashboard.
- Updated the concept, agent, client, server, transport, getting-started, index, and example documentation to distinguish ProtoLink's A2A-based runtime model from A2A 1.0 wire compatibility at the HTTP adapter boundary.
- Clarified that native `AgentCard` serialization, registry services, structured flows, non-HTTP transports, and control-plane endpoints remain ProtoLink runtime contracts rather than additional A2A 1.0 operations.

### Compatibility Notes

- This release is additive for existing ProtoLink applications: it does not remove or rename the `Agent`, `Task`, `AgentClient`, transport, or native endpoint APIs.
- `a2a=False` keeps HTTP native-only. `a2a=True` requires the exact HTTP transport and adds standard inbound routes plus outbound translation; native endpoints and native protocol selection remain available.
- Agent-originated A2A calls always enforce same-origin discovery. A card advertising a JSON-RPC interface on another scheme, host, or effective port is rejected before that interface receives a request. For an explicitly trusted split-origin deployment, construct a dedicated `AgentClient(..., a2a_allow_cross_origin=True)`.
- In `"auto"` mode, the client probes ProtoLink's native card first and falls back to the standard A2A card only after `404` or `405`. It does not resubmit a task through another protocol after authentication, connection, timeout, or server errors.
- The A2A task index is bounded but remains process-local and in-memory. It contains only tasks submitted through the inbound adapter and disappears on restart; multi-worker or restart-durable deployments still need a shared task router or store.
- Outbound protocol decisions and task-ID mappings are also bounded, process-local caches. Losing or expiring a mapping prevents continuation or cancellation by the original local task ID.
- Optional A2A message metadata, extensions, and reference task IDs are validated at the boundary but are not all retained by ProtoLink's smaller runtime models.
- The standard Agent Card route is intentionally public; the JSON-RPC task endpoint uses the Agent's configured authenticator.

### Roadmap

- A2A `SendStreamingMessage` and `SubscribeToTask` support.
- A2A task push-notification configuration and delivery.
- Extended authenticated A2A Agent Cards.

## [0.6.5] - 2026-07-14

### Added

- **Native gRPC transport**
  - Added `GRPCTransport` and the `"grpc"` factory alias for unary task requests, server-streaming task events, metadata-based credentials, deadlines, and pooled async channels.
  - Added standard `grpc.health.v1.Health` reporting and server reflection, with constructor switches for deployments that disable either service.
  - Added gRPC transport conformance and integration coverage plus the provider-free `examples/grpc_agent.py` example.
- **TLS and mutual TLS**
  - Added the top-level `TLSConfig` API for shared certificate trust, server identity, and optional client-certificate verification across HTTP, SSE JSON-RPC, WebSocket, and gRPC.
  - Added secure `https://`, `wss://`, and `grpcs://` URL handling, with TLS owned consistently by concrete transport instances.
  - Added certificate-backed integration coverage and `examples/tls_agent.py`, while keeping transport encryption independent from application authentication and authorization.
- **Shared production transport contract**
  - Added `TransportConfig`, `TransportLimits`, and `RetryPolicy` for consistent payload bounds, request/stream concurrency, explicit idempotent retries, keepalive, graceful shutdown, response deduplication, and dependency-free metrics across every built-in transport.
  - Added `TransportCapabilities`, `TransportMetricsSnapshot`, and the public `TransportRequestContext` extension type for capability inspection, operational counters, correlation IDs, idempotency keys, and retry-attempt tracking.
  - Added typed connection, timeout, protocol, remote, and payload-limit errors carrying URL, request ID, retryability, and protocol-native status metadata.
  - Added `/healthz` and `/readyz` Agent and Registry probes, configurable WebSocket ping/pong behavior, loop-owned pooled-resource cleanup, and idempotent transport lifecycle methods.
- **Multi-transport Agent metadata**
  - Added optional `AgentCard.interfaces` / `AgentInterface` metadata so one Agent can advertise additional protocol endpoints while retaining its primary URL and transport.
  - Serialized this metadata as `additionalInterfaces` for wire compatibility and preserved it through AgentCard round trips.
- Added `examples/transport_production.py` with provider-free configuration, capability, health, and metric inspection.

### Changed

- Unified transport construction across `Agent`, `AgentClient`, and `Registry`: string aliases remain the zero-configuration prototyping path, while TLS, limits, retries, keepalive, and protocol-specific settings are configured on a concrete transport object passed to the facade.
- Agent serialization now restores its primary and Registry transports with independent TLS identities and production configurations.
- `ClientRequestSpec` now declares operation idempotency explicitly. Retries remain disabled by default and run only when the request specification, method, and typed failure all permit a safe retry.
- HTTP, SSE JSON-RPC, WebSocket, gRPC, and RuntimeTransport now enforce the same serialized payload and concurrency contract, so in-process tests exercise the same resource boundaries as network deployments.
- Correlation IDs remain stable across retry attempts, while idempotency keys suppress concurrent duplicate execution and replay completed responses within the configured process-local cache window.
- Expanded the Transport, Agent, Client, Registry, and AgentCard documentation with complete signatures, defaults, protocol mappings, operational rationale, custom-transport guidance, and production examples. The documentation landing-page IDE now includes gRPC and production transport configuration with incremental line editing.

### Removed

- Removed facade-level `tls=` and `transport_config=` constructor arguments from `Agent`, `AgentClient`, and `Registry`. Advanced settings now have one owner and one API: the concrete transport instance.

### Fixed

- Fixed SSE task streams so final nested LLM events no longer close the stream before the final task-status update.
- Fixed concurrent duplicate idempotent requests so they await one in-flight operation instead of executing the same handler more than once.
- Fixed HTTP health probes so `/healthz` and `/readyz` remain available when application authentication is enabled.
- Fixed transport shutdown across background-thread and caller event loops by closing pooled clients and channels on the event loop that owns them.
- Fixed gRPC shutdown so loop-local cached channels are closed and removed correctly, including repeated `start()` and `stop()` calls.
- Fixed HTTP and SSE server-side request/stream accounting so shared concurrency limits and transport metrics apply on both sides of a connection.
- Fixed SSE terminal-frame parsing so the final task event is emitted exactly once.
- Fixed failed or cancelled WebSocket and gRPC idempotent operations so they release waiting duplicates without poisoning the completed-response cache.
- Fixed WebSocket pooling after timeouts, protocol corruption, and abandoned streams so unread frames cannot leak into a later request.
- Fixed Agent configuration round trips so restored Registry transports retain the Agent's serialized authentication strategy and credentials.
- Fixed short-lived SQLite storage, run-store, and doctor connections so every database handle closes deterministically after use.
- Fixed source-distribution contents so generated Docusaurus output and `docs/node_modules` are excluded from PyPI packages.

## [0.6.4] - 2026-07-03

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

### Changed

- Tightened GitHub Actions so Ruff, blocking `ty check protolink`, multi-version tests, package build checks, and strict docs builds run as first-class CI gates.
- Migrated the documentation site from MkDocs Material to Docusaurus with a custom ProtoLink theme, preserved docs corpus, Mermaid diagrams, admonitions, tabs, and GitHub Pages artifact deployment.
- Split LLM response parsing and fallback action repair into `protolink.llms.parsing`, keeping the public `LLM` facade stable while making the infer loop easier to maintain.

### Fixed

- Fixed `Agent.start(register=False)` so the lifecycle now honors the public `register` argument.
- Fixed RuntimeTransport async request-parser handling.
- Fixed WebSocket route registration, stale client-connection reuse, and task-stream closure semantics.
- Hardened `BearerTokenAuth` so bearer JWTs now verify HMAC signatures, algorithms, registered time claims, and optional issuer/audience constraints instead of accepting unsigned demo payloads.

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
- [x] **Transport Layer**: Add a production-ready **gRPC** transport implementation and factory registration.
- [ ] **State Modules**: Expand tool, task, and flow state modules beyond their current storage-backed extension points.
- [ ] **OpenTelemetry**: Add first-class OpenTelemetry export alongside the existing telemetry integrations.
