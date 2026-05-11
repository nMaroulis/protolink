# Agents

Agents are the core building blocks in Protolink.

## Concepts

An **Agent** in Protolink is a unified component that acts as both **client and server**, unlike Google’s A2A protocol, which separates these concerns.

It is the **core building block** of Protolink, responsible for managing identity, capabilities, and interactions between agents. The Agent integrates key components such as **tools**, **LLM**, **transport**, **memory**, **storage**, **telemetry**, and **logging**. T

Agents **communicate through Tasks**, the fundamental unit of work:
- **Receive tasks** via ``handle_task()``
- **Send tasks** via ``call_agent()``

Agents also register themselves and discover others via the registry. For inference requests ("infer"), ProtoLink automatically manages the full LLM interaction cycle until the task is resolved.

Each component is **pluggable** to the agent and can be replaced with your own implementation.

High‑level ideas:

- **Unified model**: a single `Agent` instance can send and receive messages.
- **AgentCard**: a small model describing the agent (name, description, metadata).
- **Modules**:
  - **LLMs** (e.g. `OpenAILLM`, `AnthropicLLM`, `LlamaCPPLLM`, `OllamaLLM`).
  - **Tools** (native Python functions or MCP‑backed tools).
  - **Storage** (e.g. `InMemoryStorage`, `Storage`).
  - **Telemetry** (e.g. `Telemetry`, `BaseTelemetry`).
  - **Logger** (e.g. `ConsoleLogger`, `FileLogger`).
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
from protolink.transport import HTTPTransport
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

transport = HTTPTransport()
llm = OpenAILLM(model="gpt-5.2")

# Both approaches work
agent = Agent(agent_card, transport, llm)
# OR
agent = Agent(card_dict, transport, llm)
```

You can then attach tools and start the agent.

Once the **Agent** and **Registry** objects have been initiated, they will automatically expose a web interface at `/status` where they display the registry and agent's information.

<table style="border-collapse: collapse; border: none; width: 100%;">
  <tr style="border: none;">
    <td style="text-align: center; border: none; padding: 10px; transition: transform 0.3s ease, box-shadow 0.3s ease;">
      <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/registry_status_card.png"
           alt="Registry Status Card"
           width="60%"
           style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); transition: transform 0.3s ease, box-shadow 0.3s ease;"
           onmouseover="this.style.transform='scale(1.05)'; this.style.boxShadow='0 8px 16px rgba(0,0,0,0.2)';"
           onmouseout="this.style.transform='scale(1)'; this.style.boxShadow='0 4px 8px rgba(0,0,0,0.1)';">
    </td>
  </tr>
  <tr style="border: none;">
    <td style="text-align: center; border: none; padding: 10px; transition: transform 0.3s ease, box-shadow 0.3s ease;">
      <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/agent_status_card.png" 
           alt="Agent Status Card" 
           width="60%" 
           style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); transition: transform 0.3s ease, box-shadow 0.3s ease;"
           onmouseover="this.style.transform='scale(1.05)'; this.style.boxShadow='0 8px 16px rgba(0,0,0,0.2)';"
           onmouseout="this.style.transform='scale(1)'; this.style.boxShadow='0 4px 8px rgba(0,0,0,0.1)';">
    </td>
  </tr>
</table>

## Agent-to-Agent Communication

Agents communicate over a chosen transport.

Common patterns:

- **RuntimeTransport**: agents operate dedicated native local transports connected via a globally shared memory registry. This mirrors distributed HTTP environments perfectly, enabling zero network overhead testing workflows while retaining accurate boundaries.
- **HTTPTransport / WebSocketTransport**: agents expose HTTP or WebSocket endpoints so that other agents (or external clients) can send requests.

#### Agent Transport Layers

| Layer          | Responsibility                                 |
| -------------- | ---------------------------------------------- |
| Agent          | Domain logic (what to do with a Task)          |
| AgentServer    | Wiring & lifecycle (server orchestration)      |
| Transport      | Protocol abstraction (HTTP vs WS vs gRPC)      |
| Backend        | Framework-specific routing (Starlette/FastAPI) |

e.g.

`Agent.handle_task() -> AgentServer.set_task_handler() -> Transport.setup_routes() -> Backend creates route`


---

# Agent API Reference

This section provides a detailed API reference for the `Agent` base class in `protolink.agents.base`. The `Agent` class is the core component for creating A2A-compatible agents, serving as both client and server.

!!! info "Unified Agent Model"
    Unlike the original A2A specification, Protolink's `Agent` combines client and server functionality in a single class. You can send tasks/messages to other agents while also serving incoming requests.

## Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `card` | `AgentCard` | — | **Required.** The agent's metadata card containing name, description, and other identifying information. |
| `transport` | `Transport ⎪ str ⎪ None` | `None` | Optional transport for communication. Can be a Transport instance or a string alias (e.g. "http", "runtime"). If not provided, you must set one later via the `transport` property. |
| `registry` | `Registry ⎪ RegistryClient ⎪ str ⎪ None` | `None` | Optional registry for agent discovery. Can be a Registry instance, RegistryClient, or URL string. |
| `registry_url` | `str ⎪ None` | `None` | URL of the registry when using string transport type for registry creation. |
| `llm` | `LLM ⎪ None` | `None` | Optional language model instance for the agent to use. |
| `system_prompt` | `str ⎪ None` | `None` | Optional complementary text for the system prompt to explain agent logic and role. |
| `storage` | `Storage ⎪ None` | `None` | Optional storage instance for agent data persistence. |
| `telemetry` | `Telemetry ⎪ None` | `None` | Optional telemetry instance for observability and tracing. |
| `skills` | `Literal["auto", "fixed"]` | `"auto"` | Skills mode - `"auto"` to automatically detect and add skills, `"fixed"` to use only the skills defined by the user in the AgentCard. |
| `logger` | `BaseLogger ⎪ None` | `None` | Custom logger instance (e.g. `ConsoleLogger` or `FileLogger`). |
| `discovery_ttl` | `int` | `0` | Time to live in seconds for caching Agent information discovered from the Registry. Default is `0` (no caching). |
| `override_system_prompt` | `bool` | `False` | If True, overrides the default system prompt completely with the provided `system_prompt`. |
| `memory` | `MemoryModeType` | `"none"` | Conversation memory mode: `"none"` (stateless) or `"session"` (persistent across tasks with same `session_id`). |
| `verbosity` | `Literal[0, 1, 2]` | `1` | Logging verbosity level: `0` = silent (WARNING only), `1` = normal (INFO), `2` = verbose (DEBUG). |
| `expose_chat` | `bool` | `True` | Whether the Agent will expose a chat endpoint for interaction with a UI. |

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.transport import HTTPTransport
from protolink.llms.api import OpenAILLM

url = "http://localhost:8020"
card = AgentCard(name="my_agent", description="Example agent", url=url)
llm = OpenAILLM(model="gpt-4")
transport = HTTPTransport(url=url)

agent = Agent(card=card, transport=transport, llm=llm)
```

