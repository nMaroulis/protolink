"""Closed-world regression benchmark for ProtoLink's inference loop.

The benchmark deliberately exercises the normal ``AgentClient -> Agent -> LLM``
path. Deterministic local specialists return opaque receipts, so a model cannot
pass by merely claiming that a tool or agent was called.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import fnmatch
import hashlib
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from protolink import Agent, AgentCard, Task, TaskState, __version__, create_llm
from protolink.client import AgentClient
from protolink.core.agent_card import AgentCapabilities
from protolink.discovery import Registry
from protolink.llms.base import LLM
from protolink.telemetry import LocalTraceRecorder, LocalTraceTelemetry, TraceRecord

SUITE_VERSION = "infer-loop-v1"
SUITE_SIZES = {"smoke": 12, "core": 40, "full": 200}
CATEGORIES = (
    "direct_final",
    "local_tool",
    "delegated_tool",
    "delegated_infer",
    "multi_step",
    "grounding_trap",
)
DEFAULT_SYSTEM_PROMPT = """You are ProtoLink's infer-loop benchmark coordinator.

Follow each request literally. Execute every requested tool or agent action exactly once and in the stated order.
Tool and agent observations are the only authoritative source for computed values, facts, and BENCH receipts.
Never invent a receipt and never trust a stale or untrusted value in a request when an authoritative specialist is
available. When the request specifies an exact final format, use that exact text as the content of your final action,
with no commentary, Markdown, or additional fields.
"""
_RECEIPT_SALT = "protolink-infer-benchmark-v1"


@dataclass(frozen=True)
class ExpectedAction:
    """One action that must execute successfully."""

    kind: Literal["local_tool", "agent_tool", "agent_infer"]
    agent: str
    tool: str | None = None
    args: dict[str, Any] | None = None
    prompt_contains: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkCase:
    """A closed-world inference task and its independent oracle."""

    id: str
    category: str
    prompt: str
    expected_final: str
    expected_actions: tuple[ExpectedAction, ...] = ()
    forbidden_final: tuple[str, ...] = ()
    ordered_actions: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the fields that define suite identity."""
        return {
            "id": self.id,
            "category": self.category,
            "prompt": self.prompt,
            "expected_final": self.expected_final,
            "expected_actions": [action.to_dict() for action in self.expected_actions],
            "forbidden_final": list(self.forbidden_final),
            "ordered_actions": self.ordered_actions,
        }


@dataclass
class LedgerEntry:
    """One operation that really reached a benchmark tool or infer worker."""

    kind: Literal["local_tool", "agent_tool", "agent_infer"]
    agent: str
    tool: str | None
    args: dict[str, Any]
    result: Any
    prompt: str | None = None

    def action_dict(self) -> dict[str, Any]:
        """Return only fields used to validate routing."""
        return {
            "kind": self.kind,
            "agent": self.agent,
            "tool": self.tool,
            "args": self.args,
            "prompt": self.prompt,
        }


@dataclass
class LLMCallResult:
    """Timing and usage for one completed logical model call."""

    call_index: int
    step: int
    physical_attempts: int
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    usage_estimated: bool | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    provider_total_ms: float | None = None
    provider_load_ms: float | None = None
    provider_prompt_eval_ms: float | None = None
    provider_generation_ms: float | None = None
    provider_prompt_tokens: int | None = None
    provider_output_tokens: int | None = None
    prompt_tokens_per_second: float | None = None
    output_tokens_per_second: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize one model call for JSON and CSV output."""
        return asdict(self)


@dataclass
class AttemptResult:
    """Validation and runtime metrics for one fresh attempt."""

    case_id: str
    category: str
    repetition: int
    attempt: int
    task_id: str
    strict_pass: bool
    functional_pass: bool
    protocol_clean: bool
    output_match: bool
    ledger_match: bool
    trace_match: bool
    task_state: str
    final_output: str
    failure_codes: list[str] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    non_llm_latency_ms: float | None = None
    timing_complete: bool = False
    first_llm_latency_ms: float = 0.0
    mean_llm_call_latency_ms: float = 0.0
    llm_steps: int = 0
    llm_calls: int = 0
    provider_attempts: int = 0
    completed_provider_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usage_estimated_calls: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    provider_total_ms: float = 0.0
    provider_load_ms: float = 0.0
    provider_prompt_eval_ms: float = 0.0
    provider_generation_ms: float = 0.0
    prompt_tokens_per_second: float | None = None
    output_tokens_per_second: float | None = None
    provider_timing_calls: int = 0
    parse_errors: int = 0
    provider_retries: int = 0
    duplicate_retries: int = 0
    invalid_tool_attempts: int = 0
    invalid_agent_attempts: int = 0
    action_receipts: int = 0
    hallucinated_action: bool = False
    timed_out: bool = False
    crashed: bool = False
    expected_actions: list[dict[str, Any]] = field(default_factory=list)
    observed_actions: list[dict[str, Any]] = field(default_factory=list)
    trace_actions: list[dict[str, Any]] = field(default_factory=list)
    llm_call_timings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize one attempt for JSON output."""
        return asdict(self)


@dataclass
class CaseResult:
    """All fresh attempts for one logical case repetition."""

    case_id: str
    category: str
    repetition: int
    attempts: list[AttemptResult]

    @property
    def key(self) -> str:
        """Return a baseline-stable logical case key."""
        return f"{self.case_id}#r{self.repetition}"

    @property
    def strict_pass(self) -> bool:
        """Return whether any fresh attempt passed strictly."""
        return any(result.strict_pass for result in self.attempts)

    @property
    def functional_pass(self) -> bool:
        """Return whether any fresh attempt eventually produced the correct result."""
        return any(result.functional_pass for result in self.attempts)

    @property
    def first_attempt_strict(self) -> bool:
        """Return the unmasked pass@1 result."""
        return bool(self.attempts and self.attempts[0].strict_pass)

    @property
    def selected_attempt(self) -> AttemptResult:
        """Prefer a strict result, then a functional result, then the final failure."""
        for result in self.attempts:
            if result.strict_pass:
                return result
        for result in self.attempts:
            if result.functional_pass:
                return result
        return self.attempts[-1]

    def to_dict(self) -> dict[str, Any]:
        """Serialize logical-case status and every attempt."""
        return {
            "key": self.key,
            "case_id": self.case_id,
            "category": self.category,
            "repetition": self.repetition,
            "strict_pass": self.strict_pass,
            "functional_pass": self.functional_pass,
            "first_attempt_strict": self.first_attempt_strict,
            "attempts_used": len(self.attempts),
            "selected_attempt": self.selected_attempt.attempt,
            "attempts": [result.to_dict() for result in self.attempts],
        }


@dataclass
class BenchmarkConfig:
    """Resolved benchmark configuration."""

    provider: str = "ollama"
    model: str | None = None
    base_url: str | None = None
    model_params: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)
    max_parse_failures: int = 3
    supports_tool_calling: bool = False
    suite: str = "smoke"
    count: int | None = None
    seed: int = 1337
    attempts: int = 1
    repetitions: int = 1
    timeout: float = 300.0
    categories: tuple[str, ...] = ()
    case_patterns: tuple[str, ...] = ()
    limit: int | None = None
    shuffle: bool = False
    warmup: int = 0
    preflight: bool = True
    output_root: Path = Path("benchmark_results")
    run_name: str | None = None
    baseline: Path | None = None
    fail_under: float | None = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    verbosity: Literal[0, 1, 2] = 0
    quiet: bool = False


@dataclass
class BenchmarkRun:
    """Completed benchmark result returned to callers and tests."""

    output_dir: Path
    summary: dict[str, Any]
    cases: list[CaseResult]
    attempts: list[AttemptResult]

    @property
    def strict_percent(self) -> float:
        """Return the headline score as a percentage."""
        return float(self.summary["scores"]["strict_percent"])


