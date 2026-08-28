# ProtoLink

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/protolink)](https://pypi.org/project/protolink/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/protolink?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=YELLOW&left_text=%E2%AC%87%EF%B8%8F)](https://pepy.tech/projects/protolink)

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="ProtoLink logo" width="60%">
</div>

ProtoLink is a lightweight, [**A2A**](https://a2a-protocol.org/latest/specification/)-first Python framework for building **pluggable agents** and multi-agent systems. It began as an A2A-based alternative to chain-centric frameworks such as LangChain: instead of organizing an application around chains of model calls, ProtoLink treats each `Agent` as a self-contained runtime entity with identity, capabilities, lifecycle, tools, optional reasoning, and direct task-based communication.

A2A is the architectural core, not a bolt-on integration. ProtoLink's native `AgentCard`, `Task`, `Message`, `Part`, and `Artifact` runtime model was originally built on [A2A 0.3](https://a2a-protocol.org/v0.3.0/specification/), then extended for inference, tools, structured agent flows and operational modules without abandoning those protocol primitives. That choice keeps the `Agent`/`Task` API simple and the runtime pluggable; `a2a=True` translates the implemented HTTP surface between ProtoLink's native model and canonical [A2A 1.0](https://a2a-protocol.org/latest/specification/) JSON-RPC shapes for standard peers.

The agent is the stable composition surface. Plug in only what that agent needs: an API or local **LLM**, application knowledge for **RAG**, built-in, native, or **MCP** tools, a transport, registry, storage and state, telemetry, authentication, logging, policy, or durable run records. Every module is optional and replaceable through a small public interface.

ProtoLink is deliberately **LLM-agnostic and local-first**. Provider-native tool calling is used when available; a strict JSON action fallback keeps self-hosted and smaller models on Ollama, llama.cpp, LM Studio, vLLM, or custom backends inside the same infer loop. Changing the model does not require rewriting the agent, its tools, or its communication layer.

The base package has one runtime dependency: Pydantic. HTTP servers, gRPC, hosted model SDKs, MCP, telemetry providers, and other integrations are installed only when you choose them.

> **Simple by default. Explicit when it matters.**

[Get started](https://nmaroulis.github.io/protolink/docs/getting-started/) · [Concept](https://nmaroulis.github.io/protolink/docs/concept/) · [API documentation](https://nmaroulis.github.io/protolink/docs/) · [Examples](https://nmaroulis.github.io/protolink/docs/examples/)

## Why ProtoLink?

- **Pluggable by design** - compose an agent from independent modules instead of adopting a mandatory stack.
- **A small, stable API** - string aliases cover the common path; concrete implementations expose full control when needed.
- **Local first, distributed when needed** - develop with no network or provider, then move the same task contract to HTTP, SSE JSON-RPC, WebSocket, or gRPC.
- **Friendly to smaller models** - one-action-at-a-time inference, schema validation, JSON fallback, and deterministic flows reduce reliance on hidden prompt behavior.
- **Explicit and inspectable** - tool calls, delegation, task state, policy decisions, approvals, runtime events, traces, and reports have typed representations.
- **A2A at the core** - agents communicate through cards, tasks, messages, parts, and artifacts rather than framework-private graph state.

Focus on the agent's role and capabilities. ProtoLink handles the infer loop, validated tool execution, delegation, communication, lifecycle, and the operational modules around them.

## Start with one agent

Install the HTTP extra:

```bash
uv add "protolink[http]"
```

Create and start a provider-free agent:

```python
from protolink import Agent, AgentCard

planner_agent = Agent(
    card=AgentCard(
        name="planner",
        description="Builds clear execution plans",
        url="http://127.0.0.1:8000",
    ),
    transport="http",
)

planner_agent.start()
```

No `async main()`, event-loop setup, model account, or API key is required. `start()` owns the lifecycle and blocks for a standalone service; use `start(background=True)` when embedding the agent in another application.

## Plug in only what the agent needs

The constructor is the composition surface. This expanded example uses a local Ollama model, registry discovery, SQLite state and run storage, local telemetry, authentication, file logging, dependency-free built-in web search, a native Python tool, and tools from an MCP server:

```python
from protolink import (
    Agent,
    AgentCard,
    LocalTraceTelemetry,
    SQLiteRunStore,
    create_llm,
)
from protolink.logging import FileLogger
from protolink.security import APIKeyAuth
from protolink.storage import SQLiteStorage
from protolink.tools import web_search
from protolink.tools.adapters import MCPToolAdapter

planner_agent = Agent(
    card=AgentCard(
        name="planner",
        description="Plans and coordinates work",
        url="http://127.0.0.1:8000",
    ),
    llm=create_llm(
        "ollama",
        base_url="http://127.0.0.1:11434",
        model="gemma4:e4b",
    ),
    transport="http",
    registry="http",
    registry_url="http://127.0.0.1:9000",
    storage=SQLiteStorage("planner.db", namespace="planner"),
    state=["conversation"],
    run_store=SQLiteRunStore("runs.db"),
    telemetry=LocalTraceTelemetry(path="traces.jsonl"),
    authenticator=APIKeyAuth({"dev-key": []}),
    logger=FileLogger("planner.log"),
)

planner_agent.add_tool(web_search())

@planner_agent.tool(name="search_notes", description="Search local notes")
async def search_notes(query: str) -> str:
    return f"Results for {query}"

mcp_adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["mcp_server.py"],
)
for tool in mcp_adapter.get_tools():
    planner_agent.add_tool(tool)

planner_agent.start()
```

Install the integrations used here with `uv add "protolink[http,mcp]"`; the Ollama server and example MCP process run separately. `web_search()` defaults to Brave and reads `BRAVE_SEARCH_API_KEY` only when invoked. Pass `engine="wikipedia"` for documented, keyless English Wikipedia search or `engine="duckduckgo"` for keyless, best-effort DuckDuckGo HTML search. Registering the tool performs no network request. Remove any constructor argument or tool you do not need, or replace it with your own implementation. Different agents in the same mesh can use different models, transports, credentials, storage, policies, and observability backends.

`MCPToolAdapter` supports local stdio and remote SSE servers. Once registered, MCP tools follow the same schema validation, policy, execution, and telemetry path as native Python tools.

| Plug-in surface | Built-in choices |
| --- | --- |
| [LLMs](https://nmaroulis.github.io/protolink/docs/llm/) | OpenAI, Anthropic, Gemini, Grok, DeepSeek, Hugging Face, Ollama, llama.cpp, LM Studio, vLLM, OpenAI-compatible servers, mock, custom |
| [Knowledge and RAG](https://nmaroulis.github.io/protolink/docs/rag/) | Dependency-free memory and SQLite indexes, Chroma, Pinecone, Qdrant, custom vector stores and retrievers |
| [Tools](https://nmaroulis.github.io/protolink/docs/tool/) | Built-in web search, URL fetch, calculator, current datetime, typed Python tools, MCP adapters, custom `BaseTool` implementations |
| [Transports](https://nmaroulis.github.io/protolink/docs/transport/) | Runtime, HTTP, SSE JSON-RPC, WebSocket, gRPC, custom transports |
| [Registry](https://nmaroulis.github.io/protolink/docs/registry/) | Local or network discovery through `Registry` and `RegistryClient` |
| [State and storage](https://nmaroulis.github.io/protolink/docs/state/) | In-memory or SQLite state, conversation persistence, custom storage |
| [Run storage](https://nmaroulis.github.io/protolink/docs/storage/) | `SQLiteRunStore` or custom durable `RunStore` implementations |
| [Telemetry](https://nmaroulis.github.io/protolink/docs/telemetry/) | Dependency-free local traces, Langfuse, LangSmith, multi-telemetry, custom |
| [Authentication](https://nmaroulis.github.io/protolink/docs/authentication/) | API keys, bearer JWT, basic auth, OAuth delegation, TLS |
| [Logging](https://nmaroulis.github.io/protolink/docs/logging/) | Colored console, text/JSON files, quiet logger, custom `BaseLogger` |
| [Runtime control](https://nmaroulis.github.io/protolink/docs/runtime/) | Budgets, cancellation, policy, approvals, events, reports, replay, regression diffing, redaction |

Attach private or application-owned knowledge with the same progressive-control
API:

```python
from protolink import create_knowledge

knowledge = create_knowledge(
    "memory",
    name="product_docs",
    description="product manuals and troubleshooting guides",
    sources=["docs/"],
)
planner_agent.add_knowledge(knowledge)

answer = planner_agent.sync.ask("How do I reset a device?")
print(answer.text, answer.citations)
```

`Agent.invoke()` lets the model choose the automatically registered
`search_product_docs` tool. `Agent.ask()` always retrieves first and returns
the answer together with normalized hits and citations. Existing Chroma,
Pinecone, Qdrant, or custom search systems can be attached without moving
their data. See [Retrieval-Augmented Generation](https://nmaroulis.github.io/protolink/docs/rag/).

## LLM-agnostic, with a strong local focus

For LLM-backed agents, the **infer loop** is the heart of ProtoLink:

1. The model proposes one next action, including a knowledge search when one is available.
2. ProtoLink parses and validates it.
3. The runtime executes a tool call, agent delegation, or final response.
4. The structured result is added to the task context.
5. The loop repeats until completion or a configured bound is reached.

Providers with reliable native tool calling use it. Local and smaller models can use the JSON fallback, which exposes the same `tool_call`, `agent_call`, and `final` action contract without depending on a provider-specific SDK feature.

`agent_call` has two delegation modes: `tool_call` asks another agent to execute one of its tools, while `infer` asks that agent's LLM to handle a prompt and initiates the other agent's **infer loop**.

```python
from protolink import Agent, AgentCard, create_llm

local_agent = Agent(
    card=AgentCard(
        name="local-assistant",
        description="Runs against a local model server",
        url="runtime://local-assistant",
    ),
    transport="runtime",
    llm=create_llm(
        "ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b",
    ),
)
```

Swap `"ollama"` for another built-in or custom `LLM`; the agent, tools, tasks, and flows do not change.

## A2A primitives, standard wire compatibility

ProtoLink uses A2A's core `AgentCard`, `Task`, `Message`, `Part`, and `Artifact` concepts as first-class Python runtime primitives. Delegation, lifecycle transitions, structured flows, tool results, telemetry, and replay all operate on those explicit objects rather than escaping into a separate orchestration format.

Standard wire compatibility is explicit and additive:

```python
a2a_agent = Agent(card=card, transport="http", a2a=True)

# "auto" prefers the full ProtoLink contract and discovers A2A-only peers.
result = await a2a_agent.call_agent(peer_url, task)

# Select the protocol explicitly when the peer protocol is already known.
result = await a2a_agent.call_agent(peer_url, task, protocol="a2a")
result = await a2a_agent.call_agent(peer_url, task, protocol="protolink")
```

An explicit `protocol="a2a"` choice bypasses the native-vs-A2A selection step,
but still fetches and validates the peer's standard Agent Card and compatible
JSON-RPC interface before sending work.

Agent-originated A2A discovery is always same-origin: an advertised interface
must match the Agent Card's origin. For a split-origin deployment you explicitly
trust, use a dedicated `AgentClient(..., a2a_allow_cross_origin=True)`; see
[A2A compatibility](https://nmaroulis.github.io/protolink/docs/a2a/) for the operational limits.

With the default `a2a=False`, HTTP behaves exactly as before: native tasks, status, health, chat, and control endpoints only. With `a2a=True`, the agent additionally serves the standard Agent Card and `SendMessage`, `GetTask`, `ListTasks`, and `CancelTask` JSON-RPC operations, and its client can translate outbound calls to A2A-only peers. Outbound ProtoLink `infer` instructions become A2A user text. Inbound A2A user text remains a normal ProtoLink text part for custom handlers; the default LLM engine recognizes the A2A metadata and treats that text as an inference request. Framework-specific tool-call and flow state should stay on the native protocol.

Compatibility is versioned and testable: the official [A2A Technology Compatibility Kit](https://github.com/a2aproject/a2a-tck) measures the adapter against a pinned protocol surface. The [A2A compatibility page](https://nmaroulis.github.io/protolink/docs/a2a/) records the exact binding, TCK commit, commands, current result, and the remaining upstream harness limitation.

## Structured flows

Agents can choose their own next action, but not every workflow should be probabilistic. `Pipeline`, `Parallel`, `Router`, and `Graph` provide explicit, deterministic topology while keeping every step on the same `Task -> Task` contract.

```python
from protolink import Pipeline, Task

review_flow = Pipeline(
    steps=[researcher_agent, reviewer_agent, planner_agent],
)

result = review_flow.sync.execute(
    Task.create_infer(prompt="Prepare the release plan"),
)
```

Flows can contain local agents, registry-resolved remote agents, or other nested flows. Semantic context injection tells each agent what the next step expects without coupling that agent to the overall topology. See [structured flows](https://nmaroulis.github.io/protolink/docs/flows/) and the [runnable examples](https://github.com/nMaroulis/protolink/tree/main/examples/structured_flows).

## Progressive control

The common path stays small:

```python
agent = Agent(card=card, transport="http")
```

The alias selects the communication boundary without changing the agent API:

| If you need... | Start with | Why |
| --- | --- | --- |
| Agents in one Python process | `"runtime"` | Lowest transport overhead, streaming, and no ports |
| A network service or optional A2A 1.0 endpoint | `"http"` | Status, health, optional chat, and dashboard utilities; add `a2a=True` for A2A routes and outbound translation |
| Live progress for a browser or CLI | `"sse"` | HTTP utilities plus a one-way event stream; no A2A adapter today |
| A persistent interactive connection | `"websocket"` | Bidirectional streaming with low per-frame overhead after connection setup |
| Internal gRPC infrastructure | `"grpc"` | Pooled RPCs, streaming, deadlines, standard health, and reflection |

These are qualitative protocol-overhead profiles, not benchmark results; model and tool latency commonly dominate an agent call. See the [transport guide](https://nmaroulis.github.io/protolink/docs/transport/) for the complete performance, utility, and deployment comparison.

When a boundary needs TLS, resource limits, retries, keepalive settings, or other operational controls, construct the transport and pass it to the same API:

```python
from protolink import RetryPolicy, TLSConfig, TransportConfig, TransportLimits
from protolink.transport import HTTPTransport

transport = HTTPTransport(
    url=card.url,
    tls=TLSConfig(
        certfile="certs/agent.pem",
        keyfile="certs/agent-key.pem",
        cafile="certs/ca.pem",
    ),
    config=TransportConfig(
        limits=TransportLimits(max_concurrent_requests=200),
        retry=RetryPolicy(max_attempts=3),
    ),
)

agent = Agent(card=card, transport=transport)
```

`AgentClient` and `Registry` follow the same rule: pass a string for built-in defaults or a concrete implementation for full control. The façade does not change as deployment requirements grow.

## Local telemetry and replay

ProtoLink includes dependency-free local tracing. Attach `LocalTraceTelemetry`, run a task, and replay the captured spans without sending data to an external service:

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, create_llm

telemetry = LocalTraceTelemetry(path="traces.jsonl")
agent = Agent(
    AgentCard(name="debug", description="Debug agent", url="runtime://debug"),
    transport="runtime",
    llm=create_llm("mock", default_response="done"),
    telemetry=telemetry,
    verbosity=0,
)

result = agent.sync.invoke("Trace this task")
trace = telemetry.recorder.replay()[-1]
```

The same runtime contracts power cancellation, budgets, policy decisions, approval previews, run reports, redaction, read-only replay, and normalized report comparison for regression testing. Replay and comparison never re-execute model or tool calls: execute the candidate separately against controlled dependencies, record its report, and then diff it against the baseline. Normalization is limited to known ProtoLink report-envelope fields; application-owned payloads and report metadata remain exact unless you configure an ignore rule or numeric tolerance.

## Dashboard developer tool

The `protolink dashboard` CLI command projects run-store and registry state into a dependency-free local browser UI:

```bash
protolink dashboard --store runs.db --registry-url http://127.0.0.1:9010 --open
```

It reads task snapshots and `RunReport` records from `SQLiteRunStore`, loads `AgentCard` entries from the registry, and provides local views for agent health, HTTP chat, task history, trace summaries, and run replay. The dashboard does not create agents or upload telemetry; it presents the runtime state your agents already emit.

![ProtoLink dashboard overview](https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/devtools-dashboard.gif)

The CLI also includes project scaffolding, environment diagnostics, registry inspection, run replay, and normalized report diffing:

```bash
protolink init agent
protolink doctor
protolink run list --store runs.db
protolink run diff baseline_run candidate_run --store runs.db
```

See the [developer tools guide](https://nmaroulis.github.io/protolink/docs/devtools/).


## Infer-loop benchmark

The ProtoLink repository includes a closed-world regression benchmark for prompt and infer-loop changes. It exercises
direct answers, local tools, directed and autonomous agent routing, dependent multi-step work, and grounding traps, then reports strict and
recovered functional scores plus end-to-end, model-call, provider, and repeat/cache-sensitive timing.

```bash
python -m benchmarks.infer_loop --provider ollama --model gemma4:e4b --suite smoke
```

The benchmark is source-checkout tooling under `benchmarks/`, not part of the installable package. See the
[infer-loop benchmark guide](benchmarks/infer_loop/README.md) for suite sizes, scoring, Ollama configuration, timing,
baseline comparison, filtering, and CI thresholds.


## More examples

- [Paired AI courtroom advocacy benchmark](examples/ai_courtroom_benchmark/)
- [Built-in multi-engine web search](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_web_search.py)
- [Provider-free runtime mesh](https://github.com/nMaroulis/protolink/blob/main/examples/provider_free_mesh.py)
- [Normalized run regression diffing](https://github.com/nMaroulis/protolink/blob/main/examples/run_regression_diff.py)
- [HTTP agent communication](https://github.com/nMaroulis/protolink/blob/main/examples/http_agents.py)
- [Production transport configuration](https://github.com/nMaroulis/protolink/blob/main/examples/transport_production.py)
- [Runtime policy and approvals](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_policy_and_approvals.py)
- [Task cancellation](https://github.com/nMaroulis/protolink/blob/main/examples/task_cancellation.py)
- [Structured flows](https://github.com/nMaroulis/protolink/tree/main/examples/structured_flows)
- [All examples](https://nmaroulis.github.io/protolink/docs/examples/)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](https://github.com/nMaroulis/protolink/blob/main/CONTRIBUTING.md) and the [development guide](https://nmaroulis.github.io/protolink/docs/development/).

ProtoLink is available under the [MIT License](https://github.com/nMaroulis/protolink/blob/main/LICENSE).