## Lifecycle Methods

These methods control the agent's server component lifecycle.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `start()` | `register: bool = True`, `background: bool = False` | `asyncio.Task ⎪ None` | Starts the agent runtime. Automatically detects the environment and handles event loops. |
| `stop()` | — | `None` | Stops the agent runtime and cleans up resources. |

### Execution Models: Adaptive `start()`

The `start()` method is the primary entrypoint for running an agent. It is designed to be **environment-aware**, meaning it automatically detects whether it's running in a standard Python script, an asynchronous application, or a Jupyter notebook, and adapts its execution model accordingly.

#### The `background` Parameter

The `background` parameter controls whether the agent blocks the current execution or runs in the background:

- **`background=False` (Default)**: Blocks execution until the agent is stopped (e.g., via Ctrl+C in a terminal).
- **`background=True`**: Starts the agent and returns immediately, allowing the rest of the script to continue.

#### Common Usage Patterns

**1. Standalone Python Script**
For simple scripts where the agent is the main process, use the default blocking mode:
```python
# This will block the script and run until interrupted
agent.start()
```

**2. Multi-Agent Script (Sync)**
If you need to start multiple agents in a single script, run the first ones in the background and the last one in blocking mode to keep the process alive:
```python
agent_a.start(background=True)
agent_b.start(background=True)
agent_c.start(background=False) # Keep the script alive
```

**3. Jupyter Notebooks / Interactive Environments**
Jupyter Notebooks run inside an existing event loop. `start()` detects this and returns an `asyncio.Task` immediately, regardless of the `background` setting, so it doesn't block the cell:
```python
# In a Jupyter cell
agent.start() # Returns an asyncio.Task and keeps the agent running in the background
```

