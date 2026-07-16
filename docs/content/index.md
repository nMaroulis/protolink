import ProjectMap from '@site/src/components/ProjectMap';

# Documentation

{/* SEO: Protolink - Lightweight Python Agent Runtime | A2A 1.0 JSON-RPC Adapter | AI Agents | LLMs | Tools | Multi-Agent Systems */}

<div className="centered-media">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="Protolink Logo" width="60%" />
</div>

> A lightweight, [**A2A**](https://a2a-protocol.org/latest/specification/)-first Python runtime for autonomous, pluggable agents, with progressive control from local meshes to a versioned A2A 1.0 JSON-RPC boundary.

<div className="doc-button-row">
  <a className="doc-button primary" href="getting-started">Get Started</a>
  <a className="doc-button" href="https://github.com/nMaroulis/protolink">View on GitHub</a>
</div>

---

Welcome to the Protolink documentation.

This site provides an overview of the framework, its concepts, and how to use it in your projects.

_Current release: **0.6.6** ([PyPI](https://pypi.org/project/protolink/) | [Changelog](changelog))._

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Current Version](https://img.shields.io/badge/current-0.6.6-0A84FF)](https://pypi.org/project/protolink/)
[![PyPI version](https://img.shields.io/pypi/v/protolink)](https://pypi.org/project/protolink/)
[![GitHub stars](https://img.shields.io/github/stars/nMaroulis/protolink?style=flat&logo=github)](https://github.com/nMaroulis/protolink/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/nMaroulis/protolink?style=flat&logo=github)](https://github.com/nMaroulis/protolink/forks)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/protolink?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=YELLOW&left_text=%E2%AC%87%EF%B8%8F)](https://pepy.tech/projects/protolink)

## What is Protolink?

ProtoLink is a lightweight, production-ready Python framework for building **distributed multi-agent systems** where autonomous agents **communicate directly through an A2A-based task model**.

Each ProtoLink agent is a **self-contained runtime** that can embed an **LLM**, manage execution context, expose and consume **tools** (built-in, native, or via [MCP](https://modelcontextprotocol.io/docs/getting-started/intro)), and coordinate with other agents over a unified **transport layer**.

ProtoLink is **A2A-first by design**. `AgentCard`, `Task`, `Message`, `Part`, `Artifact`, task lifecycle, and discovery form the shared language used across agents, flows, storage, telemetry, and transports. ProtoLink builds the pluggable execution runtime around that foundation: LLMs, local models, built-in, native, and MCP tools, transports, registry discovery, state, policy, authentication, logging, and observability.

These Python models are ergonomic runtime forms of A2A's core primitives, not copies of the canonical wire schema. An HTTP agent opts into the versioned [A2A 1.0](https://a2a-protocol.org/latest/specification/) JSON-RPC boundary with `Agent(..., a2a=True)`. The flag adds standard inbound routes and outbound translation without removing ProtoLink's native API. Its exact scope, pinned TCK instructions, and current verification result are documented on the [A2A compatibility page](a2a.md).

The framework emphasizes **minimal boilerplate**, **explicit control**, and **production-readiness**, making it suitable for both research and real-world systems.

:::tip[Simple API, progressive control]

ProtoLink keeps the common path intentionally small: `Agent(card=card, transport="http")` is enough to start prototyping with safe transport defaults. When a deployment needs TLS, limits, retries, or protocol-specific behavior, construct the transport explicitly and pass the completed object to `Agent`, `AgentClient`, or `Registry`. This preserves fast iteration without hiding or flattening advanced infrastructure control.

Read the [API design philosophy](concept.md#api-design-progressive-control) or jump to the [transport configuration guide](transport.md#production-configuration).

:::

## Find Your Path

<ProjectMap />

---

## Why Protolink?

The landscape of AI agents is shifting, from monolithic scripts driven by a single model, towards **Multi-Agent Systems** where specialized, autonomous agents collaborate to solve complex problems.

But today's frameworks often trap you in a **walled garden**:

- 🔒 **Locked into a specific LLM** (OpenAI, Anthropic, etc.)
- 🔒 **Locked into a specific Transport** for communication
- 🔒 **Locked into specific Tooling** schemes
- 🔒 **Agents are just functions**, not independent entities

**Protolink breaks free from this model.**

In Protolink, an Agent is an **autonomous, centralized object** that serves as the core unit of your system. It is designed to be **fully modular** so you can **plug in** any LLM, tools, transport, storage, telemetry, and authentication stack you need.

> **Care only about the logic.** Leave the communication, agent lifecycle, inference, tooling, authentication, memory, and logging to Protolink.

ProtoLink agents can delegate tasks, call tools, run model inference, or use deterministic flows through one runtime contract. This creates a **flexible mesh** where specialized agents collaborate without requiring a central orchestration service.

## A2A at the core; A2A 1.0 on the wire 💡

ProtoLink provides a higher-level runtime that unifies client, server, transport, tools, and LLMs in one composable `Agent`. With `transport="http", a2a=True`, its A2A 1.0 adapters perform inbound and outbound wire translation; internal task models and native transports are not presented as the A2A wire format. `protocol="auto"` prefers the full ProtoLink contract when a peer offers both and selects A2A for an A2A-only peer. See [A2A compatibility](a2a.md) for the tested binding and evidence.

| Concern | Native ProtoLink runtime | A2A 1.0 adapter |
| --- | --- | --- |
| Agent logic | `handle_task(Task) -> Task` | Unchanged |
| Communication | Runtime, HTTP, SSE, WebSocket, or gRPC | JSON-RPC over HTTP |
| Discovery | ProtoLink registry and native card | Standard Agent Card endpoint |
| Models | Runtime-optimized Python types | Canonical A2A JSON translation |
| Activation | Default | Explicit `a2a=True` on HTTP |
| Verification | ProtoLink test suite | Official pinned TCK |



## What you can do with Protolink

- **Build agents quickly**  
  See [Getting Started](getting-started.md) and [Agents](agent.md) for the core concepts and basic setup.

- **Choose your transport**  
  Explore [Transports](transport.md) to switch between HTTP, SSE JSON-RPC streaming, WebSocket, gRPC, and in-process runtime transports with minimal code changes.

- **Plug in LLMs & tools**  
  Use [LLMs](llm.md) and [Tools](tool.md) to wire in language models and opt-in built-in, native, or MCP tools as agent modules.


## Key ideas

- **A2A-first runtime model**: cards, tasks, messages, parts, artifacts, task states, and discovery are the shared language of the system.
- **Unified Agent model**: a single autonomous `AI Agent` instance handles both client and server responsibilities, incorporating LLMs and tools.
- **Flexible transports**: HTTP, SSE JSON-RPC streaming, WebSocket, gRPC, and in-process runtime transports.
- **LLM‑ready architecture**: first‑class integration with API, local, and server‑hosted LLMs.
- **Tools as modules**: native Python tools and MCP tools plugged directly into agents. Import tools from thousands of existing MCP servers instantly.
- **Resilience by design**: by decoupling the Brain (LLM) from the Body (Agent), you are immune to provider outages or pricing changes.
- **State Management**: Unified persistence for conversation history, tool state, task metadata, and flow context across multiple sessions.
- **Developer freedom**: the pluggable architecture means you own your stack. No vendor lock-in, no framework constraints, just clean, composable components.

Use this documentation to:

- Install Protolink and run your first agent.
- Understand how agents, transports, LLMs, and tools fit together.
- Explore practical examples you can adapt to your own systems.

---

_Protolink is open source under the MIT license. Contributions are welcome – see the repository’s **Contributing** section on GitHub._
