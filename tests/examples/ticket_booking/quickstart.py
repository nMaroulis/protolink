import asyncio
from datetime import date, datetime

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.client import AgentClient
from protolink.discovery import Registry
from protolink.llms.api import OpenAILLM
from protolink.models import Task

load_dotenv(".env")

REGISTRY_URL = "http://localhost:9010"
COORDINATOR_URL = "http://localhost:8010"
HOLIDAY_ADVISOR_URL = "http://localhost:8020"
WEATHER_AGENT_URL = "http://localhost:8030"
HOTEL_BOOKING_AGENT_URL = "http://localhost:8040"


async def main():
    # ---------------------------------------------------------
    # (1) REGISTRY
    # ---------------------------------------------------------

    registry = Registry(transport="http", url=REGISTRY_URL)
    # Start the Registry simply by using .start()
    registry.start(background=True)

    # ---------------------------------------------------------
    # (2) VACATION ADVISOR AGENT
    # ---------------------------------------------------------

    # pass the key directly as an argument or leave empty to use environment variables
    llm = OpenAILLM(model="gpt-4o")

    # The following prompt will be added to the existing predefined system prompt given by Protolink.
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
    """  # noqa: N806

    agent_card = {
        "name": "holiday_advisor",
        "description": "Expert travel consultant who recommends destinations",
        "url": HOLIDAY_ADVISOR_URL,
    }

    agent = Agent(
        card=agent_card,
        transport="http",
        llm=llm,
        registry="http",
        registry_url=REGISTRY_URL,
        system_prompt=ADVISOR_SYSTEM_PROMPT,
        verbosity=2,
    )

    agent.start(background=True)

    # ---------------------------------------------------------
    # (3) WEATHER AGENT
    # ---------------------------------------------------------

    agent_card = {
        "name": "weather_agent",
        "description": "Weather forecast provider",
        "url": WEATHER_AGENT_URL,
    }

    agent = Agent(
        card=agent_card,
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )

    # Adding a tool to the agent using the tool decorator
    @agent.tool(
        name="get_weather",
        description="Get current weather forecast for a Greek island",
        input_schema={"location": str, "travel_date": str},
    )
    def get_weather(location: str, travel_date: str) -> dict:
        # Connects to real APIs, databases, or static data.
        # Now just provides dummy data
        result = {
            "location": location,
            "date": travel_date or "Summer season",
            "temperature_celsius": 32,
            "condition": "Sunny",
            "humidity_percent": 50,
            "wind": "moderate",
            "suitable_for_vacation": True,
            "recommendation": "Perfect weather for a beach vacation!",
            "timestamp": datetime.now().isoformat(),
        }
        return result

    agent.start(background=True)

    # ---------------------------------------------------------
    # (4) HOTEL BOOKING AGENT
    # ---------------------------------------------------------

    agent = Agent(
        card={
            "name": "hotel_agent",
            "description": "Searches and books hotel accommodations.",
            "url": HOTEL_BOOKING_AGENT_URL,
        },
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        verbosity=2,
    )

    @agent.tool(
        name="book_hotel",
        description="Book a hotel for a vacation. Returns booking confirmation with details.",
        input_schema={
            "location": str,
            "check_in": str,
            "check_out": str,
            "guests": int,
            "budget": str,  # "budget", "mid-range", or "luxury"
        },
    )
    def book_hotel(
        location: str,
        check_in: str,
        check_out: str,
        guests: int = 2,
        budget: str = "mid-range",
    ) -> dict:
        try:
            check_in_date = date.fromisoformat(check_in)
            check_out_date = date.fromisoformat(check_out)
            nights = (check_out_date - check_in_date).days
        except ValueError:
            nights = 3  # Default

        total_price = 280 * nights

        # Execute transaction
        booking_id = {
            "status": "confirmed",
            "booking_id": "HTL-DAS98DA8D79D2JD9",
            "hotel": {
                "name": "Aegean Sunset Suites",
                "stars": 4,
                "location": location.title(),
                "amenities": ["pool", "spa", "breakfast", "sea view"],
            },
            "reservation": {
                "check_in": check_in,
                "check_out": check_out,
                "nights": nights,
                "guests": guests,
                "room_type": "Double Room" if guests <= 2 else "Family Suite",
            },
            "pricing": {
                "price_per_night": 280,
                "total_price": total_price,
                "currency": "EUR",
            },
            "policies": {
                "check_in_time": "15:00",
                "check_out_time": "11:00",
                "cancellation": "Free cancellation until 24h before check-in",
            },
        }

        return {"status": "confirmed", "booking_id": booking_id}

    agent.start(background=True)

    # ---------------------------------------------------------
    # (5) COORDINATOR AGENT
    # ---------------------------------------------------------

    llm = OpenAILLM(model="gpt-4o")

    agent_card = {
        "name": "coordinator",
        "description": "Vacation booking coordinator that orchestrates specialist agents",
        "url": COORDINATOR_URL,
    }

    # prompt the User can define in order to give a Role to the Agent
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
    """  # noqa: N806

    agent = Agent(
        card=agent_card,
        transport="http",
        registry="http",
        registry_url=REGISTRY_URL,
        llm=llm,
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        verbosity=2,
    )

    agent.start(background=True)

    # ---------------------------------------------------------
    # (6) AGENT CLIENT - TASK - USER INTERFACE
    # ---------------------------------------------------------

    # define Task
    user_query = "Book me a relaxing vacation to Santorini for 5 nights in mid-July 2026"
    task = Task.create_infer(prompt=user_query)

    client = AgentClient(transport="http", url="http://localhost:8050")

    result = await client.send_task(agent_url=COORDINATOR_URL, task=task)

    print("✅ RESULT:")
    print("-" * 70)
    print(result.get_last_part_content())
    print("-" * 70)

    # Keep running until Ctrl+C
    print("\nPress Ctrl+C to exit...")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        print("\nShutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
