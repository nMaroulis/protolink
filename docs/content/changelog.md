import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Changelog

:::info[About this Changelog]

All notable changes to the **Protolink** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

:::

:::tip[Update Protolink]

Upgrade to the latest published release. Entries marked **Unreleased** describe the next version and are not yet available from PyPI.
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

## [0.7.4] - Unreleased

MCP tools now preserve complete results and their original JSON schemas, report
tool failures correctly, and support Streamable HTTP with optional connection reuse.
Agent setup now supports names, model strings, and initial tools, with explicit
network endpoints and smaller provider-specific installations. This shows a focus on progressive control and simple and intuitive API.

### Added

- `Agent(name=..., description=..., url=..., llm="provider:model", tools=[...])`
  as an alternative to explicit card construction. Local agents default to a
  `runtime://` identity without creating a transport. Network aliases require a
  compatible URL and bind port; configured transports supply their own URL and
  support a separate advertised address. Invalid shorthand endpoints fail before
  provider initialization, including missing TLS server identity for secure binds.
- Provider aliases and model strings on the `llm` property and `create_llm`.
  Parsing preserves model-name case, paths, and additional colons such as Ollama
  tags. Configured LLM instances and existing factory calls remain supported.
- Provider-specific installation extras: `openai`, `anthropic`, `gemini`,
  `huggingface`, `deepseek`, `grok`, `ollama`, `openai-compatible`, `lmstudio`,
  `vllm`, `llama-cpp-server`, and `llama-cpp-local`. The `llms` bundle remains
  available; hosted-provider extras do not pull in local llama.cpp bindings.
- `streamable_http` transport for `MCPToolAdapter` and async/sync `Agent.add_mcp`,
  including configured HTTP headers. Existing URL-only registration retains legacy SSE.
- `async with adapter.session()` to share one initialized connection across discovery
  and registered tool calls, with cleanup on completion, failure, or cancellation.
- Paginated MCP tool discovery, with repeated-cursor detection and complete-list caching.
- MCP regression coverage in CI, including real Streamable HTTP and stdio server tests.

### Fixed

- MCP responses with `isError=True` raise `MCPToolError` instead of returning successful
  text. The exception retains the tool name and complete result; task execution records
  a failed tool output without automatically retrying the call.
- Rich MCP results retain all content blocks, structured data, annotations, metadata,
  and null values. A single plain text block still returns a string; rich responses
  return a dictionary with MCP fields such as `content` and `structuredContent`.
- Nullable and union schemas no longer crash discovery. MCP input and output schemas
  retain recursive references and JSON Schema defaults, with argument validation that
  does not coerce values or change `additionalProperties`.
- Blocking MCP callables reject active event loops before creating a coroutine, and
  individual errors retain their exception type through MCP session cleanup.

### Changed

- Treat an omitted transport or registry as normal local configuration, logging
  at debug level. Constructor tools reuse `add_tools`; execution continues through
  the existing `invoke`, `.sync`, and task APIs.
- Update setup guides and provider dependency errors for the new shorthand and extras.
- Document MCP result handling, schema validation, Streamable HTTP, and session lifetime.
- Declare the adapter's HTTP and JSON Schema dependencies explicitly in the `mcp` extra.

## [0.7.3] - 2026-09-22

:::note Latest Release

This release adds simpler APIs for creating and reading tasks, registering tools, discovering MCP tools, calling peers, streaming runs, and composing workflows. Optional budgets, run context, typed responses, and bounded acceptance checks bring more control to those same APIs. Updated documentation and a runnable example show how to start with defaults and introduce explicit configuration as your application grows.

:::

### Added

- Task factories accept plain text (`Task.create`), positional inference prompts and
  tool arguments, and copied `session_id`/`budget`/`context` controls. `get_last_part`
  exposes typed parts; `get_output` unwraps successful tool results and reads the
  latest answer without falling back to old answers after new input or previews.
- Per-run `budget` and `context` options on `Agent.invoke` and `ask`, with sync parity,
  explicit session precedence, and copied caller-owned controls.