class ActionLedger:
    """Append-only independent execution record."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def record(self, entry: LedgerEntry) -> None:
        """Record a completed benchmark operation."""
        self.entries.append(entry)

    def mark(self) -> int:
        """Return a cursor for the next operation."""
        return len(self.entries)

    def since(self, cursor: int) -> list[LedgerEntry]:
        """Return operations completed after ``cursor``."""
        return self.entries[cursor:]


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
            f"For {request_id}, use the source-code specialist to call search_symbol exactly once with query={query}, "
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
            f"For {request_id}, delegate to the travel data agent and call get_weather exactly once with "
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


_CASE_FACTORIES = {
    "direct_final": _direct_case,
    "local_tool": _local_tool_case,
    "delegated_tool": _delegated_tool_case,
    "delegated_infer": _delegated_infer_case,
    "multi_step": _multi_step_case,
    "grounding_trap": _grounding_case,
}


def generate_cases(count: int, *, seed: int = 1337) -> list[BenchmarkCase]:
    """Generate ``count`` deterministic, closed-world cases."""
    if count < 1:
        raise ValueError("count must be at least 1")
    rng = random.Random(seed)
    ordinals = dict.fromkeys(CATEGORIES, 0)
    cases: list[BenchmarkCase] = []
    for index in range(count):
        category = CATEGORIES[index % len(CATEGORIES)]
        ordinal = ordinals[category]
        ordinals[category] += 1
        cases.append(_CASE_FACTORIES[category](index, ordinal, seed, rng))
    return cases


class _OracleAgent(Agent):
    """Deterministic infer worker whose receipts are not present in user prompts."""

    def __init__(
        self,
        *,
        card: AgentCard,
        registry: Registry,
        ledger: ActionLedger,
        verbosity: Literal[0, 1, 2],
    ) -> None:
        self._benchmark_ledger = ledger
        super().__init__(
            card=card,
            transport="runtime",
            registry=registry,
            verbosity=verbosity,
        )
        # This worker implements infer deterministically rather than through an
        # LLM, but must advertise infer capability to the coordinator.
        self.card.capabilities.has_llm = True
        self.card.capabilities.delegation = False

    async def handle_task(self, task: Task) -> Task:
        """Resolve the strict reference fields carried in an infer prompt."""
        raw_content = task.get_last_part_content()
        prompt = str(raw_content.get("prompt", "")) if isinstance(raw_content, dict) else str(raw_content or "")
        reference_match = re.search(r"\bREFERENCE=([A-Z0-9-]+)", prompt)
        request_match = re.search(r"\bREQUEST_ID=([A-Z0-9-]+)", prompt)
        evidence_match = re.search(r"\bEVIDENCE=([A-Z0-9-]+)", prompt)
        if not reference_match or not request_match or not evidence_match:
            return task.fail("Oracle infer prompt must include REFERENCE, REQUEST_ID, and EVIDENCE")

        reference = reference_match.group(1)
        if reference not in _ORACLE_VERDICTS:
            return task.fail(f"Unknown oracle reference: {reference}")

        result = _oracle_result(
            reference=reference,
            request_id=request_match.group(1),
            evidence_receipt=evidence_match.group(1),
        )
        self._benchmark_ledger.record(
            LedgerEntry(
                kind="agent_infer",
                agent=self.card.name,
                tool=None,
                args={
                    "reference": reference,
                    "request_id": request_match.group(1),
                    "evidence_receipt": evidence_match.group(1),
                },
                result=result,
                prompt=prompt,
            )
        )
        return task.complete(json.dumps(result, ensure_ascii=False, sort_keys=True))


class BenchmarkMesh:
    """A real RuntimeTransport mesh used by every scored attempt."""

    def __init__(
        self,
        *,
        llm: LLM,
        recorder: LocalTraceRecorder,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        verbosity: Literal[0, 1, 2] = 0,
        namespace: str | None = None,
    ) -> None:
        nonce = namespace or hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:12]
        prefix = f"runtime://infer-benchmark-{nonce}"
        self.ledger = ActionLedger()
        self.registry = Registry(
            transport="runtime",
            url=f"{prefix}/registry",
            verbosity=verbosity,
        )
        self.workspace_agent = self._build_workspace_agent(
            url=f"{prefix}/workspace",
            verbosity=verbosity,
        )
        self.travel_agent = self._build_travel_agent(
            url=f"{prefix}/travel",
            verbosity=verbosity,
        )
        self.oracle_agent = _OracleAgent(
            card=AgentCard(
                name="oracle_agent",
                description=(
                    "Deterministic reference analyst. Use agent_call action=infer with a prompt containing "
                    "REFERENCE, REQUEST_ID, and EVIDENCE fields."
                ),
                url=f"{prefix}/oracle",
                capabilities=AgentCapabilities(delegation=False, has_llm=True),
            ),
            registry=self.registry,
            ledger=self.ledger,
            verbosity=verbosity,
        )
        self.coordinator = Agent(
            card=AgentCard(
                name="benchmark_coordinator",
                description="Coordinates deterministic benchmark specialists.",
                url=f"{prefix}/coordinator",
                capabilities=AgentCapabilities(delegation=True, has_llm=True),
            ),
            transport="runtime",
            registry=self.registry,
            llm=llm,
            system_prompt=system_prompt,
            telemetry=LocalTraceTelemetry(recorder=recorder),
            verbosity=verbosity,
        )
        self._add_coordinator_tools()
        self.client = AgentClient("runtime", url=f"{prefix}/client")
        self._started: list[Any] = []

    def _build_workspace_agent(self, *, url: str, verbosity: Literal[0, 1, 2]) -> Agent:
        agent = Agent(
            card=AgentCard(
                name="workspace_agent",
                description="Authoritative source-code workspace reader and symbol index.",
                url=url,
                capabilities=AgentCapabilities(delegation=False, tool_calling=True),
            ),
            transport="runtime",
            registry=self.registry,
            verbosity=verbosity,
        )

        @agent.tool(
            name="read_file",
            description="Read authoritative metadata for one known source file.",
        )
        def read_file(path: str, request_id: str) -> dict[str, Any]:
            if path not in _SOURCE_FILES:
                raise ValueError(f"Unknown benchmark source path: {path}")
            args = {"path": path, "request_id": request_id}
            result = _read_file_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "read_file", args, result))
            return result

        @agent.tool(
            name="search_symbol",
            description="Search the authoritative source index; source_receipt links a prior read_file observation.",
        )
        def search_symbol(query: str, request_id: str, source_receipt: str) -> dict[str, Any]:
            args = {
                "query": query,
                "request_id": request_id,
                "source_receipt": source_receipt,
            }
            result = _search_symbol_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "search_symbol", args, result))
            return result

        return agent

    def _build_travel_agent(self, *, url: str, verbosity: Literal[0, 1, 2]) -> Agent:
        agent = Agent(
            card=AgentCard(
                name="travel_agent",
                description="Authoritative synthetic weather and hotel data for benchmark trips.",
                url=url,
                capabilities=AgentCapabilities(delegation=False, tool_calling=True),
            ),
            transport="runtime",
            registry=self.registry,
            verbosity=verbosity,
        )

        @agent.tool(
            name="get_weather",
            description="Return deterministic weather and an opaque receipt for a supported location and date.",
        )
        def get_weather(location: str, travel_date: str, request_id: str) -> dict[str, Any]:
            if location not in _WEATHER:
                raise ValueError(f"Unknown benchmark location: {location}")
            args = {
                "location": location,
                "travel_date": travel_date,
                "request_id": request_id,
            }
            result = _weather_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "get_weather", args, result))
            return result

        @agent.tool(
            name="quote_hotel",
            description=(
                "Return a deterministic hotel total and receipt. weather_receipt must be NONE or a prior weather "
                "receipt when the request requires a dependency."
            ),
        )
        def quote_hotel(
            location: str,
            nights: int,
            guests: int,
            tier: str,
            request_id: str,
            weather_receipt: str,
        ) -> dict[str, Any]:
            if location not in _WEATHER:
                raise ValueError(f"Unknown benchmark location: {location}")
            if tier not in _HOTEL_BASE_PRICE:
                raise ValueError(f"Unknown benchmark hotel tier: {tier}")
            args = {
                "location": location,
                "nights": nights,
                "guests": guests,
                "tier": tier,
                "request_id": request_id,
                "weather_receipt": weather_receipt,
            }
            result = _hotel_result(**args)
            self.ledger.record(LedgerEntry("agent_tool", agent.card.name, "quote_hotel", args, result))
            return result

        return agent

    def _add_coordinator_tools(self) -> None:
        agent = self.coordinator

        @agent.tool(
            name="multiply_numbers",
            description="Multiply two integers and return the product with an opaque benchmark receipt.",
        )
        def multiply_numbers(a: int, b: int, request_id: str) -> dict[str, Any]:
            args = {"a": a, "b": b, "request_id": request_id}
            result = _multiply_result(**args)
            self.ledger.record(LedgerEntry("local_tool", agent.card.name, "multiply_numbers", args, result))
            return result

        @agent.tool(
            name="join_tokens",
            description="Join two strings exactly and return the joined value with an opaque benchmark receipt.",
        )
        def join_tokens(left: str, right: str, separator: str, request_id: str) -> dict[str, Any]:
            args = {
                "left": left,
                "right": right,
                "separator": separator,
                "request_id": request_id,
            }
            result = _join_result(**args)
            self.ledger.record(LedgerEntry("local_tool", agent.card.name, "join_tokens", args, result))
            return result

    async def start(self) -> None:
        """Start the registry and all agents, then verify discovery."""
        try:
            self.registry.start(background=True)
            self._started.append(self.registry)
            for agent in (
                self.workspace_agent,
                self.travel_agent,
                self.oracle_agent,
                self.coordinator,
            ):
                agent.start(background=True)
                self._started.append(agent)
            discovered = await self.coordinator.discover_agents()
            names = {card.name for card in discovered}
            required = {"workspace_agent", "travel_agent", "oracle_agent"}
            missing = sorted(required - names)
            if missing:
                raise RuntimeError(f"Benchmark discovery preflight failed; missing agents: {missing}")
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """Stop every started component in reverse order."""
        while self._started:
            component = self._started.pop()
            component.stop()


def _event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _numeric(value)
    return int(number) if number is not None else None


def _find_nested_number(value: Any, keys: tuple[str, ...]) -> float | None:
    """Find the first named numeric field in nested provider metadata."""
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                number = _numeric(value[key])
                if number is not None:
                    return number
        for nested in value.values():
            number = _find_nested_number(nested, keys)
            if number is not None:
                return number
    elif isinstance(value, list):
        for nested in value:
            number = _find_nested_number(nested, keys)
            if number is not None:
                return number
    return None


def _ollama_duration_ms(details: Any, key: str, *, provider: str) -> float | None:
    """Convert an Ollama nanosecond duration to milliseconds."""
    if provider.casefold() != "ollama":
        return None
    duration_ns = _find_nested_number(details, (key,))
    return round(duration_ns / 1_000_000, 3) if duration_ns is not None else None


def _llm_call_result(payload: dict[str, Any], call_index: int) -> LLMCallResult:
    raw_metrics = payload.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
    raw_usage = metrics.get("usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    details = usage.get("details")
    provider = str(payload.get("provider") or metrics.get("provider") or "")

    input_tokens = _integer(usage.get("input_tokens"))
    output_tokens = _integer(usage.get("output_tokens"))
    total_tokens = _integer(usage.get("total_tokens"))
    provider_prompt_tokens = _integer(_find_nested_number(details, ("prompt_eval_count", "prompt_token_count")))
    provider_output_tokens = _integer(_find_nested_number(details, ("eval_count", "completion_token_count")))
    cached_input_tokens = _integer(
        _find_nested_number(
            details,
            (
                "cached_tokens",
                "cache_read_input_tokens",
                "cached_content_token_count",
                "cache_read_tokens",
            ),
        )
    )
    cache_write_input_tokens = _integer(
        _find_nested_number(
            details,
            (
                "cache_creation_input_tokens",
                "cache_write_input_tokens",
                "cache_creation_tokens",
            ),
        )
    )
    provider_total_ms = _ollama_duration_ms(details, "total_duration", provider=provider)
    provider_load_ms = _ollama_duration_ms(details, "load_duration", provider=provider)
    provider_prompt_eval_ms = _ollama_duration_ms(details, "prompt_eval_duration", provider=provider)
    provider_generation_ms = _ollama_duration_ms(details, "eval_duration", provider=provider)

    prompt_rate = None
    if provider_prompt_tokens is not None and provider_prompt_eval_ms and provider_prompt_eval_ms > 0:
        prompt_rate = round(provider_prompt_tokens / (provider_prompt_eval_ms / 1000), 3)
    output_rate = None
    if provider_output_tokens is not None and provider_generation_ms and provider_generation_ms > 0:
        output_rate = round(provider_output_tokens / (provider_generation_ms / 1000), 3)

    return LLMCallResult(
        call_index=call_index,
        step=_integer(payload.get("step")) or call_index,
        physical_attempts=max(_integer(payload.get("attempts")) or 1, 1),
        latency_ms=round(_numeric(payload.get("latency_ms")) or 0.0, 3),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        usage_estimated=bool(usage.get("estimated")) if usage else None,
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
        provider_total_ms=provider_total_ms,
        provider_load_ms=provider_load_ms,
        provider_prompt_eval_ms=provider_prompt_eval_ms,
        provider_generation_ms=provider_generation_ms,
        provider_prompt_tokens=provider_prompt_tokens,
        provider_output_tokens=provider_output_tokens,
        prompt_tokens_per_second=prompt_rate,
        output_tokens_per_second=output_rate,
    )


def _trace_metrics(trace: TraceRecord | None) -> tuple[dict[str, Any], list[LLMCallResult]]:
    metrics: dict[str, Any] = {
        "llm_steps": 0,
        "llm_calls": 0,
        "provider_attempts": 0,
        "completed_provider_attempts": 0,
        "llm_latency_ms": 0.0,
        "first_llm_latency_ms": 0.0,
        "mean_llm_call_latency_ms": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "usage_estimated_calls": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "provider_total_ms": 0.0,
        "provider_load_ms": 0.0,
        "provider_prompt_eval_ms": 0.0,
        "provider_generation_ms": 0.0,
        "prompt_tokens_per_second": None,
        "output_tokens_per_second": None,
        "provider_timing_calls": 0,
        "parse_errors": 0,
        "provider_retries": 0,
        "duplicate_retries": 0,
        "invalid_tool_attempts": 0,
        "invalid_agent_attempts": 0,
    }
    if trace is None:
        return metrics, []
    completed_calls: list[dict[str, Any]] = []
    for event in trace.events:
        payload = _event_payload(event)
        if event.type == "llm_step":
            metrics["llm_steps"] += 1
        elif event.type == "llm_call_completed":
            completed_calls.append(payload)
        elif event.type == "llm_call_started":
            metrics["provider_attempts"] += 1
        elif event.type == "llm_parse_error":
            metrics["parse_errors"] += 1
        elif event.type == "llm_retry":
            reason = payload.get("reason")
            if reason == "transient_error":
                metrics["provider_retries"] += 1
            elif reason == "duplicate_action":
                metrics["duplicate_retries"] += 1
        elif event.type == "tool_error" and payload.get("phase") == "validation":
            metrics["invalid_tool_attempts"] += 1
        elif event.type == "agent_call_error" and payload.get("recoverable", False):
            metrics["invalid_agent_attempts"] += 1

    calls = [_llm_call_result(payload, index) for index, payload in enumerate(completed_calls, start=1)]
    metrics["llm_calls"] = len(calls)
    metrics["completed_provider_attempts"] = sum(call.physical_attempts for call in calls)
    call_latencies = [call.latency_ms for call in calls]
    metrics["llm_latency_ms"] = round(sum(call_latencies), 3)
    metrics["first_llm_latency_ms"] = call_latencies[0] if call_latencies else 0.0
    metrics["mean_llm_call_latency_ms"] = round(sum(call_latencies) / len(call_latencies), 3) if call_latencies else 0.0
    for name in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
    ):
        metrics[name] = sum(int(getattr(call, name) or 0) for call in calls)
    metrics["usage_estimated_calls"] = sum(call.usage_estimated is True for call in calls)
    for name in (
        "provider_total_ms",
        "provider_load_ms",
        "provider_prompt_eval_ms",
        "provider_generation_ms",
    ):
        metrics[name] = round(sum(float(getattr(call, name) or 0.0) for call in calls), 3)
    metrics["provider_timing_calls"] = sum(
        any(
            value is not None
            for value in (
                call.provider_total_ms,
                call.provider_load_ms,
                call.provider_prompt_eval_ms,
                call.provider_generation_ms,
            )
        )
        for call in calls
    )
    prompt_tokens = sum(int(call.provider_prompt_tokens or 0) for call in calls)
    prompt_ms = float(metrics["provider_prompt_eval_ms"])
    if prompt_tokens and prompt_ms > 0:
        metrics["prompt_tokens_per_second"] = round(prompt_tokens / (prompt_ms / 1000), 3)
    output_tokens = sum(int(call.provider_output_tokens or 0) for call in calls)
    generation_ms = float(metrics["provider_generation_ms"])
    if output_tokens and generation_ms > 0:
        metrics["output_tokens_per_second"] = round(output_tokens / (generation_ms / 1000), 3)
    return metrics, calls


def _successful_trace_actions(trace: TraceRecord | None) -> list[dict[str, Any]]:
    if trace is None:
        return []
    starts: dict[str, dict[str, Any]] = {}
    successful: list[dict[str, Any]] = []
    for event in trace.events:
        payload = _event_payload(event)
        action_id = str(payload.get("action_id") or "")
        if event.type == "tool_start":
            starts[action_id] = {
                "kind": "local_tool",
                "agent": "benchmark_coordinator",
                "tool": payload.get("tool"),
                "args": payload.get("args") or {},
                "prompt": None,
            }
        elif event.type == "agent_call_start":
            raw_model_payload = payload.get("payload")
            model_payload: dict[str, Any] = raw_model_payload if isinstance(raw_model_payload, dict) else {}
            delegated_action = payload.get("action")
            starts[action_id] = {
                "kind": "agent_infer" if delegated_action == "infer" else "agent_tool",
                "agent": payload.get("agent"),
                "tool": model_payload.get("tool"),
                "args": model_payload.get("args") or {},
                "prompt": model_payload.get("prompt"),
            }
        elif event.type in {"tool_result", "agent_call_result"}:
            action = starts.get(action_id)
            if action is not None:
                successful.append(action)
    return successful


def _action_matches(expected: ExpectedAction, observed: dict[str, Any]) -> bool:
    if expected.kind != observed.get("kind") or expected.agent != observed.get("agent"):
        return False
    if expected.tool != observed.get("tool"):
        return False
    if expected.args is not None and expected.args != observed.get("args"):
        return False
    prompt = str(observed.get("prompt") or "")
    return all(fragment in prompt for fragment in expected.prompt_contains)


def _action_list_matches(
    expected: tuple[ExpectedAction, ...],
    observed: list[dict[str, Any]],
    *,
    ordered: bool,
) -> bool:
    if len(expected) != len(observed):
        return False
    if ordered:
        return all(_action_matches(wanted, actual) for wanted, actual in zip(expected, observed, strict=True))

    remaining = list(observed)
    for wanted in expected:
        for index, actual in enumerate(remaining):
            if _action_matches(wanted, actual):
                remaining.pop(index)
                break
        else:
            return False
    return not remaining


def _find_infer_output(task: Task | None) -> str:
    if task is None:
        return ""
    candidates: list[tuple[str, Any]] = []
    for item in (*task.messages, *task.artifacts):
        for part in item.parts:
            if part.type == "infer_output":
                candidates.append((item.timestamp, part.content))
    if not candidates:
        return ""
    return str(max(candidates, key=lambda value: value[0])[1]).strip()


def _task_state(task: Task | None) -> str:
    if task is None:
        return "exception"
    return task.state.value if isinstance(task.state, TaskState) else str(task.state)


def _find_trace(
    recorder: LocalTraceRecorder,
    *,
    task_id: str,
    cursor: int,
) -> TraceRecord | None:
    for trace in reversed(recorder.traces[cursor:]):
        if trace.task_id == task_id and trace.agent_name == "benchmark_coordinator":
            return trace
    return None


def _validate_attempt(
    *,
    case: BenchmarkCase,
    repetition: int,
    attempt: int,
    task: Task | None,
    trace: TraceRecord | None,
    ledger_entries: list[LedgerEntry],
    latency_ms: float,
    error: Exception | None,
    timed_out: bool,
) -> AttemptResult:
    state = _task_state(task)
    final_output = _find_infer_output(task)
    output_match = final_output == case.expected_final and not any(
        forbidden in final_output for forbidden in case.forbidden_final
    )
    observed_actions = [entry.action_dict() for entry in ledger_entries]
    trace_actions = _successful_trace_actions(trace)
    ledger_match = _action_list_matches(case.expected_actions, observed_actions, ordered=case.ordered_actions)
    trace_match = _action_list_matches(case.expected_actions, trace_actions, ordered=case.ordered_actions)
    metrics, call_timings = _trace_metrics(trace)
    timing_complete = bool(
        trace is not None
        and error is None
        and not timed_out
        and metrics["provider_attempts"] == metrics["completed_provider_attempts"]
    )
    metrics["timing_complete"] = timing_complete
    metrics["non_llm_latency_ms"] = (
        round(max(latency_ms - float(metrics["llm_latency_ms"]), 0.0), 3) if timing_complete else None
    )
    protocol_clean = not any(
        (
            metrics["parse_errors"],
            metrics["duplicate_retries"],
            metrics["invalid_tool_attempts"],
            metrics["invalid_agent_attempts"],
        )
    )

    failure_codes: list[str] = []
    if state != TaskState.COMPLETED.value:
        failure_codes.append("task_not_completed")
    if not final_output:
        failure_codes.append("missing_final_output")
    elif not output_match:
        failure_codes.append("final_output_mismatch")
    if not ledger_match:
        failure_codes.append("execution_ledger_mismatch")
    if not trace_match:
        failure_codes.append("trace_action_mismatch")
    if metrics["parse_errors"]:
        failure_codes.append("parse_recovery")
    if metrics["duplicate_retries"]:
        failure_codes.append("duplicate_action")
    if metrics["invalid_tool_attempts"]:
        failure_codes.append("invalid_tool_action")
    if metrics["invalid_agent_attempts"]:
        failure_codes.append("invalid_agent_action")
    if timed_out:
        failure_codes.append("timeout")
    if error is not None:
        failure_codes.append("exception")
    failure_codes = list(dict.fromkeys(failure_codes))

    functional_pass = (
        state == TaskState.COMPLETED.value
        and bool(final_output)
        and output_match
        and ledger_match
        and trace_match
        and error is None
        and not timed_out
    )
    strict_pass = functional_pass and protocol_clean
    unexpected_action = not ledger_match or not trace_match
    hallucinated_action = bool(
        unexpected_action
        or metrics["invalid_tool_attempts"]
        or metrics["invalid_agent_attempts"]
        or (case.category == "grounding_trap" and not output_match)
    )
    action_receipts = (
        sum(1 for artifact in task.artifacts if artifact.kind == "action_result") if task is not None else 0
    )
    crashed = bool(error is not None or state in {TaskState.FAILED.value, TaskState.CANCELED.value, "exception"})
    return AttemptResult(
        case_id=case.id,
        category=case.category,
        repetition=repetition,
        attempt=attempt,
        task_id=task.id if task is not None else "",
        strict_pass=strict_pass,
        functional_pass=functional_pass,
        protocol_clean=protocol_clean,
        output_match=output_match,
        ledger_match=ledger_match,
        trace_match=trace_match,
        task_state=state,
        final_output=final_output,
        failure_codes=failure_codes,
        error_type=type(error).__name__ if error is not None else None,
        error_message=str(error) if error is not None else None,
        latency_ms=round(latency_ms, 3),
        action_receipts=action_receipts,
        hallucinated_action=hallucinated_action,
        timed_out=timed_out,
        crashed=crashed,
        expected_actions=[action.to_dict() for action in case.expected_actions],
        observed_actions=observed_actions,
        trace_actions=trace_actions,
        llm_call_timings=[call.to_dict() for call in call_timings],
        **metrics,
    )


async def run_attempt(
    *,
    mesh: BenchmarkMesh,
    recorder: LocalTraceRecorder,
    case: BenchmarkCase,
    repetition: int,
    attempt: int,
    timeout: float,
) -> AttemptResult:
    """Run and validate one fresh task."""
    task = Task.create_infer(prompt=case.prompt)
    task.metadata.update(
        {
            "benchmark": SUITE_VERSION,
            "benchmark_case_id": case.id,
            "benchmark_repetition": repetition,
            "benchmark_attempt": attempt,
        }
    )
    ledger_cursor = mesh.ledger.mark()
    trace_cursor = len(recorder.traces)
    started = time.perf_counter()
    result_task: Task | None = None
    error: Exception | None = None
    timed_out = False
    try:
        result_task = await asyncio.wait_for(
            mesh.client.send_task(mesh.coordinator.card.url, task),
            timeout=timeout,
        )
    except TimeoutError as exc:
        error = exc
        timed_out = True
    except Exception as exc:
        error = exc
    latency_ms = (time.perf_counter() - started) * 1000
    trace = _find_trace(recorder, task_id=task.id, cursor=trace_cursor)
    return _validate_attempt(
        case=case,
        repetition=repetition,
        attempt=attempt,
        task=result_task or task,
        trace=trace,
        ledger_entries=mesh.ledger.since(ledger_cursor),
        latency_ms=latency_ms,
        error=error,
        timed_out=timed_out,
    )


def _percent(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100.0) if denominator else 0.0, 3)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def _distribution(values: list[float]) -> dict[str, float | int]:
    """Return stable latency statistics in milliseconds."""
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "count": 0,
            "total_ms": 0.0,
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
        }
    return {
        "count": len(clean),
        "total_ms": round(sum(clean), 3),
        "mean_ms": round(statistics.fmean(clean), 3),
        "median_ms": round(statistics.median(clean), 3),
        "p95_ms": _percentile(clean, 0.95),
        "min_ms": round(min(clean), 3),
        "max_ms": round(max(clean), 3),
    }


def _speedup_percent(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return round((before - after) / before * 100.0, 3)


def _cache_probe(case_results: list[CaseResult], calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare retry-free strict first attempts across adjacent repetitions."""
    first_by_case: dict[str, dict[int, AttemptResult]] = {}
    for result in case_results:
        if result.attempts:
            first_by_case.setdefault(result.case_id, {})[result.repetition] = result.attempts[0]

    e2e_speedups: list[float] = []
    llm_speedups: list[float] = []
    first_llm_speedups: list[float] = []
    prompt_eval_speedups: list[float] = []
    first_prompt_eval_speedups: list[float] = []
    pairs = 0
    excluded_retry_pairs = 0
    for repetitions in first_by_case.values():
        for repetition in sorted(repetitions):
            if repetition <= 1 or repetition - 1 not in repetitions:
                continue
            before = repetitions[repetition - 1]
            after = repetitions[repetition]
            if not before.strict_pass or not after.strict_pass or before.llm_calls != after.llm_calls:
                continue
            if (
                not before.timing_complete
                or not after.timing_complete
                or before.provider_retries
                or after.provider_retries
                or before.provider_attempts != before.completed_provider_attempts
                or after.provider_attempts != after.completed_provider_attempts
            ):
                excluded_retry_pairs += 1
                continue
            pairs += 1
            e2e = _speedup_percent(before.latency_ms, after.latency_ms)
            llm = _speedup_percent(before.llm_latency_ms, after.llm_latency_ms)
            first_llm = _speedup_percent(before.first_llm_latency_ms, after.first_llm_latency_ms)
            prompt_eval = _speedup_percent(before.provider_prompt_eval_ms, after.provider_prompt_eval_ms)
            before_first_prompt = _numeric(
                before.llm_call_timings[0].get("provider_prompt_eval_ms") if before.llm_call_timings else None
            )
            after_first_prompt = _numeric(
                after.llm_call_timings[0].get("provider_prompt_eval_ms") if after.llm_call_timings else None
            )
            first_prompt_eval = (
                _speedup_percent(before_first_prompt, after_first_prompt)
                if before_first_prompt is not None and after_first_prompt is not None
                else None
            )
            if e2e is not None:
                e2e_speedups.append(e2e)
            if llm is not None:
                llm_speedups.append(llm)
            if first_llm is not None:
                first_llm_speedups.append(first_llm)
            if prompt_eval is not None:
                prompt_eval_speedups.append(prompt_eval)
            if first_prompt_eval is not None:
                first_prompt_eval_speedups.append(first_prompt_eval)

    explicit_cache_calls = [
        call
        for call in calls
        if call.get("cached_input_tokens") is not None or call.get("cache_write_input_tokens") is not None
    ]
    return {
        "method": "paired_adjacent_case_repetitions",
        "interpretation": (
            "first-call timing compares equivalent initial provider inputs; whole-attempt timing also includes "
            "model-generated action history. Neither proves a provider cache hit"
        ),
        "eligible_strict_pairs": pairs,
        "excluded_retry_or_incomplete_pairs": excluded_retry_pairs,
        "median_e2e_speedup_percent": (round(statistics.median(e2e_speedups), 3) if e2e_speedups else None),
        "median_llm_speedup_percent": (round(statistics.median(llm_speedups), 3) if llm_speedups else None),
        "median_first_llm_speedup_percent": (
            round(statistics.median(first_llm_speedups), 3) if first_llm_speedups else None
        ),
        "median_prompt_eval_speedup_percent": (
            round(statistics.median(prompt_eval_speedups), 3) if prompt_eval_speedups else None
        ),
        "median_first_prompt_eval_speedup_percent": (
            round(statistics.median(first_prompt_eval_speedups), 3) if first_prompt_eval_speedups else None
        ),
        "explicit_cache_metrics_available": bool(explicit_cache_calls),
        "explicit_cache_metric_calls": len(explicit_cache_calls),
        "cached_input_tokens": sum(int(call.get("cached_input_tokens") or 0) for call in explicit_cache_calls),
        "cache_write_input_tokens": sum(int(call.get("cache_write_input_tokens") or 0) for call in calls),
    }


