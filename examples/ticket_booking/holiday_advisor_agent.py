"""
Holiday Advisor Agent - LLM-powered vacation recommendations.

This agent evaluates vacation destinations and provides recommendations.
It uses an LLM for reasoning - no tools needed.

This showcases agent_call with action "infer" (LLM-to-LLM delegation).
"""

import asyncio
import os

from protolink.agents import Agent
from protolink.discovery import Registry
from protolink.llms.factory import create_llm

# System prompt for the advisor's reasoning
ADVISOR_SYSTEM_PROMPT = """You are a Greek islands vacation expert. Your job is to evaluate
vacation destinations and provide recommendations.

When asked about a destination, consider:
1. Is this a good choice for the given dates?
2. Is the budget realistic for this destination?
3. Is it suitable for the number of travelers?
4. What are the highlights and potential concerns?

RESPONSE FORMAT:
Always provide a structured response with:
- verdict: "recommended" or "not_recommended" or "consider_alternatives"
- destination: the evaluated location
- reasoning: 2-3 sentences explaining your verdict
- highlights: list of 2-3 things that make this destination great
- tips: 1-2 practical travel tips
- alternative: if not recommended, suggest ONE better option with a brief reason

Keep responses concise and helpful. You are the expert - be confident in your advice.
"""


def create_advisor_agent(
    registry: Registry | None = None,
    llm_provider: str = "ollama",
    verbosity: int = 1,
    **kwargs,
) -> Agent:
    """
    Create and configure the Holiday Advisor Agent.

    Parameters
    ----------
    registry : Registry, optional
        The agent registry for discovery
    llm_provider : str
        e.g. "ollama", "openai", "anthropic", "gemini"
    **kwargs
        Additional arguments for LLM creation
    """

    # Use factory to create LLM
    llm = create_llm(llm_provider, **kwargs)

    # Custom agent class with logging
    class HolidayAdvisorAgent(Agent):
        async def handle_task(self, task):
            # Log the incoming request
            content = task.get_last_part_content() if task.messages else "No prompt"

            # Handle both string (text part) and dict (infer part) content
            if isinstance(content, dict):
                prompt = content.get("prompt", str(content))
            else:
                prompt = str(content)

            print(f"\n   🧭 [holiday_advisor] infer called with: {prompt[:80]}...")

            # Call the parent's handle_task (which uses LLM.infer)
            result = await super().handle_task(task)

            # Log the response
            response_content = result.get_last_part_content() if result else "No response"
            response_str = str(response_content)
            preview = response_str[:100].replace("\n", " ") if response_str else ""
            print(f"   🧭 [holiday_advisor] → {preview}...")

            return result

    agent = HolidayAdvisorAgent(
        card={
            "name": "holiday_advisor",
            "description": "Vacation expert that evaluates destinations and provides recommendations",
            "url": os.getenv("ADVISOR_URL", "http://localhost:8020"),
        },
        transport="http",
        registry=registry,
        llm=llm,
        system_prompt=ADVISOR_SYSTEM_PROMPT,
        verbosity=verbosity,
    )

    return agent


# For standalone execution
if __name__ == "__main__":
    registry = Registry(
        url=os.getenv("REGISTRY_URL", "http://localhost:9000"),
        transport="http",
    )

    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    agent = create_advisor_agent(registry, llm_provider)
    asyncio.run(agent.start())
    print(f"Holiday Advisor Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        asyncio.run(agent.stop())