- `Agent.start_run(prompt_or_task)` and `RunHandle.chunks()` for one managed local run,
  raw model fragments, typed events, cancellation, final results, and reports.
- `Agent.add_tools` for native tool collections and async/sync `add_mcp` for stdio or
  SSE discovery, tool selection, local prefixes, and collision checks. MCP adapters
  now offer `list_tools_async` and `get_tools_async` for active event loops.
- `Agent.peer` and `AgentClient.peer` with inference, typed inference, native tool calls,
  full task execution, and blocking equivalents. Registry names require a unique match.
- `Flow.invoke`/`sync.invoke`, `Step`, `ToolStep`, and `RepeatUntil` for short local
  workflows and bounded acceptance over fresh execution evidence.
- `Agent.invoke_typed` and peer equivalents validate JSON answers with Pydantic.
  Repair requires an explicit attempt count, shares local workflow budgets, and never
  retries execution failures or incomplete tasks. `StructuredResponseError` retains evidence.
- One provider-free `progressive_control.py` example, an optional real MCP walkthrough,
  a progressive-control guide, and regression coverage for budgets, cancellation,
  peers, MCP registration, structured output, and bounded workflows.

### Changed

- Expand the progressive-control guide with default and explicit configurations for
  cards, transports, clients, registries, models, tools, state, knowledge, and logging;
  extend the runnable example with task creation/readers and a configured transport.
- Simplify basic tool calls, local pipeline setup, runtime mesh lifecycle, state calls,
  report capture, and the verified-workflow example using public convenience methods.
- Align package and documentation metadata for v0.7.3. Existing explicit Task, transport,
  registry, recorder, and Graph interfaces remain available.

## [0.7.2] - 2026-09-21

:::note Release Summary

**ProtoLink 0.7.2 focuses on introducing built-in tools and simple assistant presets for everyday agent work.** Agents can run shell commands, work with Git repositories, ask the user for feedback, and manage calendars and email through small, configurable APIs. These additions use the existing Agent runtime, including capability policies, approval previews, execution budgets, cancellation, and events.

The new shell and Git tools support practical coding workflows, from inspecting a repository and running checks to staging and committing changes. The user interaction tool lets a model ask a question, await an application-provided response, and continue its task with that feedback. Applications supply the working directory, environment, and interaction handler, keeping setup explicit and tool calls straightforward.

General-purpose tool factories add scoped filesystem reads and recoverable edits, JSON storage, configured HTTP requests, document extraction, and read-only database queries. Developers can register these capabilities on any Agent and supply their own policies, storage, API credentials, and database backends. Optional format libraries support PDF, Word, and spreadsheet extraction while the base package remains lightweight.

Calendar and email tools bring the same execution model to personal assistant workflows. Google Calendar, Gmail, Outlook Calendar, Outlook Email, and standard IMAP/SMTP backends support calendar listing and event creation, mailbox search and reading, draft creation, and email submission. Backends share simple interfaces, provide search guidance to the model, and leave credentials and authentication with the application. Writes require explicit tool opt-ins, and uncertain submissions are never automatically retried.

`Assistant` and `CodeAssistant` combine these tools into small, ordinary `Agent` subclasses. Applications choose their models, accounts, callbacks, and policies while retaining the familiar invocation, streaming, state, and transport APIs. The presets require approval for mutation capabilities by default. Updated documentation and runnable offline examples demonstrate every new tool family and all five service backends, with regression tests covering their execution and failure behavior.

:::

### Added

- General-purpose `storage_tools()`, `http_tool()`, `document_tools()`, and `database_tools()` factories,
  composing with any Agent through native validation, capabilities, previews, and execution events.
  Storage reuses a dedicated existing `Storage` namespace; HTTP fixes the API origin/path and selects
  read/write capabilities per request; database access has an async backend contract and bounded,
  cancellable read-only `SQLiteDatabase` implementation.
- Filesystem `read_file`, `list_files`, `search_files`, and exact `edit_file` operations. Omitting
  `checkpoints` now exposes only reads; supplying it retains existing writes/recovery and adds targeted
  edits with preimage checks. Reads enforce existing roots, reject symlinks, and bound output/traversal.
