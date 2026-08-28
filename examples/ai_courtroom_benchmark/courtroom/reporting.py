"""Dependency-free reports for the paired AI courtroom advocate benchmark.

The renderer intentionally writes one self-contained HTML file.  It does not
load fonts, scripts, styles, or data over the network, so the report remains
usable when opened directly from disk.
"""

from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

COLORS = (
    "#63d5c5",
    "#f4b85f",
    "#df7ca4",
    "#9f91ff",
    "#8bd078",
    "#73abf4",
    "#ed8d75",
    "#bdc8d8",
)


def write_benchmark_artifacts(benchmark: dict[str, Any], output_root: Path) -> None:
    """Write the paired benchmark summary, transcript, and standalone report."""
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "summary.json").write_text(
        json.dumps(_summary_payload(benchmark), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (destination / "transcript.md").write_text(
        _render_transcript(benchmark),
        encoding="utf-8",
    )
    (destination / "report.html").write_text(
        _render_report(benchmark),
        encoding="utf-8",
    )


def _summary_payload(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for trial in _trials(benchmark):
        result = _mapping(trial.get("result"))
        trials.append(
            {
                "trial_id": _text(trial.get("trial_id")),
                "replicate": trial.get("replicate"),
                "status": result.get("status", "completed"),
                "error": dict(_mapping(result.get("error"))),
                "assignment": dict(_mapping(trial.get("assignment"))),
                "case_hash": result.get("case_hash"),
                "controls_hash": result.get("controls_hash"),
                "baseline_hash": result.get("baseline_hash"),
                "treatment_hash": result.get("treatment_hash"),
                "verdict": dict(_mapping(result.get("verdict"))),
                "metrics": dict(_mapping(result.get("metrics"))),
                "final_jurors": {
                    juror_id: {
                        "label": state.get("label"),
                        "support_probability": _final_support(state),
                        "vote": state.get("vote"),
                    }
                    for juror_id, state in _jurors(result).items()
                },
            }
        )
    return {
        "schema_version": benchmark.get("schema_version"),
        "benchmark": dict(_mapping(benchmark.get("benchmark"))),
        "trials": trials,
        "fairness": dict(_mapping(benchmark.get("fairness"))),
        "candidate_metrics": dict(_mapping(benchmark.get("candidate_metrics"))),
        "caveats": list(benchmark.get("caveats", [])) if isinstance(benchmark.get("caveats"), list) else [],
    }


def _render_transcript(benchmark: Mapping[str, Any]) -> str:
    meta = _mapping(benchmark.get("benchmark"))
    case = _case(benchmark)
    candidates = _candidates(benchmark)
    paired = _benchmark_mode(benchmark) == "paired"
    lines = [
        f"# {_md(_report_headline(benchmark))}",
        "",
        f"- Benchmark: `{_md_code(meta.get('id', 'unavailable'))}`",
        f"- Case: **{_md(case.get('title', case.get('id', 'Courtroom case')))}**",
        f"- Case hash: `{_md_code(meta.get('case_hash', 'unavailable'))}`",
        f"- Controls hash: `{_md_code(meta.get('controls_hash', 'unavailable'))}`",
        f"- Started: `{_md_code(meta.get('started_at', 'unavailable'))}`",
        f"- Finished: `{_md_code(meta.get('finished_at', 'unavailable'))}`",
        "",
        "> Public arguments, juror registers, votes, and protocol events only. "
        "Observed after-message movement is a temporal association, not a causal estimate.",
        "",
        "## Candidates",
        "",
    ]
    for candidate_id, candidate in candidates.items():
        lines.append(
            f"- **{_md(_candidate_label(candidate_id, candidates))}** "
            f"(`{_md_code(candidate_id)}`): `{_md_code(_candidate_backend(candidate))}`"
        )

    assignment_heading = "Role-swap assignments" if paired else "Advocate assignment"
    lines.extend(["", f"## {assignment_heading}", ""])
    side_labels = _side_labels(benchmark)
    for trial in _trials(benchmark):
        lines.append(f"### {_md(_trial_label(trial))}")
        lines.append("")
        assignment = _mapping(trial.get("assignment"))
        for side_id, candidate_id in assignment.items():
            lines.append(
                f"- {_md(side_labels.get(_text(side_id), _humanize(side_id)))}: "
                f"**{_md(_candidate_label(candidate_id, candidates))}**"
            )
        lines.append("")

    candidate_metrics = _mapping(benchmark.get("candidate_metrics"))
    if candidate_metrics:
        lines.extend(["## Candidate metrics", ""])
        for candidate_id, metrics in candidate_metrics.items():
            lines.append(f"### {_md(_candidate_label(candidate_id, candidates))}")
            lines.append("")
            flattened = _flatten_scalars(_mapping(metrics))
            if flattened:
                for key, value in flattened.items():
                    lines.append(f"- {_md(_humanize(key))}: `{_md_code(_format_value(value, key=key))}`")
            else:
                lines.append("_No aggregate candidate metrics were recorded._")
            lines.append("")

    for trial in _trials(benchmark):
        result = _mapping(trial.get("result"))
        verdict = _mapping(result.get("verdict"))
        lines.extend(
            [
                f"## {_md(_trial_label(trial))}",
                "",
                f"- Status: `{_md_code(result.get('status', 'completed'))}`",
                f"- Verdict: **{_md(_verdict_label(verdict, side_labels))}**",
                f"- Tally: `{_md_code(_verdict_tally(verdict, side_labels))}`",
                f"- Case hash: `{_md_code(result.get('case_hash', 'unavailable'))}`",
                f"- Controls hash: `{_md_code(result.get('controls_hash', 'unavailable'))}`",
                f"- Baseline hash: `{_md_code(result.get('baseline_hash', 'unavailable'))}`",
                f"- Treatment hash: `{_md_code(result.get('treatment_hash', 'unavailable'))}`",
                "",
                "### Public arguments and observed responses",
                "",
            ]
        )
        error = _mapping(result.get("error"))
        if error:
            lines.insert(
                len(lines) - 2,
                f"- Failure: `{_md_code(error.get('type', 'Error'))}` {_md(error.get('message', ''))}",
            )
        grouped = _argument_events(result)
        for index, argument in enumerate(_arguments(result), start=1):
            argument_id = _text(argument.get("argument_id")) or f"argument-{index}"
            candidate_id = _text(argument.get("candidate_id"))
            side_id = _text(argument.get("side_id"))
            lines.extend(
                [
                    f"#### {index:02d}. {_md(argument.get('stage_label') or argument.get('stage_id') or 'Argument')} "
                    f"· {_md(argument.get('side_label') or side_labels.get(side_id, _humanize(side_id)))} "
                    f"· {_md(_candidate_label(candidate_id, candidates))}",
                    "",
                    _md_quote(argument.get("statement", "")),
                    "",
                ]
            )
            thesis = _text(argument.get("thesis"))
            if thesis:
                lines.extend([f"**Thesis:** {_md(thesis)}", ""])
            evidence_ids = _strings(argument.get("evidence_ids"))
            invalid_ids = _strings(argument.get("invalid_evidence_ids"))
            unmentioned_ids = _strings(argument.get("unmentioned_evidence_ids"))
            if evidence_ids:
                lines.extend(
                    [f"**Admitted citations:** {', '.join(f'`{_md_code(item)}`' for item in evidence_ids)}", ""]
                )
            if invalid_ids:
                lines.extend(
                    [f"**Unsupported citations:** {', '.join(f'`{_md_code(item)}`' for item in invalid_ids)}", ""]
                )
            if unmentioned_ids:
                lines.extend(
                    [
                        "**Declared but not visible in the statement:** "
                        + ", ".join(f"`{_md_code(item)}`" for item in unmentioned_ids),
                        "",
                    ]
                )
            claims = _strings(argument.get("key_claims"))
            if claims:
                lines.extend(["**Key claims:**", "", *[f"- {_md(claim)}" for claim in claims], ""])
            addressed = _strings(argument.get("addressed_opponent_claims"))
            if addressed:
                lines.extend(["**Addressed opponent claims:**", "", *[f"- {_md(claim)}" for claim in addressed], ""])
            events = grouped.get(argument_id, [])
            if events:
                lines.extend(["**Observed juror updates:**", ""])
                for event in events:
                    before = _event_before(event)
                    after = _event_after(event)
                    delta = _event_delta(event)
                    receiver = _event_receiver(event)
                    label = _juror_label(receiver, result)
                    change = (
                        f"{_format_number(before)} -> {_format_number(after)} ({_format_number(delta, signed=True)})"
                        if before is not None or after is not None
                        else "no register update"
                    )
                    lines.append(f"- **{_md(label)}:** {change}")
                    reply = _public_reply(event)
                    if reply:
                        lines.append(f"  - Public reply: {_md(reply)}")
                lines.append("")

    lines.extend(["## Fairness audit", ""])
    fairness_rows = _fairness_rows(_mapping(benchmark.get("fairness")))
    if fairness_rows:
        for label, status, detail in fairness_rows:
            mark = "PASS" if status is True else "WARN" if status is False else "INFO"
            lines.append(f"- **{mark} · {_md(label)}:** {_md(detail or 'No detail recorded.')}")
    else:
        lines.append("_No fairness audit was recorded._")

    lines.extend(["", "## Interpretation limits", ""])
    caveats = _caveats(benchmark)
    if caveats:
        lines.extend(f"- {_md(caveat)}" for caveat in caveats)
    else:
        lines.append(
            "- Observed after-message register movement is descriptive and does not establish causal persuasion."
        )
    lines.append("")
    return "\n".join(lines)


def _render_report(benchmark: Mapping[str, Any]) -> str:
    meta = _mapping(benchmark.get("benchmark"))
    case = _case(benchmark)
    candidates = _candidates(benchmark)
    trials = _trials(benchmark)
    paired = _benchmark_mode(benchmark) == "paired"
    fairness_rows = _fairness_rows(_mapping(benchmark.get("fairness")))
    fairness_status = _fairness_status(fairness_rows)
    fairness_text = {
        "ok": "Matched controls recorded",
        "warn": "Fairness checks need attention",
        "unknown": "Fairness audit is incomplete",
    }[fairness_status]
    candidate_chips = "".join(
        f'<span style="--candidate:{_candidate_color(candidate_id, candidates)}">'
        f"<i></i>{_h(_candidate_label(candidate_id, candidates))} · {_h(_candidate_backend(candidate))}</span>"
        for candidate_id, candidate in candidates.items()
    )
    trial_cards = "".join(_trial_card(trial, benchmark) for trial in trials)
    trajectories = "".join(_trajectory_panel(trial, benchmark) for trial in trials)
    caveat_items = "".join(f"<li>{_h(item)}</li>" for item in _caveats(benchmark))
    default_caveat = "<li>Observed after-message movement is descriptive and does not establish causation.</li>"
    interactive_json = _safe_script_json(_interactive_payload(benchmark))
    control = _mapping(meta.get("control"))
    headline = _report_headline(benchmark)
    hero_eyebrow = (
        "PROTOLINK · PAIRED ADVOCATE LLM BENCHMARK"
        if paired
        else "PROTOLINK · SINGLE-ASSIGNMENT ADVOCATE LLM BENCHMARK"
    )
    hero_lede = (
        "Two reciprocal trial assignments expose how model-authored advocacy was followed by "
        "juror register movement, citations, and final votes."
        if paired
        else "One controlled assignment exposes how model-authored advocacy was followed by juror register "
        "movement, citations, and final votes. Side advantage is not controlled in single mode."
    )
    audit_eyebrow = "ROLE-SWAP AUDIT" if paired else "SINGLE-RUN CONTROL AUDIT"
    assignment_eyebrow = "RECIPROCAL ASSIGNMENT" if paired else "SINGLE ASSIGNMENT"
    assignment_title = "Role-swap matrix" if paired else "Advocate assignment"
    assignment_copy = (
        "Each candidate should appear once on each side while the case and evaluator panel remain fixed."
        if paired
        else "This run records one candidate binding per side. It does not control for side advantage."
    )
    trajectory_eyebrow = "SAME SCALE, TWO ASSIGNMENTS" if paired else "ONE CONTROLLED ASSIGNMENT"
    metric_eyebrow = "ROLE-BALANCED, DESCRIPTIVE METRICS" if paired else "SINGLE-ASSIGNMENT, DESCRIPTIVE METRICS"
    metric_copy = (
        "Support movement is an observed after-message association. It is not a causal persuasion score."
        if paired
        else "Support movement is descriptive and not role-balanced in single mode. It is not a causal score."
    )
    fairness_eyebrow = "MATCHED-PAIR CONTROLS" if paired else "RECORDED SINGLE-RUN CONTROLS"
    fairness_copy = (
        "A record hash may differ because the tested advocates produced different public arguments."
        if paired
        else "Single mode records controls but cannot audit a reciprocal role swap."
    )

    body = f"""
<main>
  <header class="hero" id="summary">
    <div>
      <div class="eyebrow">{_h(hero_eyebrow)}</div>
      <h1>{_h(headline)}</h1>
      <p class="outcome">{_h(case.get("title", case.get("id", "Modular courtroom case")))}</p>
      <p class="lede">{_h(hero_lede)}</p>
      <div class="candidate-chips">{candidate_chips}</div>
      <div class="hero-actions">
        <a href="#pipeline">Replay the arguments ↓</a>
        <a href="#fairness">Inspect fairness</a>
        <a href="#transcript">Read the public ledger</a>
      </div>
    </div>
    <aside class="audit-badge {fairness_status}">
      <span>{_h(audit_eyebrow)}</span>
      <strong>{_h(fairness_text)}</strong>
      <small>{len(trials)} trial(s) · {len(candidates)} candidate model(s)</small>
      <small>Observed movement is descriptive, not causal.</small>
    </aside>
  </header>

  <section class="hash-strip" aria-label="Benchmark identifiers">
    <div><span>Benchmark</span><code>{_h(meta.get("id", "unavailable"))}</code></div>
    <div><span>Case hash</span><code>{_h(meta.get("case_hash", "unavailable"))}</code></div>
    <div><span>Controls hash</span><code>{_h(meta.get("controls_hash", "unavailable"))}</code></div>
  </section>

  <section class="panel" id="assignments">
    <div class="section-head">
      <div><div class="eyebrow">{_h(assignment_eyebrow)}</div><h2>{_h(assignment_title)}</h2></div>
      <p>{_h(assignment_copy)}</p>
    </div>
    {_assignment_matrix(benchmark)}
  </section>

  <section class="panel" id="candidate-metrics">
    <div class="section-head">
      <div><div class="eyebrow">{_h(metric_eyebrow)}</div><h2>Candidate comparison</h2></div>
      <p>{_h(metric_copy)}</p>
    </div>
    {_candidate_metric_cards(benchmark)}
    {_candidate_metric_table(benchmark)}
  </section>

  <section class="trial-grid" aria-label="Trial summaries">{trial_cards}</section>

  <section class="panel" id="trajectories">
    <div class="section-head">
      <div><div class="eyebrow">{_h(trajectory_eyebrow)}</div><h2>Juror support trajectories</h2></div>
      <p>Public application registers from 0 to 100. Categorical votes remain separate.</p>
    </div>
    <div class="trajectory-grid">{trajectories}</div>
    {_juror_legend(benchmark)}
  </section>

  <section class="panel pipeline-panel" id="pipeline">
    <div class="section-head">
      <div><div class="eyebrow">ARGUMENT -> EVIDENCE -> OBSERVED UPDATE</div>
      <h2>Interactive argument pipeline</h2></div>
      <p>Move through each public argument and inspect immediate juror register updates.</p>
    </div>
    {_pipeline_shell()}
    <script type="application/json" id="benchmark-report-data">{interactive_json}</script>
    <noscript><p class="notice">JavaScript is off. The complete public argument ledger remains below.</p></noscript>
  </section>

  <section class="panel" id="citations">
    <div class="section-head">
      <div><div class="eyebrow">ADMITTED-ID COVERAGE</div><h2>Evidence citation matrix</h2></div>
      <p>Counts show distinct authored arguments citing each exhibit. Citation does not establish support or truth.</p>
    </div>
    {_citation_matrix(benchmark)}
  </section>

  <section class="panel" id="fairness">
    <div class="section-head">
      <div><div class="eyebrow">{_h(fairness_eyebrow)}</div><h2>Fairness audit</h2></div>
      <p>{_h(fairness_copy)}</p>
    </div>
    {_fairness_table(fairness_rows)}
    <div class="control-notes">
      <div><span>Started</span><code>{_h(meta.get("started_at", "unavailable"))}</code></div>
      <div><span>Finished</span><code>{_h(meta.get("finished_at", "unavailable"))}</code></div>
      <div><span>Control summary</span><code>{_h(_compact_json(control) if control else "not recorded")}</code></div>
    </div>
  </section>

  <section class="panel caveat" id="limits">
    <div class="eyebrow">INTERPRETATION BOUNDARY</div><h2>What this benchmark does not prove</h2>
    <ul>{caveat_items or default_caveat}</ul>
    <p><strong>Fictional software experiment only. Not legal analysis or advice.</strong></p>
  </section>

  <section class="panel" id="transcript">
    <div class="section-head">
      <div><div class="eyebrow">PUBLIC FALLBACK LEDGER</div><h2>Complete argument transcript</h2></div>
      <p>All model-authored public arguments and recorded juror updates remain readable without the player.</p>
    </div>
    {_static_argument_ledger(benchmark)}
  </section>
</main>
"""
    title = headline or f"{case.get('title', 'Courtroom')} · advocate benchmark"
    return _page(_text(title), body, script=_PIPELINE_SCRIPT)


def _assignment_matrix(benchmark: Mapping[str, Any]) -> str:
    trials = _trials(benchmark)
    candidates = _candidates(benchmark)
    side_labels = _side_labels(benchmark)
    side_ids = list(side_labels)
    headings = "".join(f"<th>{_h(_trial_label(trial))}</th>" for trial in trials)
    rows: list[str] = []
    for side_id in side_ids:
        cells: list[str] = []
        for trial in trials:
            candidate_id = _text(_mapping(trial.get("assignment")).get(side_id))
            candidate = candidates.get(candidate_id, {})
            cells.append(
                f'<td><span class="candidate-dot" style="--candidate:{_candidate_color(candidate_id, candidates)}">'
                f"<i></i><strong>{_h(_candidate_label(candidate_id, candidates))}</strong>"
                f"<small>{_h(_candidate_backend(candidate))}</small></span></td>"
            )
        rows.append(f"<tr><th>{_h(side_labels[side_id])}</th>{''.join(cells)}</tr>")
    return (
        '<div class="table-wrap"><table class="assignment-table"><thead><tr><th>Advocacy side</th>'
        f"{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _candidate_metric_cards(benchmark: Mapping[str, Any]) -> str:
    candidates = _candidates(benchmark)
    candidate_metrics = _mapping(benchmark.get("candidate_metrics"))
    cards: list[str] = []
    for candidate_id, candidate in candidates.items():
        metrics = _flatten_scalars(_mapping(candidate_metrics.get(candidate_id)))
        key = _prominent_metric_key(metrics)
        value = _format_value(metrics.get(key), key=key) if key else "N/A"
        note = _humanize(key) if key else "No aggregate metric recorded"
        cards.append(
            f'<article class="candidate-card" style="--candidate:{_candidate_color(candidate_id, candidates)}">'
            f'<div class="eyebrow">{_h(_candidate_backend(candidate))}</div>'
            f"<h3>{_h(_candidate_label(candidate_id, candidates))}</h3>"
            f'<div class="candidate-score"><strong>{_h(value)}</strong><span>{_h(note)}</span></div>'
            "</article>"
        )
    return f'<div class="candidate-card-grid">{"".join(cards)}</div>'


def _candidate_metric_table(benchmark: Mapping[str, Any]) -> str:
    candidates = _candidates(benchmark)
    raw_metrics = _mapping(benchmark.get("candidate_metrics"))
    flattened = {candidate_id: _flatten_scalars(_mapping(raw_metrics.get(candidate_id))) for candidate_id in candidates}
    keys = sorted(
        {key for metrics in flattened.values() for key in metrics},
        key=_metric_sort_key,
    )
    if not keys:
        return '<p class="empty">No aggregate candidate metrics were recorded.</p>'
    rows = "".join(
        "<tr>"
        f"<th>{_h(_humanize(key))}</th>"
        + "".join(
            f"<td>{_h(_format_value(flattened[candidate_id].get(key), key=key))}</td>" for candidate_id in candidates
        )
        + "</tr>"
        for key in keys
    )
    headings = "".join(f"<th>{_h(_candidate_label(candidate_id, candidates))}</th>" for candidate_id in candidates)
    return (
        '<div class="table-wrap metrics-table"><table><thead><tr><th>Metric</th>'
        f"{headings}</tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _trial_card(trial: Mapping[str, Any], benchmark: Mapping[str, Any]) -> str:
    result = _mapping(trial.get("result"))
    verdict = _mapping(result.get("verdict"))
    metrics = _mapping(result.get("metrics"))
    side_labels = _side_labels(benchmark)
    baseline = _first_number(
        metrics,
        "baseline_mean_support_probability",
        "initial_mean_support_probability",
        "mean_support_before",
    )
    final = _first_number(
        metrics,
        "final_mean_support_probability",
        "mean_support_probability",
        "mean_support_after",
    )
    arguments = _arguments(result)
    citations = sum(len(_strings(argument.get("evidence_ids"))) for argument in arguments)
    invalid = sum(len(_strings(argument.get("invalid_evidence_ids"))) for argument in arguments)
    unmentioned = sum(len(_strings(argument.get("unmentioned_evidence_ids"))) for argument in arguments)
    status = _text(result.get("status") or "completed")
    error = _mapping(result.get("error"))
    failure_note = (
        f'<p class="notice"><strong>Partial failed trial:</strong> '
        f"{_h(error.get('type', 'Error'))}: {_h(error.get('message', 'No detail recorded.'))}</p>"
        if status == "failed"
        else ""
    )
    support_shift = (
        _format_number(final - baseline, signed=True) if final is not None and baseline is not None else "N/A"
    )
    return f"""
<article class="trial-card">
  <div class="trial-card-head"><div><div class="eyebrow">{_h(_trial_label(trial))}</div>
  <h2>{_h(_verdict_label(verdict, side_labels))}</h2></div>
  <strong>{_h(_verdict_tally(verdict, side_labels))}</strong></div>
  {failure_note}
  <div class="mini-metrics">
    {_mini_metric("Mean support", f"{_format_number(baseline)} -> {_format_number(final)}")}
    {_mini_metric("Observed shift", support_shift)}
    {_mini_metric("Arguments", str(len(arguments)))}
    {_mini_metric("Citations", f"{citations} visible · {invalid} unsupported · {unmentioned} declared only")}
  </div>
  <div class="assignment-list">{_trial_assignment_rows(trial, benchmark)}</div>
</article>
"""


def _trial_assignment_rows(trial: Mapping[str, Any], benchmark: Mapping[str, Any]) -> str:
    candidates = _candidates(benchmark)
    side_labels = _side_labels(benchmark)
    rows: list[str] = []
    for side_id, candidate_id in _mapping(trial.get("assignment")).items():
        candidate_key = _text(candidate_id)
        rows.append(
            f"<div><span>{_h(side_labels.get(_text(side_id), _humanize(side_id)))}</span>"
            f'<strong style="--candidate:{_candidate_color(candidate_key, candidates)}">'
            f"<i></i>{_h(_candidate_label(candidate_key, candidates))}</strong></div>"
        )
    return "".join(rows)


def _trajectory_panel(trial: Mapping[str, Any], benchmark: Mapping[str, Any]) -> str:
    result = _mapping(trial.get("result"))
    verdict_label = _verdict_label(_mapping(result.get("verdict")), _side_labels(benchmark))
    return (
        '<article class="trajectory-panel">'
        f'<div class="trajectory-title"><strong>{_h(_trial_label(trial))}</strong>'
        f"<span>{_h(verdict_label)}</span></div>"
        f"{_trajectory_svg(result, benchmark)}"
        "</article>"
    )


def _trajectory_svg(result: Mapping[str, Any], benchmark: Mapping[str, Any]) -> str:
    jurors = _jurors(result)
    global_ids = _all_juror_ids(benchmark)
    histories: list[tuple[str, Mapping[str, Any], list[Mapping[str, Any]]]] = []
    maximum = 1
    for juror_id, state in jurors.items():
        history = [point for point in _list_of_mappings(state.get("history")) if _support_value(point) is not None]
        if not history and _final_support(state) is not None:
            history = [{"support_probability": _final_support(state), "vote": state.get("vote")}]
        maximum = max(maximum, len(history) - 1)
        histories.append((juror_id, state, history))

    width, height = 850, 345
    left, right, top, bottom = 50, 115, 24, 48

    def x(index: int) -> float:
        return left + index / maximum * (width - left - right)

    def y(probability: float) -> float:
        return top + (100.0 - probability) / 100.0 * (height - top - bottom)

    grid = "".join(
        f'<line x1="{left}" x2="{width - right}" y1="{y(value):.1f}" y2="{y(value):.1f}" '
        f'class="gridline{" neutral" if value == 50 else ""}"/>'
        f'<text x="{left - 8}" y="{y(value) + 4:.1f}" text-anchor="end">{value}</text>'
        for value in (0, 25, 50, 75, 100)
    )
    tick_count = min(maximum, 12)
    ticks = "".join(
        f'<line x1="{x(round(index * maximum / max(tick_count, 1))):.1f}" '
        f'x2="{x(round(index * maximum / max(tick_count, 1))):.1f}" y1="{top}" y2="{height - bottom}" '
        'class="event-grid"/>'
        for index in range(1, tick_count + 1)
    )
    paths: list[str] = []
    for juror_id, state, history in histories:
        if not history:
            continue
        color = _juror_color(juror_id, global_ids)
        points = [(x(index), y(_support_value(point) or 0.0)) for index, point in enumerate(history)]
        dots = "".join(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3"><title>'
            f"{_h(_juror_label(juror_id, result))}: {_format_number(_support_value(point))} · "
            f"{_h(_humanize(point.get('vote', 'vote unavailable')))}</title></circle>"
            for (px, py), point in zip(points, history, strict=True)
        )
        last_x, last_y = points[-1]
        paths.append(
            f'<g style="--series:{color}"><polyline points="'
            + " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            + f'"/>{dots}<text class="end-label" x="{last_x + 7:.1f}" y="{last_y + 4:.1f}">'
            f"{_h(_short_name(state.get('label') or juror_id))}</text></g>"
        )
    if not paths:
        return '<p class="empty">No juror trajectory data were recorded.</p>'
    return (
        f'<div class="chart-wrap"><svg class="trajectory" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Juror support-probability trajectories"><title>Juror support trajectories</title>'
        f"{grid}{ticks}{''.join(paths)}"
        f'<text x="{left}" y="{height - 12}" class="axis-label">baseline</text>'
        f'<text x="{width - right}" y="{height - 12}" text-anchor="end" class="axis-label">final public register</text>'
        "</svg></div>"
    )


def _juror_legend(benchmark: Mapping[str, Any]) -> str:
    ids = _all_juror_ids(benchmark)
    reference = _mapping(_trials(benchmark)[0].get("result")) if _trials(benchmark) else {}
    return (
        '<div class="legend">'
        + "".join(
            f'<span style="--series:{_juror_color(juror_id, ids)}"><i></i>'
            f"{_h(_juror_label(juror_id, reference))}</span>"
            for juror_id in ids
        )
        + "</div>"
    )


def _pipeline_shell() -> str:
    return """
<div class="pipeline-toolbar">
  <label>Trial <select id="pipeline-trial" aria-label="Choose trial"></select></label>
  <button type="button" id="pipeline-prev" aria-label="Previous argument">← Prev</button>
  <button type="button" id="pipeline-play" aria-label="Play argument pipeline">Play</button>
  <button type="button" id="pipeline-next" aria-label="Next argument">Next →</button>
  <label class="pipeline-scrubber"><span>Argument</span>
    <input id="pipeline-step" type="range" min="0" value="0" aria-label="Argument number"></label>
  <span id="pipeline-count">0 / 0</span>
</div>
<div id="pipeline-status" class="sr-only" aria-live="polite"></div>
<div class="pipeline-route" aria-hidden="true">
  <span>ADVOCATE MODEL</span><i>→</i><span>PUBLIC ARGUMENT + EVIDENCE</span><i>→</i><span>JUROR PANEL</span>
</div>
<div class="pipeline-layout">
  <article class="argument-card">
    <div class="argument-meta"><span id="pipeline-stage">Stage</span><span id="pipeline-side">Side</span></div>
    <h3 id="pipeline-candidate">Candidate model</h3>
    <p id="pipeline-backend" class="muted"></p>
    <div class="message-scroll" tabindex="0" aria-label="Current public argument">
      <div class="message-block"><small>PUBLIC STATEMENT</small><p id="pipeline-statement"></p></div>
      <div class="message-block" id="pipeline-thesis-wrap"><small>THESIS</small><p id="pipeline-thesis"></p></div>
      <div class="claim-block" id="pipeline-claims-wrap"><small>KEY CLAIMS</small><ul id="pipeline-claims"></ul></div>
      <div class="claim-block" id="pipeline-addressed-wrap"><small>ADDRESSED OPPONENT CLAIMS</small>
        <ul id="pipeline-addressed"></ul></div>
    </div>
    <div class="evidence-chips" id="pipeline-evidence"></div>
  </article>
  <section class="recipient-panel" aria-label="Observed juror updates">
    <div class="recipient-head"><div><span>OBSERVED AFTER-MESSAGE UPDATES</span>
      <h3 id="pipeline-shift">No register updates</h3></div></div>
    <div id="pipeline-recipients" class="recipient-list"></div>
  </section>
</div>
"""


def _interactive_payload(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    candidates = _candidates(benchmark)
    payload_candidates = {
        candidate_id: {
            "id": candidate_id,
            "label": _candidate_label(candidate_id, candidates),
            "backend": _candidate_backend(candidate),
            "color": _candidate_color(candidate_id, candidates),
        }
        for candidate_id, candidate in candidates.items()
    }
    payload_trials: list[dict[str, Any]] = []
    for trial in _trials(benchmark):
        result = _mapping(trial.get("result"))
        grouped = _argument_events(result)
        arguments: list[dict[str, Any]] = []
        for index, argument in enumerate(_arguments(result), start=1):
            argument_id = _text(argument.get("argument_id")) or f"argument-{index}"
            recipients: list[dict[str, Any]] = []
            for event in grouped.get(argument_id, []):
                receiver = _event_receiver(event)
                before = _event_before(event)
                after = _event_after(event)
                delta = _event_delta(event)
                if delta is None and before is not None and after is not None:
                    delta = after - before
                response = _mapping(event.get("response"))
                recipients.append(
                    {
                        "juror_id": receiver,
                        "label": _juror_label(receiver, result),
                        "before": before,
                        "after": after,
                        "delta": delta,
                        "vote_before": _text(event.get("vote_before") or response.get("vote_before")),
                        "vote_after": _text(event.get("vote_after") or response.get("vote")),
                        "reply": _public_reply(event),
                    }
                )
            arguments.append(
                {
                    "argument_id": argument_id,
                    "stage_id": _text(argument.get("stage_id")),
                    "stage_label": _text(argument.get("stage_label") or argument.get("stage_id") or "Argument"),
                    "side_id": _text(argument.get("side_id")),
                    "side_label": _text(argument.get("side_label") or _humanize(argument.get("side_id"))),
                    "candidate_id": _text(argument.get("candidate_id")),
                    "statement": _text(argument.get("statement")),
                    "thesis": _text(argument.get("thesis")),
                    "evidence_ids": _strings(argument.get("evidence_ids")),
                    "declared_evidence_ids": _strings(argument.get("declared_evidence_ids")),
                    "unmentioned_evidence_ids": _strings(argument.get("unmentioned_evidence_ids")),
                    "invalid_evidence_ids": _strings(argument.get("invalid_evidence_ids")),
                    "key_claims": _strings(argument.get("key_claims")),
                    "addressed_opponent_claims": _strings(argument.get("addressed_opponent_claims")),
                    "recipients": recipients,
                }
            )
        payload_trials.append(
            {
                "trial_id": _text(trial.get("trial_id")),
                "label": _trial_label(trial),
                "replicate": trial.get("replicate"),
                "arguments": arguments,
            }
        )
    return {"candidates": payload_candidates, "trials": payload_trials}


def _citation_matrix(benchmark: Mapping[str, Any]) -> str:
    case = _case(benchmark)
    evidence = _evidence_index(case)
    candidates = _candidates(benchmark)
    side_labels = _side_labels(benchmark)
    columns: list[tuple[str, str]] = [(candidate_id, side_id) for candidate_id in candidates for side_id in side_labels]
    counts: dict[tuple[str, str, str], int] = {}
    invalid_counts: dict[tuple[str, str], int] = {}
    unmentioned_counts: dict[tuple[str, str], int] = {}
    for trial in _trials(benchmark):
        for argument in _arguments(_mapping(trial.get("result"))):
            candidate_id = _text(argument.get("candidate_id"))
            side_id = _text(argument.get("side_id"))
            for evidence_id in set(_strings(argument.get("evidence_ids"))):
                counts[(candidate_id, side_id, evidence_id)] = counts.get((candidate_id, side_id, evidence_id), 0) + 1
            invalid_counts[(candidate_id, side_id)] = invalid_counts.get((candidate_id, side_id), 0) + len(
                _strings(argument.get("invalid_evidence_ids"))
            )
            unmentioned_counts[(candidate_id, side_id)] = unmentioned_counts.get(
                (candidate_id, side_id),
                0,
            ) + len(_strings(argument.get("unmentioned_evidence_ids")))
    headings = "".join(
        f'<th><span class="matrix-candidate" style="--candidate:{_candidate_color(candidate_id, candidates)}">'
        f"<i></i>{_h(_candidate_label(candidate_id, candidates))}</span>"
        f"<small>{_h(side_labels[side_id])}</small></th>"
        for candidate_id, side_id in columns
    )
    evidence_ids = list(evidence)
    for trial in _trials(benchmark):
        for argument in _arguments(_mapping(trial.get("result"))):
            for evidence_id in _strings(argument.get("evidence_ids")):
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
    rows: list[str] = []
    for evidence_id in evidence_ids:
        evidence_text = evidence.get(evidence_id, "Citation text unavailable")
        cells = "".join(
            f"<td><strong>{counts.get((candidate_id, side_id, evidence_id), 0)}</strong></td>"
            for candidate_id, side_id in columns
        )
        rows.append(f"<tr><th><code>{_h(evidence_id)}</code><small>{_h(evidence_text)}</small></th>{cells}</tr>")
    invalid_row = "".join(
        f'<td class="invalid-count">{invalid_counts.get((candidate_id, side_id), 0)}</td>'
        for candidate_id, side_id in columns
    )
    rows.append(f"<tr><th>Unsupported citation occurrences</th>{invalid_row}</tr>")
    unmentioned_row = "".join(
        f'<td class="invalid-count">{unmentioned_counts.get((candidate_id, side_id), 0)}</td>'
        for candidate_id, side_id in columns
    )
    rows.append(f"<tr><th>Declared IDs not visible in the public statement</th>{unmentioned_row}</tr>")
    if not rows:
        return '<p class="empty">No evidence index or citations were recorded.</p>'
    return (
        '<div class="table-wrap citation-table"><table><thead><tr><th>Exhibit</th>'
        f"{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _fairness_table(rows: list[tuple[str, bool | None, str]]) -> str:
    if not rows:
        return '<p class="empty">No fairness checks were recorded.</p>'
    rendered = "".join(
        f'<tr><td><span class="check-icon {"ok" if status is True else "warn" if status is False else "unknown"}">'
        f"{'PASS' if status is True else 'WARN' if status is False else 'INFO'}</span></td>"
        f"<th>{_h(label)}</th><td>{_h(detail or 'No detail recorded.')}</td></tr>"
        for label, status, detail in rows
    )
    return f'<div class="table-wrap fairness-table"><table><tbody>{rendered}</tbody></table></div>'


def _static_argument_ledger(benchmark: Mapping[str, Any]) -> str:
    candidates = _candidates(benchmark)
    chunks: list[str] = []
    for trial in _trials(benchmark):
        result = _mapping(trial.get("result"))
        grouped = _argument_events(result)
        items: list[str] = []
        for index, argument in enumerate(_arguments(result), start=1):
            argument_id = _text(argument.get("argument_id")) or f"argument-{index}"
            evidence = " ".join(
                f'<code class="evidence-pill">{_h(evidence_id)}</code>'
                for evidence_id in _strings(argument.get("evidence_ids"))
            )
            invalid = " ".join(
                f'<code class="evidence-pill invalid">{_h(evidence_id)}</code>'
                for evidence_id in _strings(argument.get("invalid_evidence_ids"))
            )
            unmentioned = " ".join(
                f'<code class="evidence-pill invalid">{_h(evidence_id)} (declared only)</code>'
                for evidence_id in _strings(argument.get("unmentioned_evidence_ids"))
            )
            updates: list[str] = []
            for event in grouped.get(argument_id, []):
                receiver = _event_receiver(event)
                before = _event_before(event)
                after = _event_after(event)
                delta = _event_delta(event)
                reply = _public_reply(event)
                updates.append(
                    '<div class="ledger-update">'
                    f"<strong>{_h(_juror_label(receiver, result))}</strong>"
                    f"<span>{_format_number(before)} -> {_format_number(after)} "
                    f"({_format_number(delta, signed=True)})</span>"
                    + (f"<blockquote>{_h(reply)}</blockquote>" if reply else "")
                    + "</div>"
                )
            candidate_id = _text(argument.get("candidate_id"))
            items.append(
                f'<details class="ledger-item"><summary><span>{index:02d}</span>'
                f"<b>{_h(argument.get('stage_label') or argument.get('stage_id') or 'Argument')}</b>"
                f"<em>{_h(argument.get('side_label') or _humanize(argument.get('side_id')))}</em>"
                f"<i>{_h(_candidate_label(candidate_id, candidates))}</i></summary>"
                f'<div class="ledger-content"><p>{_h(argument.get("statement", ""))}</p>'
                + (
                    f'<p class="thesis"><strong>Thesis:</strong> {_h(argument.get("thesis"))}</p>'
                    if argument.get("thesis")
                    else ""
                )
                + f'<div class="ledger-evidence">{evidence}{invalid}{unmentioned}</div>'
                + (
                    f'<div class="ledger-updates">{"".join(updates)}</div>'
                    if updates
                    else '<p class="empty">No juror update events linked to this argument.</p>'
                )
                + "</div></details>"
            )
        items_html = "".join(items) or '<p class="empty">No public arguments were recorded.</p>'
        chunks.append(f'<section class="ledger-trial"><h3>{_h(_trial_label(trial))}</h3>{items_html}</section>')
    return "".join(chunks) or '<p class="empty">No trials were recorded.</p>'


def _argument_events(result: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in _events(result):
        if _text(event.get("kind")) != "juror_update":
            continue
        argument_id = _text(
            event.get("reply_to_argument_id")
            or event.get("source_argument_id")
            or event.get("argument_id")
            or _mapping(event.get("reply_metadata")).get("argument_id")
        )
        if argument_id:
            grouped.setdefault(argument_id, []).append(event)
    return grouped


def _fairness_rows(fairness: Mapping[str, Any]) -> list[tuple[str, bool | None, str]]:
    root = _mapping(fairness.get("checks")) or fairness
    rows: list[tuple[str, bool | None, str]] = []
    skipped = {"status", "all_passed", "passed", "ok", "summary", "checks"}
    for key, value in root.items():
        if key in skipped:
            continue
        if isinstance(value, bool):
            rows.append((_humanize(key), value, "Matched." if value else "Values differ or were not controlled."))
            continue
        if isinstance(value, Mapping):
            status_value = value.get("passed", value.get("ok", value.get("match")))
            status = status_value if isinstance(status_value, bool) else None
            details: list[str] = []
            if value.get("detail") or value.get("reason") or value.get("message"):
                details.append(_text(value.get("detail") or value.get("reason") or value.get("message")))
            if "expected" in value:
                details.append(f"expected: {_compact_json(value.get('expected'))}")
            if "actual" in value:
                details.append(f"actual: {_compact_json(value.get('actual'))}")
            if "values" in value:
                details.append(f"values: {_compact_json(value.get('values'))}")
            if not details:
                remaining = {
                    nested_key: nested_value
                    for nested_key, nested_value in value.items()
                    if nested_key not in {"passed", "ok", "match"}
                }
                if remaining:
                    details.append(_compact_json(remaining))
            rows.append((_humanize(key), status, " · ".join(details)))
            continue
        if value is not None:
            rows.append((_humanize(key), None, _compact_json(value)))
    if not rows:
        summary = _text(fairness.get("summary"))
        explicit = fairness.get("all_passed", fairness.get("passed", fairness.get("ok")))
        if summary or isinstance(explicit, bool):
            rows.append(("Overall audit", explicit if isinstance(explicit, bool) else None, summary))
    return rows


def _fairness_status(rows: list[tuple[str, bool | None, str]]) -> str:
    statuses = [status for _, status, _ in rows if status is not None]
    if any(status is False for status in statuses):
        return "warn"
    if statuses and all(status is True for status in statuses):
        return "ok"
    return "unknown"


def _caveats(benchmark: Mapping[str, Any]) -> list[str]:
    raw = benchmark.get("caveats")
    if not isinstance(raw, list):
        return []
    caveats: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            text = _text(item.get("text") or item.get("message") or item.get("description"))
        else:
            text = _text(item)
        if text:
            caveats.append(text)
    return caveats


def _benchmark_mode(benchmark: Mapping[str, Any]) -> str:
    mode = _text(_mapping(benchmark.get("benchmark")).get("mode")).strip().lower()
    if mode in {"paired", "single"}:
        return mode
    return "single" if len(_trials(benchmark)) == 1 else "paired"


def _report_headline(benchmark: Mapping[str, Any]) -> str:
    if _benchmark_mode(benchmark) == "single":
        return "One case. One advocate assignment."
    meta = _mapping(benchmark.get("benchmark"))
    return _text(meta.get("title") or "The same case. The models switch sides.")


def _case(benchmark: Mapping[str, Any]) -> Mapping[str, Any]:
    meta_case = _mapping(_mapping(benchmark.get("benchmark")).get("case"))
    if meta_case:
        return meta_case
    for trial in _trials(benchmark):
        case = _mapping(_mapping(trial.get("result")).get("case"))
        if case:
            return case
    return {}


def _candidates(benchmark: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = _mapping(benchmark.get("benchmark")).get("candidates")
    candidates: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            candidates[_text(key)] = _mapping(value)
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            candidate = _mapping(value)
            candidate_id = _text(candidate.get("candidate_id") or candidate.get("id") or f"candidate_{index + 1}")
            candidates[candidate_id] = candidate
    if candidates:
        return candidates
    for trial in _trials(benchmark):
        result = _mapping(trial.get("result"))
        agent_models = _mapping(_mapping(result.get("run")).get("agent_models"))
        for candidate_id in _mapping(trial.get("assignment")).values():
            key = _text(candidate_id)
            candidates.setdefault(key, _mapping(agent_models.get(key)))
    return candidates


def _trials(benchmark: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _list_of_mappings(benchmark.get("trials"))


def _arguments(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _list_of_mappings(result.get("arguments"))


def _events(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    events = _list_of_mappings(result.get("events"))
    return sorted(events, key=lambda event: (_integer(event.get("sequence")), _text(event.get("event_id"))))


def _jurors(result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(key): _mapping(value) for key, value in _mapping(result.get("jurors")).items()}


def _side_labels(benchmark: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    preferred = ("victim_lawyer", "manufacturer", "claimant", "defense")
    assignment_ids: list[str] = []
    case_sides = _case(benchmark).get("sides")
    if isinstance(case_sides, list):
        for side in _list_of_mappings(case_sides):
            side_id = _text(side.get("id"))
            if side_id:
                assignment_ids.append(side_id)
                labels[side_id] = _text(side.get("label") or side.get("advocate_label")) or _humanize(side_id)
    elif isinstance(case_sides, Mapping):
        for side_id, raw_side in case_sides.items():
            key = _text(side_id)
            side = _mapping(raw_side)
            assignment_ids.append(key)
            labels[key] = _text(side.get("label") or side.get("advocate_label")) or _humanize(key)
    for trial in _trials(benchmark):
        for side_id in _mapping(trial.get("assignment")):
            key = _text(side_id)
            if key not in assignment_ids:
                assignment_ids.append(key)
        for argument in _arguments(_mapping(trial.get("result"))):
            side_id = _text(argument.get("side_id"))
            if side_id:
                labels[side_id] = _text(argument.get("side_label")) or _humanize(side_id)
    ordered = [item for item in preferred if item in assignment_ids]
    ordered.extend(item for item in assignment_ids if item not in ordered)
    return {side_id: labels.get(side_id, _humanize(side_id)) for side_id in ordered}


def _candidate_label(candidate_id: Any, candidates: Mapping[str, Mapping[str, Any]]) -> str:
    key = _text(candidate_id)
    candidate = _mapping(candidates.get(key))
    return _text(
        candidate.get("label") or candidate.get("name") or candidate.get("model") or key or "Unknown candidate"
    )


def _candidate_backend(candidate: Mapping[str, Any]) -> str:
    provider = _text(candidate.get("provider"))
    model = _text(candidate.get("model") or candidate.get("model_id"))
    if provider and model:
        return f"{provider}/{model}"
    return provider or model or "backend unavailable"


def _candidate_color(candidate_id: str, candidates: Mapping[str, Mapping[str, Any]]) -> str:
    ids = list(candidates)
    try:
        index = ids.index(candidate_id)
    except ValueError:
        index = 0
    return COLORS[index % len(COLORS)]


def _all_juror_ids(benchmark: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for trial in _trials(benchmark):
        for juror_id in _jurors(_mapping(trial.get("result"))):
            if juror_id not in ids:
                ids.append(juror_id)
    return ids


def _juror_color(juror_id: str, juror_ids: list[str]) -> str:
    try:
        index = juror_ids.index(juror_id)
    except ValueError:
        index = 0
    return COLORS[(index + 2) % len(COLORS)]


def _juror_label(juror_id: str, result: Mapping[str, Any]) -> str:
    state = _jurors(result).get(juror_id, {})
    participant = _mapping(_mapping(result.get("participants")).get(juror_id))
    return _text(state.get("label") or participant.get("label") or _humanize(juror_id))


def _event_receiver(event: Mapping[str, Any]) -> str:
    return _text(event.get("receiver") or event.get("juror_id") or _mapping(event.get("response")).get("juror_id"))


def _event_before(event: Mapping[str, Any]) -> float | None:
    return _number(event.get("belief_before", event.get("support_before")))


def _event_after(event: Mapping[str, Any]) -> float | None:
    return _number(event.get("belief_after", event.get("support_after")))


def _event_delta(event: Mapping[str, Any]) -> float | None:
    value = _number(event.get("belief_delta", event.get("support_delta")))
    if value is not None:
        return value
    before = _event_before(event)
    after = _event_after(event)
    return after - before if before is not None and after is not None else None


def _public_reply(event: Mapping[str, Any]) -> str:
    response = _mapping(event.get("response"))
    values = (
        event.get("public_reply"),
        response.get("public_reply"),
        response.get("reply"),
        response.get("public_reason"),
    )
    return next((_text(value) for value in values if _text(value)), "")


def _support_value(value: Mapping[str, Any]) -> float | None:
    for key in ("support_probability", "probability", "guilt_probability"):
        numeric = _number(value.get(key))
        if numeric is not None:
            return numeric
    return None


def _final_support(state: Mapping[str, Any]) -> float | None:
    value = _support_value(state)
    if value is not None:
        return value
    history = _list_of_mappings(state.get("history"))
    for point in reversed(history):
        value = _support_value(point)
        if value is not None:
            return value
    return None


def _evidence_index(case: Mapping[str, Any]) -> dict[str, str]:
    raw = case.get("evidence")
    evidence: dict[str, str] = {}
    if isinstance(raw, Mapping):
        for evidence_id, value in raw.items():
            item = _mapping(value)
            text = _text(item.get("text") or item.get("title")) if item else _text(value)
            evidence[_text(evidence_id)] = text
    elif isinstance(raw, list):
        for item in _list_of_mappings(raw):
            evidence_id = _text(item.get("id"))
            if not evidence_id:
                continue
            title = _text(item.get("title"))
            text = _text(item.get("text"))
            evidence[evidence_id] = f"{title}: {text}" if title and text else title or text
    return evidence


def _trial_label(trial: Mapping[str, Any]) -> str:
    replicate = trial.get("replicate")
    trial_id = _text(trial.get("trial_id"))
    if replicate is not None:
        return f"Trial {replicate} · {trial_id}" if trial_id else f"Trial {replicate}"
    return trial_id or "Trial"


def _verdict_label(verdict: Mapping[str, Any], side_labels: Mapping[str, str]) -> str:
    side_id = _text(verdict.get("winning_side_id") or verdict.get("winner") or verdict.get("side_id"))
    if side_id:
        return side_labels.get(side_id, _humanize(side_id))
    value = _text(verdict.get("verdict") or verdict.get("decision") or verdict.get("outcome"))
    return _humanize(value) if value else "Verdict unavailable"


def _verdict_tally(verdict: Mapping[str, Any], side_labels: Mapping[str, str]) -> str:
    counts = _mapping(verdict.get("vote_counts") or verdict.get("votes_by_side") or verdict.get("tally"))
    if counts:
        return " · ".join(
            f"{_integer(count)} {side_labels.get(_text(side_id), _humanize(side_id))}"
            for side_id, count in counts.items()
        )
    guilty = _number(verdict.get("guilty_votes"))
    not_guilty = _number(verdict.get("not_guilty_votes"))
    if guilty is not None or not_guilty is not None:
        return f"{_integer(guilty)} guilty · {_integer(not_guilty)} not guilty"
    positive = _number(verdict.get("positive_votes"))
    negative = _number(verdict.get("negative_votes"))
    if positive is not None or negative is not None:
        side_names = list(side_labels.values())
        positive_label = side_names[0] if side_names else "positive vote"
        negative_label = side_names[1] if len(side_names) > 1 else "negative vote"
        return f"{_integer(positive)} {positive_label} · {_integer(negative)} {negative_label}"
    return "Tally unavailable"


def _prominent_metric_key(metrics: Mapping[str, Any]) -> str:
    preferred = (
        "role_balanced_observed_shift",
        "role_balanced_mean_shift",
        "role_balanced_shift",
        "mean_observed_aligned_shift_points",
        "mean_aligned_shift",
        "mean_aligned_support_shift",
        "aligned_mean_shift",
        "directional_support_shift",
        "side_wins",
    )
    for key in preferred:
        if key in metrics and _number(metrics.get(key)) is not None:
            return key
    return next((key for key, value in metrics.items() if _number(value) is not None), "")


def _metric_sort_key(key: str) -> tuple[int, str]:
    preferred_fragments = (
        "role_balanced",
        "aligned",
        "shift",
        "vote",
        "win",
        "evidence",
        "citation",
        "token",
        "latency",
    )
    for index, fragment in enumerate(preferred_fragments):
        if fragment in key:
            return index, key
    return len(preferred_fragments), key


def _flatten_scalars(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else _text(key)
        if isinstance(item, Mapping):
            flattened.update(_flatten_scalars(item, path))
        elif item is None or isinstance(item, (str, int, float, bool)):
            flattened[path] = item
    return flattened


def _first_number(mapping: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(mapping.get(key))
        if value is not None:
            return value
    return None


def _mini_metric(label: str, value: str) -> str:
    return f"<div><span>{_h(label)}</span><strong>{_h(value)}</strong></div>"


def _format_value(value: Any, *, key: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "yes" if value else "no"
    numeric = _number(value)
    if numeric is not None:
        if float(numeric).is_integer() and any(
            token in key for token in ("count", "wins", "flips", "messages", "citations", "tokens")
        ):
            return str(int(numeric))
        return f"{numeric:+.2f}" if any(token in key for token in ("shift", "delta", "movement")) else f"{numeric:.2f}"
    return _text(value)


def _format_number(value: Any, *, signed: bool = False) -> str:
    numeric = _number(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:+.2f}" if signed else f"{numeric:.2f}"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _integer(value: Any) -> int:
    numeric = _number(value)
    return int(numeric) if numeric is not None else 0


def _humanize(value: Any) -> str:
    text = _text(value).replace(".", " · ").replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else "Unavailable"


def _short_name(value: Any) -> str:
    parts = _text(value).split()
    if not parts:
        return "Juror"
    if parts[0].rstrip(".") in {"Dr", "Judge"} and len(parts) > 1:
        return parts[1]
    return parts[0]


def _compact_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return _text(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return []


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _h(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _md(value: Any) -> str:
    text = html.escape(_text(value), quote=False).replace("\\", "\\\\")
    return re.sub(r"([`*_\[\]#|])", r"\\\1", text).replace("\r", " ").replace("\n", " ")


def _md_code(value: Any) -> str:
    return _md(value).replace("`", "\\`")


def _md_quote(value: Any) -> str:
    lines = _text(value).splitlines() or [""]
    return "\n".join(f"> {_md(line)}" for line in lines)


def _safe_script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _page(title: str, body: str, *, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>{_h(title)}</title><style>{_CSS}</style></head>
<body>{body}<footer>Generated by ProtoLink · fictional courtroom advocate benchmark</footer>
{f"<script>{script}</script>" if script else ""}</body></html>"""


_PIPELINE_SCRIPT = r"""
(() => {
  const dataNode = document.getElementById("benchmark-report-data");
  if (!dataNode) return;
  const data = JSON.parse(dataNode.textContent);
  const $ = (id) => document.getElementById(id);
  const elements = {
    trial: $("pipeline-trial"), prev: $("pipeline-prev"), play: $("pipeline-play"),
    next: $("pipeline-next"), step: $("pipeline-step"), count: $("pipeline-count"),
    status: $("pipeline-status"), stage: $("pipeline-stage"), side: $("pipeline-side"),
    candidate: $("pipeline-candidate"), backend: $("pipeline-backend"),
    statement: $("pipeline-statement"), thesis: $("pipeline-thesis"),
    thesisWrap: $("pipeline-thesis-wrap"), claims: $("pipeline-claims"),
    claimsWrap: $("pipeline-claims-wrap"), addressed: $("pipeline-addressed"),
    addressedWrap: $("pipeline-addressed-wrap"), evidence: $("pipeline-evidence"),
    recipients: $("pipeline-recipients"), shift: $("pipeline-shift")
  };
  let trialIndex = 0;
  let argumentIndex = 0;
  let timer = null;
  const finite = (value) => Number.isFinite(value);
  const signed = (value) => finite(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}` : "N/A";
  const probability = (value) => finite(value) ? value.toFixed(2) : "N/A";
  const humanize = (value) => String(value || "unavailable").replaceAll("_", " ").replaceAll("-", " ");
  const replaceList = (element, values) => {
    element.replaceChildren();
    (values || []).forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      element.appendChild(item);
    });
  };
  const stop = () => {
    if (timer) window.clearInterval(timer);
    timer = null;
    elements.play.textContent = "Play";
    elements.play.setAttribute("aria-label", "Play argument pipeline");
  };
  const activeTrial = () => data.trials[trialIndex] || {arguments: []};
  function renderEmpty(message) {
    elements.stage.textContent = "NO ARGUMENT";
    elements.side.textContent = "No side";
    elements.candidate.textContent = "No public argument recorded";
    elements.backend.textContent = "";
    elements.statement.textContent = message;
    elements.thesisWrap.hidden = true;
    elements.claimsWrap.hidden = true;
    elements.addressedWrap.hidden = true;
    elements.evidence.replaceChildren();
    elements.recipients.replaceChildren();
    elements.shift.textContent = "No register updates";
    elements.count.textContent = "0 / 0";
    elements.step.max = 0;
    elements.step.value = 0;
    elements.prev.disabled = true;
    elements.next.disabled = true;
    elements.play.disabled = true;
    elements.status.textContent = message;
  }
  function renderRecipient(recipient) {
    const row = document.createElement("article");
    row.className = "recipient-row";
    const top = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = recipient.label || humanize(recipient.juror_id);
    const values = document.createElement("span");
    values.textContent = `${probability(recipient.before)} -> ${probability(recipient.after)} ` +
      `(${signed(recipient.delta)})`;
    top.append(name, values);
    const track = document.createElement("i");
    const before = document.createElement("b");
    before.className = "before-marker";
    before.style.left = `${Math.max(0, Math.min(100, finite(recipient.before) ? recipient.before : 0))}%`;
    const after = document.createElement("b");
    after.className = "after-marker";
    after.style.left = `${Math.max(0, Math.min(100, finite(recipient.after) ? recipient.after : 0))}%`;
    track.append(before, after);
    row.append(top, track);
    if (recipient.vote_before || recipient.vote_after) {
      const vote = document.createElement("small");
      vote.textContent = `vote ${humanize(recipient.vote_before)} -> ${humanize(recipient.vote_after)}`;
      row.appendChild(vote);
    }
    if (recipient.reply) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Public reply";
      const reply = document.createElement("p");
      reply.textContent = recipient.reply;
      details.append(summary, reply);
      row.appendChild(details);
    }
    return row;
  }
  function render() {
    const trial = activeTrial();
    const argumentsList = trial.arguments || [];
    if (!argumentsList.length) {
      renderEmpty("This trial has no linked public arguments.");
      return;
    }
    elements.play.disabled = false;
    argumentIndex = Math.max(0, Math.min(argumentIndex, argumentsList.length - 1));
    const argument = argumentsList[argumentIndex];
    const candidate = data.candidates[argument.candidate_id] || {
      label: argument.candidate_id || "Unknown candidate", backend: "backend unavailable", color: "#bdc8d8"
    };
    elements.stage.textContent = argument.stage_label || humanize(argument.stage_id);
    elements.side.textContent = argument.side_label || humanize(argument.side_id);
    elements.candidate.textContent = candidate.label;
    elements.candidate.style.setProperty("--candidate", candidate.color);
    elements.backend.textContent = candidate.backend;
    elements.statement.textContent = argument.statement || "No public statement text.";
    elements.thesisWrap.hidden = !argument.thesis;
    elements.thesis.textContent = argument.thesis || "";
    elements.claimsWrap.hidden = !(argument.key_claims || []).length;
    replaceList(elements.claims, argument.key_claims);
    elements.addressedWrap.hidden = !(argument.addressed_opponent_claims || []).length;
    replaceList(elements.addressed, argument.addressed_opponent_claims);
    elements.evidence.replaceChildren();
    (argument.evidence_ids || []).forEach((evidenceId) => {
      const chip = document.createElement("code");
      chip.textContent = evidenceId;
      elements.evidence.appendChild(chip);
    });
    (argument.invalid_evidence_ids || []).forEach((evidenceId) => {
      const chip = document.createElement("code");
      chip.className = "invalid";
      chip.textContent = `${evidenceId} unsupported`;
      elements.evidence.appendChild(chip);
    });
    elements.recipients.replaceChildren();
    let netShift = 0;
    let shiftCount = 0;
    (argument.recipients || []).forEach((recipient) => {
      if (finite(recipient.delta)) { netShift += recipient.delta; shiftCount += 1; }
      elements.recipients.appendChild(renderRecipient(recipient));
    });
    if (!(argument.recipients || []).length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No juror update events were linked to this argument.";
      elements.recipients.appendChild(empty);
    }
    elements.shift.textContent = shiftCount ? `${signed(netShift)} net support points across ${shiftCount} update(s)` :
      "No register updates";
    elements.count.textContent = `${argumentIndex + 1} / ${argumentsList.length}`;
    elements.step.max = Math.max(0, argumentsList.length - 1);
    elements.step.value = argumentIndex;
    elements.prev.disabled = argumentIndex === 0;
    elements.next.disabled = argumentIndex === argumentsList.length - 1;
    elements.status.textContent = `${trial.label}, argument ${argumentIndex + 1} of ${argumentsList.length}. ` +
      `${candidate.label} for ${argument.side_label}. ${elements.shift.textContent}.`;
  }
  function setTrial(index) {
    stop();
    trialIndex = Math.max(0, Math.min(index, data.trials.length - 1));
    argumentIndex = 0;
    render();
  }
  function play() {
    if (timer) { stop(); return; }
    const argumentsList = activeTrial().arguments || [];
    if (!argumentsList.length) return;
    if (argumentIndex >= argumentsList.length - 1) argumentIndex = 0;
    elements.play.textContent = "Pause";
    elements.play.setAttribute("aria-label", "Pause argument pipeline");
    timer = window.setInterval(() => {
      if (argumentIndex >= argumentsList.length - 1) { stop(); return; }
      argumentIndex += 1;
      render();
    }, 1800);
  }
  elements.trial.replaceChildren();
  (data.trials || []).forEach((trial, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = trial.label || trial.trial_id || `Trial ${index + 1}`;
    elements.trial.appendChild(option);
  });
  elements.trial?.addEventListener("change", () => setTrial(Number(elements.trial.value)));
  elements.prev?.addEventListener("click", () => { stop(); argumentIndex -= 1; render(); });
  elements.next?.addEventListener("click", () => { stop(); argumentIndex += 1; render(); });
  elements.play?.addEventListener("click", play);
  elements.step?.addEventListener("input", () => { stop(); argumentIndex = Number(elements.step.value); render(); });
  document.addEventListener("keydown", (event) => {
    if (event.target?.matches("input, select, textarea, button") || event.target?.closest?.("details")) return;
    if (event.key === "ArrowLeft") { stop(); argumentIndex -= 1; render(); }
    if (event.key === "ArrowRight") { stop(); argumentIndex += 1; render(); }
    if (event.key === " ") { event.preventDefault(); play(); }
  });
  if (!(data.trials || []).length) renderEmpty("No benchmark trials were recorded.");
  else setTrial(0);
})();
"""


_CSS = r"""
:root {
  color-scheme: dark;
  --bg: #091018;
  --surface: #131c28;
  --surface2: #1b2635;
  --surface3: #222f41;
  --ink: #f1f5fa;
  --muted: #9eacbe;
  --line: #314055;
  --gold: #efbe69;
  --green: #68d2a9;
  --red: #ee8190;
  --blue: #71aaf4;
  --radius: 18px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 8% 0, rgba(52, 75, 118, .46) 0, transparent 34rem),
    radial-gradient(circle at 92% 8%, rgba(48, 112, 102, .18) 0, transparent 27rem),
    var(--bg);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}
main { width: min(1240px, calc(100% - 30px)); margin: auto; padding: 52px 0 82px; }
h1, h2, h3, p { margin-top: 0; }
h1 {
  max-width: 940px;
  margin: 8px 0 16px;
  font: 400 clamp(2.7rem, 6.5vw, 5.8rem) / .96 Georgia, serif;
  letter-spacing: -.048em;
}
h2 { margin: 3px 0; font-size: 1.4rem; }
h3 { margin: 6px 0; }
a { color: inherit; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.eyebrow {
  color: var(--gold);
  font-size: .68rem;
  font-weight: 800;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 38px;
  align-items: end;
  margin-bottom: 24px;
}
.outcome { max-width: 820px; margin-bottom: 8px; font-size: 1.2rem; }
.lede, .section-head p, .muted, .caveat { color: var(--muted); }
.candidate-chips, .hero-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; }
.candidate-chips span, .hero-actions a {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 7px 11px;
  font-size: .75rem;
  text-decoration: none;
}
.candidate-chips i, .candidate-dot i, .matrix-candidate i, .assignment-list i {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--candidate);
}
.hero-actions a:first-child { border-color: var(--gold); }
.audit-badge, .panel, .trial-card, .candidate-card {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(19, 28, 40, .94);
}
.audit-badge {
  display: flex;
  min-height: 190px;
  flex-direction: column;
  justify-content: end;
  gap: 5px;
  padding: 24px;
  box-shadow: inset 0 3px var(--muted);
}
.audit-badge.ok { box-shadow: inset 0 3px var(--green); }
.audit-badge.warn { box-shadow: inset 0 3px var(--red); }
.audit-badge span, .audit-badge small { color: var(--muted); font-size: .7rem; }
.audit-badge strong { font: 400 2rem/1.05 Georgia, serif; }
.hash-strip {
  display: grid;
  grid-template-columns: .8fr 1fr 1fr;
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--line);
}
.hash-strip div { min-width: 0; padding: 12px 15px; background: var(--surface); }
.hash-strip span, .control-notes span {
  display: block;
  color: var(--muted);
  font-size: .66rem;
  text-transform: uppercase;
}
.hash-strip code, .control-notes code {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: .68rem;
  white-space: nowrap;
}
.panel { padding: 25px; margin-top: 18px; }
.section-head { display: flex; align-items: end; justify-content: space-between; gap: 25px; margin-bottom: 18px; }
.section-head p { max-width: 500px; margin-bottom: 0; font-size: .82rem; }
.table-wrap, .chart-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .8rem; }
th, td { border-bottom: 1px solid var(--line); padding: 11px; text-align: left; vertical-align: top; }
thead th { color: var(--muted); font-size: .66rem; text-transform: uppercase; }
.assignment-table th:first-child { min-width: 190px; }
.candidate-dot { display: flex; min-width: 180px; flex-direction: column; align-items: start; gap: 3px; }
.candidate-dot i { float: left; margin: 5px 7px 0 0; }
.candidate-dot small, .matrix-candidate + small { display: block; color: var(--muted); font-size: .67rem; }
.candidate-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 13px; }
.candidate-card { position: relative; overflow: hidden; padding: 21px; box-shadow: inset 3px 0 var(--candidate); }
.candidate-card h3 { font: 400 1.65rem Georgia, serif; }
.candidate-score { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-top: 24px; }
.candidate-score strong { font-size: 1.65rem; font-variant-numeric: tabular-nums; }
.candidate-score span { max-width: 150px; color: var(--muted); font-size: .68rem; text-align: right; }
.metrics-table { margin-top: 16px; }
.metrics-table td { font-variant-numeric: tabular-nums; }
.trial-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 17px; margin-top: 18px; }
.trial-card { min-width: 0; padding: 23px; }
.trial-card-head { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.trial-card-head h2 { margin-top: 6px; font: 400 2rem Georgia, serif; }
.trial-card-head > strong { color: var(--gold); font-size: .77rem; text-align: right; }
.mini-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; margin: 15px 0; background: var(--line); }
.mini-metrics div { padding: 12px; background: var(--surface2); }
.mini-metrics span, .mini-metrics strong { display: block; }
.mini-metrics span { color: var(--muted); font-size: .66rem; }
.mini-metrics strong { margin-top: 2px; font-size: .86rem; }
.assignment-list > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--line);
}
.assignment-list span { color: var(--muted); font-size: .75rem; }
.assignment-list strong { display: inline-flex; align-items: center; gap: 6px; font-size: .78rem; }
.trajectory-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.trajectory-panel { min-width: 0; border: 1px solid var(--line); border-radius: 13px; background: var(--surface2); }
.trajectory-title { display: flex; justify-content: space-between; gap: 12px; padding: 13px 15px 0; }
.trajectory-title span { color: var(--muted); font-size: .72rem; }
.trajectory { width: 100%; min-width: 570px; }
.trajectory text { fill: var(--muted); font-size: 10px; }
.trajectory .gridline, .trajectory .event-grid { stroke: var(--line); }
.trajectory .gridline.neutral { stroke: var(--gold); stroke-dasharray: 5 5; opacity: .7; }
.trajectory .event-grid { opacity: .26; }
.trajectory polyline { fill: none; stroke: var(--series); stroke-width: 2.5; }
.trajectory circle { fill: var(--surface); stroke: var(--series); stroke-width: 2; }
.trajectory .end-label { fill: var(--ink); }
.trajectory .axis-label { font-size: 9px; }
.legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-top: 12px; }
.legend span { color: var(--muted); font-size: .72rem; }
.legend i {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 5px;
  border-radius: 50%;
  background: var(--series);
}
.pipeline-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; }
.pipeline-toolbar label { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: .73rem; }
.pipeline-toolbar button, .pipeline-toolbar select {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 8px 12px;
  background: transparent;
  color: var(--ink);
}
.pipeline-toolbar button:hover { border-color: var(--gold); }
.pipeline-scrubber { flex: 1; min-width: 190px; }
.pipeline-scrubber input { width: 100%; }
.pipeline-route {
  display: grid;
  grid-template-columns: 1fr auto 1.3fr auto 1fr;
  gap: 12px;
  align-items: center;
  margin: 18px 0 10px;
  color: var(--muted);
  font-size: .65rem;
  letter-spacing: .1em;
  text-align: center;
}
.pipeline-route i { color: var(--gold); font-size: 1rem; font-style: normal; }
.pipeline-layout { --pipeline-height: 34rem; display: grid; grid-template-columns: .9fr 1.1fr; gap: 15px; }
.argument-card, .recipient-panel {
  height: var(--pipeline-height);
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface2);
}
.argument-card { display: grid; grid-template-rows: auto auto auto minmax(0, 1fr) auto; padding: 20px; }
.argument-meta { display: flex; gap: 7px; }
.argument-meta span {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 7px;
  color: var(--muted);
  font-size: .65rem;
}
#pipeline-candidate {
  padding-left: 10px;
  border-left: 3px solid var(--candidate, var(--gold));
  font: 400 1.6rem Georgia, serif;
}
.message-scroll { min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.message-block, .claim-block { margin: 13px 0; padding: 13px; background: rgba(9, 16, 24, .42); }
.message-block { border-left: 2px solid var(--gold); }
.message-block small, .claim-block small, .recipient-head span {
  color: var(--gold);
  font-size: .64rem;
  letter-spacing: .1em;
}
.message-block p { margin: 5px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.claim-block ul { margin-bottom: 0; padding-left: 19px; }
.evidence-chips { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 12px; }
.evidence-chips code, .evidence-pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 7px;
  color: var(--gold);
  font-size: .66rem;
}
.evidence-chips code.invalid, .evidence-pill.invalid { border-color: var(--red); color: var(--red); }
.recipient-panel { display: grid; grid-template-rows: auto minmax(0, 1fr); padding: 20px; }
.recipient-head { padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.recipient-list { min-height: 0; overflow-y: auto; scrollbar-gutter: stable; }
.recipient-row { padding: 14px 2px; border-bottom: 1px solid var(--line); }
.recipient-row > div { display: flex; justify-content: space-between; gap: 10px; }
.recipient-row > div span { font-variant-numeric: tabular-nums; font-size: .75rem; }
.recipient-row > i {
  position: relative;
  display: block;
  height: 7px;
  margin: 9px 4px;
  border-radius: 8px;
  background: #344156;
}
.recipient-row > i b {
  position: absolute;
  top: -3px;
  width: 3px;
  height: 13px;
  border-radius: 2px;
  transform: translateX(-50%);
}
.recipient-row .before-marker { background: var(--muted); }
.recipient-row .after-marker { background: var(--gold); }
.recipient-row small { color: var(--muted); }
.recipient-row details { margin-top: 8px; color: var(--muted); font-size: .72rem; }
.recipient-row details p { margin: 7px 0 0; color: var(--ink); white-space: pre-wrap; }
.citation-table th:first-child { min-width: 330px; }
.citation-table th small {
  display: block;
  max-width: 520px;
  margin-top: 4px;
  color: var(--muted);
  font-weight: 400;
  text-transform: none;
}
.citation-table td { text-align: center; font-variant-numeric: tabular-nums; }
.matrix-candidate { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.invalid-count { color: var(--red); }
.check-icon {
  display: inline-block;
  min-width: 48px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 7px;
  font-size: .61rem;
  text-align: center;
}
.check-icon.ok { border-color: var(--green); color: var(--green); }
.check-icon.warn { border-color: var(--red); color: var(--red); }
.check-icon.unknown { color: var(--muted); }
.fairness-table th { min-width: 190px; }
.fairness-table td:last-child { color: var(--muted); white-space: normal; }
.control-notes { display: grid; grid-template-columns: 1fr 1fr 2fr; gap: 9px; margin-top: 15px; }
.control-notes div {
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface2);
}
.caveat ul { padding-left: 19px; }
.caveat li { margin: 7px 0; }
.ledger-trial + .ledger-trial { margin-top: 25px; }
.ledger-item { border-top: 1px solid var(--line); }
.ledger-item summary {
  display: grid;
  grid-template-columns: 42px 1fr 180px 180px;
  gap: 10px;
  padding: 14px 2px;
  cursor: pointer;
}
.ledger-item summary span, .ledger-item summary em, .ledger-item summary i {
  color: var(--muted);
  font-size: .72rem;
  font-style: normal;
}
.ledger-content { margin: 0 0 18px 52px; color: var(--muted); }
.ledger-content > p:first-child { color: var(--ink); white-space: pre-wrap; }
.ledger-evidence { display: flex; flex-wrap: wrap; gap: 5px; }
.ledger-updates {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.ledger-update { padding: 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface2); }
.ledger-update span { display: block; font-size: .72rem; font-variant-numeric: tabular-nums; }
blockquote { margin: 8px 0 0; padding: 9px 11px; border-left: 2px solid var(--gold); color: var(--ink); }
.empty, .notice { color: var(--muted); }
button:focus-visible, select:focus-visible, input:focus-visible, .message-scroll:focus-visible,
a:focus-visible, summary:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
footer { padding: 28px; border-top: 1px solid var(--line); color: var(--muted); text-align: center; font-size: .7rem; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
  white-space: nowrap;
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
@media (max-width: 900px) {
  .hero, .pipeline-layout { grid-template-columns: 1fr; }
  .audit-badge { min-height: 150px; }
  .pipeline-route { display: none; }
  .pipeline-layout { --pipeline-height: 29rem; margin-top: 16px; }
  .trajectory-grid, .trial-grid { grid-template-columns: 1fr; }
  .hash-strip, .control-notes { grid-template-columns: 1fr; }
  .section-head { align-items: start; flex-direction: column; }
}
@media (max-width: 570px) {
  main { width: calc(100% - 18px); padding-top: 28px; }
  .panel, .trial-card { padding: 16px; }
  .candidate-card-grid, .mini-metrics { grid-template-columns: 1fr; }
  .ledger-item summary { grid-template-columns: 34px 1fr auto; }
  .ledger-item summary em { display: none; }
  .ledger-item summary i { grid-column: 2 / -1; }
  .ledger-content { margin-left: 36px; }
  .pipeline-toolbar { align-items: stretch; }
  .pipeline-toolbar label:first-child { width: 100%; }
  .pipeline-toolbar select { flex: 1; }
}
@media print {
  :root {
    color-scheme: light;
    --bg: #fff;
    --surface: #fff;
    --surface2: #f5f5f5;
    --ink: #111;
    --muted: #555;
    --line: #bbb;
  }
  body { background: #fff; }
  .hero-actions, .pipeline-toolbar { display: none; }
  .panel, .trial-card, .candidate-card, .audit-badge { break-inside: avoid; }
}
"""
