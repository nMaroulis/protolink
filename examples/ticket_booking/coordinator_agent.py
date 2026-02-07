"""
Coordinator Agent - The LLM-powered orchestrator.

This agent receives user vacation requests and coordinates with specialist agents
(Weather, Hotel) to fulfill the request using agent_call delegation.
"""

import asyncio
import os

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.llms.factory import create_llm

# System prompt that defines the coordinator's role and workflow
COORDINATOR_SYSTEM_PROMPT = """You are a vacation booking coordinator.

Your role is to help users plan and book trips by orchestrating available specialist agents.
You will discover available agents dynamically - each agent has a description and capabilities
that tell you what it can do.

When handling a vacation request, follow this general workflow:
1. **Gather information**: Get travel advice and destination recommendations from advisory agents.
2. **Check conditions**: Verify weather, availability, or other relevant factors before booking.
3. **Make bookings**: Reserve accommodations, transportation, or other services as needed.
4. **Summarize**: Provide the user with a complete summary of their trip details.

Use your judgment to determine which agents to consult based on their descriptions and the user's needs.
If an agent has an LLM, ask it for advice. If an agent has tools, call those tools with appropriate parameters.
"""


def create_coordinator_agent(
    registry: Registry,
    llm_provider: str = "ollama",
    **kwargs,
) -> Agent:
    """
    Create and configure the Coordinator Agent.

    Parameters
    ----------
    registry : Registry
        The agent registry for discovery
    llm_provider : str
        e.g. "ollama", "openai", "anthropic", "gemini"
    **kwargs
        Additional arguments for LLM creation
    """

    llm = create_llm(llm_provider, **kwargs)

    agent = Agent(
        card={
            "name": "coordinator",
            "description": "Vacation booking coordinator that orchestrates specialist agents",
            "url": os.getenv("COORDINATOR_URL", "http://localhost:8010"),
        },
        transport="http",
        registry=registry,
        llm=llm,
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
    )

    return agent


# For standalone execution
if __name__ == "__main__":
    from protolink.discovery import Registry

    registry = Registry(
        url=os.getenv("REGISTRY_URL", "http://localhost:9000"),
        transport="http",
    )

    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    agent = create_coordinator_agent(registry, llm_provider)
    asyncio.run(agent.start())
    print(f"Coordinator Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        asyncio.run(agent.stop())
