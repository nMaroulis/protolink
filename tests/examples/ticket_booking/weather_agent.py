"""
Weather Agent - Tool-only specialist for weather data.

This agent provides weather forecasts for vacation destinations.
No LLM is used - weather data is deterministic.
"""

import os
from datetime import datetime

from protolink.agents import Agent
from protolink.discovery import Registry

# Greek islands with realistic summer weather
WEATHER_DATA = {
    "santorini": {"temp": 28, "condition": "Sunny", "humidity": 45, "wind": "Light breeze"},
    "mykonos": {"temp": 27, "condition": "Sunny", "humidity": 50, "wind": "Moderate"},
    "crete": {"temp": 30, "condition": "Clear", "humidity": 40, "wind": "Light"},
    "rhodes": {"temp": 29, "condition": "Sunny", "humidity": 48, "wind": "Calm"},
    "corfu": {"temp": 26, "condition": "Partly cloudy", "humidity": 55, "wind": "Light breeze"},
    "zakynthos": {"temp": 27, "condition": "Sunny", "humidity": 52, "wind": "Light"},
    "naxos": {"temp": 26, "condition": "Clear", "humidity": 47, "wind": "Moderate"},
    "paros": {"temp": 27, "condition": "Sunny", "humidity": 49, "wind": "Light breeze"},
}


def create_weather_agent(registry: Registry | None = None, verbosity: int = 1) -> Agent:
    """Create and configure the Weather Agent."""

    agent = Agent(
        card={
            "name": "weather_agent",
            "description": "Provides weather forecasts for any location.",
            "url": os.getenv("WEATHER_AGENT_URL", "http://localhost:8030"),
        },
        transport="http",
        registry=registry,
        verbosity=verbosity,
    )

    @agent.tool(
        name="get_weather",
        description="Get current weather forecast for a Greek island destination",
        input_schema={
            "location": str,
            "travel_date": str,  # Optional, for display purposes
        },
    )
    def get_weather(location: str, travel_date: str = "") -> dict:
        """
        Get weather forecast for a location.

        Parameters
        ----------
        location : str
            The destination (e.g., "Santorini", "Mykonos")
        travel_date : str
            Optional travel date for context

        Returns
        -------
        dict
            Weather forecast with temperature, conditions, and recommendation
        """
        print(f"\n   🌤️  [weather_agent] get_weather called: location={location}, date={travel_date}")

        location_key = location.lower().strip()

        if location_key not in WEATHER_DATA:
            # Return generic Mediterranean summer weather for unknown locations
            weather = {"temp": 27, "condition": "Sunny", "humidity": 50, "wind": "Light"}
        else:
            weather = WEATHER_DATA[location_key]

        # Determine if weather is suitable for vacation
        is_good = weather["temp"] >= 24 and weather["condition"] in ["Sunny", "Clear", "Partly cloudy"]

        result = {
            "location": location.title(),
            "date": travel_date or "Summer season",
            "temperature_celsius": weather["temp"],
            "condition": weather["condition"],
            "humidity_percent": weather["humidity"],
            "wind": weather["wind"],
            "suitable_for_vacation": is_good,
            "recommendation": "Perfect weather for a beach vacation!"
            if is_good
            else "Consider checking alternative dates.",
            "timestamp": datetime.now().isoformat(),
        }

        print(f"   🌤️  [weather_agent] → {weather['temp']}°C, {weather['condition']}, suitable={is_good}")
        return result

    return agent


# For standalone execution
if __name__ == "__main__":
    agent = create_weather_agent()
    print(f"Weather Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()
