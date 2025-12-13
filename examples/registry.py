import asyncio

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.models import AgentCard, Message, Task
from protolink.transport import HTTPAgentTransport


# ----------------------------------------------------------------------
# Autonomous Agent Class Extension
# ----------------------------------------------------------------------
class AutonomousAgent(Agent):
    """An agent that autonomously discovers peers and sends a task after a delay."""

    async def start(self) -> None:
        """Start agent server and autonomous logic."""
        await super().start()  # starts server and auto-registers
        self._autonomous_task = asyncio.create_task(self.autonomous_loop())

    async def handle_task(self, task: Task) -> Task:
        """Simple handler that replies to user messages."""
        # echo back the last user message
        user_message = task.messages[-1].parts[0].content if task.messages else "Hello"
        response = Message.agent(f"Received your message: {user_message}")
        task.add_message(response)
        return task

    async def stop(self) -> None:
        """Stop the agent and cancel autonomous task."""
        # Cancel the autonomous background task if it exists
        if hasattr(self, "_autonomous_task"):
            self._autonomous_task.cancel()
            try:
                await self._autonomous_task
            except asyncio.CancelledError:
                pass  # Expected when cancelling

        await super().stop()

    async def autonomous_loop(self):
        """Autonomous loop: wait 10s, discover other agents, send task."""
        await asyncio.sleep(6)  # wait before acting

        print(f"[{self.card.name}] Discovering other agents...")
        agents = await self.discover_agents()
        peers = [a for a in agents if a.url != self.card.url]
        print("-------------------")
        print("Agents Discovered:")
        for a in agents:
            print(a)
        print("-------------------")
        for peer in peers:
            print(f"[{self.card.name}] Sending task to {peer.name}")
            task = Task.create(Message.user(f"Hello from {self.card.name}!"))
            result_task = await self.send_task_to(peer.url, task)
            for msg in result_task.messages:
                print(f"[{peer.name} -> {self.card.name}] {msg.role}: {msg.parts[0].content}")


# ----------------------------------------------------------------------
# Setup Registry
# ----------------------------------------------------------------------
async def start_registry() -> Registry:
    registry = Registry(url="http://localhost:9000")
    await registry.start()
    print("[Registry] Running at http://localhost:9000")
    return registry


# ----------------------------------------------------------------------
# Setup Agent
# ----------------------------------------------------------------------
async def setup_agent(name: str, port: int) -> AutonomousAgent:
    card = AgentCard(name=name, url=f"http://localhost:{port}", description="Does all the work", skills=[])
    transport = HTTPAgentTransport(url=f"http://localhost:{port}")
    agent = AutonomousAgent(card=card, transport=transport, registry="http://localhost:9000")
    await agent.start()  # starts server and autonomous loop
    print(f"[{name}] Started and registered to registry.")
    return agent


# ----------------------------------------------------------------------
# Main Orchestrator
# ----------------------------------------------------------------------
async def main():
    registry = await start_registry()
    agent1 = await setup_agent("agent1", 8001)
    agent2 = await setup_agent("agent2", 8002)

    # Keep the script alive long enough for autonomous actions
    await asyncio.sleep(40)

    # Cleanup
    await agent1.stop()
    await agent2.stop()
    await registry.stop()


if __name__ == "__main__":
    asyncio.run(main())
