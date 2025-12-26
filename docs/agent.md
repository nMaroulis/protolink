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


<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/agent_architecture.png" alt="Agent Architecture" width="100%">
</div>

## Creating an Agent

A minimal agent consists of three pieces:

1. An `AgentCard` describing the agent.
2. A `Transport` implementation.
3. An optional LLM and tools.

Example:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPAgentTransport
from protolink.llms.api import OpenAILLM

# Agent card can be an AgentCard object or a dict for simplicity, both are handled the same way.
# Option 1: Using AgentCard object
agent_card = AgentCard(
    name="example_agent",
    description="A dummy agent",
)

# Option 2: Using dictionary (simpler)
card_dict = {
    "name": "example_agent",
    "description": "A dummy agent",
    "url": "http://localhost:8000"
}

transport = HTTPAgentTransport()
llm = OpenAILLM(model="gpt-5.2")

# Both approaches work
agent = Agent(agent_card, transport, llm)
# OR
agent = Agent(card_dict, transport, llm)
```

You can then attach tools and start the agent.

Once the Agent has been initiated, it automatically exposes a web interface at `/status` where it exposes the agent's information.

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/agent_status_card.png" alt="Agent Status Card" width="50%">
</div>

## Agent-to-Agent Communication

Agents communicate over a chosen transport.

Common patterns:

- **RuntimeAgentTransport**: multiple agents in the same process share an in‑memory transport, which is ideal for local testing and composition.
- **HTTPAgentTransport / WebSocketAgentTransport**: agents expose HTTP or WebSocket endpoints so that other agents (or external clients) can send requests.
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
| `transport` | `AgentTransport \| None` | `None` | Optional transport for communication. If not provided, you must set one later via `set_transport()`. |
| `registry` | `Registry \| RegistryClient \| str \| None` | `None` | Optional registry for agent discovery. Can be a Registry instance, RegistryClient, or URL string (defaults to HTTPRegistryTransport). |
| `llm` | `LLM \| None` | `None` | Optional language model instance for the agent to use. |
| `skills` | `Literal["auto", "fixed"]` | `"auto"` | Skills mode - `"auto"` to automatically detect and add skills, `"fixed"` to use only the skills defined by the user in the AgentCard. |

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPAgentTransport
from protolink.llms.api import OpenAILLM

url = "http://localhost:8020"
card = AgentCard(name="my_agent", description="Example agent", url=url)
llm = OpenAILLM(model="gpt-4")
transport = HTTPAgentTransport(url=url)

agent = Agent(card=card, transport=transport, llm=llm)
```

## Lifecycle Methods

These methods control the agent's server component lifecycle.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `start()` | `register: bool = True` | `None` | Starts the agent's server component if a transport is configured. Optionally registers with the registry (default True). |
| `stop()` | — | `None` | Stops the agent's server component and cleans up resources. |

!!! warning "Transport Required"
    The `start()` method requires a transport to be configured. If no transport was provided during construction, call `set_transport()` first.

## Transport Management

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `set_transport()` | `transport: Transport` | `None` | Sets or updates the transport used by this agent. |
| `client` (property) | — | `AgentClient` | Returns the client instance for sending requests to other agents. |
| `server` (property) | — | `AgentServer \| None` | Returns the server instance if one is available via the transport. |

#### Agent Transport Layers

| Layer          | Responsibility                                 |
| -------------- | ---------------------------------------------- |
| Agent          | Domain logic (what to do with a Task)          |
| AgentServer    | Wiring & lifecycle (server orchestration)      |
| AgentTransport | Protocol abstraction (HTTP vs WS vs gRPC)      |
| Backend        | Framework-specific routing (Starlette/FastAPI) |

e.g.

`Agent.handle_task() -> AgentServer.set_task_handler() -> AgentTransport.on_task_received() -> Backend route calls transport._task_handler()`


## Task and Message Handling

### Core Task Processing

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `handle_task()` | `task: Task` | `Task` | **Abstract method.** Subclasses must implement this to define how tasks are processed. |
| `handle_task_streaming()` | `task: Task` | `AsyncIterator` | Optional method for agents that want to emit real-time updates. Default implementation calls `handle_task` and emits status functionality events. |
| `process()` | `message_text: str` | `str` | Convenience method for synchronous processing of user text input. Wraps input in a Task and returns response text. |

### Communication Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `send_task_to()` | `agent_url: str`, `task: Task` | `Task` | Sends a task to another agent and returns the processed result. |
| `send_message_to()` | `agent_url: str`, `message: Message` | `Message` | Sends a message to another agent and returns the response. |



## Skills Management

Skills represent the capabilities that an agent can perform. Skills are stored in the `AgentCard` and can be automatically detected or added.

### Skills Modes

| Mode | Description |
|------|-------------|
| `"auto"` | Automatically detects skills from tools and public methods, and adds them to the AgentCard |
| `"fixed"` | Uses only the skills explicitly defined in the AgentCard |

### Skill Detection

When using `"auto"` mode, the agent detects skills from:

1. **Tools**: Each registered tool becomes a skill
2. **Public Methods**: Optional detection of public methods (controlled by `include_public_methods` parameter)

```python
# Auto-detect skills from tools only
agent = Agent(card, skills="auto")

# Use only skills defined in AgentCard
agent = Agent(card, skills="fixed")
```

### Skills in AgentCard

Skills are persisted in the AgentCard and serialized when the card is exported to JSON:

```python
from protolink.models import AgentCard, AgentSkill

# Create skills manually in AgentCard
card = AgentCard(
    name="weather_agent",
    description="Weather information agent",
    skills=[
        AgentSkill(
            id="get_weather",
            description="Get current weather for a location",
            tags=["weather", "forecast"],
            examples=["What's the weather in New York?"]
        )
    ]
)

# Use fixed mode to only use these skills
agent = Agent(card, skills="fixed")
```

## Tool Management

Tools allow agents to execute external functions and APIs.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `add_tool()` | `tool: BaseTool` | `None` | Registers a tool with the agent and automatically adds it as a skill to the AgentCard. |
| `tool()` | `name: str`, `description: str` | `decorator` | Decorator for registering Python functions as tools (automatically adds as skills). |
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

## Registry & Discovery

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `discover_agents()` | `filter_by: dict \| None = None` | `list[AgentCard]` | Discover agents in the registry matching the filter criteria. |
| `register()` | — | `None` | Registers this agent in the global registry. |
| `unregister()` | — | `None` | Unregisters this agent from the global registry. |

## Utility Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `get_agent_card()` | `as_json: bool = True` | `AgentCard \| dict` | Returns the agent's identity card. |
| `set_llm()` | `llm: LLM` | `None` | Updates the agent's language model instance. |
| `get_context_manager()` | — | `ContextManager` | Returns the context manager for this agent. |

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


