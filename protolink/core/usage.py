"""Read-only usage summaries for recorded model calls."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from protolink.llms.metrics import LLMCost, LLMUsage


@dataclass(frozen=True)
class RunUsage:
    """Observed model usage, with estimates and unknown pricing kept explicit.

    ``reported`` contains provider-only calls. ``estimated`` contains calls
    with any estimated token count, including mixed provider/estimate calls.
    Counts are ``None`` when absent or missing from any call in that group.
    ``costs`` groups known pricing by currency and its estimation flag;
    ``unpriced_calls`` counts calls without any price information. These are
    observed totals, not a billing guarantee or proof of remote completeness.
    """

    calls: int
    reported_calls: int
    estimated_calls: int
    unknown_calls: int
    reported: LLMUsage
    estimated: LLMUsage
    costs: tuple[LLMCost, ...]
    unpriced_calls: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize totals without replacing unknown values with zero."""
        return {
            "calls": self.calls,
            "reported_calls": self.reported_calls,
            "estimated_calls": self.estimated_calls,
            "unknown_calls": self.unknown_calls,
            "reported": self.reported.to_dict(),
            "estimated": self.estimated.to_dict(),
            "costs": [cost.to_dict() for cost in self.costs],
            "unpriced_calls": self.unpriced_calls,
        }


def summarize_usage(metrics: Iterable[dict[str, Any]]) -> RunUsage:
    """Aggregate already deduplicated call metrics without guessing values."""
    calls = tuple(metrics)
    reported: list[dict[str, Any]] = []
    estimated: list[dict[str, Any]] = []
    unknown_calls = 0
    unpriced_calls = 0
    costs: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for metric in calls:
        nested = metric.get("metrics")
        value = nested if isinstance(nested, dict) else metric
        usage = value.get("usage")
        if not isinstance(usage, dict) or all(usage.get(name) is None for name in _TOKEN_FIELDS):
            unknown_calls += 1
        elif usage.get("estimated") or "estimate" in str(usage.get("source", "")):
            estimated.append(usage)
        else:
            reported.append(usage)
        cost = value.get("cost")
        if not isinstance(cost, dict) or not cost.get("currency"):
            unpriced_calls += 1
        elif all(cost.get(name) is None for name in _COST_FIELDS):
            unpriced_calls += 1
        else:
            costs[(str(cost["currency"]), bool(cost.get("estimated", True)))].append(cost)
    return RunUsage(
        calls=len(calls),
        reported_calls=len(reported),
        estimated_calls=len(estimated),
        unknown_calls=unknown_calls,
        reported=LLMUsage(**_totals(reported, _TOKEN_FIELDS), source="provider"),
        estimated=LLMUsage(**_totals(estimated, _TOKEN_FIELDS), estimated=True, source="estimate"),
        costs=tuple(
            LLMCost(**_totals(items, _COST_FIELDS), currency=currency, estimated=is_estimated)
            for (currency, is_estimated), items in sorted(costs.items())
        ),
        unpriced_calls=unpriced_calls,
    )


_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
_COST_FIELDS = ("input_cost", "output_cost", "total_cost")


def _totals(items: list[dict[str, Any]], names: tuple[str, ...]) -> dict[str, Any]:
    """Sum a field only when every contributing call knows that field."""
    totals: dict[str, Any] = {}
    for name in names:
        values = [item.get(name) for item in items]
        numbers = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
        if not values or len(numbers) != len(values):
            totals[name] = None
        else:
            totals[name] = sum(numbers)
    return totals