**4. Async Applications (FastAPI, etc.)**
When integrating into an async app, `start()` can be called normally. It will return a task that you can optionally await or manage:
```python
async def main():
    # Start the agent as a background task in the existing loop
    task = agent.start(background=True)
    
    # ... other async logic ...
    
    await asyncio.Event().wait() # Keep the loop running
```

!!! tip "Graceful Shutdown"
    Always use `agent.stop()` to ensure that the agent unregisters from the registry and releases its network ports cleanly. In a standard script, `agent.start()` handles `KeyboardInterrupt` gracefully if `background=False`.

## Transport Management

## Transport Management

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `transport` (property) | `Transport ⎪ str ⎪ None` | `None` | Gets or sets the transport used by this agent. Setting this initializes the client and server components. |
| `client` (property) | — | `AgentClient ⎪ None` | Returns the client instance for sending requests to other agents, or None if no transport is set. |
| `server` (property) | — | `AgentServer ⎪ None` | Returns the server instance if one is available via the transport. |

## Task and Message Handling

### Core Task Processing

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `handle_task()` | `task: Task` | `Task` | Default task handler. Interprets the Task's Parts (tool calls, inference) and executes them. Can be overridden for custom orchestration. |
| `handle_task_streaming()` | `task: Task` | `AsyncIterator` | Optional method for agents that want to emit real-time updates. Default implementation calls `handle_task` and emits status functionality events. |
| `execute_task()` | `task: Task` | `Task` | Core execution method. For `infer` parts, it delegates to `LLM.infer()` to run the multi-step reasoning loop. For `tool_call` parts, it executes the tool directly. |
| `invoke()` | `message, part_type="infer", tool_name=None, tool_args=None, session_id="invocation_session_id"` | `str` | **Async.** Convenience method for direct agent invocation. Supports `infer` and `tool_call`. Accepts an optional `session_id` for memory. |
| `invoke_sync()` | `message, part_type="infer", tool_name=None, tool_args=None, session_id="invocation_session_id"` | `str` | Synchronous version of `invoke()`. Useful for testing and simple scripts. |

#### The Inference Loop Integration

When `execute_task()` encounters an `infer` part, it delegates to `LLM.infer()` with:

1. **The query**: Extracted from the task's message content
2. **The agent's tools**: All registered tools passed as a dictionary
3. **An agent callback**: Enables the LLM to delegate work to other agents

```python
# Simplified view of what happens inside execute_task()
result = await self.llm.infer(
    query=query,
    tools=self.tools,
    agent_callback=self._handle_agent_call  # Enables agent delegation
)
```

The **agent callback** (`_handle_agent_call`) is invoked when the LLM produces an `agent_call` action. It:

1. **Resolves the agent name to URL** by querying the registry
2. **Creates a Task** with the appropriate message/tool call
3. **Sends the task** to the target agent via `call_agent()`
4. **Returns the result** to the inference loop

This enables a coordinator agent to delegate work to specialized agents without manual orchestration.

!!! info "Agent Delegation Flow"
    ```
    User Query → Coordinator Agent → LLM.infer()
                                        ↓
                                   agent_call action
                                        ↓
                               _handle_agent_call()
                                        ↓
                               resolve agent URL
                                        ↓
                               call_agent(weather_agent)
                                        ↓
                               Weather Agent processes task
                                        ↓
                               Result returned to LLM
                                        ↓
                               LLM produces final response
    ```



### Communication Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `call_agent()` | `agent_url: str`, `task: Task` | `Task` | Sends a task to another agent and returns the processed result. |
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
| `discover_agents()` | `filter_by: dict ⎪ None = None` | `list[AgentCard]` | Discover agents in the registry matching the filter criteria. |
| `register()` | — | `None` | Registers this agent in the global registry. |
| `unregister()` | — | `None` | Unregisters this agent from the global registry. |

## Utility Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `get_agent_card()` | `as_json: bool = True` | `AgentCard ⎪ dict` | Returns the agent's identity card. |
| `get_status()` | `output_format: Literal["html", "json"] = "html"` | `str` | Returns the agent's status as HTML or JSON. HTML is a rich status page for the agent (displayed at `/status`). JSON is a machine-readable representation of the agent's status. |
| `get_chat()` | — | `str` | Returns a self-contained chat UI as HTML. Only functional when the agent has an LLM configured (served at `/chat`). |
| `handle_chat_message()` | `data: dict` | `dict` | Processes an incoming chat message via the agent's `invoke()` method and returns the response. |
| `llm` (property) | `LLM ⎪ None` | `None` | Gets or sets the agent's language model. Setting this validates the connection and updates `card.capabilities.has_llm` automatically. |
| `storage` (property) | `Storage` | `None` | Gets or sets the agent's storage instance. Setting this automatically updates the internal `SessionManager`. |
| `set_registry()` | `registry, registry_url=None` | `None` | Configures the agent's connection to a Protolink registry. |
| `get_context_manager()` | — | `ContextManager` | Returns the context manager for this agent. |

