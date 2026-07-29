"""Deterministic fixtures and case generation for the infer-loop benchmark."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from .models import CATEGORIES, BenchmarkCase, ExpectedAction

_RECEIPT_SALT = "protolink-infer-benchmark-v1"


def _stable_receipt(prefix: str, payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{_RECEIPT_SALT}:{prefix}:{normalized}".encode()).hexdigest()[:10].upper()
    return f"BENCH-{prefix}-{digest}"


def _multiply_result(*, a: int, b: int, request_id: str) -> dict[str, Any]:
    result = {"a": a, "b": b, "product": a * b, "request_id": request_id}
    return {**result, "receipt": _stable_receipt("MUL", result)}


def _join_result(*, left: str, right: str, separator: str, request_id: str) -> dict[str, Any]:
    result = {
        "joined": f"{left}{separator}{right}",
        "left": left,
        "right": right,
        "separator": separator,
        "request_id": request_id,
    }
    return {**result, "receipt": _stable_receipt("JOIN", result)}


_SOURCE_FILES: dict[str, dict[str, Any]] = {
    "utils.py": {"digest": "SRC-U7F31", "symbols": ["clamp", "slugify"], "line_count": 18},
    "pricing.py": {"digest": "SRC-P9A22", "symbols": ["calculate_total", "discount_rate"], "line_count": 27},
    "models.py": {"digest": "SRC-M4C08", "symbols": ["Booking", "Ticket"], "line_count": 31},
    "router.py": {"digest": "SRC-R2D77", "symbols": ["choose_route", "normalize_path"], "line_count": 24},
}
_SEARCH_INDEX: dict[str, list[str]] = {
    "clamp": ["utils.py:4"],
    "slugify": ["utils.py:11"],
    "calculate_total": ["pricing.py:6", "tests/test_pricing.py:14"],
    "Ticket": ["models.py:19", "router.py:8"],
    "normalize_path": ["router.py:15"],
}


def _read_file_result(*, path: str, request_id: str) -> dict[str, Any]:
    source = _SOURCE_FILES[path]
    result = {"path": path, "request_id": request_id, **source}
    return {**result, "receipt": _stable_receipt("READ", result)}


def _search_symbol_result(
    *,
    query: str,
    request_id: str,
    source_receipt: str,
) -> dict[str, Any]:
    result = {
        "query": query,
        "request_id": request_id,
        "source_receipt": source_receipt,
        "matches": _SEARCH_INDEX.get(query, []),
        "index_revision": "IDX-42",
    }
    return {**result, "receipt": _stable_receipt("SEARCH", result)}


_WEATHER: dict[str, tuple[int, str]] = {
    "Santorini": (28, "sunny"),
    "Zurich": (19, "rain"),
    "Kyoto": (23, "cloudy"),
    "Reykjavik": (11, "windy"),
    "Lisbon": (26, "clear"),
}


def _weather_result(*, location: str, travel_date: str, request_id: str) -> dict[str, Any]:
    temperature, condition = _WEATHER[location]
    result = {
        "location": location,
        "travel_date": travel_date,
        "temperature_c": temperature,
        "condition": condition,
        "request_id": request_id,
    }
    return {**result, "receipt": _stable_receipt("WX", result)}


_HOTEL_BASE_PRICE = {"budget": 90, "mid": 180, "luxury": 310}
_LOCATION_PRICE_ADJUSTMENT = {"Santorini": 25, "Zurich": 40, "Kyoto": 15, "Reykjavik": 35, "Lisbon": 10}


def _hotel_result(
    *,
    location: str,
    nights: int,
    guests: int,
    tier: str,
    request_id: str,
    weather_receipt: str,
) -> dict[str, Any]:
    nightly = _HOTEL_BASE_PRICE[tier] + _LOCATION_PRICE_ADJUSTMENT[location]
    result = {
        "location": location,
        "nights": nights,
        "guests": guests,
        "tier": tier,
        "request_id": request_id,
        "weather_receipt": weather_receipt,
        "nightly_eur": nightly,
        "total_eur": nightly * nights,
    }
    return {**result, "receipt": _stable_receipt("HOTEL", result)}


_ORACLE_VERDICTS = {
    "REF-A1": "amber",
    "REF-B7": "green",
    "REF-C3": "red",
    "REF-D9": "green",
    "REF-E5": "amber",
}


def _oracle_result(
    *,
    reference: str,
    request_id: str,
    evidence_receipt: str,
) -> dict[str, Any]:
    result = {
        "reference": reference,
        "request_id": request_id,
        "evidence_receipt": evidence_receipt,
        "verdict": _ORACLE_VERDICTS[reference],
    }
    return {**result, "receipt": _stable_receipt("ORACLE", result)}


def _request_id(seed: int, index: int) -> str:
    return f"REQ-{abs(seed) % 100000:05d}-{index + 1:04d}"


def _direct_case(index: int, ordinal: int, seed: int, _rng: random.Random) -> BenchmarkCase:
    request_id = _request_id(seed, index)
    token = _stable_receipt("FINAL", {"request_id": request_id, "ordinal": ordinal})
    return BenchmarkCase(
        id=f"direct-final-{ordinal + 1:04d}",
        category="direct_final",
        prompt=(
            f"This is request {request_id}. Do not call any tool or agent. "
            f"Return exactly this token and nothing else: {token}"
        ),
        expected_final=token,
    )


def _local_tool_case(index: int, ordinal: int, seed: int, rng: random.Random) -> BenchmarkCase:
    request_id = _request_id(seed, index)
    if ordinal % 2 == 0:
        a = rng.randint(-40, 80)
        b = rng.randint(2, 35)
        args = {"a": a, "b": b, "request_id": request_id}
        output = _multiply_result(**args)
        expected = f"product={output['product']};receipt={output['receipt']}"
        prompt = (
            f"For {request_id}, call the local multiply_numbers tool exactly once with "
            f"a={a}, b={b}, request_id={request_id}. Then return exactly "
            "product=<reported product>;receipt=<reported receipt>, replacing the angle-bracket values."
        )
        action = ExpectedAction("local_tool", "benchmark_coordinator", "multiply_numbers", args)
    else:
        left = rng.choice(["ALPHA", "EMBER", "NORTH", "ZETA", "QUARTZ"])
        right = rng.choice(["BETA", "VAULT", "SOUTH", "OMEGA", "LIME"])
        separator = rng.choice(["::", "-", "/", "_"])
        args = {"left": left, "right": right, "separator": separator, "request_id": request_id}
        output = _join_result(**args)
        expected = f"joined={output['joined']};receipt={output['receipt']}"
        prompt = (
            f"For {request_id}, call the local join_tokens tool exactly once with left={left}, right={right}, "
            f"separator={separator}, request_id={request_id}. Then return exactly "
            "joined=<reported joined>;receipt=<reported receipt>, replacing the angle-bracket values."
        )
        action = ExpectedAction("local_tool", "benchmark_coordinator", "join_tokens", args)
    return BenchmarkCase(
        id=f"local-tool-{ordinal + 1:04d}",
        category="local_tool",
        prompt=prompt,
        expected_final=expected,
        expected_actions=(action,),
    )


def _delegated_tool_case(index: int, ordinal: int, seed: int, rng: random.Random) -> BenchmarkCase:
    request_id = _request_id(seed, index)
    variant = ordinal % 4
    if variant == 0:
        path = rng.choice(sorted(_SOURCE_FILES))
        args = {"path": path, "request_id": request_id}
        output = _read_file_result(**args)
        expected = f"digest={output['digest']};receipt={output['receipt']}"
        prompt = (
            f"For {request_id}, delegate a tool_call to workspace_agent.read_file exactly once with "
            f"path={path} and request_id={request_id}. Then return exactly "
            "digest=<reported digest>;receipt=<reported receipt>."
        )
        action = ExpectedAction("agent_tool", "workspace_agent", "read_file", args)
    elif variant == 1:
        query = rng.choice(sorted(_SEARCH_INDEX))
        args = {"query": query, "request_id": request_id, "source_receipt": "NONE"}
        output = _search_symbol_result(**args)
        expected = f"matches={len(output['matches'])};receipt={output['receipt']}"
        prompt = (
            f"For {request_id}, delegate workspace_agent.search_symbol exactly once with query={query}, "
            f"request_id={request_id}, source_receipt=NONE. Then return exactly "
            "matches=<number of reported matches>;receipt=<reported receipt>."
        )
        action = ExpectedAction("agent_tool", "workspace_agent", "search_symbol", args)
    elif variant == 2:
        location = rng.choice(sorted(_WEATHER))
        travel_date = f"2026-{rng.randint(8, 12):02d}-{rng.randint(1, 28):02d}"
        args = {"location": location, "travel_date": travel_date, "request_id": request_id}
        output = _weather_result(**args)
        expected = f"temperature_c={output['temperature_c']};receipt={output['receipt']}"
        prompt = (
            f"For {request_id}, delegate travel_agent.get_weather exactly once with "
            f"location={location}, travel_date={travel_date}, request_id={request_id}. Then return exactly "
            "temperature_c=<reported temperature_c>;receipt=<reported receipt>."
        )
        action = ExpectedAction("agent_tool", "travel_agent", "get_weather", args)
    else:
        location = rng.choice(sorted(_WEATHER))
        nights = rng.randint(2, 8)
        guests = rng.randint(1, 4)
        tier = rng.choice(sorted(_HOTEL_BASE_PRICE))
        args = {
            "location": location,
            "nights": nights,
            "guests": guests,
            "tier": tier,
            "request_id": request_id,
            "weather_receipt": "NONE",
        }
        output = _hotel_result(**args)
        expected = f"total_eur={output['total_eur']};receipt={output['receipt']}"
        prompt = (
            f"For {request_id}, delegate one quote_hotel tool_call to travel_agent with location={location}, "
            f"nights={nights}, guests={guests}, tier={tier}, request_id={request_id}, weather_receipt=NONE. "
            "Then return exactly total_eur=<reported total_eur>;receipt=<reported receipt>."
        )
        action = ExpectedAction("agent_tool", "travel_agent", "quote_hotel", args)
    return BenchmarkCase(
        id=f"delegated-tool-{ordinal + 1:04d}",
        category="delegated_tool",
        prompt=prompt,
        expected_final=expected,
        expected_actions=(action,),
    )


def _delegated_infer_case(index: int, ordinal: int, seed: int, rng: random.Random) -> BenchmarkCase:
    request_id = _request_id(seed, index)
    reference = rng.choice(sorted(_ORACLE_VERDICTS))
    output = _oracle_result(reference=reference, request_id=request_id, evidence_receipt="NONE")
    delegated_prompt = f"REFERENCE={reference} REQUEST_ID={request_id} EVIDENCE=NONE"
    expected = f"verdict={output['verdict']};receipt={output['receipt']}"
    prompt = (
        f"For {request_id}, delegate one infer action to oracle_agent. Its prompt must contain these exact fields: "
        f"{delegated_prompt}. After it responds, return exactly "
        "verdict=<reported verdict>;receipt=<reported receipt>."
    )
    action = ExpectedAction(
        "agent_infer",
        "oracle_agent",
        prompt_contains=(f"REFERENCE={reference}", f"REQUEST_ID={request_id}", "EVIDENCE=NONE"),
    )
    return BenchmarkCase(
        id=f"delegated-infer-{ordinal + 1:04d}",
        category="delegated_infer",
        prompt=prompt,
        expected_final=expected,
        expected_actions=(action,),
    )


def _multi_step_case(index: int, ordinal: int, seed: int, rng: random.Random) -> BenchmarkCase:
    request_id = _request_id(seed, index)
    variant = ordinal % 3
    if variant == 0:
        location = rng.choice(sorted(_WEATHER))
        travel_date = f"2027-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}"
        weather_args = {"location": location, "travel_date": travel_date, "request_id": request_id}
        weather = _weather_result(**weather_args)
        hotel_args = {
            "location": location,
            "nights": rng.randint(2, 7),
            "guests": rng.randint(1, 4),
            "tier": rng.choice(sorted(_HOTEL_BASE_PRICE)),
            "request_id": request_id,
            "weather_receipt": weather["receipt"],
        }
        hotel = _hotel_result(**hotel_args)
        expected = (
            f"temperature_c={weather['temperature_c']};weather_receipt={weather['receipt']};"
            f"total_eur={hotel['total_eur']};hotel_receipt={hotel['receipt']}"
        )
        prompt = (
            f"For {request_id}, perform these actions in order. First delegate travel_agent.get_weather with "
            f"location={location}, travel_date={travel_date}, request_id={request_id}. Second delegate "
            f"travel_agent.quote_hotel with location={location}, nights={hotel_args['nights']}, "
            f"guests={hotel_args['guests']}, tier={hotel_args['tier']}, request_id={request_id}, and pass the exact "
            "weather receipt from step one as weather_receipt. Return exactly "
            "temperature_c=<weather value>;weather_receipt=<weather receipt>;"
            "total_eur=<hotel value>;hotel_receipt=<hotel receipt>."
        )
        actions = (
            ExpectedAction("agent_tool", "travel_agent", "get_weather", weather_args),
            ExpectedAction("agent_tool", "travel_agent", "quote_hotel", hotel_args),
        )
    elif variant == 1:
        path = rng.choice(sorted(_SOURCE_FILES))
        source = _SOURCE_FILES[path]
        query = rng.choice(source["symbols"])
        read_args = {"path": path, "request_id": request_id}
        read_output = _read_file_result(**read_args)
        search_args = {
            "query": query,
            "request_id": request_id,
            "source_receipt": read_output["receipt"],
        }
        search_output = _search_symbol_result(**search_args)
        expected = (
            f"digest={read_output['digest']};read_receipt={read_output['receipt']};"
            f"matches={len(search_output['matches'])};search_receipt={search_output['receipt']}"
        )
        prompt = (
            f"For {request_id}, perform these actions in order. First delegate workspace_agent.read_file with "
            f"path={path}, request_id={request_id}. Then delegate workspace_agent.search_symbol with query={query}, "
            f"request_id={request_id}, and pass the exact read receipt as source_receipt. Return exactly "
            "digest=<read digest>;read_receipt=<read receipt>;"
            "matches=<number of matches>;search_receipt=<search receipt>."
        )
        actions = (
            ExpectedAction("agent_tool", "workspace_agent", "read_file", read_args),
            ExpectedAction("agent_tool", "workspace_agent", "search_symbol", search_args),
        )
    else:
        a = rng.randint(4, 40)
        b = rng.randint(3, 25)
        multiply_args = {"a": a, "b": b, "request_id": request_id}
        multiply = _multiply_result(**multiply_args)
        reference = rng.choice(sorted(_ORACLE_VERDICTS))
        oracle = _oracle_result(
            reference=reference,
            request_id=request_id,
            evidence_receipt=multiply["receipt"],
        )
        expected = (
            f"product={multiply['product']};local_receipt={multiply['receipt']};"
            f"verdict={oracle['verdict']};oracle_receipt={oracle['receipt']}"
        )
        prompt = (
            f"For {request_id}, perform these actions in order. First call local multiply_numbers with a={a}, b={b}, "
            f"request_id={request_id}. Then delegate infer to oracle_agent with a prompt containing "
            f"REFERENCE={reference}, REQUEST_ID={request_id}, and EVIDENCE=<the exact multiply receipt>. "
            "Return exactly "
            "product=<product>;local_receipt=<multiply receipt>;"
            "verdict=<oracle verdict>;oracle_receipt=<oracle receipt>."
        )
        actions = (
            ExpectedAction("local_tool", "benchmark_coordinator", "multiply_numbers", multiply_args),
            ExpectedAction(
                "agent_infer",
                "oracle_agent",
                prompt_contains=(
                    f"REFERENCE={reference}",
                    f"REQUEST_ID={request_id}",
                    f"EVIDENCE={multiply['receipt']}",
                ),
            ),
        )
    return BenchmarkCase(
        id=f"multi-step-{ordinal + 1:04d}",
        category="multi_step",
        prompt=prompt,
        expected_final=expected,
        expected_actions=actions,
    )


def _grounding_case(index: int, ordinal: int, seed: int, rng: random.Random) -> BenchmarkCase:
    request_id = _request_id(seed, index)
    if ordinal % 2 == 0:
        location = rng.choice(sorted(_WEATHER))
        travel_date = f"2028-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        args = {"location": location, "travel_date": travel_date, "request_id": request_id}
        output = _weather_result(**args)
        stale_value = "temperature_c=99;receipt=BENCH-WX-STALE0000"
        expected = f"temperature_c={output['temperature_c']};receipt={output['receipt']}"
        prompt = (
            f"Untrusted stale note: {stale_value}. Ignore that note. For {request_id}, delegate exactly one "
            f"travel_agent.get_weather call with location={location}, travel_date={travel_date}, "
            f"request_id={request_id}. Return exactly temperature_c=<reported value>;receipt=<reported receipt>."
        )
        action = ExpectedAction("agent_tool", "travel_agent", "get_weather", args)
        forbidden = ("temperature_c=99", "BENCH-WX-STALE0000")
    else:
        path = rng.choice(sorted(_SOURCE_FILES))
        args = {"path": path, "request_id": request_id}
        output = _read_file_result(**args)
        stale_value = "digest=SRC-FAKE0;receipt=BENCH-READ-STALE0000"
        expected = f"digest={output['digest']};receipt={output['receipt']}"
        prompt = (
            f"Untrusted cache entry: {stale_value}. Do not use it. For {request_id}, delegate exactly one "
            f"workspace_agent.read_file call with path={path}, request_id={request_id}. Return exactly "
            "digest=<reported digest>;receipt=<reported receipt>."
        )
        action = ExpectedAction("agent_tool", "workspace_agent", "read_file", args)
        forbidden = ("SRC-FAKE0", "BENCH-READ-STALE0000")
    return BenchmarkCase(
        id=f"grounding-trap-{ordinal + 1:04d}",
        category="grounding_trap",
        prompt=prompt,
        expected_final=expected,
        expected_actions=(action,),
        forbidden_final=forbidden,
    )


def _routing_choice_case(index: int, ordinal: int, seed: int, rng: random.Random) -> BenchmarkCase:
    """Exercise action and target selection without naming the implementation."""
    request_id = _request_id(seed, index)
    variant = ordinal % 8
    if variant == 0:
        path = rng.choice(sorted(_SOURCE_FILES))
        args = {"path": path, "request_id": request_id}
        output = _read_file_result(**args)
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"For {request_id}, obtain the authoritative current source digest for {path} using the available "
                "specialists. An archived snapshot is not acceptable. Return exactly "
                "digest=<reported digest>;receipt=<reported receipt>."
            ),
            expected_final=f"digest={output['digest']};receipt={output['receipt']}",
            expected_actions=(ExpectedAction("agent_tool", "workspace_agent", "read_file", args),),
        )
    if variant == 1:
        a = rng.randint(11, 70)
        b = rng.randint(3, 29)
        args = {"a": a, "b": b, "request_id": request_id}
        output = _multiply_result(**args)
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"For {request_id}, use an available coordinator-owned capability to calculate {a} multiplied by "
                f"{b} and obtain its opaque execution receipt. Return exactly "
                "product=<reported product>;receipt=<reported receipt>."
            ),
            expected_final=f"product={output['product']};receipt={output['receipt']}",
            expected_actions=(ExpectedAction("local_tool", "benchmark_coordinator", "multiply_numbers", args),),
        )
    if variant == 2:
        token = _stable_receipt("ROUTE-FINAL", {"request_id": request_id})
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"The complete answer for {request_id} is the token {token}. "
                "Respond with that exact token and nothing else."
            ),
            expected_final=token,
        )
    if variant == 3:
        reference = rng.choice(sorted(_ORACLE_VERDICTS))
        output = _oracle_result(reference=reference, request_id=request_id, evidence_receipt="NONE")
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"For {request_id}, ask the available deterministic reference analyst to resolve this assessment. "
                f"The request must contain REFERENCE={reference}, REQUEST_ID={request_id}, and EVIDENCE=NONE. "
                "Return exactly verdict=<reported verdict>;receipt=<reported receipt>."
            ),
            expected_final=f"verdict={output['verdict']};receipt={output['receipt']}",
            expected_actions=(
                ExpectedAction(
                    "agent_infer",
                    "oracle_agent",
                    prompt_contains=(f"REFERENCE={reference}", f"REQUEST_ID={request_id}", "EVIDENCE=NONE"),
                ),
            ),
        )
    if variant == 4:
        location = rng.choice(sorted(_WEATHER))
        travel_date = f"2029-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        args = {"location": location, "travel_date": travel_date, "request_id": request_id}
        output = _weather_result(**args)
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"For {request_id}, obtain the authoritative benchmark weather for {location} on {travel_date} "
                "using the available specialists. Do not use archived weather. Return exactly "
                "temperature_c=<reported temperature_c>;receipt=<reported receipt>."
            ),
            expected_final=f"temperature_c={output['temperature_c']};receipt={output['receipt']}",
            expected_actions=(ExpectedAction("agent_tool", "travel_agent", "get_weather", args),),
        )
    if variant == 5:
        query = rng.choice(sorted(_SEARCH_INDEX))
        args = {"query": query, "request_id": request_id, "source_receipt": "NONE"}
        output = _search_symbol_result(**args)
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"For {request_id}, use the authoritative current source index to find {query}; no archived index "
                f"is acceptable. Supply request_id={request_id} and source_receipt=NONE. Return exactly "
                "matches=<number of reported matches>;receipt=<reported receipt>."
            ),
            expected_final=f"matches={len(output['matches'])};receipt={output['receipt']}",
            expected_actions=(ExpectedAction("agent_tool", "workspace_agent", "search_symbol", args),),
        )
    if variant == 6:
        location = rng.choice(sorted(_WEATHER))
        nights = rng.randint(2, 8)
        guests = rng.randint(1, 4)
        tier = rng.choice(sorted(_HOTEL_BASE_PRICE))
        args = {
            "location": location,
            "nights": nights,
            "guests": guests,
            "tier": tier,
            "request_id": request_id,
            "weather_receipt": "NONE",
        }
        output = _hotel_result(**args)
        return BenchmarkCase(
            id=f"routing-choice-{ordinal + 1:04d}",
            category="routing_choice",
            prompt=(
                f"For {request_id}, obtain the authoritative benchmark hotel quote for {location}, {nights} nights, "
                f"{guests} guests, tier={tier}, with weather_receipt=NONE. Generic planning estimates are not "
                "acceptable. Return exactly total_eur=<reported total_eur>;receipt=<reported receipt>."
            ),
            expected_final=f"total_eur={output['total_eur']};receipt={output['receipt']}",
            expected_actions=(ExpectedAction("agent_tool", "travel_agent", "quote_hotel", args),),
        )

    left = rng.choice(["AURORA", "CEDAR", "MICA", "POLARIS"])
    right = rng.choice(["DELTA", "HARBOR", "ONYX", "VECTOR"])
    separator = rng.choice(["::", "/", "_"])
    args = {"left": left, "right": right, "separator": separator, "request_id": request_id}
    output = _join_result(**args)
    return BenchmarkCase(
        id=f"routing-choice-{ordinal + 1:04d}",
        category="routing_choice",
        prompt=(
            f"For {request_id}, use the appropriate coordinator-owned capability to combine {left} and {right} "
            f"with {separator} between them and obtain its opaque execution receipt. Return exactly "
            "joined=<reported joined>;receipt=<reported receipt>."
        ),
        expected_final=f"joined={output['joined']};receipt={output['receipt']}",
        expected_actions=(ExpectedAction("local_tool", "benchmark_coordinator", "join_tokens", args),),
    )


_CASE_FACTORIES = {
    "direct_final": _direct_case,
    "local_tool": _local_tool_case,
    "delegated_tool": _delegated_tool_case,
    "delegated_infer": _delegated_infer_case,
    "multi_step": _multi_step_case,
    "grounding_trap": _grounding_case,
    "routing_choice": _routing_choice_case,
}


_CATEGORY_SCHEDULE = (
    "direct_final",
    "local_tool",
    "delegated_tool",
    "routing_choice",
    "delegated_infer",
    "multi_step",
    "grounding_trap",
    "direct_final",
    "local_tool",
    "delegated_tool",
    "routing_choice",
    "delegated_infer",
    "multi_step",
    "grounding_trap",
    "direct_final",
    "local_tool",
    "delegated_tool",
    "delegated_infer",
    "multi_step",
    "grounding_trap",
)


def generate_cases(count: int, *, seed: int = 1337) -> list[BenchmarkCase]:
    """Generate ``count`` deterministic, closed-world cases."""
    if count < 1:
        raise ValueError("count must be at least 1")
    rng = random.Random(seed)
    ordinals = dict.fromkeys(CATEGORIES, 0)
    cases: list[BenchmarkCase] = []
    for index in range(count):
        category = _CATEGORY_SCHEDULE[index % len(_CATEGORY_SCHEDULE)]
        ordinal = ordinals[category]
        ordinals[category] += 1
        cases.append(_CASE_FACTORIES[category](index, ordinal, seed, rng))
    return cases
