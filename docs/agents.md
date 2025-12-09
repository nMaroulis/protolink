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

---

# Agent API Reference

This section provides a detailed API reference for the `Agent` base class in `protolink.agents.base`. The `Agent` class is the core component for creating A2A-compatible agents, serving as both client and server.

!!! info "Unified Agent Model"
    Unlike the original A2A specification, Protolink's `Agent` combines client and server functionality in a single class. You can send tasks/messages to other agents while also serving incoming requests.

## Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `card` | `AgentCard` | — | **Required.** The agent's metadata card containing name, description, and other identifying information. |
| `llm` | `LLM \| None` | `None` | Optional language model instance for AI-powered task processing. |
| `transport` | `Transport \| None` | `None` | Optional transport for communication. If not provided, you must set one later via `set_transport()`. |
| `auth_provider` | `AuthProvider \| None` | `None` | Optional authentication provider for securing agent communications. |

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPTransport
from protolink.llms.api import OpenAILLM

card = AgentCard(name="my_agent", description="Example agent")
llm = OpenAILLM(model="gpt-4")
transport = HTTPTransport()

agent = Agent(card=card, llm=llm, transport=transport)
```

## Lifecycle Methods

These methods control the agent's server component lifecycle.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `start()` | — | `None` | Starts the agent's server component if a transport is configured. |
| `stop()` | — | `None` | Stops the agent's server component and cleans up resources. |

!!! warning "Transport Required"
    The `start()` method requires a transport to be configured. If no transport was provided during construction, call `set_transport()` first.

## Transport Management

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `set_transport()` | `transport: Transport` | `None` | Sets or updates the transport used by this agent. |
| `client` (property) | — | `AgentClient` | Returns the client instance for sending requests to other agents. |
| `server` (property) | — | `Server \| None` | Returns the server instance if one is available via the transport. |

## Task and Message Handling

### Core Task Processing

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `handle_task()` | `task: Task` | `Task` | **Abstract method.** Subclasses must implement this to define how tasks are processed. |
| `handle_task_streaming()` | `task: Task` | `AsyncIterator[Task]` | Optional streaming handler for real-time task updates. Default raises `NotImplementedError`. |

### Communication Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `send_task_to()` | `agent_url: str`, `task: Task`, `skill: str \| None = None` | `Task` | Sends a task to another agent and returns the processed result. |
| `send_message_to()` | `agent_url: str`, `message: Message` | `Message` | Sends a message to another agent and returns the response. |

!!! note "Authentication"
    All outgoing requests are automatically signed if an `auth_provider` is configured. Incoming requests are verified against the same provider.

## Tool Management

Tools allow agents to execute external functions and APIs.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `add_tool()` | `tool: BaseTool` | `None` | Registers a tool with the agent. |
| `tool()` | `name: str`, `description: str` | `decorator` | Decorator for registering Python functions as tools. |
| `call_tool()` | `tool_name: str`, `**kwargs` | `Any` | Executes a registered tool by name with provided arguments. |

```python
# Using the decorator approach
@agent.tool("calculate", "Performs basic calculations")
def calculate(operation: str, a: float, b: float) -> float:
    if operation == "add":
        return a + b
    elif operation == "multiply":
        return a * b
    else:
        raise ValueError(f"Unsupported operation: {operation}")

# Direct tool registration
from protolink.tools import BaseTool

class WeatherTool(BaseTool):
    def call(self, location: str) -> dict:
        # Weather API logic here
        return {"temperature": 72, "conditions": "sunny"}

agent.add_tool(WeatherTool())
```

## Utility Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `get_agent_card()` | — | `AgentCard` | Returns the agent's metadata card. |
| `set_llm()` | `llm: LLM` | `None` | Updates the agent's language model instance. |
| `verify_auth()` | `request: Request` | `bool` | Verifies authentication for incoming requests if an auth provider is configured. |

## Abstract Methods

Subclasses of `Agent` must implement the following methods:

- **`handle_task(task: Task) -> Task`**: Defines the core logic for processing incoming tasks.

!!! example "Minimal Agent Implementation"
    ```python
    from protolink.agents import Agent
    from protolink.models import AgentCard, Task, Message
    
    class EchoAgent(Agent):
        async def handle_task(self, task: Task) -> Task:
            # Echo back all messages
            response_messages = []
            for message in task.messages:
                response_messages.append(
                    Message(
                        content=f"Echo: {message.content}",
                        role="assistant"
                    )
                )
            
            return Task(
                messages=response_messages,
                parent_task_id=task.id
            )
    ```

## Error Handling

The `Agent` class includes several error handling patterns:

- **Missing Transport**: Raises `ValueError` if trying to start without a transport.
- **Authentication Failures**: Returns `401` or `403` responses for invalid auth.
- **Tool Errors**: Tool execution errors are propagated to the caller.
- **Task Processing**: Errors in `handle_task()` are caught and returned as error messages to the sender.

## Authentication Integration

When an `auth_provider` is configured, the agent automatically:

1. **Signs outgoing requests** with appropriate authentication headers
2. **Verifies incoming requests** using the same auth mechanism
3. **Returns appropriate HTTP status codes** for auth failures (401, 403)

Supported auth providers include API key authentication, OAuth, and custom implementations.