- Optional `documents` extra for PDF/DOCX/XLSX extraction; text and CSV/TSV need no extra dependency.
  Located text/table results and literal search report truncation. Added one offline `generic_tools.py`
  example covering all five tool families and regression tests with real document formats and SQLite.
- `shell_tool()` exposes `run_shell(command)` with an application-configured working directory, copied environment,
  executable, time/output limits, and optional execution backend. It uses native previews, process events, budgets,
  and cancellation. Each call starts a fresh noninteractive shell.
- `git_tool()` provides structured status, diff, log, show, add, and commit operations. Reading is enabled by default;
  staging/committing require an explicit factory opt-in and a separate `git.write` capability. Literal paths and
  option validation prevent model arguments from becoming arbitrary Git flags. Hooks, fsmonitor, signing,
  external diff, and textconv are disabled; staging filters and host execution remain application trust decisions.
- `ask_user_tool(handler)` lets a model ask for clarification and await the application's async UI callback before
  continuing. Typed requests/results include unique correlation IDs, suggested choices, and free-text answers;
  declines and timeouts never invent an answer. Events, cancellation, and runtime budgets cover the live wait.
- `calendar_tools()` and `email_tools()` expose small async backend contracts with first-party `GoogleCalendar`
  and `Gmail` adapters. Calendar listing/personal event creation and mailbox search/read/draft/send use native
  policy, previews, pagination, explicit write opt-ins, bounded HTTP responses, and no automatic retries.
  OAuth credentials and token refresh remain application-owned. Optional `integrations` extra installs HTTPX.
- `OutlookCalendar` and `OutlookEmail` use Microsoft Graph with selected-user/calendar support, refreshed tokens,
  recurring calendar views, bounded plain-text mail reads, drafts, and sending. Continuations stay on the selected
  collection; send results report acceptance without inventing a message ID or claiming delivery.
- `IMAPEmail` adds dependency-free IMAP/SMTP with verified TLS, app-password callbacks, account/folder-scoped
  UID pagination, read-only `BODY.PEEK` reads, bounded MIME, explicit draft folders, and optional SMTP submission.
  Worker cancellation interrupts sockets; send results distinguish accepted and refused recipients without retries.
  All five backends fit the same tools and `Assistant` API, with provider-specific search guidance in tool descriptions.
- `examples/service_backends.py` exercises all five service backends through `Assistant` with offline transport
  fixtures. Regression tests cover pagination isolation, MIME limits, TLS ordering, partial rejection, and cancellation.
- `Assistant` and `CodeAssistant` are small `Agent` subclasses that compose these tools and default policies.
  Models, accounts, callbacks, and standard Agent settings remain caller-supplied; mutation capabilities require
  approval by default. Public imports are available from `protolink` and `protolink.agents.builtins`.
- One provider-free `examples/builtin_assistants.py` walkthrough verifies every new tool family and both presets
  using a temporary Git repository, mock model, and in-memory calendar/mailbox. Added host, integration-contract,
  inference-continuation, policy, validation, and lifecycle regression tests and a complete API guide.

### Changed

- Consolidate all built-in tool references in [Built-in Tools](builtin-tools.md) and agent presets in [Built-in Agents](builtin-agents.md),
  with direct links from the Tool/Agent APIs and sidebar. The agents catalog includes a note about future additions.

- Share process preparation/execution between argv, shell, and Git tools while preserving `process_tool()`'s API.
  Reject noninteger output limits and defensively copy explicit environments.
- Export configured tool factories and integration contracts through `protolink.tools` as well as
  `protolink.tools.builtins`. Configured backends/callbacks must be explicitly reattached after Agent restoration.
- Align package, lockfile, and documentation metadata for the next 0.7.2 release.

## [0.7.1] - 2026-09-15

:::note Release Summary

