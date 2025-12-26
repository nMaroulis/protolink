<style>
.md-content .md-typeset h1 { display: none; }
</style>
<!-- SEO: Protolink - Agent-to-Agent Communication Framework | Lightweight Production-Ready A2A Protocol Extension -->
<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="Protolink Logo" width="80%">
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
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/protolink?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=YELLOW&left_text=%E2%AC%87%EF%B8%8F)](https://pepy.tech/projects/protolink)

## Contents

### Overview
- [Concept](concept.md)
- [Getting Started](getting-started.md)

### API Reference
- [Agent](agent.md)
- [Client](client.md)
- [LLM](llm.md)
- [Models](models.md)
- [Registry](registry.md)
- [Server](server.md)
- [Tool](tool.md)
- [Transport](transport.md)
- [Types](types.md)

### Examples
- [Examples](examples.md)

### Resources
- [Relevant Projects](relevant.md)

## What is Protolink ?

ProtoLink is a lightweight, production-ready Python framework for building **distributed multi-agent systems** where AI agents **communicate directly with each other**.

Each ProtoLink agent is a **self-contained runtime** that can embed an **LLM**, manage execution context, expose and consume **tools** (native or via [MCP](https://modelcontextprotocol.io/docs/getting-started/intro)), and coordinate with other agents over a unified **transport layer**.

ProtoLink implements and extends [Google’s Agent-to-Agent (A2A)](https://a2a-protocol.org/v0.3.0/specification/?utm_source=chatgpt.com) specification for **agent identity, capability declaration, and discovery**, while **going beyond A2A** by enabling **true agent-to-agent collaboration**.

The framework emphasizes **minimal boilerplate**, **explicit control**, and **production-readiness**, making it suitable for both research and real-world systems.


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


## Key ideas:

- **Unified Agent model**: a single autonomous `AI Agent` instance handles both client and server responsibilities, incorporating LLMs and tools.
- **Flexible transports**: HTTP, WebSocket, in‑process runtime, and planned JSON‑RPC / gRPC transports.
- **LLM‑ready architecture**: first‑class integration with API, local, and server‑hosted LLMs.
- **Tools as modules**: native Python tools and MCP tools plugged directly into agents.

Use this documentation to:

- Install Protolink and run your first agent.
- Understand how agents, transports, LLMs, and tools fit together.
- Explore practical examples you can adapt to your own systems.

---

_Protolink is open source under the MIT license. Contributions are welcome – see the repository’s **Contributing** section on GitHub._

