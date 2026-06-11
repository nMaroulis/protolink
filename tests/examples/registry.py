"""Registry Example - Dynamic Agent Discovery.

This script demonstrates how to leverage the `Registry` service to enable dynamic
discovery of agents. Instead of hardcoding agent URLs, clients can query the
registry to find available agents by name or capabilities.

Workflow:
1. Start a centralized `Registry` service.
2. Start an `Agent` that automatically registers its identity and URL to the registry.
3. Use the `Registry` to discover the agent's endpoint.
4. Communicate with the discovered agent using `AgentClient`.
"""

from __future__ import annotations

import asyncio
import time

from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.models import AgentCard, Message, Task
from protolink.transport import HTTPTransport


class EchoAgent(Agent):
    """A simple agent that echoes back messages."""

    def __init__(self, name: str, description: str, port: int, registry: Registry) -> None:
        # Configure transport
        transport = HTTPTransport(url=f"http://127.0.0.1:{port}")
        card = AgentCard(name=name, description=description, url=f"http://127.0.0.1:{port}")

        # Initialize with registry to enable auto-registration
        super().__init__(card, transport=transport, registry=registry)

    async def handle_task(self, task: Task) -> Task:
        """Echo the last message back."""
        user_text = task.messages[-1].parts[0].content
        return task.complete(f"[{self.card.name}] echo: {user_text}")


def main() -> None:
    """Orchestrate the registry discovery test."""

    registry_url = "http://127.0.0.1:9000"
    server_port = 8020

    # 1. Start the Registry
    # The registry acts as a phonebook for agents.
    print(f"Starting Registry at {registry_url}...")
    registry = Registry(url=registry_url, transport="http")
    registry.start(background=True)

    # 2. Start the Agent
    # By passing the registry instance, the agent will call `register()` upon startup.
    print(f"Starting EchoAgent on port {server_port}...")
    agent = EchoAgent(
        name="discovery_agent",
        description="I am a discoverable service",
        port=server_port,
        registry=registry,
    )
    agent.start(background=True)

    time.sleep(1.0)

    # 3. Discover Agents via Registry
    # In a real distributed system, the client wouldn't know the agent's port.
    # It only knows the Registry URL.
    print("\n--- Step 3: Discovery ---")

    # We use the registry's discovery method. Since this example is a sync script,
    # we run the async discover() method using asyncio.run().
    discovered_cards = asyncio.run(registry.discover())

    print(f"Found {len(discovered_cards)} agent(s) in the registry:")
    for card in discovered_cards:
        print(f"  • Name: {card.name}")
        print(f"    URL:  {card.url}")
        print(f"    Role: {card.description}")

    if not discovered_cards:
        print("FAILED: No agents discovered.")
        return

    # 4. Communicate with the discovered agent
    # We take the first discovered agent and talk to it via its registered URL.
    target_card = discovered_cards[0]
    client = AgentClient(transport="http")

    print(f"\n--- Step 4: Communication with {target_card.name} ---")
    msg = Message.user("Is anyone there?")

    # Use the synchronous client API
    response = client.sync.send_message(target_card.url, msg)

    print(f"Sent: '{msg.parts[0].content}'")
    print(f"Received: '{response.parts[0].content}'")

    # 5. Cleanup
    print("\nShutting down...")
    agent.stop()
    registry.stop()
    print("Done.")


if __name__ == "__main__":
    main()