**ProtoLink 0.7.1 makes live execution easier to follow and its results easier to inspect**, improving model streaming while bringing delegated evidence, persistence redaction, and checkpoint inventory into the library. Applications can show progress as generation happens, evaluate work performed by delegated agents from the parent's report, configure secret masking at the storage boundary, and inspect recovery records through a public API. These changes build on the execution and recovery facilities introduced in 0.7.0 and reduce the application code needed to connect them to a frontend or operator workflow.

Model output now reaches stream consumers while generation is still running. Ollama and the OpenAI-compatible server clients use asynchronous HTTP reads, so a pending response does not prevent the event loop from delivering chunks or handling cancellation. This covers llama.cpp server, vLLM, LM Studio, and generic compatible endpoints. OpenAI, Anthropic, Gemini, DeepSeek, Hugging Face, and local llama.cpp move synchronous iterator creation and reads onto a worker, while application callbacks remain on the application's event loop. Both JSON-action and native-tool streaming retain their existing behavior: `llm_chunk` carries incremental text, `llm_final` carries the complete answer, and the terminal task status establishes the run's final state.

Streaming also handles interruptions and protocol boundaries more consistently. HTTP readers recognize completion markers, assemble fragmented UTF-8 and lines, and surface malformed responses and provider errors. Responses, clients, and nested generators close on completion or interruption; synchronous SDK iterators close on their worker after any in-progress operation returns. Native tool calls are still assembled before execution, and Ollama chat requests retain configured headers and authentication. Regression tests verify that consumers receive early output before generation finishes, alongside cancellation, failure, and cleanup behavior. The `llms` extra now explicitly includes `httpx`, while the base package continues to require only Pydantic.

Delegation now contributes worker events and execution receipts directly to the parent's stream, task snapshots, and `RunReport`, including work delegated through multiple agents. Events preserve the worker's run, task, and action identities, with links back to the calling action. Receipts arriving through both a live stream and a final snapshot are deduplicated, and a child's terminal marker cannot finish the parent run. Streaming is selected according to the peer's advertised capability; custom workers that provide only a request/response handler keep that execution path. Parent completion checks can inspect actual worker tool outcomes without joining separate stored runs. Delegation-only receipts remain distinct from tool execution evidence, and failures or interrupted streams preserve observed effects without automatically resubmitting the work.

Persistence redaction is configured once through `SQLiteRunStore(..., redaction_policy=...)` and applied before every task, report, and caller metadata payload is written, including intermediate snapshots. Alongside recursive masking of sensitive fields, `RedactionPolicy.sensitive_values` removes known credentials from free text such as command output and error messages. Default sensitive keys also cover recovery `data_base64` fields in presentation copies. Redaction operates on copies, preserving live model and tool inputs and the separate protected approval and recovery records required for execution and restoration. The policy is optional; existing rows and relational index columns are unchanged, and unknown secrets in arbitrary text still require application-specific handling.

Checkpoint inventory is available through `list_changes()`, with combined filters for state, resource, originating run, and originating task, plus pagination. Applications can find uncertain writes, inspect recent changes, or present recovery history without reading the underlying Storage namespace directly. Results are detached records in reverse insertion order, and querying them does not inspect or modify files, resolve uncertainty, or resume execution. Because inventory includes the original recovery bytes, it retains the same access requirements as individual checkpoint lookup. Together with updated API documentation and explanatory docstrings, these additions give applications a clearer path from live progress to recorded evidence and recovery inspection.

:::

### Added

- **Delegated evidence:** Model-driven delegation forwards native worker events into the parent's stream and task receipts, including nested work. Worker event/run/task/action IDs remain intact, receipts are deduplicated against final snapshots, and child terminal markers cannot close the parent. Failed or interrupted delegations retain observed effects without resubmission. `Agent.call_agent(..., event_sink=...)` exposes optional native streaming to direct callers; transports without streaming contribute returned snapshots.
- **Storage redaction:** `SQLiteRunStore(..., redaction_policy=...)` applies one optional policy to every saved task, report, and caller metadata payload without changing live execution or separate approval/recovery storage. `RedactionPolicy.sensitive_values` masks known secrets in free text; default sensitive keys now include recovery `data_base64` fields.
- **Checkpoint inventory:** `CheckpointStore.list_changes()` and `StorageCheckpointStore.list_changes()` return detached recovery records with combined state/resource/run/task filters and pagination, without accessing resources or changing recovery state.