def _timing_summary(
    *,
    case_results: list[CaseResult],
    attempts: list[AttemptResult],
    warmups: list[dict[str, Any]],
    lifecycle: dict[str, float],
) -> dict[str, Any]:
    first_attempts = [result.attempts[0] for result in case_results if result.attempts]
    strict_first_attempts = [result for result in first_attempts if result.strict_pass]
    selected_attempts = [result.selected_attempt for result in case_results]
    calls = [
        {
            **call,
            "case_id": attempt.case_id,
            "repetition": attempt.repetition,
            "attempt": attempt.attempt,
            "task_id": attempt.task_id,
        }
        for attempt in attempts
        for call in attempt.llm_call_timings
    ]

    by_repetition: list[dict[str, Any]] = []
    for repetition in sorted({result.repetition for result in case_results}):
        selected = [
            result.attempts[0] for result in case_results if result.repetition == repetition and result.attempts
        ]
        by_repetition.append(
            {
                "repetition": repetition,
                "first_attempt_e2e_ms": _distribution([result.latency_ms for result in selected]),
                "first_attempt_llm_ms": _distribution([result.llm_latency_ms for result in selected]),
                "strict_first_attempts": sum(result.strict_pass for result in selected),
            }
        )

    by_llm_step: list[dict[str, Any]] = []
    for step in sorted({int(call["step"]) for call in calls}):
        selected = [call for call in calls if int(call["step"]) == step]
        by_llm_step.append(
            {
                "step": step,
                "latency_ms": _distribution([float(call["latency_ms"]) for call in selected]),
                "prompt_eval_ms": _distribution(
                    [
                        float(call["provider_prompt_eval_ms"])
                        for call in selected
                        if call.get("provider_prompt_eval_ms") is not None
                    ]
                ),
                "input_tokens": sum(int(call.get("input_tokens") or 0) for call in selected),
                "output_tokens": sum(int(call.get("output_tokens") or 0) for call in selected),
            }
        )

    prompt_tokens = sum(int(call.get("provider_prompt_tokens") or 0) for call in calls)
    prompt_eval_ms = sum(float(call.get("provider_prompt_eval_ms") or 0.0) for call in calls)
    output_tokens = sum(int(call.get("provider_output_tokens") or 0) for call in calls)
    generation_ms = sum(float(call.get("provider_generation_ms") or 0.0) for call in calls)
    warmup_latencies = [float(item["latency_ms"]) for item in warmups]
    return {
        "clock": "time.perf_counter",
        "unit": "ms",
        **{name: round(value, 3) for name, value in lifecycle.items()},
        "attempt_e2e_ms": _distribution([result.latency_ms for result in attempts]),
        "first_attempt_e2e_ms": _distribution([result.latency_ms for result in first_attempts]),
        "strict_first_attempt_e2e_ms": _distribution([result.latency_ms for result in strict_first_attempts]),
        "selected_attempt_e2e_ms": _distribution([result.latency_ms for result in selected_attempts]),
        "llm_per_attempt_ms": _distribution([result.llm_latency_ms for result in attempts]),
        "non_llm_per_attempt_ms": _distribution(
            [result.non_llm_latency_ms for result in attempts if result.non_llm_latency_ms is not None]
        ),
        "llm_calls": {
            "count": len(calls),
            "latency_ms": _distribution([float(call["latency_ms"]) for call in calls]),
            "input_tokens": sum(int(call.get("input_tokens") or 0) for call in calls),
            "output_tokens": sum(int(call.get("output_tokens") or 0) for call in calls),
            "total_tokens": sum(int(call.get("total_tokens") or 0) for call in calls),
            "estimated_usage_calls": sum(call.get("usage_estimated") is True for call in calls),
        },
        "provider": {
            "timing_available_calls": sum(
                any(
                    call.get(name) is not None
                    for name in (
                        "provider_total_ms",
                        "provider_load_ms",
                        "provider_prompt_eval_ms",
                        "provider_generation_ms",
                    )
                )
                for call in calls
            ),
            "total_ms": round(sum(float(call.get("provider_total_ms") or 0.0) for call in calls), 3),
            "load_ms": round(sum(float(call.get("provider_load_ms") or 0.0) for call in calls), 3),
            "prompt_eval_ms": round(prompt_eval_ms, 3),
            "generation_ms": round(generation_ms, 3),
            "prompt_tokens_per_second": (
                round(prompt_tokens / (prompt_eval_ms / 1000), 3) if prompt_tokens and prompt_eval_ms > 0 else None
            ),
            "output_tokens_per_second": (
                round(output_tokens / (generation_ms / 1000), 3) if output_tokens and generation_ms > 0 else None
            ),
        },
        "warmup": {
            "requested": len(warmups),
            "completed": sum(item["completed"] for item in warmups),
            "failed": sum(not item["completed"] for item in warmups),
            "e2e_ms": _distribution(warmup_latencies),
            "runs": warmups,
        },
        "by_repetition": by_repetition,
        "by_llm_step": by_llm_step,
        "cache_probe": _cache_probe(case_results, calls),
    }


