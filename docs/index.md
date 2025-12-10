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

## Contents

- [Getting Started](getting-started.md)
- [Agents](agents.md)
- [Transports](transports.md)
- [LLMs](llms.md)
- [Tools](tools.md)
- [Examples](examples.md)

## What you can do with Protolink

- **Build agents quickly**  
  See [Getting Started](getting-started.md) and [Agents](agents.md) for the core concepts and basic setup.

- **Choose your transport**  
  Explore [Transports](transports.md) to switch between HTTP, WebSocket, runtime, and future transports with minimal code changes.

- **Plug in LLMs & tools**  
  Use [LLMs](llms.md) and [Tools](tools.md) to wire in language models and both native & MCP tools as agent modules.

## Overview

Protolink is a lightweight, production‑ready framework for **agent‑to‑agent communication**, built around and extending Google’s A2A protocol.

Key ideas:

- **Unified Agent model**: a single `Agent` instance handles both client and server responsibilities.
- **Flexible transports**: HTTP, WebSocket, in‑process runtime, and planned JSON‑RPC / gRPC transports.
- **LLM‑ready architecture**: first‑class integration with API, local, and server‑hosted LLMs.
- **Tools as modules**: native Python tools and MCP tools plugged directly into agents.

Use this documentation to:

- Install Protolink and run your first agent.
- Understand how agents, transports, LLMs, and tools fit together.
- Explore practical examples you can adapt to your own systems.

---

_Protolink is open source under the MIT license. Contributions are welcome – see the repository’s **Contributing** section on GitHub._