### Fixed

- Completion checks exclude delegation-only receipts from executed tool evidence. Parent checks can use actual worker outcomes directly, without composing separate RunStore snapshots.
- Delegation honors the peer's streaming capability. Custom unary task handlers are advertised without streaming unless they also provide a streaming handler, preserving existing execution behavior.
- **Live LLM streaming:** Ollama now uses asynchronous HTTP reads for both JSON-action and native-tool streams, allowing `RunHandle.events()` consumers to receive `llm_chunk` while generation is still running. The same fix covers llama.cpp server, vLLM, LM Studio, and generic OpenAI-compatible servers.
- **SDK and local streaming:** OpenAI, Anthropic, Gemini, DeepSeek, Hugging Face, and local llama.cpp open and read synchronous iterators on a worker, keeping the event loop available for consumers and cancellation. Callbacks stay on the application's event loop; native tool assembly is preserved.
- **Stream cleanup:** HTTP responses and clients close on completion, cancellation, provider errors, and callback failures. The JSON-action fallback closes nested streams when interrupted. Synchronous SDK iterators close on their worker after any in-progress operation returns.
- **HTTP stream handling:** Respect protocol completion markers, decode fragmented UTF-8 and lines, surface malformed JSON and provider errors, and forward Ollama custom headers or `OLLAMA_API_KEY` authentication to chat requests.

### Changed

- Include `httpx` explicitly in the `llms` extra. Minimal server-streaming installations can use `pip install protolink httpx`; the core package still requires only Pydantic.
- Keep the existing API and event contract: `llm_chunk` carries incremental text, `llm_final` carries the complete answer, and terminal task status completes the run. Add explanatory docstrings, an embedded streaming guide, and corrected Hugging Face streaming documentation.
- Add gated HTTP and SDK regression tests covering early delivery through `RunHandle.events()`, JSON-action and native-tool modes, tool assembly, cancellation, errors, and resource cleanup.

## [0.7.0] - 2026-09-11

:::note Release Summary

**ProtoLink 0.7.0 provides a more complete execution engine for agent applications**, bringing command execution, recoverable file changes, managed agent groups, approval lifecycles, and completion checks into the existing runtime. These capabilities are particularly useful for coding agents that need to run commands, edit files, request permission, and verify results. The same building blocks support research assistants, data processing, and operational automation. Applications continue to define their own roles, models, domain knowledge, workflows, and interfaces.

Command tools now prepare the exact argument array, working directory, environment, limits, and execution boundary before authorization. Output streams through native events, and typed results expose exit status, truncation, timeout, cancellation, and duration. Execution limits and subprocess cleanup give applications control over long-running work. A command agent can run without an LLM, and a small backend interface allows applications to supply other execution environments. The first-party local backend runs on the host and does not provide sandbox isolation.

Filesystem tools add a recoverable path from a proposed change to an applied edit and, when needed, an approved restoration. Diff previews are bound to the resolved target and its actual preimage. Original bytes and permission modes are saved before mutation, stale approvals are rejected, and restoration refuses to overwrite a resource that has changed since the edit. Recovery records distinguish applied, restored, failed, and uncertain changes, preserving the information needed to inspect interrupted work.

The reusable approval broker handles multiple pending requests, correlates decisions with the exact prepared action, and releases waits on cancellation or expiration. Application adapters supply authentication and presentation while ProtoLink tracks the approval lifecycle. Reconnecting clients can inspect pending requests and prior decisions without executing an action again. Approval remains separate from proof of execution, and interrupted effects remain explicitly uncertain.

Embedded applications can manage owned agents with `AgentGroup`, including readiness checks, cleanup after partial startup, and shutdown of active runs. `RunHandle` exposes typed events, cancellation, a normalized final result, and the existing `RunReport`, reducing the need for applications to reconstruct outcomes from transport-specific stream shapes. Local invocation and the existing network transports share these runtime facilities.