def _aggregate_scores(case_results: list[CaseResult], attempts: list[AttemptResult]) -> dict[str, Any]:
    total = len(case_results)
    strict = sum(result.strict_pass for result in case_results)
    functional = sum(result.functional_pass for result in case_results)
    first_try = sum(result.first_attempt_strict for result in case_results)
    rescued = sum(result.strict_pass and not result.first_attempt_strict for result in case_results)
    categories: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        selected = [result for result in case_results if result.category == category]
        if not selected:
            continue
        category_strict = sum(result.strict_pass for result in selected)
        category_functional = sum(result.functional_pass for result in selected)
        categories[category] = {
            "total": len(selected),
            "strict": category_strict,
            "strict_percent": _percent(category_strict, len(selected)),
            "functional": category_functional,
            "functional_percent": _percent(category_functional, len(selected)),
        }

    steps = [float(result.llm_steps) for result in attempts]
    latencies = [result.latency_ms for result in attempts]
    return {
        "total": total,
        "strict": strict,
        "strict_percent": _percent(strict, total),
        "functional": functional,
        "functional_percent": _percent(functional, total),
        "first_attempt_strict": first_try,
        "first_attempt_strict_percent": _percent(first_try, total),
        "rescued_on_later_attempt": rescued,
        "failed": total - strict,
        "attempts_executed": len(attempts),
        "timed_out_attempts": sum(result.timed_out for result in attempts),
        "crashed_attempts": sum(result.crashed for result in attempts),
        "hallucinated_action_attempts": sum(result.hallucinated_action for result in attempts),
        "parse_recovery_attempts": sum(result.parse_errors > 0 for result in attempts),
        "provider_retry_attempts": sum(result.provider_retries > 0 for result in attempts),
        "average_llm_steps": round(sum(steps) / len(steps), 3) if steps else 0.0,
        "p95_llm_steps": _percentile(steps, 0.95),
        "average_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "categories": categories,
    }


