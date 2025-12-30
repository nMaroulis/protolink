# Protolink

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/protolink)](https://pypi.org/project/protolink/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/protolink?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=YELLOW&left_text=%E2%AC%87%EF%B8%8F)](https://pepy.tech/projects/protolink)

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="Protolink Logo" width="60%">
</div>

> 📌 The framework is currently in **alpha** and is subject to change. 

ProtoLink is a lightweight Python framework that allows you to build **autonomous, LLM-powered agents** that communicate directly, manage context, and **integrate tools seamlessly**. Build **distributed multi-agent systems** with minimal boilerplate and production-ready reliability.

Each ProtoLink agent is a **self-contained runtime** that can embed an **LLM**, manage execution context, expose and consume **tools** (native or via [MCP](https://modelcontextprotocol.io/docs/getting-started/intro)), and coordinate with other agents over a unified **transport layer**.

ProtoLink implements and extends [Google’s Agent-to-Agent (A2A)](https://a2a-protocol.org/v0.3.0/specification/?utm_source=chatgpt.com) specification for **agent identity, capability declaration, and discovery**, while **going beyond A2A** by enabling **LLM & tool integration**.

The framework emphasizes **minimal boilerplate**, **explicit control**, and **production-readiness**, making it suitable for both research and real-world systems.

> **Focus on your agent logic** - ProtoLink handles communication, authentication, LLM integration, and tool management for you.


Follow the API documentation here 📚 [documentation](https://nmaroulis.github.io/protolink/).

## Features

- **A2A Protocol Implementation**: Fully compatible with **Google's A2A specification**
- **Extended Capabilities**:
  - **Unified Client/Server Agent Model**: Single agent instance handles both client and server responsibilities, reducing complexity.
  - **Transport Layer Flexibility**: Swap between *HTTP*, *WebSocket*, *gRPC* or *in-memory* transports with minimal code changes.
  - **Simplified Agent Creation and Registration**: Create and register **autonomous AI agents** with just a few lines of code.
  - **LLM-Ready** Architecture: Native support for integrating LLMs to agents (APIs & local) directly as agent modules, allowing agents to expose LLM calls, reasoning functions, and chain-of-thought utilities with zero friction.
  - **Tooling**: **Native support** for integrating tools to agents (APIs & local) directly as agent modules. Native Adapter for **MCP tooling**.
  - **Runtime Transport Layer**: In-process agent communication using a shared memory space. Agents can easily communicate with each other within the same process, making it easier to build and test agent systems.
  - **Enhanced Security**: **OAuth 2.0** and **API key support**.
  - Built-in support for streaming and async operations.
- **Planned Integrations**:
  - **Advanced Orchestration Patterns**
    - Multi-step workflows, supervisory agents, role routing, and hierarchical control systems.

## 💡 Protolink vs Google's A2A

ProtoLink implements Google’s A2A protocol at the **wire level**, while providing a higher-level agent runtime that unifies client, server, transport, tools, and LLMs into a single composable abstraction **the Agent**.

| Concept   | Google A2A              | ProtoLink       |
| --------- | ----------------------- | --------------- |
| Agent     | Protocol-level concept  | Runtime object  |
| Transport | External server concern | Agent-owned     |
| Client    | Separate                | Built-in        |
| LLM       | Out of scope            | First-class     |
| Tools     | Out of scope            | Native + MCP    |
| UX        | Enterprise infra        | Developer-first |

### Architecture - Centralized Agent & Transport Layer Design

Protolink takes a **centralized agent** approach compared to Google's A2A protocol, which separates client and server concerns. Here's how it differs:

| Feature | Google's A2A | Protolink |
|---------|-------------|-----------|
| **Architecture** | Decoupled client/server | Unified agent with built-in client/server |
| **Transport** | Factory-based with provider pattern | Direct interface implementation |
| **Deployment** | Requires managing separate services | Single process by default, scales to distributed |
| **Complexity** | Higher (needs orchestration) | Lower (simpler to reason about) |
| **Flexibility** | Runtime configuration via providers | Code-based implementation |
| **Use Case** | Large-scale, distributed systems | Both simple and complex agent systems |

</br>
<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/agent_architecture.png" alt="Agent Architecture" width="100%">
</div>

#### Key Benefits

1. **Simplified Development**: Manage a single agent runtime without separate client/server codebases.
2. **Reduced Boilerplate**: Common functionality is handled by the base [Agent]() class, letting you focus on agent logic.
3. **Flexible Deployment**: Start with a single process, scale to distributed when needed
4. **Unified State Management**: Shared context between client and server operations
5. **Maintainability**: 
   - Direct code paths for easier debugging
   - Clear control flow with fewer abstraction layers
   - Type-safe interfaces for better IDE support
6. **Extensibility**:
   - Easily add new transport implementations
   - Simple interface-based design
   - No complex configuration needed for common use cases

## Why Protolink? 🚀
- **Real Multi-Agent Systems**: Build **autonomous agents** with embedded LLMs, tools, and memory that communicate directly.
- **Simple API**: Built from the ground-up for **minimal boilerplate**, letting you focus on agent logic rather than infrastructure.
- **Developer Friendly**: Clean abstractions and direct code paths make debugging and maintenance a breeze.
- **Production Ready**: Designed for **performance, reliability, and scalability** in real-world deployments.
- **Extensible & Interoperable**: Add new agents, transports, or protocols easily; compatible with **A2A** and **MCP** standards.
- **Community Focused**: Designed for the open-source community with clear contribution guidelines.


## Installation

### Basic Installation
This will install the base package without any optional dependencies.
```bash
# Using uv (recommended)
uv add protolink

# Using pip
pip install protolink
```

### Optional Dependencies
Protolink supports optional features through extras. Install them using square brackets:
Note: `uv add` can be replace with `pip install` if preferred.
```bash
# Install with all optional dependencies
uv add "protolink[all]"

# Install with HTTP support (for web-based agents)
uv add "protolink[http]"

# Install all the supported LLM libraries
uv add "protolink[llms]"

# For development (includes all optional dependencies and testing tools)
uv add "protolink[dev]"
```


### Development Installation
To install from source and all optional dependencies:

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink
uv pip install -e ".[dev]"
```

## Hello World Example

👉 The example found in the jupyter notebooks here: [Hello World Example](https://github.com/nMaroulis/protolink/tree/main/examples/notebooks/basic_example)


```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.tools.adapters import MCPToolAdapter
from protolink.llms.api import OpenAILLM
from protolink.discovery import Registry

# Initialize Registry for A2A Discovery
registry = Registry(url="http://127.0.0.1:9000", transport="http")
await registry.start()

# Define the agent card
agent_card = AgentCard(
    name="example_agent",
    description="A dummy agent",
    url="http://127.0.0.1:8020",
)

# OpenAI API LLM
llm = OpenAILLM(model="gpt-5.2")

# Initialize the agent
agent = Agent(agent_card, transport="http", llm=llm, registry=registry)

# Add Native tool
@agent.tool(name="add", description="Add two numbers")
async def add_numbers(a: int, b: int):
    return a + b

# Add MCP tool
mcp_tool = MCPToolAdapter(mcp_client, "multiply")
agent.add_tool(mcp_tool)


# Start the agent
await agent.start()
```

Once the Agent has been initiated, it automatically exposes a web interface at `/status` where it exposes the agent's information.

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/agent_status_card.png" alt="Agent Status Card" width="50%">
</div>

## Documentation

Follow the API documentation here: [Documentation](https://nmaroulis.github.io/protolink/)
### API Documentation

#### Transport:

For Agent-to-Agent & Agent-to-Registry communication:

- `http` · [HTTPTransport](): Uses HTTP/HTTPS for synchronous requests. Two ASGI implementations are available.
  - Lightweight: `starlette`, `httpx` & `uvicorn`
  - Advanced | Schema Validation: `fastapi`, `pydantic` & `uvicorn`
- `websocket` · [WebSocketTransport](): Uses WebSocket for streaming requests. [`websockets`]
- `grpc` · [GRPCTransport](): TBD
- `runtime` · [RuntimeTransport](): Simple **in-process, in-memory transport**.

#### LLMs:

Protolink separates LLMs into three types: `api`, `local`, and `server`.
The following are the Protolink wrappers for each type. If you want to use another model, you can use it directly without going through Protolink’s `LLM` class.

<p align="center">
  <font color="#888" size="2">[ API ]</font>   <font color="#888" size="2">[ Server ]</font>   <font color="#888" size="2">[ Local ]</font>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/openai.svg" width="45" alt="OpenAI" title="OpenAI"/>  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/anthropic_black.svg" width="45" alt="Anthropic" />  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/gemini.svg" width="45" alt="Gemini" />  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/deepseek.svg" width="45" alt="DeepSeek" />    <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/ollama_light.svg" width="45" alt="Ollama" />  <img src="https://raw.githubusercontent.com/abetlen/llama-cpp-python/main/docs/icon.svg" width="45" alt="Llama.cpp" />
</p>


- **API**, calls the API, requires an API key:
  - [OpenAILLM](https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/openai_client.py): Uses **OpenAI API** for sync & async requests.
  - [AnthropicLLM](https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/anthropic_client.py): Uses **Anthropic API** for sync & async requests.
  - [GeminiLLM](https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/gemini_client.py): Uses **Gemini API** for sync & async requests.
  - [DeepSeekLLM](https://github.com/nMaroulis/protolink/blob/main/protolink/llms/api/deepseek_client.py): Uses **DeepSeek API** for sync & async requests.
- **Local**, runs the model in runtime:
  - [LlamaCPPLLM]() - **TBD**: Uses **local runtime llama.cpp** for sync & async requests.
- **Server**, connects to an LLM Server, deployed locally or remotely:
  - [OllamaLLM](https://github.com/nMaroulis/protolink/blob/main/protolink/llms/server/ollama_client.py): Uses **Ollama** for sync & async requests.

#### Tools:

- [Native Tool](https://github.com/nMaroulis/protolink/blob/main/protolink/tools/tool.py): Uses native tools.
- [MCPToolAdapter](https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp.py) - **TBD**: Connects to MCP Server and registers MCP tools as native tools.


## License

MIT

## Contributing

All contributions are more than welcome! Please see [CONTRIBUTING.md](https://github.com/nMaroulis/protolink/blob/main/CONTRIBUTING.md) for more information.