Completion checks let applications define success using task and tool outcomes, artifacts, and resource revisions. Evidence becomes stale when its referenced resource changes. Configurable Graph and Pipeline limits bound workflow iterations and repair attempts, while denied actions and uncertain transport failures are never automatically replayed. These additions reuse ProtoLink's policies, budgets, cancellation, storage, reports, and flows, preserve the `Agent` constructor, and add no base-package dependencies.

:::

### Added

- Optional `process_tool()` with a small `ExecutionBackend` interface and local host implementation. Commands use explicit argv, cwd, environment, and limits; prepared artifacts pass through native authorization. Typed results and events retain bounded output, exit status, timeout/cancellation details, and duration. POSIX process groups are cleaned up; host execution is explicitly not a sandbox.
- `PreparedTool` and `ToolExecution` for optional tools that execute their exact authorized preparation, including native budget, cancellation, task correlation, and event access. Existing callable tools retain their contract.
- `AgentGroup` for owned/external resource lifecycle, readiness, partial-start rollback, and shutdown. `RunHandle` normalizes local and transported task events, final results, cancellation, and existing `RunReport`/`RunStore` integration without replaying uncertain operations.
- `ApprovalBroker` with scoped request inspection, exact prepared-action fingerprints, simultaneous approvals, explicit resolution outcomes, cancellation/expiry, reconnectable subscriptions, and optional existing Storage persistence. Orphan requests are inspection-only uncertainty records.
- Optional `filesystem_tools()` for create, replace, preview, and separately authorized restoration. POSIX descriptor-relative access rejects symlinks and stale preimages; dedicated checkpoints preserve original bytes/modes before atomic mutation. Recovery conflicts and interrupted writes remain explicit. Added small resource/revision/checkpoint interfaces and `StorageCheckpointStore`.
- `CompletionCheck`, `CompletionValidator`, typed evidence/outcomes, and resource-dependent `ValidationResult` records. Native events, reports, and report comparisons retain acceptance results; approval-only evidence cannot prove execution, and changed revisions invalidate checks.
- Configurable Graph total/per-node visit limits and Pipeline step limits, shared native budgets across nested bounded workflows, and structured `WorkflowLimitError` blockers. Repair limits are independent of transport retries.
- Five provider-free examples and an execution/recovery guide with public API contracts, ownership rules, migration guidance, and platform/recovery limits.

### Changed

- Direct tool dispatch enforces native budgets and emits action lifecycle receipts. Repeated calls with the same live `RunContext` share tool counters; delegated tool dispatch also counts against its parent's tool limit. Active task permissions propagate to nested direct tool calls.
- Structured flows use separate node task identities while preserving the enclosing task ID, partial results, and live cancellation; they stop on failed, canceled, or input-required tasks. Existing default Graph iteration limits and callable/delegation signatures are preserved.
- Aligned runtime metadata and documentation versions for 0.7.0.
- Require pytest-asyncio 1.4 or newer in the test extra to avoid an implicit event-loop leak in older test runners. Runtime dependencies are unchanged.

### Fixed

- SQLite knowledge-store operations and dashboard run-store inspection now close their database connections on both success and failure. Writes retain commit/rollback behavior, preventing connection accumulation in long-running applications. Regression tests also verify rollback after a failed index replacement.
- Dashboard agent pings and doctor probes now close HTTP error responses before returning diagnostics, preventing socket leaks when a remote endpoint returns an error status.
- Native task submission keeps response deduplication but disables automatic transport retries; a lost response cannot prove a side effect did not occur. Request/response transports return structured task policy/budget failures.
- Approval callbacks cannot silently mutate prepared arguments or artifacts after they have been presented for authorization.
- Partially failed server startup now attempts transport cleanup before propagating the startup failure.
- Direct and streaming policy/budget failures retain structured task blockers instead of requiring applications to interpret error prose.
- Closing a task stream promptly closes its nested execution and subprocesses. Streaming budgets remain scoped to execution even when a consumer closes the stream from another asyncio task on Python 3.11.

