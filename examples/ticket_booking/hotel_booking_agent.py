import hashlib
import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from dotenv import load_dotenv

from protolink.agents import Agent
from protolink.models import Task

load_dotenv("./endpoints.env")


AGENT_CARD = {
    "url": os.getenv("HOTEL_AGENT_URL"),
    "name": "hotel_booking_agent",
    "description": "Books hotels and returns the tickets",
}


class HotelBookingAgent(Agent):
    async def handle_task(self, task: Task) -> Task:
        """
        Override the handle_task method to receive a request.
        """
        # TODO: Implement hotel booking logic here
        # For now, just return the task as is
        return await super().handle_task(task)


agent = HotelBookingAgent(
    card=AGENT_CARD,
    transport="http",
    registry="http",
    registry_url=os.getenv("REGISTRY_URL"),
)


def _parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string (YYYY-MM-DD). Got: {value!r}") from exc


def _to_decimal_money(value: str | int | float | None, *, field_name: str) -> Decimal | None:
    if value is None:
        return None

    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a number. Got: {value!r}") from exc

    if dec < 0:
        raise ValueError(f"{field_name} must be >= 0. Got: {value!r}")
    return dec


def _quantize_currency(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@agent.tool(
    name="book_hotel",
    description="Book a hotel and return a structured booking confirmation.",
    tags=["booking"],
)
async def book_hotel(
    location: str,
    check_in: str,
    check_out: str,
    *,
    adults: int = 1,
    children: int = 0,
    rooms: int = 1,
    currency: str = "USD",
    min_price_per_night: float | int | str | None = None,
    max_price_per_night: float | int | str | None = None,
    hotel_class: int | None = None,
    refundable: bool | None = None,
    preferences: list[str] | None = None,
) -> dict[str, Any]:
    """Book a hotel (dummy implementation with professional validation).

    Parameters
    ----------
    location:
        Destination city/area.
    check_in, check_out:
        ISO date strings (YYYY-MM-DD). ``check_out`` must be after ``check_in``.
    adults, children, rooms:
        Guest composition.
    currency:
        3-letter ISO currency code.
    min_price_per_night, max_price_per_night:
        Optional nightly budget bounds.
    hotel_class:
        Optional star rating constraint (1-5).
    refundable:
        Optional preference for refundable rates.
    preferences:
        Optional list of preferences (e.g. ["breakfast_included", "wifi", "gym"]).

    Returns
    -------
    dict
        JSON-serializable booking confirmation.
    """

    normalized_location = (location or "").strip()
    if not normalized_location:
        raise ValueError("location must be a non-empty string")

    check_in_date = _parse_iso_date(check_in, field_name="check_in")
    check_out_date = _parse_iso_date(check_out, field_name="check_out")
    if check_out_date <= check_in_date:
        raise ValueError("check_out must be after check_in")

    if adults < 1:
        raise ValueError("adults must be >= 1")
    if children < 0:
        raise ValueError("children must be >= 0")
    if rooms < 1:
        raise ValueError("rooms must be >= 1")

    currency_code = (currency or "").strip().upper()
    if len(currency_code) != 3 or not currency_code.isalpha():
        raise ValueError("currency must be a 3-letter ISO code (e.g. 'USD')")

    min_dec = _to_decimal_money(min_price_per_night, field_name="min_price_per_night")
    max_dec = _to_decimal_money(max_price_per_night, field_name="max_price_per_night")
    if min_dec is not None and max_dec is not None and min_dec > max_dec:
        raise ValueError("min_price_per_night must be <= max_price_per_night")

    if hotel_class is not None and hotel_class not in {1, 2, 3, 4, 5}:
        raise ValueError("hotel_class must be one of: 1, 2, 3, 4, 5")

    pref_list = [p.strip().lower() for p in (preferences or []) if p and p.strip()]
    nights = (check_out_date - check_in_date).days

    # Dummy hotel inventory (would be replaced with a real provider integration).
    inventory = [
        {
            "hotel_id": "H-ALPINE-001",
            "name": "Alpine Grand Hotel",
            "class": 5,
            "area": "City Center",
            "amenities": ["wifi", "gym", "spa", "breakfast_included"],
            "base_price_per_night": Decimal("220.00"),
            "refundable": True,
        },
        {
            "hotel_id": "H-CENTRAL-014",
            "name": "Central Boutique Stay",
            "class": 4,
            "area": "Old Town",
            "amenities": ["wifi", "breakfast_included"],
            "base_price_per_night": Decimal("145.00"),
            "refundable": False,
        },
        {
            "hotel_id": "H-BUDGET-207",
            "name": "Riverside Budget Inn",
            "class": 3,
            "area": "Riverside",
            "amenities": ["wifi"],
            "base_price_per_night": Decimal("89.00"),
            "refundable": True,
        },
    ]

    def matches(h: dict[str, Any]) -> bool:
        if hotel_class is not None and h["class"] != hotel_class:
            return False
        if refundable is not None and bool(h["refundable"]) != refundable:
            return False
        price = h["base_price_per_night"]
        if min_dec is not None and price < min_dec:
            return False
        if max_dec is not None and price > max_dec:
            return False
        if pref_list:
            amenities = set(h["amenities"])  # type: ignore[arg-type]
            if not set(pref_list).issubset(amenities):
                return False
        return True

    candidates = [h for h in inventory if matches(h)]
    if not candidates:
        raise ValueError(
            "No hotels found matching constraints. Try relaxing hotel_class/refundable/preferences/price range."
        )

    # Deterministic selection for repeatability.
    selector_payload = "|".join(
        [
            normalized_location.lower(),
            check_in_date.isoformat(),
            check_out_date.isoformat(),
            str(adults),
            str(children),
            str(rooms),
            currency_code,
            ",".join(sorted(pref_list)),
            str(hotel_class) if hotel_class is not None else "",
            str(refundable) if refundable is not None else "",
        ]
    )
    digest = hashlib.sha256(selector_payload.encode("utf-8")).hexdigest()
    chosen = candidates[int(digest[:8], 16) % len(candidates)]

    # Pricing model (dummy): base * nights * rooms + a fixed service fee.
    nightly = chosen["base_price_per_night"]
    service_fee = Decimal("12.50")
    subtotal = nightly * Decimal(nights) * Decimal(rooms)
    total = _quantize_currency(subtotal + service_fee)

    booking_id = f"BK-{digest[:10].upper()}"
    confirmation_number = digest[10:18].upper()

    return {
        "status": "confirmed",
        "booking_id": booking_id,
        "confirmation_number": confirmation_number,
        "provider": "protolink-demo-provider",
        "trip": {
            "location": normalized_location,
            "check_in": check_in_date.isoformat(),
            "check_out": check_out_date.isoformat(),
            "nights": nights,
            "guests": {"adults": adults, "children": children},
            "rooms": rooms,
        },
        "hotel": {
            "hotel_id": chosen["hotel_id"],
            "name": chosen["name"],
            "class": chosen["class"],
            "area": chosen["area"],
            "amenities": chosen["amenities"],
            "refundable": chosen["refundable"],
        },
        "price": {
            "currency": currency_code,
            "nightly": str(_quantize_currency(nightly)),
            "service_fee": str(_quantize_currency(service_fee)),
            "total": str(total),
        },
        "requested_constraints": {
            "min_price_per_night": str(_quantize_currency(min_dec)) if min_dec is not None else None,
            "max_price_per_night": str(_quantize_currency(max_dec)) if max_dec is not None else None,
            "hotel_class": hotel_class,
            "refundable": refundable,
            "preferences": pref_list or None,
        },
        "policies": {
            "cancellation": "Free cancellation until 24h before check-in" if chosen["refundable"] else "Non-refundable",
            "check_in_time": "15:00",
            "check_out_time": "11:00",
        },
    }
