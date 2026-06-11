# Client

The **Client** layer in Protolink provides a high-level interface for agent-to-agent communication. It abstracts transport details and offers convenient methods for sending tasks, messages, and retrieving agent metadata.

## AgentClient

The `AgentClient` is the primary entry point for programmatic agent interactions. It wraps a transport and provides a unified interface for communicating with Protolink agents.

### Design Philosophy: Async vs Sync

Protolink's client architecture exposes two APIs to accommodate different workflows:

1. **Async API (Recommended)**: The core implementation. Ideal for modern applications, web servers (e.g., FastAPI), and high-performance multi-agent orchestration where non-blocking I/O is crucial.
2. **Sync API (`client.sync`)**: A thin, blocking wrapper over the async methods. Designed for simple scripts, CLI tools, and environments where managing an `asyncio` event loop is cumbersome.

!!! warning "Async Loop Constraint"
    The Sync API (`client.sync`) uses `asyncio.run()` under the hood. It **cannot** be used inside an already running event loop (e.g., inside an async function). If you are inside an `async def`, always use the standard Async API.

### Quick Start

```python
from protolink.client import AgentClient
from protolink.models import Task

# Create a client (transport type + URL)
client = AgentClient(transport="http", url="http://localhost:8000")

# Create a task with an inference request
task = Task.create_infer(prompt="Book me a vacation to Santorini")

# Send to a remote agent
result = await client.send_task(agent_url="http://localhost:8010", task=task)

# Get the response
print(result.get_last_part_content())
```

### Constructor

```python
AgentClient(transport: Transport | TransportType, url: str | None = None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `transport` | `Transport ⎪ str` | A Transport instance or type string (`"http"`, `"websocket"`, etc.) |
| `url` | `str ⎪ None` | Base URL when using a transport type string |
| `timeout` | `int` | Timeout in seconds for the request (default: 300) |

**Examples:**

```python
# Using transport type string
client = AgentClient(transport="http", url="http://localhost:8000", timeout=120)

# Using an existing transport instance
from protolink.transport import HTTPTransport
transport = HTTPTransport(url="http://localhost:8000")
client = AgentClient(transport=transport)
```

---

## Core Methods

### `send_task()`

Sends a `Task` to a remote agent and returns the processed result.

```python
async def send_task(agent_url: str, task: Task) -> Task
```

| Parameter | Description |
|-----------|-------------|
| `agent_url` | The full URL of the target agent (e.g., `"http://localhost:8010"`) |
| `task` | The `Task` object to send |

**Example:**

```python
from protolink.models import Task

# Create an infer task
task = Task.create_infer(prompt="What's the weather in Athens?")

# Send and get result
result = await client.send_task("http://localhost:8010", task)
print(result.get_last_part_content())
```

---

### `send_task_streaming()`

Sends a task and yields streamed events as they arrive. This is the public client API for live task progress, LLM chunks, tool events, and final task completion.

```python
async def send_task_streaming(agent_url: str, task: Task) -> AsyncIterator[Any]
```

!!! warning "Transport Support"
    Requires a transport that advertises streaming support and implements `subscribe()`. Supported choices include `"sse"`, `"json-rpc"`, `"websocket"`, and `"runtime"`. Plain `"http"` remains request/response only and raises `NotImplementedError`.

**Example with SSE JSON-RPC:**

```python
from protolink.client import AgentClient
from protolink.models import Task

client = AgentClient(transport="sse", url="http://localhost:8000")
task = Task.create_infer(prompt="Write a short haiku about agents")

async for event in client.send_task_streaming("http://localhost:8010", task):
    if event.get("type") == "task_llm_stream":
        print(event.get("content") or "", end="", flush=True)
    if event.get("final"):
        print("\nstream complete")
```

---

### `send_message()`

Convenience wrapper that creates a Task from a Message, sends it, and returns the response message.

```python
async def send_message(agent_url: str, message: Message) -> Message
```

**Example:**

```python
from protolink.models import Message

response = await client.send_message(
    agent_url="http://localhost:8010",
    message=Message.user("Hello, agent!")
)
print(response.parts[0].content)
```

---

### `get_agent_card()`

Retrieves the public `AgentCard` from a remote agent. Useful for discovery and capability inspection.

```python
async def get_agent_card(agent_url: str) -> AgentCard
```

**Example:**

```python
card = await client.get_agent_card("http://localhost:8010")
print(f"Agent: {card.name}")
print(f"Description: {card.description}")
print(f"Skills: {[s.id for s in card.skills]}")
```

---

## Synchronous API

The `AgentClient` provides synchronous versions of its core methods for use in non-async contexts (scripts, notebooks, CLI tools). These are accessible via the `client.sync` property.

Internally, these methods use `asyncio.run()` to handle the asynchronous transport logic.

!!! warning "Do Not Use in Async Loops"
    The synchronous API should **NOT** be used inside an active event loop (e.g., inside FastAPI endpoints or async Jupyter cells) as it uses `asyncio.run()`, which will raise a `RuntimeError`.

| Async Method | Synchronous Equivalent | Description |
|--------------|------------------------|-------------|
| `send_task()` | `client.sync.send_task()` | Synchronously send a task and wait for the result. |
| `send_task_streaming()` | `client.sync.send_task_streaming()` | Synchronously iterate over streamed task events. |
| `send_message()` | `client.sync.send_message()` | Synchronously send a message and wait for the response message. |
| `get_agent_card()` | `client.sync.get_agent_card()` | Synchronously retrieve an agent's public card. |

**Example:**

```python
from protolink.client import AgentClient
from protolink.models import Task

client = AgentClient(transport="http", url="http://localhost:8000")
task = Task.create_infer(prompt="Hello, agent!")

# No 'await' or 'async def' needed. Use the .sync property!
result = client.sync.send_task("http://localhost:8010", task)
print(result.get_last_part_content())
```

**Synchronous streaming example:**

```python
client = AgentClient(transport="sse", url="http://localhost:8000")
task = Task.create_infer(prompt="Stream this response")

for event in client.sync.send_task_streaming("http://localhost:8010", task):
    print(event)
```

---

## ClientRequestSpec

`ClientRequestSpec` defines the contract for an API endpoint in a transport-agnostic way.

```python
@dataclass(frozen=True)
class ClientRequestSpec:
    name: str                    # Human-readable name (e.g., "send_task")
    path: str                    # URL path (e.g., "/tasks/")
    method: HttpMethod           # HTTP method (e.g., "POST")
    response_parser: Callable    # Function to parse response data
    request_source: str          # Where to put request data ("body", "query", etc.)
```

### Built-in Request Specs

| Spec | Path | Method | Description |
|------|------|--------|-------------|
| `TASK_REQUEST` | `/tasks/` | POST | Send a task to an agent |
| `AGENT_CARD_REQUEST` | `/.well-known/agent.json` | GET | Retrieve agent metadata |
| `TASK_STREAM_REQUEST` | `/tasks/stream` | POST | Send task with streaming |

### How It Works

When you call a method like `send_task()`:

1. The client selects the appropriate `ClientRequestSpec` (e.g., `TASK_REQUEST`)
2. Passes the spec and data to `transport.send()`
3. The transport uses the spec to construct the wire request

This pattern allows new endpoints without modifying transport implementations.
