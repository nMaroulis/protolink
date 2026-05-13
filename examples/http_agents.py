"""HTTP Transport Example - Distributed Agent Communication.

This script demonstrates how to leverage `HTTPTransport` to orchestrate communication
between completely independent agent instances over a physical TCP network interface
(localhost in this example).

Unlike `RuntimeTransport`, the `HTTPTransport` physically spins up a highly concurrent
ASGI server (Starlette/FastAPI) in a background thread and transmits standard RESTful JSON
payloads over the wire. This example specifically validates the agent's ability to act
simultaneously as a server (listening for tasks) and a client (dispatching tasks to others)
without event loop contamination.
"""

from __future__ import annotations

from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.models import AgentCard, Message, Task
from protolink.transport import HTTPTransport


class EchoAgent(Agent):
    """A deterministic domain agent built to validate distributed networking capabilities.

    This agent extends the core `Agent` class and binds itself to an `HTTPTransport`.
    It is designed to receive network requests, parse the incoming JSON payload back
    into a Protolink `Task` object, and echo the payload back to the caller. This proves
    full end-to-end traversal of the ASGI backend, the Pydantic serialization layer,
    and the asynchronous HTTP client pooling.
    """

    def __init__(self, name: str, description: str, port: int) -> None:
        """Initialize the agent, its identity card, and its network binding.

        Args:
            name: The internal identifier for the agent.
            description: The semantic role of the agent, exposed via its `AgentCard`.
            port: The TCP port on `127.0.0.1` that the background ASGI server will bind to.
        """
        transport = HTTPTransport(url=f"http://127.0.0.1:{port}", backend="starlette")
        card = AgentCard(name=name, description=description, url=f"http://127.0.0.1:{port}")
        super().__init__(card, transport=transport)

    # Overrides the base class handle_task method to add custom logic.
    async def handle_task(self, task: Task) -> Task:
        """Process incoming HTTP requests and return a mutated task state.

        When the agent's background server receives a `POST /tasks/` request, it
        deserializes the JSON body into a `Task` and delegates it to this handler.
        We extract the most recent user prompt and return a completed state. The
        underlying server then serializes this response back into JSON to be transmitted
        over the wire.
        """
        user_text = task.messages[-1].parts[0].content
        return task.complete(f"[{self.card.name}] echo: {user_text}")


def main() -> None:
    """Orchestrate the distributed network test sequence.

    This control plane executes the following architectural workflow:
    1. **Initialization**: Spins up a discrete agent on port 8020.
    2. **Background Execution**: Calls `.start(background=True)` to offload the
       Starlette server into a loop-isolated background thread.
    3. **Client Setup**: Initializes an `AgentClient` to communicate with the agent.
    4. **Card Discovery Test**: Validates the client's ability to query the remote server's
       metadata (via `GET /`).
    5. **Message Dispatch Test**: Validates sending atomic, stateless `Message` payloads
       across the network using `client.sync.send_message`.
    6. **Task Orchestration Test**: Validates sending stateful `Task` containers that track
       workflow progression using `client.sync.send_task`.
    7. **Graceful Teardown**: Synchronously terminates the background server.
    """

    # 1. Setup Server Agent
    server_port = 8020
    server_agent = EchoAgent("server_agent", "I echo messages", port=server_port)

    # Start the server in the background
    print(f"Starting server agent on port {server_port}...")
    server_agent.start(background=True)

    # 2. Setup AgentClient
    # The client is transport-agnostic and will handle communication over HTTP.
    client = AgentClient(transport="http")

    target_url = server_agent.card.url

    try:
        print(f"\nTarget Agent URL: {target_url}")

        # ---------------------------------------------------------
        # Test 1: get_agent_card
        # ---------------------------------------------------------
        print("\n--- Test 1: get_agent_card ---")
        card = client.sync.get_agent_card(target_url)
        print(f"SUCCESS: Retrieved card for '{card.name}'")
        print(f"Description: {card.description}")

        # ---------------------------------------------------------
        # Test 2: send_message
        # ---------------------------------------------------------
        print("\n--- Test 2: send_message ---")
        msg = Message.user("Hello World")
        response_msg = client.sync.send_message(target_url, msg)
        print(f"Sent: '{msg.parts[0].content}'")
        print(f"Received: '{response_msg.parts[0].content}'")

        assert "echo: Hello World" in response_msg.parts[0].content
        print("SUCCESS: Message echo verified.")

        # ---------------------------------------------------------
        # Test 3: Send Task
        # ---------------------------------------------------------
        print("\n--- Test 3: send_task ---")
        task = Task.create(Message.user("Do complex task"))
        response_task = client.sync.send_task(target_url, task)

        last_msg_content = response_task.messages[-1].parts[0].content
        print(f"Sent Task ID: {task.id}")
        print(f"Received Task Result: '{last_msg_content}'")

        assert "echo: Do complex task" in last_msg_content
        print("SUCCESS: Task echo verified.")

    except Exception as e:
        print(f"\nFAILED: {e}")
        raise
    finally:
        print("\nShutting down agents...")
        server_agent.stop()


if __name__ == "__main__":
    main()