## [0.6.9] - 2026-09-03


:::note Release Summary

This release adds Protolink Studio and simplifies the path from a typed Python function to a local agent. It also makes convenience-call failures explicit, completes the blocking task and tool APIs, and ships type metadata with the package.

:::

### Added

- New CLI `studio` command -> `protolink studio --blueprint --ip --port`. You can load the studio with a blueprint JSON as input.
- Promoted the dashboard's Studio tab from a preview to an active visual builder for Agent, LLM, Tool, Registry, Flow, and operational Module nodes. The canvas supports compatible declarative connections, node/project editing, undo/redo, browser-local draft persistence, and JSON import/export; served dashboards additionally generate Python that can be viewed, copied, and downloaded.
- Added `/studio` and the `/api/studio/catalog`, `/api/studio/generate`, `/api/studio/status`, `/api/studio/run`, and `/api/studio/stop` routes. Studio validates bounded JSON, rejects embedded secrets in favor of environment-variable references, and runs at most one generated project in a loopback-controlled subprocess that is stopped and cleaned up with the dashboard.
- Added public Studio blueprint, validation, catalog, code-generation, and runtime helpers, and updated the provider-free dashboard example to embed the standard runnable starter blueprint.
- Added `@agent.tool` and `@agent.tool()` registration with inferred function names, cleaned docstrings, and typed schemas. Explicit keyword and positional metadata remain supported, and the original function and callable type are preserved.
- Added direct callable registration with `agent.add_tool(add)`. Synchronous and asynchronous functions, bound methods, and callable objects are wrapped automatically with `Tool.from_callable()`; existing tool objects retain their identity, metadata, and policy behavior.
- Added `Tool.from_callable()` for reusable tool definitions with optional schema, discovery, capability, and approval-preview metadata.
- Added `agent.sync.call_tool()` for raw validated and authorized tool results, and `agent.sync.run_task()` for complete task execution and inspection.
- Added `Task.raise_for_status()` and the exported `TaskExecutionError`, whose `.task` attribute retains the original failed or canceled task and its partial outputs.
- Added the `py.typed` package marker for installed type-checker support.

### Changed

- `invoke()` and `ask()` now execute through `run_task()`, preserving active-task registration, cancellation, and configured run persistence for custom handlers.
- README and getting-started examples now begin with a provider-free tool call using only the base package, then introduce tasks, inference, and HTTP. Updated API references, session guidance, public docstrings, and release checks.
- Aligned Python package metadata, runtime version, lockfiles, and documentation version labels for 0.6.9.
- CI now installs the built wheel in an isolated environment with only base dependencies and checks the typed marker, imports, CLI, and local runtime. Release versions and Ruff pins are aligned across package and CI configuration.

### Fixed

- Replaced deprecated string-based `logging.getLevelName()` calls with `logging.getLevelNamesMapping()`.
- `invoke()` and `ask()` now raise `TaskExecutionError` when a handler returns a failed or canceled task instead of presenting it as a successful response. Exceptions raised directly during execution retain their original types.
- `invoke()` preserves valid empty strings, zero, false, and empty containers, and no longer returns an unchanged request as the response. `ask()` also preserves empty answer text and excludes unchanged request content. The no-response fallback applies only when response content is absent or `None`.
- Every `SyncAgent` method now detects an active event loop before creating a coroutine and directs callers to the corresponding async method, avoiding unawaited-coroutine warnings on this misuse.
- Callable-instance tools now resolve `__call__` annotations for schema inference and argument validation. `Tool.from_callable()` rejects blank or non-string names before registration.

### Compatibility

Python 3.11 or newer is now required.

Successful explicit tool calls through `invoke(..., part_type="tool_call")` still return `ToolOutput`; use `call_tool()` for the raw tool return value. Code that previously inspected an error-bearing result from `invoke()` or `ask()` should catch `TaskExecutionError` and inspect `exception.task`, or use `run_task()` to handle returned states directly. `raise_for_status()` checks only failed and canceled states; it neither waits for completion nor rejects `input-required` or other nonterminal states.

