# Examples

This section links to example projects and code snippets in the repository.

:::tip[New here?]

Start with the **Jupyter Notebooks** in `examples/notebooks/basic_example`! They provide the easiest and best interactive introduction to running the Registry and Agents.

:::
## Jupyter Notebooks (Recommended)

The best way to get started is by running the interactive notebooks in [`examples/notebooks/basic_example`](https://github.com/nMaroulis/protolink/tree/main/examples/notebooks/basic_example). These notebooks teach you the core concepts of Protolink through a complete multi-agent system:

### 🎯 What You'll Learn

- **Registry Setup**: How to run a central discovery service for agents
- **Agent Creation**: Building agents with tools and task handling
- **Agent Communication**: How agents discover and communicate with each other
- **Transport Configuration**: Using HTTP transport for agent-to-agent messaging
- **Tool Integration**: Adding native tools to agents using decorators

### 📚 Notebook Sequence

Run these notebooks in order to build a complete weather monitoring system:

#### 1. **[`registry.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/registry.ipynb)** - Start the Registry
- Sets up the central discovery service on `localhost:9010`
- Exposes REST API endpoints for agent registration and discovery
- Provides a web interface at `/status` to view registered agents

#### 2. **[`weather_agent.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/weather_agent.ipynb)** - Create a Data Provider
- Builds an agent that provides mock weather data
- Demonstrates tool creation with the `@tool` decorator
- Shows agent registration and task handling patterns
- Runs on `localhost:8010`

#### 3. **[`alert_agent.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/alert_agent.ipynb)** - Create a Consumer Agent
- Builds an agent that processes weather data and sends alerts
- Demonstrates agent-to-agent communication via the registry
- Shows different transport configuration patterns
- Runs on `localhost:8020`

### 🏗️ System Architecture

```
┌─────────────────┐    HTTP REST API   ┌─────────────────┐
│   Registry      │◄──────────────────►│  Alert Agent    │
│  (localhost:    │                    │  (localhost:    │
│   9010)         │                    │   8020)         │
└─────────────────┘                    └─────────────────┘
         ▲                                   ▲
         │                                   │
         │ HTTP REST API                     │ HTTP REST API
         │                                   │
┌─────────────────┐                    ┌─────────────────┐
│ Weather Agent   │◄──────────────────►│  Alert Agent    │
│ (localhost:     │                    │                 │
│  8010)          │                    │                 │
└─────────────────┘                    └─────────────────┘
```

### 🚀 Quick Start

1. **Start the Registry** (run `registry.ipynb` first)
2. **Start the Weather Agent** (run `weather_agent.ipynb`)
3. **Start the Alert Agent** (run `alert_agent.ipynb`)
4. **Test the System**: Visit `http://localhost:9010/status` to see all registered agents

### 💡 Key Concepts Demonstrated

- **Transport Flexibility**: Use transport strings (`"http"`) or `HTTPTransport` instances
- **Registry Patterns**: Pass registry as URL string or `Registry` object
- **Tool Creation**: Native tools with automatic schema inference
- **Task Handling**: Implement `handle_task` for processing incoming tasks
- **Agent Discovery**: Find and communicate with other agents via the registry



## Example Scripts

The repository includes several **standalone example scripts** that demonstrate specific Protolink capabilities:

### Retrieval-augmented Agent

- [`rag_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/rag_agent.py)
  builds a dependency-free in-memory knowledge base from two `Document` values
  and attaches it to an Agent in automatic retrieval mode. Its `MockLLM`
  selects the generated `search_handbook` tool, reads the actual retrieved
  passage, and returns a citation-bearing answer through the normal inference
  loop.

```bash
python examples/rag_agent.py
```

The example opens no port and needs no API key, model server, vector-database
service, or network access. Read the
[Retrieval-Augmented Generation guide](rag.md) for persistent SQLite
knowledge, existing Chroma/Pinecone/Qdrant indexes, custom retrievers,
deterministic `Agent.ask()`, filters, index lifecycle, and citation metadata.

### Built-in web search

- [`builtin_web_search.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_web_search.py) registers `web_search()` on a runtime Agent with an explicit `network.read` policy. It defaults to English Wikipedia's documented keyless search API and accepts `--engine`, `--freshness`, and `--max-results` options. DuckDuckGo remains an explicit best-effort HTML option; select Brave after exporting `BRAVE_SEARCH_API_KEY`.

```bash
python examples/builtin_web_search.py "What is the capital of Greece?"

export BRAVE_SEARCH_API_KEY="your-key"
python examples/builtin_web_search.py "Python structured concurrency" --engine brave

python examples/builtin_web_search.py "Python structured concurrency" --engine duckduckgo
```

Run it without a query to inspect the CLI without making a network request.

### A2A core and A2A 1.0 boundary

- [`provider_free_mesh.py`](https://github.com/nMaroulis/protolink/blob/main/examples/provider_free_mesh.py) runs a deterministic three-agent mesh with no provider, API key, registry, or network port. It demonstrates the A2A-derived `AgentCard`, `Task`, and `Message` model through the in-process runtime transport.
- [`a2a_tck_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/a2a_tck_agent.py) is the provider-free HTTP fixture for the official A2A 1.0 TCK. It explicitly uses `Agent(..., a2a=True)`; ordinary HTTP agents remain native-only by default. It is a compatibility test target, not a substitute for a published passing TCK result; follow the pinned instructions in [A2A Core and 1.0 Compatibility](a2a.md).

### Run regression diffing

- [`run_regression_diff.py`](https://github.com/nMaroulis/protolink/blob/main/examples/run_regression_diff.py) creates provider-free baseline and candidate reports with different known runtime IDs, timestamps, sequence counters, and bounded latency, proves that schema-aware normalization plus an explicit tolerance remove that noise, and then detects a real final-output change with `diff_run_reports()` and `assert_run_matches()`. Real candidate runs must be executed and recorded separately.

### 🧩 Protolink 0.6.3 runtime-control examples

The 0.6.3 examples are small, provider-free scripts intended for application integrators:

- [`v063_context_budget.py`](https://github.com/nMaroulis/protolink/blob/main/examples/v063_context_budget.py) shows `ContextManifest`, `LLMModelProfile`, and enforced `RunBudget` behavior before a model call.
- [`v063_history_compaction.py`](https://github.com/nMaroulis/protolink/blob/main/examples/v063_history_compaction.py) shows local `recent`, `tokens`, and isolated `summary` compaction plus remote `AgentClient.compact_history()` over the request-spec endpoint.
- [`v063_state_control.py`](https://github.com/nMaroulis/protolink/blob/main/examples/v063_state_control.py) shows client/server state `describe`, `compact`, and `reset` requests for one persistent conversation session.
- [`v063_run_reports.py`](https://github.com/nMaroulis/protolink/blob/main/examples/v063_run_reports.py) shows `RunRecorder`, `RunReport`, `RunReplay`, golden-run assertions, and redaction.
- [`v063_protoagent_policy_mesh.py`](https://github.com/nMaroulis/protolink/blob/main/examples/v063_protoagent_policy_mesh.py) sketches the ProtoAgent Explorer/Coder/Architect structure abstractly. The prompts are intentionally tiny; the example focuses on tool capabilities, `CapabilityPolicy`, diff-preview `action_builder`s, and approval-gated workspace writes.

### Production case study: [ProtoAgent](protoagent_case_study.md)

ProtoAgent is a full local-first coding assistant built on ProtoLink. Read the case study to see how the runtime engine powers its Architect, Explorer, and Coder agent deck, approval-gated diffs, completion validation, Context Loom evidence, cancellation, history control, and run reports.

### Flagship experiment: [AI Courtroom](ai_courtroom_example.md)

The AI Courtroom is a replayable multi-agent experiment built around a
fictional autonomous-vehicle liability case. It compares one generalist, five
independent specialists, a foreperson-star topology, and a direct
agent-selected mesh while keeping public evidence and observable decision
contracts controlled. Read the example page to see how jurors author direct
ProtoLink messages, how one communication topology produces a different
deterministic verdict, and how every run automatically generates standalone
interactive HTML reports for replay and comparison.

For a model-versus-model experiment, see the
[`ai_courtroom_benchmark`](https://github.com/nMaroulis/protolink/tree/main/examples/ai_courtroom_benchmark)
example. It runs two advocates on opposite sides of a portable JSON case,
swaps their roles, keeps the judge and independent jury fixed, and generates a
standalone replay report with opinion trajectories, citations, vote flips, and
fairness checks.

### 🛠️ [`devtools_dashboard.py`](https://github.com/nMaroulis/protolink/blob/main/examples/devtools_dashboard.py)
**Purpose**: Local devtools, run replay, registry snapshot, and dashboard

- Uses `create_llm("mock")`, so it runs without provider credentials
- Creates several agents and registers their cards in an in-process registry
- Runs a small task loop and records each streamed run with `RunRecorder`
- Saves durable task snapshots and `RunReport` records to `SQLiteRunStore`
- Renders static dashboard HTML using `DevtoolsHtmlRenderer`, including the disabled Studio preview
- Prints follow-up commands for `protolink run list`, `protolink run replay`, and `protolink dashboard`
- Supports `--serve-live` to start provider-free HTTP agents, an HTTP registry, and the dashboard so ping/chat actions can be clicked
- The dashboard also contains registry health, selected-agent detail, run replay, and chat panels

### 📝 [`basic_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/basic_agent.py)
**Purpose**: Minimal agent setup focused on core concepts

- Demonstrates simplified agent creation using dictionary-based `AgentCard`
- Shows how to add native tools using the `@agent.tool` decorator with automatic schema inference
- Demonstrates direct agent invocation using convenience methods: `invoke()` and `sync.invoke()`
- Includes optional LLM integration for reasoning and inference
- Uses `runtime` transport for in-memory execution (no network dependencies)

### 🧠 [`agent_memory.py`](https://github.com/nMaroulis/protolink/blob/main/examples/agent_memory.py)
**Purpose**: Conversation memory and persistence across tasks

- Demonstrates the difference between stateless agents (`state=None`) and persistent agents (`state=["conversation"]`)
- Shows how `sync.invoke()` handles session history automatically using a default `session_id`
- Demonstrates history persistence across sequential calls to the same agent instance
- Useful for building conversational bots and multi-turn interaction assistants

### 🌐 [`http_agents.py`](https://github.com/nMaroulis/protolink/blob/main/examples/http_agents.py)
**Purpose**: HTTP transport and agent-to-agent communication

- Demonstrates two agents communicating over HTTP
- Tests client functions: `get_agent_card`, `send_message_to`, `call_agent`
- Shows how to set up multiple agents on different ports
- Includes comprehensive error handling and cleanup

### 🔒 [`authentication.py`](https://github.com/nMaroulis/protolink/blob/main/examples/authentication.py)
**Purpose**: Authentication, credentials propagation, and security verification

- Demonstrates API key, Basic, and signed Bearer JWT authentication providers
- Covers server-side route authentication (returning `401 Unauthorized` for failed requests)
- Covers client-side lazy authentication (automatic signature/credential injection on outgoing requests)
- Verifies both HTTP (Starlette and FastAPI backends) and WebSocket handshake verification
- Demonstrates success and failure scenarios for both transports

### 🤖 [LLM notebooks](https://github.com/nMaroulis/protolink/tree/main/examples/notebooks/llm_test)
**Purpose**: LLM backend integration, inference loops, and delegation
- Demonstrates direct API LLM usage
- Shows `infer()` with local tool calling
- Shows `agent_call` delegation between agents
- Complements the [LLM Examples](llm_examples.md) guide

### 📋 [`registry.py`](https://github.com/nMaroulis/protolink/blob/main/examples/registry.py)
**Purpose**: Registry discovery and autonomous agent behaviour

- Creates autonomous agents that discover peers and send tasks
- Demonstrates registry-based agent discovery
- Shows background task management and cleanup
- Multi-agent orchestration with automatic peer communication

### ⚡ [`runtime_agents.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_agents.py)
**Purpose**: In-memory agent communication interoperability

- Uses explicitly mapped URL `RuntimeTransport` instances for agent-to-agent communication without HTTP configuration
- Demonstrates safe registry discovery enabling native message parsing safely inside isolated testing contexts
- Shows how to build reliable agent networks safely running within a single process retaining production semantics
- Useful for test pipelines scaling native workflow isolation

### 📡 [`streaming_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/streaming_agent.py)
**Purpose**: Real-time streaming with progress updates

- Demonstrates streaming task handlers with progress events
- Shows artifact production and streaming
- Context management for multi-turn conversations
- Event-driven architecture with task status updates

### 🔌 [`websocket_basic_example.py`](https://github.com/nMaroulis/protolink/blob/main/examples/websocket_basic_example.py)
**Purpose**: WebSocket transport with streaming support

- Mirrors the basic notebook example but uses WebSocket transport
- Demonstrates both request/response and streaming task patterns
- Shows registry discovery over WebSockets
- Real-time progress updates via WebSocket events

### [`grpc_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/grpc_agent.py)
**Purpose**: gRPC transport request/response and streaming smoke test

- Starts a provider-free mock-LLM agent on a local `grpc://` port
- Fetches the agent card and sends a normal task through `AgentClient`
- Consumes task events through the gRPC streaming API
- Demonstrates the `transport="grpc"` factory path without generated protobuf files

### [`tls_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/tls_agent.py)
**Purpose**: Native TLS and mutual TLS through the high-level agent API

- Starts a provider-free mock agent on an `https://` endpoint using `TLSConfig`
- Configures verified client trust without disabling hostname or certificate checks
- Supports `--require-client-cert` to demonstrate mutual TLS
- Keeps certificate transport security separate from bearer/API-key authentication

### 🔄 [`structured_flows/`](https://github.com/nMaroulis/protolink/tree/main/examples/structured_flows)
**Purpose**: Advanced flow orchestration patterns

- Demonstrates Graph flow for complex state machine topologies with cyclic loops
- Shows conditional branching and multi-step review workflows
- Examples include sequential processing, parallel execution, and dynamic routing
- Illustrates integration of multiple agents in structured flow patterns