def _suite_hash(cases: list[BenchmarkCase]) -> str:
    payload = {
        "suite_version": SUITE_VERSION,
        "cases": [case.to_dict() for case in cases],
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def _repository_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "protolink").is_dir():
            return parent
    return None


def _prompt_source_hash() -> str:
    repository_root = _repository_root()
    package_root = repository_root / "protolink" if repository_root is not None else Path(__file__).resolve().parents[2]
    candidates = sorted((package_root / "llms" / "prompts").glob("*.py"))
    candidates.append(package_root / "llms" / "base.py")
    digest = hashlib.sha256()
    for path in candidates:
        if path.exists():
            digest.update(str(path.relative_to(package_root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_metadata() -> dict[str, Any]:
    repository_root = _repository_root()
    if repository_root is None:
        return {"commit": None, "dirty": None}
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": revision, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:80] or "run"


def _create_output_dir(config: BenchmarkConfig) -> Path:
    root = config.output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default_name = f"{timestamp}-{_safe_slug(config.provider)}-{_safe_slug(config.model or 'default')}"
    path = root / _safe_slug(config.run_name or default_name)
    if path.exists():
        suffix = 2
        while path.with_name(f"{path.name}-{suffix}").exists():
            suffix += 1
        path = path.with_name(f"{path.name}-{suffix}")
    path.mkdir(parents=False)
    return path


def _redact_config(value: Any) -> Any:
    secret_fragments = ("api_key", "apikey", "authorization", "credential", "password", "secret", "token")
    if isinstance(value, dict):
        return {
            str(key): (
                "***REDACTED***"
                if any(fragment in str(key).casefold() for fragment in secret_fragments)
                else _redact_config(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_config(item) for item in value]
    return value


def _attempt_row(
    *,
    run_id: str,
    suite_hash: str,
    provider: str,
    model: str,
    result: AttemptResult,
) -> dict[str, Any]:
    row = result.to_dict()
    row.update(
        {
            "run_id": run_id,
            "suite_hash": suite_hash,
            "provider": provider,
            "model": model,
            "failure_codes": "|".join(result.failure_codes),
            "expected_actions": json.dumps(result.expected_actions, ensure_ascii=False, sort_keys=True),
            "observed_actions": json.dumps(result.observed_actions, ensure_ascii=False, sort_keys=True),
            "trace_actions": json.dumps(result.trace_actions, ensure_ascii=False, sort_keys=True),
            "llm_call_timings": json.dumps(result.llm_call_timings, ensure_ascii=False, sort_keys=True),
        }
    )
    return row


def _llm_call_rows(
    *,
    run_id: str,
    suite_hash: str,
    provider: str,
    model: str,
    attempts: list[AttemptResult],
) -> list[dict[str, Any]]:
    return [
        {
            "case_id": result.case_id,
            "category": result.category,
            "repetition": result.repetition,
            "attempt": result.attempt,
            "task_id": result.task_id,
            "strict_pass": result.strict_pass,
            "functional_pass": result.functional_pass,
            "run_id": run_id,
            "suite_hash": suite_hash,
            "provider": provider,
            "model": model,
            **call,
        }
        for result in attempts
        for call in result.llm_call_timings
    ]


def _llm_call_fieldnames() -> list[str]:
    return [
        "case_id",
        "category",
        "repetition",
        "attempt",
        "task_id",
        "strict_pass",
        "functional_pass",
        "run_id",
        "suite_hash",
        "provider",
        "model",
        *(item.name for item in dataclass_fields(LLMCallResult)),
    ]


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str] | None = None,
) -> None:
    resolved_fieldnames = list(fieldnames or ())
    for row in rows:
        for key in row:
            if key not in resolved_fieldnames:
                resolved_fieldnames.append(key)
    if not resolved_fieldnames:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=resolved_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _paired_performance_metric(
    pairs: list[tuple[dict[str, Any], AttemptResult]],
    field: str,
    *,
    require_same_call_count: bool = False,
    require_provider_timing: bool = False,
) -> dict[str, Any]:
    baseline_values: list[float] = []
    current_values: list[float] = []
    deltas: list[float] = []
    delta_percents: list[float] = []
    for old, new in pairs:
        if require_same_call_count and _integer(old.get("llm_calls")) != new.llm_calls:
            continue
        if require_provider_timing and (
            (_integer(old.get("provider_timing_calls")) or 0) < 1 or new.provider_timing_calls < 1
        ):
            continue
        old_value = _numeric(old.get(field))
        new_value = _numeric(getattr(new, field, None))
        if old_value is None or new_value is None:
            continue
        baseline_values.append(old_value)
        current_values.append(new_value)
        deltas.append(new_value - old_value)
        if old_value > 0:
            delta_percents.append((new_value - old_value) / old_value * 100.0)
    return {
        "field": field,
        "matched_pairs": len(baseline_values),
        "baseline_ms": _distribution(baseline_values),
        "current_ms": _distribution(current_values),
        "median_paired_delta_ms": round(statistics.median(deltas), 3) if deltas else None,
        "median_paired_delta_percent": (round(statistics.median(delta_percents), 3) if delta_percents else None),
        "median_paired_speedup_percent": (round(-statistics.median(delta_percents), 3) if delta_percents else None),
    }


def compare_with_baseline(
    *,
    current_cases: list[CaseResult],
    current_suite_hash: str,
    baseline_path: Path,
    current_timing: dict[str, Any] | None = None,
    current_performance_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare correctness and paired timing against a previous summary."""
    baseline = json.loads(baseline_path.expanduser().read_text(encoding="utf-8"))
    baseline_hash = baseline.get("suite", {}).get("hash")
    if baseline_hash != current_suite_hash:
        raise ValueError(
            "Baseline suite hash does not match this run. Use the same suite, seed, filters, and generated case count."
        )
    old_case_items = {
        str(item["key"]): item for item in baseline.get("case_results", []) if isinstance(item, dict) and "key" in item
    }
    old_cases = {
        item["key"]: bool(item["strict_pass"])
        for item in baseline.get("case_results", [])
        if isinstance(item, dict) and "key" in item
    }
    current = {result.key: result.strict_pass for result in current_cases}
    if set(old_cases) != set(current):
        raise ValueError("Baseline logical case keys do not match this run")
    transitions = {"fixed": [], "regressed": [], "stable_pass": [], "stable_fail": []}
    for key, passed in current.items():
        old_passed = old_cases[key]
        if old_passed and passed:
            transitions["stable_pass"].append(key)
        elif old_passed and not passed:
            transitions["regressed"].append(key)
        elif not old_passed and passed:
            transitions["fixed"].append(key)
        else:
            transitions["stable_fail"].append(key)
    previous_strict = sum(old_cases.values())
    current_strict = sum(current.values())
    strict_first_pairs: list[tuple[dict[str, Any], AttemptResult]] = []
    excluded_retry_or_incomplete_pairs = 0
    for result in current_cases:
        old_item = old_case_items[result.key]
        old_attempts = old_item.get("attempts")
        if not isinstance(old_attempts, list) or not old_attempts or not result.attempts:
            continue
        old_first = old_attempts[0]
        new_first = result.attempts[0]
        if isinstance(old_first, dict) and bool(old_first.get("strict_pass")) and new_first.strict_pass:
            if (
                (_integer(old_first.get("provider_retries")) or 0) > 0
                or new_first.provider_retries > 0
                or not new_first.timing_complete
            ):
                excluded_retry_or_incomplete_pairs += 1
                continue
            strict_first_pairs.append((old_first, new_first))

    baseline_fingerprint = baseline.get("performance_fingerprint")
    fingerprint_match = (
        baseline_fingerprint == current_performance_fingerprint
        if baseline_fingerprint is not None and current_performance_fingerprint is not None
        else None
    )
    performance = {
        "available": bool(strict_first_pairs),
        "fingerprint_match": fingerprint_match,
        "warning": (
            "Provider or performance settings differ; timing deltas are not directly comparable."
            if fingerprint_match is False
            else None
        ),
        "matched_strict_first_attempts": len(strict_first_pairs),
        "excluded_retry_or_incomplete_pairs": excluded_retry_or_incomplete_pairs,
        "e2e": _paired_performance_metric(strict_first_pairs, "latency_ms"),
        "llm": _paired_performance_metric(
            strict_first_pairs,
            "llm_latency_ms",
            require_same_call_count=True,
        ),
        "provider_prompt_eval": _paired_performance_metric(
            strict_first_pairs,
            "provider_prompt_eval_ms",
            require_same_call_count=True,
            require_provider_timing=True,
        ),
        "scored_wall_ms": {
            "baseline": _numeric(baseline.get("timing", {}).get("scored_wall_ms")),
            "current": _numeric((current_timing or {}).get("scored_wall_ms")),
        },
        "cache_probe": {
            "baseline": baseline.get("timing", {}).get("cache_probe"),
            "current": (current_timing or {}).get("cache_probe"),
        },
    }
    return {
        "path": str(baseline_path.expanduser().resolve()),
        "previous_strict": previous_strict,
        "current_strict": current_strict,
        "delta": current_strict - previous_strict,
        "performance": performance,
        **transitions,
    }


def _select_cases(config: BenchmarkConfig) -> list[BenchmarkCase]:
    generated_count = config.count if config.count is not None else SUITE_SIZES[config.suite]
    selected = generate_cases(generated_count, seed=config.seed)
    if config.categories:
        selected = [case for case in selected if case.category in config.categories]
    if config.case_patterns:
        selected = [
            case for case in selected if any(fnmatch.fnmatchcase(case.id, pattern) for pattern in config.case_patterns)
        ]
    if config.shuffle:
        random.Random(config.seed).shuffle(selected)
    if config.limit is not None:
        selected = selected[: config.limit]
    if not selected:
        raise ValueError("Case selection is empty")
    return selected


def _create_llm(config: BenchmarkConfig) -> LLM:
    options = dict(config.provider_options)
    if config.model is not None:
        options["model"] = config.model
    if config.base_url is not None:
        options["base_url"] = config.base_url
    if config.model_params:
        options["model_params"] = dict(config.model_params)
    options["max_parse_failures"] = config.max_parse_failures
    if config.provider in {"ollama", "llama.cpp-server", "lmstudio", "openai-compatible", "vllm"}:
        options["supports_tool_calling"] = config.supports_tool_calling
    return create_llm(config.provider, **options)


async def _warm_up(
    mesh: BenchmarkMesh,
    recorder: LocalTraceRecorder,
    count: int,
    timeout: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index in range(count):
        token = f"BENCH-WARMUP-{index + 1}"
        task = Task.create_infer(prompt=f"Do not call tools or agents. Return exactly {token}")
        task.metadata["benchmark_warmup"] = True
        trace_cursor = len(recorder.traces)
        started = time.perf_counter()
        result_task: Task | None = None
        error: Exception | None = None
        try:
            result_task = await asyncio.wait_for(
                mesh.client.send_task(mesh.coordinator.card.url, task),
                timeout=timeout,
            )
        except Exception as exc:
            error = exc
            # A warm-up is excluded from scores; the scored suite will expose a
            # persistent provider or prompt problem with full diagnostics.
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        trace = _find_trace(recorder, task_id=task.id, cursor=trace_cursor)
        metrics, call_timings = _trace_metrics(trace)
        final_output = _find_infer_output(result_task or task)
        results.append(
            {
                "index": index + 1,
                "task_id": task.id,
                "completed": (
                    error is None
                    and _task_state(result_task or task) == TaskState.COMPLETED.value
                    and final_output == token
                ),
                "latency_ms": latency_ms,
                "llm_latency_ms": metrics["llm_latency_ms"],
                "provider_load_ms": metrics["provider_load_ms"],
                "provider_prompt_eval_ms": metrics["provider_prompt_eval_ms"],
                "provider_generation_ms": metrics["provider_generation_ms"],
                "llm_call_timings": [call.to_dict() for call in call_timings],
                "error_type": type(error).__name__ if error is not None else None,
                "error_message": str(error) if error is not None else None,
            }
        )
    return results


def _progress_line(
    *,
    logical_index: int,
    logical_total: int,
    result: AttemptResult,
) -> str:
    if result.strict_pass:
        status = "STRICT PASS"
    elif result.functional_pass:
        status = "FUNCTIONAL/RECOVERED"
    else:
        status = "FAIL"
    return (
        f"[{logical_index:>3}/{logical_total}] {result.case_id} "
        f"attempt {result.attempt}: {status} "
        f"({result.llm_steps} step(s), e2e={result.latency_ms / 1000:.2f}s, "
        f"llm={result.llm_latency_ms / 1000:.2f}s)"
    )


async def run_benchmark(config: BenchmarkConfig, *, llm: LLM | None = None) -> BenchmarkRun:
    """Execute a configured benchmark and write its artifacts."""
    benchmark_started = time.perf_counter()
    cases = _select_cases(config)
    suite_hash = _suite_hash(cases)
    git = _git_metadata()
    prompt_hash = _prompt_source_hash()
    output_dir = _create_output_dir(config)
    run_id = output_dir.name
    recorder = LocalTraceRecorder(path=output_dir / "traces.jsonl", max_traces=0)
    active_llm = llm or _create_llm(config)
    preflight_started = time.perf_counter()
    if config.preflight:
        if not active_llm.validate_connection():
            raise RuntimeError(
                f"Provider preflight failed for {config.provider}/{getattr(active_llm, 'model', config.model)}"
            )
    preflight_ms = (time.perf_counter() - preflight_started) * 1000 if config.preflight else 0.0
    resolved_model = str(getattr(active_llm, "model", None) or config.model or "default")
    mesh = BenchmarkMesh(
        llm=active_llm,
        recorder=recorder,
        system_prompt=config.system_prompt,
        verbosity=config.verbosity,
    )
    case_results: list[CaseResult] = []
    attempt_results: list[AttemptResult] = []
    logical_total = len(cases) * config.repetitions
    logical_index = 0
    startup_ms = 0.0
    warmup_results: list[dict[str, Any]] = []
    warmup_wall_ms = 0.0
    scored_wall_ms = 0.0
    progress_output_ms = 0.0
    teardown_ms = 0.0
    try:
        startup_started = time.perf_counter()
        await mesh.start()
        startup_ms = (time.perf_counter() - startup_started) * 1000
        warmup_started = time.perf_counter()
        warmup_results = await _warm_up(mesh, recorder, config.warmup, config.timeout)
        warmup_wall_ms = (time.perf_counter() - warmup_started) * 1000
        scored_started = time.perf_counter()
        # Case-major repetitions keep identical prompts adjacent, which makes
        # the paired repeat signal more useful for prompt-cache comparisons.
        for case in cases:
            for repetition in range(1, config.repetitions + 1):
                logical_index += 1
                current_attempts: list[AttemptResult] = []
                for attempt_number in range(1, config.attempts + 1):
                    result = await run_attempt(
                        mesh=mesh,
                        recorder=recorder,
                        case=case,
                        repetition=repetition,
                        attempt=attempt_number,
                        timeout=config.timeout,
                    )
                    current_attempts.append(result)
                    attempt_results.append(result)
                    if not config.quiet:
                        progress_started = time.perf_counter()
                        print(
                            _progress_line(
                                logical_index=logical_index,
                                logical_total=logical_total,
                                result=result,
                            ),
                            flush=True,
                        )
                        progress_output_ms += (time.perf_counter() - progress_started) * 1000
                    if result.strict_pass:
                        break
                case_results.append(
                    CaseResult(
                        case_id=case.id,
                        category=case.category,
                        repetition=repetition,
                        attempts=current_attempts,
                    )
                )
        scored_wall_ms = max((time.perf_counter() - scored_started) * 1000 - progress_output_ms, 0.0)
    finally:
        teardown_started = time.perf_counter()
        mesh.stop()
        teardown_ms = (time.perf_counter() - teardown_started) * 1000

    scores = _aggregate_scores(case_results, attempt_results)
    timing = _timing_summary(
        case_results=case_results,
        attempts=attempt_results,
        warmups=warmup_results,
        lifecycle={
            "preflight_ms": preflight_ms,
            "startup_ms": startup_ms,
            "warmup_wall_ms": warmup_wall_ms,
            "scored_wall_ms": scored_wall_ms,
            "progress_output_ms": progress_output_ms,
            "teardown_ms": teardown_ms,
            "benchmark_wall_ms": (time.perf_counter() - benchmark_started) * 1000,
        },
    )
    provider_summary = {
        "name": config.provider,
        "model": resolved_model,
        "base_url": config.base_url,
        "model_params": _redact_config(config.model_params),
        "provider_options": _redact_config(config.provider_options),
        "supports_tool_calling": config.supports_tool_calling,
        "action_mode": "native" if active_llm.uses_native_action_prompt else "json_prompt",
        "max_parse_failures": config.max_parse_failures,
    }
    performance_fingerprint = {
        "provider": provider_summary,
        "warmup": config.warmup,
        "warmup_completed": sum(item["completed"] for item in warmup_results),
        "warmup_failed": sum(not item["completed"] for item in warmup_results),
        "repetition_order": "case_major",
        "repetitions": config.repetitions,
        "max_fresh_attempts": config.attempts,
        "timeout": config.timeout,
        "verbosity": config.verbosity,
    }
    summary: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protolink_version": __version__,
        "provider": provider_summary,
        "suite": {
            "id": config.suite,
            "version": SUITE_VERSION,
            "hash": suite_hash,
            "seed": config.seed,
            "generated_count": config.count if config.count is not None else SUITE_SIZES[config.suite],
            "selected_count": len(cases),
            "repetitions": config.repetitions,
            "max_fresh_attempts": config.attempts,
            "categories": list(config.categories),
            "case_patterns": list(config.case_patterns),
            "shuffle": config.shuffle,
            "repetition_order": "case_major",
        },
        "prompt_hash": prompt_hash,
        "benchmark_system_prompt_hash": hashlib.sha256(config.system_prompt.encode()).hexdigest(),
        "git": git,
        "scores": scores,
        "timing": timing,
        "performance_fingerprint": performance_fingerprint,
        "case_results": [result.to_dict() for result in case_results],
    }
    if config.baseline is not None:
        summary["baseline_comparison"] = compare_with_baseline(
            current_cases=case_results,
            current_suite_hash=suite_hash,
            baseline_path=config.baseline,
            current_timing=timing,
            current_performance_fingerprint=performance_fingerprint,
        )

    rows = [
        _attempt_row(
            run_id=run_id,
            suite_hash=suite_hash,
            provider=config.provider,
            model=resolved_model,
            result=result,
        )
        for result in attempt_results
    ]
    _write_csv(output_dir / "results.csv", rows)
    llm_call_rows = _llm_call_rows(
        run_id=run_id,
        suite_hash=suite_hash,
        provider=config.provider,
        model=resolved_model,
        attempts=attempt_results,
    )
    _write_csv(
        output_dir / "llm_calls.csv",
        llm_call_rows,
        fieldnames=_llm_call_fieldnames(),
    )
    failure_keys = {result.key for result in case_results if not result.strict_pass}
    failure_rows = [
        row
        for row, result in zip(rows, attempt_results, strict=True)
        if f"{result.case_id}#r{result.repetition}" in failure_keys
    ]
    _write_csv(
        output_dir / "failures.csv",
        failure_rows,
        fieldnames=list(rows[0]) if rows else None,
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return BenchmarkRun(
        output_dir=output_dir,
        summary=summary,
        cases=case_results,
        attempts=attempt_results,
    )


def _parse_key_value(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("expected KEY=JSON_VALUE")
    key, raw_value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("configuration key must not be empty")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return key, value


def _pairs_to_dict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        values[key] = value
    return values


def build_parser() -> argparse.ArgumentParser:
    """Create the benchmark command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark ProtoLink's infer loop with deterministic final, tool, delegation, multi-step, "
            "and grounding tasks."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    provider_group = parser.add_argument_group("provider")
    provider_group.add_argument("--provider", default="ollama", help="Provider passed to create_llm().")
    provider_group.add_argument("--model", help="Exact model id; provider default when omitted.")
    provider_group.add_argument(
        "--base-url",
        help="Provider server URL. Ollama defaults to OLLAMA_URL or http://localhost:11434.",
    )
    provider_group.add_argument("--temperature", type=float, default=0.0)
    provider_group.add_argument("--model-seed", type=int, default=1337, help="Ollama sampling seed.")
    provider_group.add_argument("--num-ctx", type=int, default=8192, help="Ollama context window.")
    provider_group.add_argument("--num-predict", type=int, default=2048, help="Ollama generation limit.")
    provider_group.add_argument(
        "--model-param",
        action="append",
        default=[],
        type=_parse_key_value,
        metavar="KEY=JSON_VALUE",
        help="Repeatable provider model parameter; overrides convenience defaults.",
    )
    provider_group.add_argument(
        "--provider-option",
        action="append",
        default=[],
        type=_parse_key_value,
        metavar="KEY=JSON_VALUE",
        help="Repeatable create_llm constructor option outside model_params.",
    )
    provider_group.add_argument(
        "--api-key-env",
        help="Read an API key from this environment variable and pass it as api_key.",
    )
    provider_group.add_argument(
        "--supports-tool-calling",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use a server model's native tool interface instead of the JSON prompt fallback.",
    )
    provider_group.add_argument(
        "--max-parse-failures",
        type=int,
        default=3,
        help="Consecutive action-envelope parse attempts allowed by the infer loop (1..10).",
    )
    provider_group.add_argument(
        "--preflight",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate the provider connection before scoring.",
    )
    provider_group.add_argument(
        "--warmup",
        type=int,
        help="Unscored warm-up tasks. Defaults to 1 for Ollama and 0 for other providers.",
    )

    suite_group = parser.add_argument_group("suite")
    suite_group.add_argument("--suite", choices=sorted(SUITE_SIZES), default="smoke")
    suite_group.add_argument("--count", type=int, help="Override the suite's generated case count.")
    suite_group.add_argument("--seed", type=int, default=1337, help="Deterministic task-generation seed.")
    suite_group.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Fresh attempts per logical case, stopping after the first strict pass.",
    )
    suite_group.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Repeat each selected case adjacently for reliability and cache-sensitive timing.",
    )
    suite_group.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Best-effort timeout in seconds per task.",
    )
    suite_group.add_argument(
        "--category",
        action="append",
        choices=CATEGORIES,
        default=[],
        help="Run only this category; repeat the option to select more.",
    )
    suite_group.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run case ids matching this shell-style pattern; repeatable.",
    )
    suite_group.add_argument("--limit", type=int, help="Run only the first N filtered cases.")
    suite_group.add_argument("--shuffle", action="store_true", help="Shuffle selected cases with --seed.")
    suite_group.add_argument(
        "--list-cases",
        action="store_true",
        help="Print selected case ids and prompts without contacting a provider.",
    )

    output_group = parser.add_argument_group("output and comparison")
    output_group.add_argument(
        "--output-dir", default="benchmark_results", help="Parent directory for timestamped runs."
    )
    output_group.add_argument("--run-name", help="Optional output subdirectory name.")
    output_group.add_argument(
        "--baseline",
        type=Path,
        help="Previous summary.json to compare correctness transitions and paired timing.",
    )
    output_group.add_argument(
        "--fail-under",
        type=float,
        help="Exit 2 when the strict percentage is lower than this threshold.",
    )
    output_group.add_argument(
        "--system-prompt-file",
        type=Path,
        help="Replace the benchmark's complementary coordinator instructions from a UTF-8 file.",
    )
    output_group.add_argument("--quiet", action="store_true", help="Hide per-attempt progress.")
    output_group.add_argument("--verbosity", type=int, choices=(0, 1, 2), default=0)
    return parser