## [0.6.8] - 2026-07-30

:::note Release Summary

This patch release introduces first-party **Retrieval-Augmented Generation
(RAG)**, a deterministic **infer-loop benchmark** for evaluating model
correctness, tool use, delegation, semantic agent routing, recovery, and
performance, and a substantially expanded local observability workflow.
Telemetry traces can now be inspected and replayed in the dashboard through
the `protolink dashboard` CLI command, alongside improved Registry and Runs
views. The CLI also gains explicit version reporting, while richer parse errors
and benchmark artifacts make local-model behavior easier to diagnose,
compare, and improve.

:::

### Added

- Added first-party Retrieval-Augmented Generation through the `Knowledge`
  facade and `create_knowledge()`: dependency-free in-memory and persistent
  SQLite indexes, automatic loading/chunking/embedding, vector, keyword, and
  hybrid search, metadata filters, MMR, reranking, managed index lifecycle,
  normalized hits, structured citations, and async/blocking APIs.
- Added retrieval-only adapters for user-owned Chroma collections, Pinecone
  indexes, Qdrant collections, arbitrary `Retriever` implementations, and sync
  or async search functions. External clients, credentials, embedding
  compatibility, and index ownership remain with the application.
- Added `Agent(..., knowledge=..., retrieval="auto"|"always"|"required")`,
  generated `search_<name>` tools, `Agent.add_knowledge()`,
  `@agent.retriever`, and deterministic `Agent.ask()` / `agent.sync.ask()`
  returning `RAGAnswer` text, hits, and citations. Knowledge reads participate
  in policy, approvals, cancellation, budgets, telemetry, task metadata, and
  the existing native/JSON-fallback inference loop. Raw knowledge passages are
  ephemeral to the active authorized model loop and are omitted from
  persistent conversation history, task boundaries, and telemetry.
- Added the dependency-free `examples/rag_agent.py` and a complete RAG guide
  covering managed indexes, existing vector databases, custom retrievers,
  retrieval modes, citations, source lifecycle, and operational safety.
- Added a deterministic, repository-local infer-loop benchmark that exercises
  the real `AgentClient`, `Task`, coordinator `Agent`, provider adapter, model
  inference loop, local tools, delegated agents, runtime events, and telemetry
  against controlled inputs and independently recorded outcomes.
- Added benchmark coverage for direct answers, coordinator-owned tool calls,
  delegated tool calls, delegated inference, structured output, grounding
  traps, and semantic routing choices. Routing cases require the coordinator
  to decide whether to answer directly, use a local tool, delegate a tool, or
  delegate inference; authoritative and decoy agents can return identical
  values so the action ledger and trace prove which agent was actually
  selected.
- Added deterministic `smoke`, `core`, and `full` benchmark suites, including a
  200-case full catalog, reproducible seeds, category and case filters,
  repetitions, warm-up controls, prompt-file overrides, and native-tool or
  portable JSON-action configurations.
- Added strict, functional, and first-try benchmark scoring together with
  rescued-attempt counts, parse-recovery and hallucinated-action diagnostics,
  inference-step statistics, latency percentiles, scored wall time, provider
  call timing, repeat probes, and baseline comparison support.
- Added self-contained HTML benchmark reports plus JSON and CSV artifacts. The
  report keeps dense bar charts within a horizontally scrollable viewport and
  provides an attempt review for unresolved and recovered failures, including
  the original request, expected outcome, actual output, model decisions,
  successful actions, traces, and runtime errors.
- Added `InferParseError` with the failed response, attempt count, parser cause, and a concise explanation.
- Added a local dashboard Telemetry explorer for `traces.jsonl`, with CLI or browser-file loading, bounded recent-first paging, lazy trace detail, span waterfalls, grouped task records, and playable event replay.
- Added session-only Registry and read-only Runs source controls, a redesigned searchable run replay workspace, a corrected span waterfall selection/timeline layout, `protolink --version`, and the dashboard version label.

## [0.6.7] - 2026-07-27

:::note Release Summary

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

:::note Release Summary

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