## Storage and Persistence

Protolink provides a storage abstraction to allow agents to persist data across tasks or even standalone.

### Core Storage Interface

The `Storage` base class defines the CRUD interface:

```python
from protolink.storage import Storage

class MyStorage(Storage):
    def save(self, data): ...
    def load(self): ...
    def update(self, data): ...
    def delete(self): ...
```

### In-Memory Storage (Default)

Protolink includes a built-in `InMemoryStorage` which is the **default storage backend** for all agents. It is a lightweight, RAM-backed dictionary that supports TTL (Time-To-Live) for automatic cleanup.

```python
from protolink.storage import InMemoryStorage

# Default: shared class-level store
storage = InMemoryStorage(namespace="my_agent", ttl=3600)
agent = Agent(card=card, storage=storage)
```

### SQLite Storage

For persistent storage across restarts, use the built-in `SQLiteStorage`:

```python
from protolink.storage import SQLiteStorage

storage = SQLiteStorage(db_path="my_agent.db", namespace="main_agent")
agent = Agent(card=card, storage=storage)
```

## Session Persistence

When an agent is initialized with `memory="session"`, it tracks conversation state across multiple task executions based on the `session_id`.

1. **Activation**: Set `memory="session"` in the Agent constructor.
2. **Identification**: Include a `session_id` in your task metadata:
   ```python
   task = Task.create(Message.user("My name is Alice"))
   task.metadata["session_id"] = "user_123"
   await agent.execute_task(task)
   ```
3. **Resumption**: Subsequent tasks with the same `session_id` will automatically load the previous conversation history into the LLM context.

!!! tip "Session IDs"
    When using direct invocation methods like `invoke()` or `invoke_sync()`, a default `session_id` of `"invocation_session_id"` is used if none is provided. This ensures that sequential calls to the same agent instance share history by default when `memory="session"` is enabled.

    If no `session_id` is provided in the task metadata (for non-invoke calls), the agent falls back to using the `task.id`, effectively making that specific task stateless unless further responses are sent to it.


## Chat Gateway

When an agent is configured with an **LLM**, Protolink automatically exposes a built-in **Chat UI** at the `/chat` endpoint. This provides a browser-based interface for interacting with the agent directly — ideal for development, demos, and quick testing.

### How It Works

- **`GET /chat`** — Serves a self-contained HTML/CSS/JS chat interface. The page is always registered but displays a fallback message if no LLM is configured.
- **`POST /chat`** — Accepts `{"message": "...", "session_id": "..."}` and returns `{"response": "..."}`. This endpoint is only registered when the agent has an LLM.

The chat page displays agent metadata (name, description, skills) and LLM configuration (provider, model, temperature) in a sidebar, alongside a modern conversational interface.

### Usage

No extra setup is needed — just provide an LLM when creating your agent:

```python
from protolink.agents import Agent
from protolink.llms.api import OpenAILLM

agent = Agent(
    card={"name": "assistant", "description": "A helpful assistant", "url": "http://localhost:8000"},
    transport="http",
    llm=OpenAILLM(model="gpt-4o"),
)

agent.start()
# Chat UI is now available at http://localhost:8000/chat
```

### Session Memory

The chat UI generates a unique `session_id` per browser tab. When combined with `memory="session"`, conversations persist across messages within the same tab:

```python
agent = Agent(
    card=card,
    transport="http",
    llm=OpenAILLM(model="gpt-4o"),
    memory="session",  # Enables cross-message memory in chat
)
```

!!! tip "Chat vs Status"
    The `/status` page shows the agent's operational health and metadata. The `/chat` page provides an interactive conversation interface. Both are served automatically when the agent starts.


## Abstract Methods

The `Agent` class provides a default implementation for `handle_task` that handles tool use and LLM inference automatically. You generally do **not** need to implement any abstract methods unless you require custom logic.

- **`handle_task(task: Task) -> Task`**: Override this if you need custom task processing logic (e.g., conditional execution, routing).


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