def _validate_cli_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.count is not None and args.count < 1:
        parser.error("--count must be at least 1")
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.warmup is not None and args.warmup < 0:
        parser.error("--warmup must not be negative")
    if args.max_parse_failures < 1 or args.max_parse_failures > 10:
        parser.error("--max-parse-failures must be between 1 and 10")
    if args.fail_under is not None and not 0 <= args.fail_under <= 100:
        parser.error("--fail-under must be between 0 and 100")
    if args.num_ctx < 1 or args.num_predict < 1:
        parser.error("--num-ctx and --num-predict must be at least 1")


def config_from_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> BenchmarkConfig:
    """Resolve provider-aware defaults without hiding them from the summary."""
    _validate_cli_args(parser, args)
    provider = str(args.provider).lower()
    model_params: dict[str, Any] = {"temperature": args.temperature}
    base_url = args.base_url
    if provider == "ollama":
        base_url = base_url or os.getenv("OLLAMA_URL") or "http://localhost:11434"
        model_params.update(
            {
                "seed": args.model_seed,
                "num_ctx": args.num_ctx,
                "num_predict": args.num_predict,
            }
        )
    model_params.update(_pairs_to_dict(args.model_param))
    provider_options = _pairs_to_dict(args.provider_option)
    if args.api_key_env:
        api_key = os.getenv(args.api_key_env)
        if not api_key:
            parser.error(f"--api-key-env points to unset or empty variable {args.api_key_env!r}")
        provider_options["api_key"] = api_key
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if args.system_prompt_file:
        try:
            system_prompt = args.system_prompt_file.expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"could not read --system-prompt-file: {exc}")
    warmup = args.warmup if args.warmup is not None else (1 if provider == "ollama" else 0)
    return BenchmarkConfig(
        provider=provider,
        model=args.model,
        base_url=base_url,
        model_params=model_params,
        provider_options=provider_options,
        max_parse_failures=args.max_parse_failures,
        supports_tool_calling=args.supports_tool_calling,
        suite=args.suite,
        count=args.count,
        seed=args.seed,
        attempts=args.attempts,
        repetitions=args.repetitions,
        timeout=args.timeout,
        categories=tuple(args.category),
        case_patterns=tuple(args.case),
        limit=args.limit,
        shuffle=args.shuffle,
        warmup=warmup,
        preflight=args.preflight,
        output_root=Path(args.output_dir),
        run_name=args.run_name,
        baseline=args.baseline,
        fail_under=args.fail_under,
        system_prompt=system_prompt,
        verbosity=args.verbosity,
        quiet=args.quiet,
    )


