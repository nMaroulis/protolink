# Client

The **Client** layer in Protolink provides a high-level interface for agent-to-agent communication. It abstracts transport details and offers convenient methods for sending tasks, messages, and retrieving agent metadata.

## AgentClient

The `AgentClient` is the primary entry point for programmatic agent interactions. It wraps a transport and provides typed methods for common operations.

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
| `transport` | `Transport \| str` | A Transport instance or type string (`"http"`, `"websocket"`, etc.) |
| `url` | `str \| None` | Base URL when using a transport type string |

**Examples:**

```python
# Using transport type string
client = AgentClient(transport="http", url="http://localhost:8000")

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

Sends a task and yields streamed events as they arrive. Useful for real-time updates.

```python
async def send_task_streaming(agent_url: str, task: Task) -> AsyncIterator[Any]
```

!!! warning "Transport Support"
    Requires a transport that implements streaming (e.g., WebSocket). Raises `NotImplementedError` for HTTP transport.

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

