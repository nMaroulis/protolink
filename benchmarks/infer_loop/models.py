"""Shared data models and suite constants for the infer-loop benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

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
