"""
Hotel Booking Agent - Tool-only specialist for accommodation booking.

This agent handles hotel searches and bookings.
No LLM is used - bookings are direct tool executions.
"""

import hashlib
import os
from datetime import date

from protolink.agents import Agent
from protolink.discovery import Registry

# Sample hotel inventory for Greek islands
HOTELS = {
    "santorini": [
        {
            "name": "Aegean Sunset Suites",
            "stars": 5,
            "price": 280,
            "amenities": ["pool", "spa", "breakfast", "sea view"],
        },
        {"name": "Oia Boutique Hotel", "stars": 4, "price": 180, "amenities": ["pool", "breakfast", "wifi"]},
        {"name": "Fira Central Stay", "stars": 3, "price": 95, "amenities": ["wifi", "breakfast"]},
    ],
    "mykonos": [
        {"name": "Mykonos Blu Resort", "stars": 5, "price": 320, "amenities": ["pool", "spa", "gym", "beach"]},
        {"name": "Windmill View Hotel", "stars": 4, "price": 195, "amenities": ["pool", "breakfast", "wifi"]},
        {"name": "Town Square Inn", "stars": 3, "price": 110, "amenities": ["wifi", "breakfast"]},
    ],
    "crete": [
        {"name": "Heraklion Palace", "stars": 5, "price": 240, "amenities": ["pool", "spa", "gym", "kids club"]},
        {"name": "Chania Harbor Hotel", "stars": 4, "price": 150, "amenities": ["pool", "breakfast", "sea view"]},
        {"name": "Rethymno Budget Stay", "stars": 3, "price": 75, "amenities": ["wifi", "breakfast"]},
    ],
}

# Default hotels for other islands
DEFAULT_HOTELS = [
    {"name": "Island Paradise Resort", "stars": 4, "price": 160, "amenities": ["pool", "breakfast", "wifi"]},
    {"name": "Seaside Budget Hotel", "stars": 3, "price": 85, "amenities": ["wifi", "breakfast"]},
]


def create_hotel_agent(registry: Registry | None = None, verbosity: int = 1) -> Agent:
    """Create and configure the Hotel Booking Agent."""

    agent = Agent(
        card={
            "name": "hotel_agent",
            "description": "Searches and books hotel accommodations.",
            "url": os.getenv("HOTEL_AGENT_URL", "http://localhost:8040"),
        },
        transport="http",
        registry=registry,
        verbosity=verbosity,
    )

    # The input schema is automatically inferred from the function signature and type hints.
    @agent.tool(
        name="book_hotel",
        description="Book a hotel for a vacation. Returns booking confirmation with details.",
    )
    def book_hotel(
        location: str,
        check_in: str,
        check_out: str,
        guests: int = 2,
        budget: str = "mid-range",
    ) -> dict:
        """
        Book a hotel for the specified location and dates.

        Parameters
        ----------
        location : str
            Destination (e.g., "Santorini")
        check_in : str
            Check-in date (YYYY-MM-DD)
        check_out : str
            Check-out date (YYYY-MM-DD)
        guests : int
            Number of guests
        budget : str
            Budget category: "budget", "mid-range", or "luxury"

        Returns
        -------
        dict
            Booking confirmation with hotel details and pricing
        """
        print(
            f"\n   🏨 [hotel_agent] book_hotel called: {location}, {check_in} to {check_out}, {guests} guests, {budget}"
        )

        location_key = location.lower().strip()

        # Get hotel inventory
        hotels = HOTELS.get(location_key, DEFAULT_HOTELS)

        # Select hotel based on budget
        budget_map = {"budget": 3, "mid-range": 4, "luxury": 5}
        target_stars = budget_map.get(budget.lower(), 4)

        # Find matching hotel
        hotel = None
        for h in hotels:
            if h["stars"] == target_stars:
                hotel = h
                break
        if not hotel:
            hotel = hotels[0]  # Fallback to first option

        # Calculate nights and total
        try:
            check_in_date = date.fromisoformat(check_in)
            check_out_date = date.fromisoformat(check_out)
            nights = (check_out_date - check_in_date).days
        except ValueError:
            nights = 3  # Default

        if nights <= 0:
            nights = 1

        total_price = hotel["price"] * nights

        # Generate booking ID
        booking_hash = hashlib.md5(f"{location}{check_in}{check_out}{guests}".encode()).hexdigest()[:8]

        result = {
            "status": "confirmed",
            "booking_id": f"HTL-{booking_hash.upper()}",
            "hotel": {
                "name": hotel["name"],
                "stars": hotel["stars"],
                "location": location.title(),
                "amenities": hotel["amenities"],
            },
            "reservation": {
                "check_in": check_in,
                "check_out": check_out,
                "nights": nights,
                "guests": guests,
                "room_type": "Double Room" if guests <= 2 else "Family Suite",
            },
            "pricing": {
                "price_per_night": hotel["price"],
                "total_price": total_price,
                "currency": "EUR",
            },
            "policies": {
                "check_in_time": "15:00",
                "check_out_time": "11:00",
                "cancellation": "Free cancellation until 24h before check-in",
            },
        }

        print(f"   🏨 [hotel_agent] → Booked {hotel['name']} ({hotel['stars']}⭐), €{total_price} total")
        return result

    return agent


# For standalone execution
if __name__ == "__main__":
    agent = create_hotel_agent()
    print(f"Hotel Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()
