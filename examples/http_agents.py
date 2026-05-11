"""HTTP transport example to verify Agent Client functionality."""

from __future__ import annotations

import asyncio

from protolink.agents import Agent
from protolink.models import AgentCard, Message, Task
from protolink.transport import HTTPTransport


class EchoAgent(Agent):
    """Simple agent that replies with a templated message."""

    def __init__(self, name: str, description: str, port: int) -> None:
        transport = HTTPTransport(url=f"http://127.0.0.1:{port}", backend="starlette")
        card = AgentCard(name=name, description=description, url=f"http://127.0.0.1:{port}")
        super().__init__(card, transport=transport)

    async def handle_task(self, task: Task) -> Task:
        user_text = task.messages[-1].parts[0].content
        return task.complete(f"[{self.card.name}] echo: {user_text}")


async def main() -> None:
    """Spin up agents and verify client functions."""

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
