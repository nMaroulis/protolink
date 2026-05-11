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

import asyncio

from protolink.agents import Agent
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


async def main() -> None:
    """Orchestrate the distributed network test sequence.

    This control plane executes the following architectural workflow:
    1. **Initialization**: Spins up two discrete agents on isolated network ports (8020 and 8021).
    2. **Background Execution**: Calls `.start(background=True)` to offload their respective
       Starlette servers into highly concurrent, loop-isolated background threads.
    3. **Card Discovery Test**: Validates the client's ability to query the remote server's
       metadata (via `GET /`).
    4. **Message Dispatch Test**: Validates sending atomic, stateless `Message` payloads
       across the network.
    5. **Task Orchestration Test**: Validates sending stateful `Task` containers that track
       workflow progression and return mutated state.
    6. **Graceful Teardown**: Synchronously terminates the background servers and closes
       all TCP sockets.
    """

    # 1. Setup Agents
    server_port = 8020
    client_port = 8021

    server_agent = EchoAgent("server_agent", "I echo messages", port=server_port)
    client_agent = EchoAgent("client_agent", "I am the client", port=client_port)

    # Start both
    server_agent.start(background=True)
    client_agent.start(background=True)

    # Wait briefly for startup
    await asyncio.sleep(0.5)

    target_url = server_agent.card.url

    try:
        print(f"\nTarget Agent URL: {target_url}")

        # ---------------------------------------------------------
        # Test 1: get_agent_card
        # Accessing via _client as Agent doesn't expose it directly yet,
        # but User asked to test client funcs from the agent.
        # ---------------------------------------------------------
        print("\n--- Test 1: get_agent_card ---")
        if client_agent._client:
            card = await client_agent._client.get_agent_card(target_url)
            print(f"SUCCESS: Retrieved card for '{card.name}'")
            print(f"Description: {card.description}")
        else:
            print("ERROR: Client agent has no transport client configured.")

        # ---------------------------------------------------------
        # Test 2: send_message (via Agent.send_message_to)
        # ---------------------------------------------------------
        print("\n--- Test 2: send_message_to ---")
        msg = Message.user("Hello World")
        response_msg = await client_agent.send_message_to(target_url, msg)
        print(f"Sent: '{msg.parts[0].content}'")
        print(f"Received: '{response_msg.parts[0].content}'")

        assert "echo: Hello World" in response_msg.parts[0].content
        print("SUCCESS: Message echo verified.")

        # ---------------------------------------------------------
        # Test 3: Send Task (via Agent.call_agent)
        # ---------------------------------------------------------
        print("\n--- Test 3: call_agent ---")
        task = Task.create(Message.user("Do complex task"))
        response_task = await client_agent.call_agent(target_url, task)

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
        client_agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
