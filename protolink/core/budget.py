"""Runtime budget policy and enforcement primitives.

This module turns :class:`~protolink.core.run_context.RunBudget` from a typed metadata carrier into an enforceable
runtime contract. The default policy is small and deterministic: it allows work under budget, emits warning decisions
near configured limits, and denies work that would exceed hard limits.

Applications can subclass ``BudgetPolicy`` or provide their own policy object with the same ``evaluate()`` method when
they want compaction, truncation, approval, or custom callback behavior instead of the default allow/warn/deny semantics
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from protolink.core.run_context import RunBudget, RunContext
from protolink.utils import utc_now

BudgetDecisionEffect = Literal["allow", "warn", "deny", "compact", "truncate", "require_approval"]
"""Supported budget decision effects.

The default policy emits only ``"allow"``, ``"warn"``, and ``"deny"``. Additional effects are reserved for application
policies that want to handle context pressure through compaction, truncation, approval, or another callback before a
model call proceeds.
"""


@dataclass(frozen=True)
class BudgetUsage:
    """Observed resource usage for one run.

    Attributes:
        steps: Current logical inference/runtime step.
        llm_calls: Number of LLM calls started by this enforcer.
        tool_calls: Number of tool calls started by this enforcer.
        input_tokens: Aggregate estimated input tokens accepted by this enforcer.
        output_tokens: Aggregate output tokens observed after LLM calls.
        runtime_seconds: Wall-clock runtime measured by the enforcer.
        metadata: Extra application-owned usage counters.
    """

    steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    runtime_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize usage into a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BudgetUsage:
        """Create usage from serialized data."""
        if not data:
            return cls()
        return cls(
            steps=_coerce_int(data.get("steps")) or 0,
            llm_calls=_coerce_int(data.get("llm_calls")) or 0,
            tool_calls=_coerce_int(data.get("tool_calls")) or 0,
            input_tokens=_coerce_int(data.get("input_tokens")) or 0,
            output_tokens=_coerce_int(data.get("output_tokens")) or 0,
            runtime_seconds=_coerce_float(data.get("runtime_seconds")) or 0.0,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class BudgetDecision:
    """Result of evaluating current or projected usage against a budget.

    Attributes:
        effect: Decision effect. ``"deny"`` is the default hard-stop effect.
        limit_name: Name of the budget field that produced the decision.
        observed: Observed or projected value for the limit.
        limit: Configured hard limit from ``RunBudget``.
        message: Human-readable summary suitable for events and errors.
        usage: Usage snapshot evaluated by the policy.
        metadata: Extra application-owned decision details.
        timestamp: ISO timestamp for the decision.
    """

    effect: BudgetDecisionEffect = "allow"
    limit_name: str | None = None
    observed: int | float | None = None
    limit: int | float | None = None
    message: str | None = None
    usage: BudgetUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: utc_now())

    @property
    def allowed(self) -> bool:
        """Return whether execution may continue under this decision."""
        return self.effect in {"allow", "warn"}

    def to_dict(self) -> dict[str, Any]:
        """Serialize the decision into a JSON-compatible dictionary."""
        return {
            "effect": self.effect,
            "limit_name": self.limit_name,
            "observed": self.observed,
            "limit": self.limit,
            "message": self.message,
            "usage": self.usage.to_dict() if self.usage else None,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def allow(cls, usage: BudgetUsage) -> BudgetDecision:
        """Create an allow decision for ``usage``."""
        return cls(effect="allow", usage=usage, message="Budget allows execution")


class BudgetExceededError(RuntimeError):
    """Raised when a budget policy denies execution."""

    def __init__(self, decision: BudgetDecision) -> None:
        """Initialize the exception from a deny decision."""
        super().__init__(decision.message or "Run budget exceeded")
        self.decision = decision


class BudgetPolicy:
    """Default deterministic policy for ``RunBudget`` enforcement.

    The policy compares a usage snapshot to the configured hard limits. It denies when any observed value exceeds its
    limit and warns when usage is at or above ``warning_ratio`` of a configured limit. Warnings are decisions, not
    failures; ``BudgetEnforcer`` suppresses repeated warning events for the same limit.
    """

    def __init__(self, *, warning_ratio: float = 0.8) -> None:
        """Create a policy.

        Args:
            warning_ratio: Fraction of a configured limit that should produce a
                warning decision. Set to ``0`` to disable warnings.
        """
        if warning_ratio < 0:
            raise ValueError("warning_ratio must be non-negative")
        self.warning_ratio = warning_ratio

    def evaluate(self, budget: RunBudget, usage: BudgetUsage) -> BudgetDecision:
        """Evaluate usage against a budget and return one decision."""
        for limit_name, observed, limit in _iter_limits(budget, usage):
            if limit is not None and observed > limit:
                return BudgetDecision(
                    effect="deny",
                    limit_name=limit_name,
                    observed=observed,
                    limit=limit,
                    message=f"Run budget exceeded: {limit_name} observed {observed} > limit {limit}",
                    usage=usage,
                )

        if self.warning_ratio > 0:
            for limit_name, observed, limit in _iter_limits(budget, usage):
                if limit is not None and limit > 0 and observed >= limit * self.warning_ratio:
                    return BudgetDecision(
                        effect="warn",
                        limit_name=limit_name,
                        observed=observed,
                        limit=limit,
                        message=f"Run budget warning: {limit_name} observed {observed} near limit {limit}",
                        usage=usage,
                    )

        return BudgetDecision.allow(usage)


class BudgetEnforcer:
    """Stateful helper that applies a ``BudgetPolicy`` during a run."""

    def __init__(
        self,
        context_or_budget: RunContext | RunBudget | None = None,
        *,
        policy: BudgetPolicy | None = None,
    ) -> None:
        """Create an enforcer for a run context or budget."""
        if isinstance(context_or_budget, RunContext):
            self.budget = context_or_budget.budget
        elif isinstance(context_or_budget, RunBudget):
            self.budget = context_or_budget
        else:
            self.budget = RunBudget()
        self.policy = policy or BudgetPolicy()
        self.usage = BudgetUsage()
        self._started_at = time.monotonic()
        self._warned_limits: set[str] = set()

    @property
    def has_output_token_limit(self) -> bool:
        """Return whether output-token usage must be checked after LLM calls."""
        return self.budget.max_output_tokens is not None

    def check_step(self, step: int) -> BudgetDecision:
        """Record and evaluate the current runtime step."""
        return self._evaluate_candidate(replace(self.usage, steps=step), commit=True)

    def check_next_step(self) -> BudgetDecision:
        """Increment and evaluate the task-wide runtime step counter.

        ``LLM.infer()`` can be invoked more than once while one task is being processed (for example, when the latest
        message contains multiple infer parts).  A caller-provided enforcer must therefore advance from its current
        usage rather than overwrite the counter with an infer-local step number.
        """
        return self.check_step(self.usage.steps + 1)

    def check_llm_call(self, *, input_tokens: int = 0) -> BudgetDecision:
        """Record and evaluate a model call before it starts."""
        candidate = replace(
            self.usage,
            llm_calls=self.usage.llm_calls + 1,
            input_tokens=self.usage.input_tokens + max(input_tokens, 0),
        )
        return self._evaluate_candidate(candidate, commit=True)

    def check_tool_call(self) -> BudgetDecision:
        """Record and evaluate a tool call before it starts."""
        candidate = replace(self.usage, tool_calls=self.usage.tool_calls + 1)
        return self._evaluate_candidate(candidate, commit=True)

    def record_output_tokens(self, output_tokens: int | None) -> BudgetDecision:
        """Record output tokens observed after a model call."""
        if output_tokens is None:
            return BudgetDecision.allow(self._usage_with_runtime())
        candidate = replace(self.usage, output_tokens=self.usage.output_tokens + max(output_tokens, 0))
        return self._evaluate_candidate(candidate, commit=True)

    def evaluate(self) -> BudgetDecision:
        """Evaluate the current usage without modifying counters."""
        return self._evaluate_candidate(self.usage, commit=False)

    def _evaluate_candidate(self, candidate: BudgetUsage, *, commit: bool) -> BudgetDecision:
        candidate = self._usage_with_runtime(candidate)
        decision = self.policy.evaluate(self.budget, candidate)
        if decision.allowed and commit:
            self.usage = candidate
        if decision.effect == "warn":
            limit_key = decision.limit_name or "budget"
            if limit_key in self._warned_limits:
                return BudgetDecision.allow(candidate)
            self._warned_limits.add(limit_key)
        return decision

    def _usage_with_runtime(self, usage: BudgetUsage | None = None) -> BudgetUsage:
        active_usage = usage or self.usage
        return replace(active_usage, runtime_seconds=round(time.monotonic() - self._started_at, 6))


def _iter_limits(
    budget: RunBudget,
    usage: BudgetUsage,
) -> tuple[tuple[str, int | float, int | float | None], ...]:
    return (
        ("max_steps", usage.steps, budget.max_steps),
        ("max_llm_calls", usage.llm_calls, budget.max_llm_calls),
        ("max_tool_calls", usage.tool_calls, budget.max_tool_calls),
        ("max_input_tokens", usage.input_tokens, budget.max_input_tokens),
        ("max_output_tokens", usage.output_tokens, budget.max_output_tokens),
        ("max_runtime_seconds", usage.runtime_seconds, budget.max_runtime_seconds),
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
