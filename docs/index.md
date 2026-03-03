<style>
.md-content .md-typeset h1 { display: none; }
</style>
<!-- SEO: Protolink - Agent-to-Agent Communication Framework | Lightweight Production-Ready A2A Protocol Extension | Python Library | AI Agents | LLMs | Tools | Multi-Agent Systems | Distributed Computing -->
<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="Protolink Logo" width="60%">
</div>
> A lightweight, production-ready framework for **agent-to-agent communication**, built on and extending Google's A2A protocol.

[Get Started](getting-started.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/nMaroulis/protolink){ .md-button }

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

## Contents

<div class="nav-grid">
  <div class="nav-item">
    <div class="nav-emoji">📚</div>
    <div class="nav-content">
      <a href="concept">Concept</a>
      <div class="nav-desc">Core concepts and architecture</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🚀</div>
    <div class="nav-content">
      <a href="getting-started">Getting Started</a>
      <div class="nav-desc">Quick start guide and setup</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🤖</div>
    <div class="nav-content">
      <a href="agent">Agent</a>
      <div class="nav-desc">Agent implementation and lifecycle</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🌐</div>
    <div class="nav-content">
      <a href="client">Client</a>
      <div class="nav-desc">HTTP client and communication</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🧠</div>
    <div class="nav-content">
      <a href="llm">LLM</a>
      <div class="nav-desc">Large Language Model integrations</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🗂️</div>
    <div class="nav-content">
      <a href="models">Models</a>
      <div class="nav-desc">Data models and schemas</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🗃️</div>
    <div class="nav-content">
      <a href="registry">Registry</a>
      <div class="nav-desc">Agent discovery and registration</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🌐</div>
    <div class="nav-content">
      <a href="server">Server</a>
      <div class="nav-desc">Server implementations</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🔧</div>
    <div class="nav-content">
      <a href="tool">Tool</a>
      <div class="nav-desc">Tool system and adapters</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🌐</div>
    <div class="nav-content">
      <a href="transport">Transport</a>
      <div class="nav-desc">Communication layers</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🗂️</div>
    <div class="nav-content">
      <a href="types">Types</a>
      <div class="nav-desc">Type definitions and aliases</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">💡</div>
    <div class="nav-content">
      <a href="examples">Examples</a>
      <div class="nav-desc">Code examples and tutorials</div>
    </div>
  </div>
  <div class="nav-item">
    <div class="nav-emoji">🔗</div>
    <div class="nav-content">
      <a href="relevant">Relevant Projects</a>
      <div class="nav-desc">Related tools and projects</div>
    </div>
  </div>
</div>

<style>
.nav-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.5rem;
  margin: 1.5rem 0;
}

.nav-item {
  padding: 0.75rem 1rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-left: 4px solid #cbd5e1;
  border-radius: 6px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.nav-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
  z-index: -1;
}

.nav-item:hover {
  border-left-color: #3b82f6;
  border-color: #bfdbfe;
  transform: translateY(-2px);
  box-shadow: 0 4px 20px rgba(59, 130, 246, 0.1);
}

.nav-item:hover::before {
  opacity: 1;
}

.nav-emoji {
  font-size: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(148, 163, 184, 0.1);
  border-radius: 6px;
  transition: all 0.3s ease;
  flex-shrink: 0;
}

.nav-item:hover .nav-emoji {
  background: rgba(59, 130, 246, 0.1);
  transform: scale(1.1);
}

.nav-content {
  flex: 1;
  min-width: 0;
}

.nav-item a {
  color: #334155;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.75rem;
  transition: color 0.3s ease;
  display: block;
  margin-bottom: 0.15rem;
}

.nav-item:hover a {
  color: #1e40af;
}

.nav-desc {
  color: #64748b;
  font-size: 0.6rem;
  line-height: 1.3;
  transition: color 0.3s ease;
}

.nav-item:hover .nav-desc {
  color: #475569;
}

/* Add subtle gradient backgrounds for different sections */
.nav-item:nth-child(1), .nav-item:nth-child(2) {
  border-left-color: #8b5cf6;
}

.nav-item:nth-child(1):hover, .nav-item:nth-child(2):hover {
  border-left-color: #7c3aed;
  box-shadow: 0 4px 20px rgba(139, 92, 246, 0.1);
}

.nav-item:nth-child(1):hover .nav-emoji, .nav-item:nth-child(2):hover .nav-emoji {
  background: rgba(139, 92, 246, 0.1);
}

.nav-item:nth-child(3), .nav-item:nth-child(4), .nav-item:nth-child(5), 
.nav-item:nth-child(6), .nav-item:nth-child(7), .nav-item:nth-child(8), 
.nav-item:nth-child(9), .nav-item:nth-child(10), .nav-item:nth-child(11) {
  border-left-color: #06b6d4;
}

