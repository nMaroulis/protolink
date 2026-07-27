#!/usr/bin/env python3
"""Compare saved AI Liability Tribunal summaries without making new model calls."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

CONDITION_ORDER = {
    "solo": 0,
    "independent": 1,
    "star": 2,
    "mesh": 3,
}
GUILTY_VERDICTS = {"guilty"}
NOT_GUILTY_VERDICTS = {"not_guilty"}


def load_summaries(paths: list[str]) -> list[tuple[Path, dict[str, Any]]]:
    """Resolve summary files from explicit files or result directories."""
    candidates: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            candidates.extend(path.glob("**/summary.json"))
        else:
            candidates.append(path)

    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(set(candidates)):
        if not path.exists():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "run" not in payload or "metrics" not in payload:
            raise ValueError(f"{path} is not a courtroom summary")
        loaded.append((path, payload))
    if not loaded:
        raise ValueError("No summary.json files found")
    return loaded


def build_comparison_markdown(records: list[tuple[Path, dict[str, Any]]]) -> str:
    """Aggregate repeated cells and return a publication-friendly Markdown table."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for _, summary in records:
        run = summary["run"]
        key = (str(run["provider"]), str(run["model"]), str(run["condition"]))
        groups[key].append(summary)

    lines = [
        "# AI Liability Tribunal comparison",
        "",
        "Aggregate of saved runs. `±` is population standard deviation across repetitions; "
        "a single run has zero spread.",
        "",
        "| Provider / model | Topology | n | Guilty verdict rate | Truth match | Final guilt p | Polarization | "
        "Consensus gain | Grounding | Clean first pass | Latency / A2A message |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    grouped_rows = sorted(
        groups.items(),
        key=lambda item: (
            _condition_sort_key(item[0][2]),
            item[0][0],
            item[0][1],
        ),
    )
    for (provider, model, condition), summaries in grouped_rows:
        metrics = [summary["metrics"] for summary in summaries]
        guilty_rate = _verdict_rate(summaries)
        truth_match = _boolean_rate(metrics, "matches_synthetic_truth")
        final_mean = _mean_spread(
            metrics,
            "final_mean_guilt_probability",
            fallback_key="final_mean_probability",
        )
        polarization = _mean_spread(metrics, "final_polarization")
        consensus = _mean_spread(metrics, "deliberation_consensus_gain")
        grounding = _rate(metrics, "evidence_grounding_rate")
        clean_first_pass = _rate(
            metrics,
            "protocol_clean_first_attempt_rate",
            fallback_key="schema_valid_first_attempt_rate",
        )
        latency_per_message = _latency_per_a2a_message(metrics)
        provider_cell = _markdown_cell(provider)
        model_cell = _markdown_cell(model)
        condition_cell = _markdown_cell(condition)
        lines.append(
            f"| {provider_cell} / `{model_cell}` | {condition_cell} | {len(summaries)} | {guilty_rate} | "
            f"{truth_match} | {final_mean} | {polarization} | {consensus} | {grounding} | "
            f"{clean_first_pass} | {latency_per_message} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- A one-run cell is a demonstration, not a model ranking.",
            "- The synthetic truth supports a controlled truth-match metric; it does not make the fictional tribunal "
            "realistic.",
            "- Solo versus multi-agent conditions change the number of decision-makers as well as communication, so "
            "that contrast is not a topology-only treatment.",
            "- Immediate register shifts are temporal association proxies. Causal claims require paired message "
            "ablations and repeated runs.",
            "- Consensus is not accuracy. Polarization and consensus gain are N/A for a single solo decision-maker.",
            "- Provider comparisons should freeze prompts and transcript, rotate persona assignments, and include "
            "failures.",
            "",
            "## Source files",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path, _ in records)
    return "\n".join(lines) + "\n"


def _mean_spread(
    metrics: list[dict[str, Any]],
    key: str,
    *,
    fallback_key: str | None = None,
) -> str:
    values = _numeric_values(metrics, key, fallback_key=fallback_key)
    if not values:
        return "N/A"
    return f"{statistics.fmean(values):.2f} ± {statistics.pstdev(values):.2f}"


def _verdict_rate(summaries: list[dict[str, Any]]) -> str:
    verdicts = [_normalize_verdict(summary.get("verdict", {}).get("verdict")) for summary in summaries]
    recognized = [verdict for verdict in verdicts if verdict in GUILTY_VERDICTS | NOT_GUILTY_VERDICTS]
    if not recognized:
        return "N/A"
    guilty = sum(verdict in GUILTY_VERDICTS for verdict in recognized)
    return f"{guilty / len(recognized):.0%}"


def _boolean_rate(metrics: list[dict[str, Any]], key: str) -> str:
    values = [metric[key] for metric in metrics if metric.get(key) is not None]
    if not values:
        return "N/A"
    return f"{statistics.fmean(1.0 if bool(value) else 0.0 for value in values):.0%}"


def _rate(
    metrics: list[dict[str, Any]],
    key: str,
    *,
    fallback_key: str | None = None,
) -> str:
    values = _numeric_values(metrics, key, fallback_key=fallback_key)
    if not values:
        return "N/A"
    return f"{statistics.fmean(values):.0%}"


def _latency_per_a2a_message(metrics: list[dict[str, Any]]) -> str:
    values: list[float] = []
    for metric in metrics:
        messages = _numeric_value(metric.get("a2a_messages"))
        latency = _numeric_value(metric.get("latency_ms_total"))
        if messages is None or latency is None or messages <= 0:
            continue
        values.append(latency / messages)
    if not values:
        return "N/A"
    return f"{statistics.fmean(values):.1f} ms"


def _numeric_values(
    metrics: list[dict[str, Any]],
    key: str,
    *,
    fallback_key: str | None = None,
) -> list[float]:
    values: list[float] = []
    for metric in metrics:
        raw_value = metric.get(key)
        if raw_value is None and fallback_key is not None:
            raw_value = metric.get(fallback_key)
        value = _numeric_value(raw_value)
        if value is not None:
            values.append(value)
    return values


def _numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _normalize_verdict(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _condition_sort_key(condition: str) -> tuple[int, str]:
    normalized = str(condition).strip().lower()
    return CONDITION_ORDER.get(normalized, len(CONDITION_ORDER)), normalized


def _markdown_cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("\n", " ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare existing AI Liability Tribunal summary files.")
    parser.add_argument("summaries", nargs="+", help="summary.json files or directories containing them.")
    parser.add_argument("--output", help="Write Markdown here instead of stdout.")
    args = parser.parse_args()
    markdown = build_comparison_markdown(load_summaries(args.summaries))
    if args.output:
        destination = Path(args.output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(markdown, encoding="utf-8")
        print(destination)
    else:
        print(markdown, end="")


if __name__ == "__main__":
    main()
