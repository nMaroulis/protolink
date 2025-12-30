# Client

The **Client** layer in Protolink provides a high-level, user-friendly interface for interacting with agents. It abstracts away the low-level details of the transport layer, providing convenient methods for sending tasks, messages, and retrieving agent information.

## AgentClient

The `AgentClient` is the primary entry point for client-side agent interactions. It wraps a `Transport` instance and uses it to send typed requests to remote agents.

### Usage

```python
from protolink.client import AgentClient
from protolink.transport import HTTPTransport
from protolink.models import Message

# Initialize transport and client
transport = HTTPTransport()
client = AgentClient(transport)

# Send a message
response_message = await client.send_message(
    agent_url="http://localhost:8000",
    message=Message.user("Hello, agent!")
)
print(response_message.parts[0].content)
```

### API Reference

#### `__init__(transport: Transport)`
Initializes the client with a specific transport implementation.

#### `async send_task(agent_url: str, task: Task) -> Task`
Sends a `Task` to a remote agent and returns the updated `Task` (containing the agent's response).

*   **agent_url**: The base URL or ID of the target agent.
*   **task**: The `Task` object to send.

#### `async send_message(agent_url: str, message: Message) -> Message`
A convenience wrapper that creates a `Task` from a single `Message`, sends it using `send_task`, and returns the last message from the response.

*   **agent_url**: The base URL or ID of the target agent.
*   **message**: The `Message` object to send.

#### `async get_agent_card(agent_url: str) -> AgentCard`
Retrieves the public `AgentCard` from a remote agent. This is useful for discovery.

*   **agent_url**: The base URL or ID of the target agent.

---

## ClientRequestSpec

`ClientRequestSpec` is a dataclass that defines the contract for a specific API endpoint on an agent. It allows the `AgentClient` to describe *what* it wants to do (e.g., "send a task") in a transport-agnostic way.

### Structure

```python
@dataclass(frozen=True)
class ClientRequestSpec:
    name: str                                   # Human-readable name (e.g., "send_task")
    path: str                                   # URL path (e.g., "/tasks/")
    method: HttpMethod                          # HTTP method (e.g., "POST")
    response_parser: Callable[[Any], Any] | None # Function to parse response data
    request_source: RequestSourceType = "body"  # Where to put the request data ("body", "query", etc.)
    content_type: ContentType | None = None     # Content-Type header
    accept: ContentType | None = None           # Accept header
```

### How it works

When you call a method on `AgentClient` (like `send_task`), it:
1.  Selects the appropriate `ClientRequestSpec` definition (e.g., `AgentClient.TASK_REQUEST`).
2.  Passes this definition, along with the data, to `transport.send()`.
3.  The transport uses the `ClientRequestSpec` to construct the actual wire request (e.g., forming the HTTP URL and method).

This pattern allows new endpoints to be added to the client without modifying the transport implementations.