def _print_summary(run: BenchmarkRun) -> None:
    scores = run.summary["scores"]
    timing = run.summary["timing"]
    print()
    print(f"STRICT     {scores['strict']}/{scores['total']} ({scores['strict_percent']:.1f}%)")
    print(f"FUNCTIONAL {scores['functional']}/{scores['total']} ({scores['functional_percent']:.1f}%)")
    print(
        f"FIRST TRY  {scores['first_attempt_strict']}/{scores['total']} ({scores['first_attempt_strict_percent']:.1f}%)"
    )
    print(f"RESCUED ON LATER ATTEMPT {scores['rescued_on_later_attempt']}")
    print(
        "ATTEMPT DIAGNOSTICS "
        f"parse-recovery={scores['parse_recovery_attempts']} "
        f"hallucinated-action={scores['hallucinated_action_attempts']} "
        f"crashed={scores['crashed_attempts']} timed-out={scores['timed_out_attempts']}"
    )
    strict_timing = timing["strict_first_attempt_e2e_ms"]
    print(
        f"LLM STEPS avg={scores['average_llm_steps']:.2f} p95={scores['p95_llm_steps']:.0f}; "
        f"STRICT FIRST-TRY LATENCY median={strict_timing['median_ms'] / 1000:.2f}s "
        f"p95={strict_timing['p95_ms'] / 1000:.2f}s"
    )
    print(
        f"WALL TIME  scored={timing['scored_wall_ms'] / 1000:.2f}s "
        f"warmup={timing['warmup_wall_ms'] / 1000:.2f}s; "
        f"LLM CALLS median={timing['llm_calls']['latency_ms']['median_ms'] / 1000:.2f}s"
    )
    cache_probe = timing["cache_probe"]
    if cache_probe["eligible_strict_pairs"]:
        e2e_speedup = cache_probe["median_e2e_speedup_percent"]
        first_llm_speedup = cache_probe["median_first_llm_speedup_percent"]
        first_prompt_speedup = cache_probe["median_first_prompt_eval_speedup_percent"]
        print(
            "REPEAT PROBE "
            f"pairs={cache_probe['eligible_strict_pairs']} "
            f"e2e-speedup={f'{e2e_speedup:+.1f}%' if e2e_speedup is not None else 'n/a'} "
            f"first-llm={f'{first_llm_speedup:+.1f}%' if first_llm_speedup is not None else 'n/a'} "
            f"first-prompt-eval={f'{first_prompt_speedup:+.1f}%' if first_prompt_speedup is not None else 'n/a'}"
        )
    comparison = run.summary.get("baseline_comparison")
    if comparison:
        delta = int(comparison["delta"])
        print(f"BASELINE   delta={delta:+d} fixed={len(comparison['fixed'])} regressed={len(comparison['regressed'])}")
        performance = comparison["performance"]
        paired = performance["e2e"]
        if paired["matched_pairs"]:
            paired_speedup = paired["median_paired_speedup_percent"]
            print(
                "PERFORMANCE "
                f"strict-pairs={paired['matched_pairs']} "
                f"median-delta={paired['median_paired_delta_ms']:+.1f}ms "
                f"speedup={f'{paired_speedup:+.1f}%' if paired_speedup is not None else 'n/a'}"
            )
        if performance["warning"]:
            print(f"WARNING    {performance['warning']}")
    print(f"RESULTS    {run.output_dir}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(parser, args)
    try:
        cases = _select_cases(config)
    except ValueError as exc:
        parser.error(str(exc))
    if args.list_cases:
        for case in cases:
            print(f"{case.id}\t{case.category}\t{case.prompt}")
        print(f"\n{len(cases)} selected case(s); suite hash {_suite_hash(cases)}")
        return 0

    try:
        run = asyncio.run(run_benchmark(config))
    except KeyboardInterrupt:
        print("Benchmark interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Benchmark infrastructure failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    _print_summary(run)
    if config.fail_under is not None and run.strict_percent < config.fail_under:
        print(
            f"Strict score {run.strict_percent:.3f}% is below --fail-under {config.fail_under:.3f}%.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