.nav-item:nth-child(3):hover, .nav-item:nth-child(4):hover, .nav-item:nth-child(5):hover,
.nav-item:nth-child(6):hover, .nav-item:nth-child(7):hover, .nav-item:nth-child(8):hover,
.nav-item:nth-child(9):hover, .nav-item:nth-child(10):hover, .nav-item:nth-child(11):hover {
  border-left-color: #0891b2;
  box-shadow: 0 4px 20px rgba(6, 182, 212, 0.1);
}

.nav-item:nth-child(3):hover .nav-emoji, .nav-item:nth-child(4):hover .nav-emoji, 
.nav-item:nth-child(5):hover .nav-emoji, .nav-item:nth-child(6):hover .nav-emoji, 
.nav-item:nth-child(7):hover .nav-emoji, .nav-item:nth-child(8):hover .nav-emoji, 
.nav-item:nth-child(9):hover .nav-emoji, .nav-item:nth-child(10):hover .nav-emoji, 
.nav-item:nth-child(11):hover .nav-emoji {
  background: rgba(6, 182, 212, 0.1);
}

.nav-item:nth-child(12) {
  border-left-color: #10b981;
}

.nav-item:nth-child(12):hover {
  border-left-color: #059669;
  box-shadow: 0 4px 20px rgba(16, 185, 129, 0.1);
}

.nav-item:nth-child(12):hover .nav-emoji {
  background: rgba(16, 185, 129, 0.1);
}

.nav-item:nth-child(13) {
  border-left-color: #f59e0b;
}

.nav-item:nth-child(13):hover {
  border-left-color: #d97706;
  box-shadow: 0 4px 20px rgba(245, 158, 11, 0.1);
}

.nav-item:nth-child(13):hover .nav-emoji {
  background: rgba(245, 158, 11, 0.1);
}

@media (max-width: 768px) {
  .nav-grid {
    grid-template-columns: 1fr;
    gap: 0.4rem;
  }
  
  .nav-item {
    padding: 0.625rem 0.875rem;
  }
  
  .nav-item:hover {
    transform: translateY(-1px);
  }
  
  .nav-emoji {
    width: 24px;
    height: 24px;
    font-size: 1.1rem;
  }
  
  .nav-item a {
    font-size: 0.85rem;
  }
  
  .nav-desc {
    font-size: 0.7rem;
  }
}
</style>

## What is Protolink ?

ProtoLink is a lightweight, production-ready Python framework for building **distributed multi-agent systems** where AI agents **communicate directly with each other**.

Each ProtoLink agent is a **self-contained runtime** that can embed an **LLM**, manage execution context, expose and consume **tools** (native or via [MCP](https://modelcontextprotocol.io/docs/getting-started/intro)), and coordinate with other agents over a unified **transport layer**.

ProtoLink implements and extends [Google’s Agent-to-Agent (A2A)](https://a2a-protocol.org/v0.3.0/specification/?utm_source=chatgpt.com) specification for **agent identity, capability declaration, and discovery**, while **going beyond A2A** by enabling **true agent-to-agent collaboration**.

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

In Protolink, an Agent is an **autonomous, centralized object** that serves as the core unit of your system. It is designed to be **fully modular** so you can **plug in** any LLM, Tools, Transport, Storage, OpenTelemetry, and Authentication stack you need.

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
  Explore [Transports](transport.md) to switch between HTTP, WebSocket, runtime, and future transports with minimal code changes.

- **Plug in LLMs & tools**  
  Use [LLMs](llm.md) and [Tools](tool.md) to wire in language models and both native & MCP tools as agent modules.


## Key ideas

- **Unified Agent model**: a single autonomous `AI Agent` instance handles both client and server responsibilities, incorporating LLMs and tools.
- **Flexible transports**: HTTP, WebSocket, in‑process runtime, and planned JSON‑RPC / gRPC transports. Change one line of code to switch protocols.
- **LLM‑ready architecture**: first‑class integration with API, local, and server‑hosted LLMs.
- **Tools as modules**: native Python tools and MCP tools plugged directly into agents. Import tools from thousands of existing MCP servers instantly.
- **Resilience by design**: by decoupling the Brain (LLM) from the Body (Agent), you are immune to provider outages or pricing changes.
- **Developer freedom**: the pluggable architecture means you own your stack. No vendor lock-in, no framework constraints—just clean, composable components.

Use this documentation to:

- Install Protolink and run your first agent.
- Understand how agents, transports, LLMs, and tools fit together.
- Explore practical examples you can adapt to your own systems.

---

_Protolink is open source under the MIT license. Contributions are welcome – see the repository’s **Contributing** section on GitHub._

