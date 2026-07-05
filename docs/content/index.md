# Documentation

{/* SEO: Protolink - Agent-to-Agent Communication Framework | Lightweight Production-Ready A2A Protocol Extension | Python Library | AI Agents | LLMs | Tools | Multi-Agent Systems | Distributed Computing */}

<div className="centered-media">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="Protolink Logo" width="60%" />
</div>

> A lightweight, production-ready framework for **agent-to-agent communication**, built on and extending Google's A2A protocol.

<div className="doc-button-row">
  <a className="doc-button primary" href="getting-started">Get Started</a>
  <a className="doc-button" href="https://github.com/nMaroulis/protolink">View on GitHub</a>
</div>

---

Welcome to the Protolink documentation.

This site provides an overview of the framework, its concepts, and how to use it in your projects.

_Current release: see [protolink on PyPI](https://pypi.org/project/protolink/)._ 

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/protolink)](https://pypi.org/project/protolink/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/protolink?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=YELLOW&left_text=%E2%AC%87%EF%B8%8F)](https://pepy.tech/projects/protolink)

## Find Your Path

<div className="docs-compass">
  <a className="docs-compass-feature" href="getting-started">
    <span>Start here</span>
    <strong>Getting Started</strong>
    <p>Install ProtoLink, create a first agent, and use the CLI starter when you want a runnable local entry point.</p>
  </a>

  <div className="docs-compass-panel">
    <div className="docs-compass-heading">
      <span>Understand</span>
      <strong>Architecture and runtime model</strong>
    </div>
    <div className="docs-link-list">
      <a href="concept">Concept</a>
      <a href="whitepaper">Whitepaper</a>
      <a href="runtime">Runtime</a>
      <a href="flows">Flows</a>
    </div>
  </div>

  <div className="docs-compass-panel">
    <div className="docs-compass-heading">
      <span>Build</span>
      <strong>Agents, tools, models, and transports</strong>
    </div>
    <div className="docs-link-list">
      <a href="agent">Agent</a>
      <a href="llm">LLM</a>
      <a href="tool">Tool</a>
      <a href="transport">Transport</a>
      <a href="client">Client</a>
      <a href="server">Server</a>
    </div>
  </div>

  <div className="docs-compass-panel">
    <div className="docs-compass-heading">
      <span>Operate</span>
      <strong>State, registry, telemetry, and local inspection</strong>
    </div>
    <div className="docs-link-list">
      <a href="cli">CLI</a>
      <a href="devtools">Developer Tools</a>
      <a href="registry">Registry</a>
      <a href="state">State</a>
      <a href="storage">Storage</a>
      <a href="telemetry">Telemetry</a>
    </div>
  </div>

  <div className="docs-compass-panel">
    <div className="docs-compass-heading">
      <span>Reference</span>
      <strong>Schemas, security, examples, and project material</strong>
    </div>
    <div className="docs-link-list">
      <a href="models">Models</a>
      <a href="types">Types</a>
      <a href="authentication">Authentication</a>
      <a href="examples">Examples</a>
      <a href="llm_examples">LLM Usage</a>
      <a href="ticket_booking_example">Ticket Booking</a>
      <a href="code_assistant_example">Code Assistant</a>
      <a href="development">Development</a>
      <a href="changelog">Changelog</a>
      <a href="relevant">Related Projects</a>
    </div>
  </div>
</div>


## What is Protolink?

ProtoLink is a lightweight, production-ready Python framework for building **distributed multi-agent systems** where AI agents **communicate directly with each other**.

Each ProtoLink agent is a **self-contained runtime** that can embed an **LLM**, manage execution context, expose and consume **tools** (native or via [MCP](https://modelcontextprotocol.io/docs/getting-started/intro)), and coordinate with other agents over a unified **transport layer**.

ProtoLink implements and extends [Google's Agent-to-Agent (A2A)](https://a2a-protocol.org/v0.3.0/specification/) specification for **agent identity, capability declaration, and discovery**, while **going beyond A2A** by enabling **true agent-to-agent collaboration**.

The framework emphasizes **minimal boilerplate**, **explicit control**, and **production-readiness**, making it suitable for both research and real-world systems.

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

Unlike the base A2A specifications, Protolink enables **more open and flexible communication**: agents can call another agent's LLM for reasoning, invoke its tools directly, or define custom communication schemes. This creates a **flexible mesh** where specialized agents leverage each other's native capabilities without rigid orchestration bottlenecks.


## Protolink vs Google A2A 💡

ProtoLink implements Google’s A2A protocol at the **wire level**, while providing a higher-level agent runtime that unifies client, server, transport, tools, and LLMs into a single composable abstraction **the Agent**.

| Concept   | Google A2A              | ProtoLink       |
| --------- | ----------------------- | --------------- |
| Agent     | Protocol-level concept  | Runtime object  |
| Transport | External server concern | Agent-owned     |
| Client    | Separate                | Built-in        |
| LLM       | Out of scope            | First-class     |
| Tools     | Out of scope            | Native + MCP    |
| UX        | Enterprise infra        | Developer-first |



## What you can do with Protolink

- **Build agents quickly**  
  See [Getting Started](getting-started.md) and [Agents](agent.md) for the core concepts and basic setup.

- **Choose your transport**  
  Explore [Transports](transport.md) to switch between HTTP, SSE JSON-RPC streaming, WebSocket, and in-process runtime transports with minimal code changes.

- **Plug in LLMs & tools**  
  Use [LLMs](llm.md) and [Tools](tool.md) to wire in language models and both native & MCP tools as agent modules.


## Key ideas

- **Unified Agent model**: a single autonomous `AI Agent` instance handles both client and server responsibilities, incorporating LLMs and tools.
- **Flexible transports**: HTTP, SSE JSON-RPC streaming, WebSocket, and in-process runtime transports. The `grpc` type is reserved for future support, but it is not registered in the default transport factory yet.
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
