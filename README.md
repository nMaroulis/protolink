# Protolink

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/protolink)](https://pypi.org/project/protolink/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/protolink?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=YELLOW&left_text=%E2%AC%87%EF%B8%8F)](https://pepy.tech/projects/protolink)

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="Protolink Logo" width="60%">
</div>

> 📌 The framework is currently in **alpha** and is subject to change. 


ProtoLink is a lightweight Python framework that allows you to build **autonomous, LLM-powered agents** that communicate directly, manage context, and **integrate tools seamlessly**. Build **distributed multi-agent systems** with minimal boilerplate and production-oriented architecture.

Each ProtoLink agent is a **self-contained runtime** that can embed an **LLM**, manage execution context, expose and consume **tools** (native or via [MCP](https://modelcontextprotocol.io/docs/getting-started/intro)), and coordinate with other agents over a unified **transport layer**.

ProtoLink implements and extends [Google’s Agent-to-Agent (A2A)](https://a2a-protocol.org/v0.3.0/specification/?utm_source=chatgpt.com) specification for **agent identity, capability declaration, and discovery**, while **going beyond A2A** by enabling **LLM & tool integration**.

#### 🎯 The Philosophy

The framework emphasizes **minimal boilerplate**, **explicit control**, and **production-readiness**, making it suitable for both research and real-world systems.

**Tool Execution**, **Agent calling**, and **LLM invocation** are all provided by Protolink. No need to care on how to call tools or other agent's, ProtoLink handles it for you, through **predefined LLM prompts** that provide the **Agent's LLM** the ability to **interact with its environment**, leaving only the logic to you.

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
- **Production Oriented**: Designed for **performance, reliability, and scalability** in real-world deployments.
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

Once the **Agent** and **Registry** objects have been initiated, they will automatically expose a web interface at `/status` where they display the registry and agent's information.

<table>
  <tr style="border: none;">
    <td style="text-align: center; border: none;">
      <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/registry_status_card.png" alt="Registry Status Card" width="100%">
    </td>
    <td style="text-align: center; border: none;">
      <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/agent_status_card.png" alt="Agent Status Card" width="100%">
    </td>
  </tr>
</table>

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


#### How Protolink Eliminates LLM Orchestration Boilerplate

Protolink treats agentic systems as **distributed programs**, not probabilistic workflows.  
Every interaction between models, tools, and agents is expressed as an explicit, typed action with deterministic execution semantics. The goal is to replace emergent behavior and prompt-driven control flow with **inspectable, replayable, and verifiable computation**, while preserving the expressive power of modern LLMs.

Protolink provides a **deterministic execution layer** for LLMs, tools, and agents, allowing users to focus purely on business logic instead of orchestration glue.

Building agentic systems usually means wrestling with tool-calling prompts, JSON schemas, output parsing, routing between agents, retries, and error handling. This boilerplate is repetitive, fragile, and completely orthogonal to the problem you actually want to solve.

Protolink removes that complexity by standardizing all interactions through a small set of explicit primitives:

- **Task** — a shared unit of work
- **Message** — communication within a task
- **Part** — an atomic, machine-interpretable action or result

Agents never infer behavior implicitly. Instead, they declare intent explicitly using structured Parts such as:

- **tool_call** — execute a local tool
- **agent_call** — delegate work to another agent
- **infer** — invoke LLM reasoning
- **text** — return user-facing output

and more...

From there, the runtime handles everything deterministically.

#### Zero-Boilerplate LLM → Tool → Agent Flow

You do **not** need to:

- Prompt the LLM to decide when to **call tools**
- **Parse** raw LLM text or JSON
- Write **routing** or **delegation logic**
- Implement planners, routers, or state machines

The runtime automatically:

- Builds structured system prompts
- Injects tool schemas and agent capabilities
- Enforces strict output contracts
- Executes declared actions deterministically

Tool calls, agent calls, and LLM invocations only happen when explicitly declared.
All results are returned as structured Parts — no hidden side effects, no magic.
From the user’s perspective:

```python
task = Task.create(
    Message.user("What's the weather in Geneva?")
)
```
That’s it.

#### Deterministic by Design

This is not a black-box agent framework.
- No hidden reasoning
- No implicit planning
- No speculative execution

Every action is **explicit, inspectable, and replayable**.

If a tool runs, you see a `tool_call`.
If an agent is contacted, you see an `agent_call`.
If an LLM is invoked, you see an `infer`.

This makes the system predictable, debuggable, composable, and production-ready.

#### LLM-Agnostic and Provider-Independent

The runtime is **fully LLM-agnostic**.
Any model — **API-based, self-hosted, or local** can be swapped in without changing behavior or results. OpenAI, Anthropic, local servers, or custom backends all operate through the same unified execution model.

The orchestration stays the same.
The contracts stay the same.
Only the model changes.

This lets you evolve providers, costs, latency, or deployment strategy without rewriting your agents.


## Task, Message, Artifact, and Part in the Agent System

This project uses a structured, Agent-to-Agent (A2A) style communication model. Understanding how **Tasks**, **Messages**, **Artifacts**, and **Parts** interact is key to using the agent effectively.

### Concepts

### 1. Task
A **Task** represents a unit of work or a conversation thread between agents.  
- It contains **Messages** and **Artifacts**.
- Tracks **metadata** such as state (`submitted`, `working`, `completed`) and execution history.
- Tasks are sent between agents; each agent executes what is explicitly defined in the task.

### 2. Message
A **Message** is a communicative unit in a task.
- Can be sent by a user or an agent.
- Contains **Parts** representing atomic content.
- Example roles:
  - `"user"` — input from a human or another agent
  - `"agent"` — output from an agent

### 3. Artifact
An **Artifact** is a container for outputs generated by the agent.
- Stores **Parts** that result from executing a tool (**tool_call**) or an LLM inference (**infer**).
- Can include tool results, reasoning traces, or structured outputs.
- Artifacts allow agents to append results without modifying the original message.

### 4. Part
A **Part** is the atomic content of a Message or Artifact.
- Defines **what to do** or **what was produced**.
- Example Part types (`PartType`):
  - `"text"`: plain text content
  - `"json"`: structured data
  - `"tool_call"`: request to execute a registered tool
  - `"tool_output"`: result outputfrom executing a tool
  - `"infer"`: input to invoke the agent's LLM
  - `"status"`, `"error"`, `"image"`, `"audio"`, etc.

### Communication Flow

1. **Task Creation**  
   A user or agent creates a `Task` with a `Message` containing one or more `Parts`.

2. **Task Execution**  
   - The receiving agent inspects the **last message or artifact** in the task.
   - Executes each `Part` sequentially:
     - `tool_call` → executes a registered tool → produces `tool_output` Part in an Artifact.
     - `infer` → invokes the agent's LLM → produces `infer_output` Part in an Artifact.

3. **Appending Outputs**  
   - Results are appended to the Task as new **Artifacts**.
   - Lifecycle state transitions (`working`, `completed`, `failed`) are updated in the Task metadata.

4. **Sequential Processing**  
   - Tasks are processed sequentially at the message/artifact level.
   - Parallel execution is possible **within the parts of a single message/artifact**, but not across multiple messages/artifacts in the same task.

#### Simple Example

```python
from protolink.models import Message, Part, Task

# 1️⃣ User creates a Task with a message containing a Part
task = Task.create(Message.user("What's the weather in Athens?"))

# 2️⃣ Add a tool call Part
tool_part = Part.tool_call(tool_name="weather_api", args={"city": "Athens"})
task.add_message(Message.agent(parts=[tool_part]))

# 3️⃣ Agent executes the task
result_task = await agent.execute_task(task)

# 4️⃣ Outputs are appended as artifacts
for artifact in result_task.artifacts:
    for part in artifact.parts:
        if part.type == "tool_output":
            print("Tool Output:", part.content)

# 5️⃣ If needed, a infer Part can trigger the agent's LLM
infer_part = Part.infer(prompt="Summarize today's weather in Athens")
task.add_message(Message.agent(parts=[infer_part]))
result_task = await agent.execute_task(task)
```

**Key Notes:**

- Each `Task` maintains the full history of messages and artifacts.
- Agents execute the **last message or artifact** to determine the next action.
- Parts inside a message or artifact can be executed in parallel if needed.
- Agents **do not guess intent**; they execute exactly what is defined in the Parts.

This structured approach ensures predictable, deterministic agent behavior while still supporting multi-step interactions and LLM/tool execution.



## License

MIT

## Contributing

All contributions are more than welcome! Please see [CONTRIBUTING.md](https://github.com/nMaroulis/protolink/blob/main/CONTRIBUTING.md) for more information.