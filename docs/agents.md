# Agents

Agents are the core building blocks in Protolink.

## Concepts

An **Agent** in Protolink is a unified component that can act as both **client and server**. This is different from the original A2A spec, which separates client and server concerns.

High‑level ideas:

- **Unified model**: a single `Agent` instance can send and receive messages.
- **AgentCard**: a small model describing the agent (name, description, metadata).
- **Modules**:
  - **LLMs** (e.g. `OpenAILLM`, `AnthropicLLM`, `LlamaCPPLLM`, `OllamaLLM`).
  - **Tools** (native Python functions or MCP‑backed tools).
- **Transport abstraction**: agents communicate over transports such as HTTP, WebSocket, gRPC, or the in‑process runtime transport.

## Creating an Agent

A minimal agent consists of three pieces:

1. An `AgentCard` describing the agent.
2. A `Transport` implementation.
3. An optional LLM and tools.

Example:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPTransport
from protolink.llms.api import OpenAILLM


agent_card = AgentCard(
    name="example_agent",
    description="A dummy agent",
)

transport = HTTPTransport()
llm = OpenAILLM(model="gpt-5.1")

agent = Agent(agent_card, transport, llm)
```

You can then attach tools and start the agent.

## Agent-to-Agent Communication

Agents communicate over a chosen transport.

Common patterns:

- **RuntimeTransport**: multiple agents in the same process share an in‑memory transport, which is ideal for local testing and composition.
- **HTTPTransport / WebSocketTransport**: agents expose HTTP or WebSocket endpoints so that other agents (or external clients) can send requests.
- **gRPC / JSON‑RPC (planned)**: additional transports for more structured or high‑performance communication.

From the framework’s perspective, all of these are implementations of the same transport interface, so you can swap them with minimal code changes.

