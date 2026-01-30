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

# System prompt that instructs the LLM how to coordinate agents
COORDINATOR_SYSTEM_PROMPT = """You are a vacation booking coordinator. Your job is to help users plan and book
trips to Greek islands.

You have access to THREE specialist agents:

1. **holiday_advisor** - A vacation expert (has LLM, no tools).
   Use agent_call with action "infer" to ask for destination recommendations.
   Ask about: location, dates, budget, number of travelers.

2. **weather_agent** - Has a `get_weather` tool to check weather conditions.
   Use agent_call with action "tool_call" to get weather data.

3. **hotel_agent** - Has a `book_hotel` tool to book accommodations.
   Use agent_call with action "tool_call" to book hotels.

WORKFLOW:
When a user asks to book a vacation:
1. FIRST, ask holiday_advisor (using "infer") if this destination is recommended
2. Check weather using weather_agent (using "tool_call")
3. If advisor recommends and weather is good, book hotel using hotel_agent (using "tool_call")
4. Provide a complete summary including advisor's recommendation, weather, and booking

HOW TO USE agent_call:
- For holiday_advisor (LLM): {"type": "agent_call", "action": "infer", "agent": "holiday_advisor", "prompt": "Is Santorini good for a 5-night trip in July for 2 people with mid-range budget?"}
- For weather_agent (tool): {"type": "agent_call", "action": "tool_call", "agent": "weather_agent", "tool": "get_weather", "args": {"location": "Santorini", "travel_date": "2026-07-15"}}
- For hotel_agent (tool): {"type": "agent_call", "action": "tool_call", "agent": "hotel_agent", "tool": "book_hotel", "args": {"location": "Santorini", "check_in": "2026-07-15", "check_out": "2026-07-20", "guests": 2, "budget": "mid-range"}}

IMPORTANT:
- Always consult the holiday_advisor FIRST
- Use action "infer" for holiday_advisor (it has an LLM, not tools)
- Use action "tool_call" for weather_agent and hotel_agent
- For dates, use format YYYY-MM-DD (e.g., 2026-07-15)
- For budget, use: "budget", "mid-range", or "luxury"
- If user doesn't specify dates, suggest July or August 2026
- If user doesn't specify budget, assume mid-range
"""  # noqa: E501


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
