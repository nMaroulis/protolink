"""Dependency-free, replay-first reports for the AI Liability Tribunal."""

from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .case_data import ACTOR_PROFILES, public_participant_profile

COLORS = (
    "#56c8c8",
    "#f2b65f",
    "#dd7da2",
    "#9d8cff",
    "#86cc78",
    "#72a8f2",
    "#e98b72",
    "#b3bfce",
)
CONDITIONS = ("solo", "independent", "star", "mesh")


def write_condition_artifacts(result: dict[str, Any], condition_dir: Path) -> None:
    """Write a safe public transcript and a standalone interactive report."""
    destination = Path(condition_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "transcript.md").write_text(_render_transcript(result), encoding="utf-8")
    (destination / "report.html").write_text(_render_condition_report(result), encoding="utf-8")


def write_comparison_index(results: list[dict[str, Any]], output_root: Path) -> None:
    """Write a standalone four-condition comparison entry point."""
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(_render_comparison(results), encoding="utf-8")


def _render_transcript(result: Mapping[str, Any]) -> str:
    run = _mapping(result.get("run"))
    case = _mapping(result.get("case"))
    verdict = _mapping(result.get("verdict"))
    lines = [
        f"# {_md(case.get('title', 'AI Liability Tribunal'))}",
        "",
        f"- Condition: `{_md_code(run.get('condition', 'unknown'))}`",
        f"- Provider/model: `{_md_code(run.get('provider', 'unknown'))}` / `{_md_code(run.get('model', 'unknown'))}`",
        f"- Seed: `{_md_code(run.get('seed', 'unknown'))}`",
        f"- Evidence order: `{_md_code(run.get('evidence_order', 'unknown'))}`",
        f"- Record hash: `{_md_code(result.get('record_hash', run.get('record_hash', 'unavailable')))}`",
        f"- Verdict: **{_md(_verdict_text(verdict.get('verdict')))}** "
        f"({_integer(verdict.get('guilty_votes'))}-{_integer(verdict.get('not_guilty_votes'))})",
        "",
        "> Public communication artifacts only. Decision registers are observable application state, "
        "not hidden chain-of-thought.",
        "",
        "## A2A transcript",
        "",
    ]
    for event in _events(result):
        response = _mapping(event.get("response"))
        lines.extend(
            [
                f"### {_integer(event.get('sequence')):03d} · {_md(event.get('phase', 'unknown'))} · "
                f"{_md(_label(event.get('sender'), result))} → {_md(_label(event.get('receiver'), result))}",
                "",
                f"**Kind:** `{_md_code(event.get('kind', 'message'))}`",
                "",
                _md_quote(event.get("message", "")),
                "",
            ]
        )
        action = _mapping(event.get("authored_action"))
        if action:
            action_line = " · ".join(
                part
                for part in (
                    _text(action.get("action")),
                    _text(action.get("public_intent")),
                    f"target: {_text(action.get('target_id'))}" if action.get("target_id") else "",
                )
                if part
            )
            lines.extend([f"**Authored action:** {_md(action_line)}", ""])
        reply = _public_response(response)
        if reply and reply.strip() != _text(event.get("message")).strip():
            lines.extend(["**Public reply:**", "", _md_quote(reply), ""])
        before = _number(event.get("belief_before"))
        after = _number(event.get("belief_after"))
        if before is not None and after is not None:
            lines.extend(
                [
                    f"**Guilt register:** {before:.2f} → {after:.2f} ({after - before:+.2f})",
                    "",
                ]
            )
        evidence = _strings(response.get("evidence_ids") or event.get("evidence_ids"))
        if evidence:
            lines.extend([f"**Evidence:** {', '.join(f'`{_md_code(item)}`' for item in evidence)}", ""])
        warnings = _strings(event.get("warnings"))
        if warnings:
            lines.extend([f"**Protocol warnings:** {_md('; '.join(warnings))}", ""])
    announcement = _text(verdict.get("announcement"))
    lines.extend(
        [
            "## Verdict announcement",
            "",
            _md_quote(announcement) if announcement else "_No public announcement recorded._",
            "",
            "## Interpretation boundary",
            "",
            "A register shift immediately after a message is a temporal association, not an estimated causal effect. "
            "Causal claims require paired message ablations and repeated runs.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_condition_report(result: Mapping[str, Any]) -> str:
    run = _mapping(result.get("run"))
    case = _mapping(result.get("case"))
    verdict = _mapping(result.get("verdict"))
    metrics = _mapping(result.get("metrics"))
    checkpoints = _checkpoints(result)
    headline, outcome = _condition_headline(run, verdict, metrics, checkpoints)
    replay = _replay_payload(result)
    metric_cards = "".join(
        (
            _metric("Final mean guilt", _format_number(metrics.get("final_mean_guilt_probability")), "0-100 register"),
            _metric("Final polarization", _format_number(metrics.get("final_polarization")), "N/A for solo"),
            _metric(
                "Consensus gain",
                _format_number(metrics.get("deliberation_consensus_gain"), signed=True),
                "pre minus post dispersion",
            ),
            _metric("Direct A2A", str(_integer(metrics.get("a2a_messages"))), "serialized messages"),
        )
    )
    body = f"""
<main>
  <header class="hero" id="summary">
    <div>
      <div class="eyebrow">PROTOLINK · AI LIABILITY TRIBUNAL</div>
      <h1>{_h(headline)}</h1>
      <p class="outcome">{_h(outcome)}</p>
      <p class="lede">{_h(case.get("short_title", case.get("title", "Fictional tribunal")))}</p>
      <div class="chips">
        <span>{_h(run.get("condition", "unknown"))}</span>
        <span>{_h(run.get("provider", "unknown"))}</span>
        <span>{_h(run.get("model", "unknown"))}</span>
        <span>seed {_h(run.get("seed", "—"))}</span>
      </div>
      <div class="hero-actions">
        <a href="#replay" data-jump-turning>Replay the turning point ↓</a>
        <a href="#observed-shifts">Inspect observed shifts</a>
      </div>
    </div>
    <aside class="verdict">
      <span>PROCEDURAL VERDICT</span>
      <strong>{_h(_verdict_text(verdict.get("verdict")))}</strong>
      <b>{_integer(verdict.get("guilty_votes"))} guilty ·
      {_integer(verdict.get("not_guilty_votes"))} not guilty</b>
      <small>Truth-match evaluation appears below, not in the decision loop.</small>
    </aside>
  </header>

  <section class="metric-grid" aria-label="Run metrics">{metric_cards}</section>

  <section class="panel replay-panel" id="replay">
    <div class="section-head">
      <div><div class="eyebrow">THE COMMUNICATION IS THE EXPERIMENT</div><h2>Playable A2A replay</h2></div>
      <p>Watch public messages travel between autonomous roles and the explicit juror registers update.</p>
    </div>
    {_replay_shell()}
    <script type="application/json" id="replay-data">{_safe_script_json(replay)}</script>
    <noscript><p class="notice">JavaScript is off. The complete static ledger remains available below.</p></noscript>
  </section>

  <section class="turning-grid">{_turning_cards(result, checkpoints)}</section>

  <section class="panel">
    <div class="section-head">
      <div><div class="eyebrow">SYNCHRONIZED FALLBACK</div><h2>Guilt-register trajectories</h2></div>
      <p>Public application registers, shown separately from each juror's categorical vote.</p>
    </div>
    {_trajectory_svg(result)}
    {_legend(result)}
  </section>

  <section class="panel" id="observed-shifts">
    <div class="section-head">
      <div><div class="eyebrow">DESCRIPTIVE, NOT CAUSAL</div><h2>Observed after-message shifts</h2></div>
      <p>Immediate temporal association. Establishing causality requires matched message ablations.</p>
    </div>
    <div class="split">
      <div><h3>Peer deliberation</h3>{_shift_table(result, "peer")}</div>
      <div><h3>Courtroom record</h3>{_shift_table(result, "courtroom")}</div>
    </div>
  </section>

  <section class="split">
    <section class="panel">
      <div class="eyebrow">OBSERVED INFLUENCE MAP</div><h2>Routes weighted by movement</h2>
      <p>Thicker lines accumulated more immediate absolute register movement. This is descriptive, not a causal
      persuasion score.</p>
      {_network_svg(result)}
    </section>
    <section class="panel">
      <div class="eyebrow">FINAL PANEL</div><h2>Different paths through one record</h2>
      {_jury_rows(result)}
    </section>
  </section>

  <section class="panel">
    <div class="section-head">
      <div><div class="eyebrow">PUBLIC FALLBACK LEDGER</div><h2>Complete interaction timeline</h2></div>
      <p>Every message remains readable without the player.</p>
    </div>
    {_timeline(result)}
  </section>

  <section class="split">
    <section class="panel">
      <div class="eyebrow">ADMITTED RECORD</div><h2>Evidence cited by the agents</h2>
      {_evidence_rows(result)}
    </section>
    <section class="panel caveat">
      <div class="eyebrow">REPRODUCIBILITY & LIMITS</div><h2>Read the outcome carefully</h2>
      <p>Record hash:
      <code>{_h(result.get("record_hash", run.get("record_hash", "unavailable")))}</code></p>
      <p>Control fingerprint:
      <code>{_h(result.get("control_fingerprint", run.get("control_fingerprint", "unavailable")))}</code></p>
      <p>Truth match: <strong>{"yes" if verdict.get("matches_synthetic_truth") else "no"}</strong>.
      The synthetic fixture was not visible to the agents.</p>
      <p>Agreement is not accuracy. A public rationale may be compressed or post-hoc.</p>
      <p><strong>Fictional software experiment only. Not legal analysis or advice.</strong></p>
    </section>
  </section>
</main>
"""
    return _page(
        f"{case.get('short_title', case.get('title', 'AI Liability Tribunal'))} · {run.get('condition', '')}",
        body,
        script=_REPLAY_SCRIPT,
    )


def _render_comparison(results: list[dict[str, Any]]) -> str:
    indexed = {_text(_mapping(item.get("run")).get("condition")): item for item in results}
    reference = next(iter(results), {})
    case = _mapping(reference.get("case"))
    headline, subhead = _comparison_headline(indexed)
    fingerprint_values = [
        _text(item.get("control_fingerprint") or _mapping(item.get("run")).get("control_fingerprint"))
        for item in results
    ]
    fingerprints = {value for value in fingerprint_values if value}
    controlled = bool(results) and all(fingerprint_values) and len(fingerprints) == 1
    cards = "".join(_comparison_card(condition, indexed.get(condition)) for condition in CONDITIONS)
    rows = "".join(_comparison_row(condition, indexed.get(condition)) for condition in CONDITIONS)
    body = f"""
<main>
  <header class="hero comparison-hero">
    <div>
      <div class="eyebrow">PROTOLINK · FOUR COMMUNICATION CONDITIONS</div>
      <h1>{_h(headline)}</h1>
      <p class="outcome">{_h(subhead)}</p>
      <p class="lede">{_h(case.get("short_title", case.get("title", "AI Liability Tribunal")))}</p>
      <div class="control-status {"ok" if controlled else "warn"}">
        {"Shared control fingerprint" if controlled else "Exploratory comparison: control fingerprints differ"}
      </div>
    </div>
  </header>
  <section class="treatment-ladder">{cards}</section>
  <section class="panel">
    <div class="section-head">
      <div><div class="eyebrow">SAME RECORD, DIFFERENT COMMUNICATION</div><h2>Treatment ladder</h2></div>
      <p>Solo also changes the number of decision-makers, so it is not a topology-only contrast.</p>
    </div>
    {_treatment_svg(indexed)}
  </section>
  <section class="panel">
    <div class="section-head">
      <div><div class="eyebrow">SIDE BY SIDE</div><h2>Outcome and communication metrics</h2></div>
      <p>Consensus is not accuracy. Solo polarization and consensus gain are N/A by definition.</p>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Condition</th><th>Verdict</th><th>Tally</th><th>Mean guilt</th>
      <th>Polarization</th><th>Consensus gain</th><th>A2A</th><th>Peer</th><th>Flips</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>
  </section>
  <section class="panel caveat">
    <div class="eyebrow">CAUSAL BOUNDARY</div><h2>Communication is a treatment, not a guarantee</h2>
    <p>These are descriptive outcomes from matched seeded runs. Immediate shifts are temporal associations.
    Strong causal claims require repeated paired runs and message ablations.</p>
  </section>
</main>
"""
    return _page(f"{case.get('short_title', 'AI Liability Tribunal')} · comparison", body)


def _replay_shell() -> str:
    return """
<div class="replay-layout">
  <div class="replay-stage">
    <svg id="replay-network" viewBox="0 0 720 410" role="img"
      aria-label="Active agent-to-agent communication network"></svg>
    <div id="replay-status" class="sr-only" aria-live="polite"></div>
  </div>
  <article class="message-card" aria-labelledby="replay-route">
    <div class="message-kicker" id="replay-kicker">Select an event</div>
    <h3 id="replay-route">Sender → receiver</h3>
    <p class="message-people" id="replay-people">Participant details</p>
    <div class="message-scroll" id="replay-transcript" role="region" tabindex="0"
      aria-label="Current replay event transcript">
      <div class="message-block"><small>PUBLIC MESSAGE</small><p id="replay-message"></p></div>
      <div class="message-block" id="action-wrap"><small>AUTHORED ACTION / QUESTION</small>
        <p id="replay-action"></p></div>
      <div class="message-block" id="reply-wrap"><small>PUBLIC REPLY</small><p id="replay-reply"></p></div>
      <div class="register-change" id="replay-change">No decision-register update</div>
      <div class="protocol-row" id="replay-protocol"></div>
    </div>
  </article>
</div>
<div class="juror-bars" id="replay-bars" aria-label="Current juror guilt registers"></div>
<div class="replay-controls">
  <button type="button" id="replay-prev" aria-label="Previous message">← Prev</button>
  <button type="button" id="replay-play" aria-label="Play replay">Play</button>
  <button type="button" id="replay-next" aria-label="Next message">Next →</button>
  <label class="scrubber"><span>Message</span><input id="replay-scrub" type="range" min="0" value="0"></label>
  <span id="replay-count">0 / 0</span>
  <label><input type="checkbox" id="replay-peer"> Peer only</label>
  <label>Speed <select id="replay-speed"><option value="1800">0.5x</option>
    <option value="950" selected>1x</option><option value="450">2x</option></select></label>
</div>
"""


def _replay_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    jurors = _jurors(result)
    events = _events(result)
    actor_ids = list(
        dict.fromkeys(
            [
                *ACTOR_PROFILES,
                *jurors,
                *(_text(event.get("sender")) for event in events),
                *(_text(event.get("receiver")) for event in events),
            ]
        )
    )
    actor_ids = [actor_id for actor_id in actor_ids if actor_id]
    positions = _actor_positions(actor_ids, set(jurors))
    actors = {
        actor_id: {
            "id": actor_id,
            "label": _label(actor_id, result),
            "role": _actor_role(actor_id, result),
            "age": _actor_age(actor_id, result),
            "gender": _actor_gender(actor_id, result),
            "juror": actor_id in jurors,
            "color": _color(actor_id, actor_ids),
            "x": positions[actor_id][0],
            "y": positions[actor_id][1],
        }
        for actor_id in actor_ids
    }
    state = {
        juror_id: {
            "label": _text(juror.get("label")) or _label(juror_id, result),
            "guilt_probability": _juror_baseline(juror),
            "vote": _normalize_vote(juror.get("baseline_vote")),
            "confidence": None,
        }
        for juror_id, juror in jurors.items()
    }
    histories_by_sequence = {
        juror_id: {
            _integer(point.get("sequence")): point
            for point in _list_of_mappings(juror.get("history"))
            if _number(point.get("guilt_probability")) is not None
        }
        for juror_id, juror in jurors.items()
    }
    histories_by_event = {
        juror_id: {
            _text(point.get("source_event_id")): point
            for point in _list_of_mappings(juror.get("history"))
            if _text(point.get("source_event_id"))
        }
        for juror_id, juror in jurors.items()
    }
    frames: list[dict[str, Any]] = []
    for event in events:
        sequence = _integer(event.get("sequence"))
        event_id = _text(event.get("event_id")) or f"event-{sequence}"
        receiver = _text(event.get("receiver"))
        before = _number(event.get("belief_before"))
        after = _number(event.get("belief_after"))
        change: dict[str, Any] | None = None
        if receiver in state and after is not None:
            before_value = before if before is not None else _number(state[receiver]["guilt_probability"])
            point = histories_by_event.get(receiver, {}).get(
                event_id,
                histories_by_sequence.get(receiver, {}).get(sequence, {}),
            )
            response = _mapping(event.get("response"))
            vote_before = _normalize_vote(state[receiver].get("vote"))
            vote_after = _normalize_vote(point.get("vote")) or _normalize_vote(response.get("vote")) or vote_before
            state[receiver] = {
                "label": state[receiver]["label"],
                "guilt_probability": after,
                "vote": vote_after,
                "confidence": _number(point.get("confidence")),
            }
            change = {
                "juror_id": receiver,
                "before": before_value,
                "after": after,
                "delta": after - before_value if before_value is not None else None,
                "vote_before": vote_before,
                "vote_after": vote_after,
                "vote_changed": bool(vote_before and vote_after and vote_before != vote_after),
            }
        response = _mapping(event.get("response"))
        action = _mapping(event.get("authored_action"))
        frames.append(
            {
                "event_id": event_id,
                "sequence": sequence,
                "phase": _text(event.get("phase")),
                "kind": _text(event.get("kind")),
                "sender": _text(event.get("sender")),
                "receiver": receiver,
                "message": _text(event.get("message")),
                "public_response": _public_response(response),
                "authored_action": {
                    "action": _text(action.get("action")),
                    "message": _text(action.get("message") or action.get("question")),
                    "public_intent": _text(action.get("public_intent")),
                    "target_id": _text(action.get("target_id")),
                }
                if action
                else None,
                "evidence_ids": _strings(response.get("evidence_ids") or event.get("evidence_ids")),
                "warnings": _strings(event.get("warnings")),
                "task_ids": _strings(event.get("task_ids")),
                "provider": _text(event.get("provider")),
                "model": _text(event.get("model")),
                "latency_ms": _number(event.get("latency_ms")),
                "attempts": _integer(event.get("attempts")),
                "tokens": _integer(event.get("input_tokens_estimate")) + _integer(event.get("output_tokens_estimate")),
                "peer": _is_peer_event(event),
                "change": change,
                "juror_states": json.loads(json.dumps(state)),
            }
        )
    turning = next(
        (
            index
            for index, frame in enumerate(frames)
            if frame.get("peer") and _mapping(frame.get("change")).get("vote_changed")
        ),
        next(
            (index for index, frame in enumerate(frames) if _mapping(frame.get("change")).get("vote_changed")),
            0,
        ),
    )
    return {"actors": actors, "frames": frames, "turning_index": turning}


def _checkpoints(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    jurors = _jurors(result)
    events = _events(result)
    recorded = _mapping(result.get("checkpoints"))
    peer_sequences = [_integer(event.get("sequence")) for event in events if _is_peer_event(event)]
    first_peer = min(peer_sequences) if peer_sequences else math.inf
    last_peer = max(peer_sequences) if peer_sequences else -math.inf
    baseline: dict[str, Mapping[str, Any]] = {}
    pre: dict[str, Mapping[str, Any]] = {}
    post: dict[str, Mapping[str, Any]] = {}
    for juror_id, juror in jurors.items():
        history = _list_of_mappings(juror.get("history"))
        baseline[juror_id] = {
            "guilt_probability": _juror_baseline(juror),
            "vote": _normalize_vote(juror.get("baseline_vote")),
        }
        pre[juror_id] = _history_snapshot(history, lambda sequence: sequence < first_peer) or baseline[juror_id]
        post[juror_id] = (
            _history_snapshot(history, lambda sequence: sequence <= last_peer) if peer_sequences else pre[juror_id]
        ) or pre[juror_id]
    final = {
        juror_id: {
            "guilt_probability": _number(juror.get("guilt_probability")),
            "vote": _normalize_vote(juror.get("vote")),
        }
        for juror_id, juror in jurors.items()
    }
    return {
        "baseline": _checkpoint(_mapping(recorded.get("baseline")) or baseline),
        "pre_deliberation": _checkpoint(_mapping(recorded.get("pre_deliberation")) or pre),
        "post_deliberation": _checkpoint(_mapping(recorded.get("post_deliberation")) or post),
        "final": _checkpoint(final),
    }


def _checkpoint(snapshots: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {juror_id: _mapping(value) for juror_id, value in snapshots.items()}
    probabilities = {juror_id: _number(snapshot.get("guilt_probability")) for juror_id, snapshot in normalized.items()}
    votes = {juror_id: _normalize_vote(snapshot.get("vote")) for juror_id, snapshot in normalized.items()}
    usable = [value for value in probabilities.values() if value is not None]
    guilty = sum(vote == "guilty" for vote in votes.values())
    not_guilty = sum(vote == "not_guilty" for vote in votes.values())
    verdict = "unavailable"
    if guilty or not_guilty:
        verdict = "guilty" if guilty > not_guilty else "not_guilty"
    return {
        "jurors": probabilities,
        "votes": votes,
        "guilty_votes": guilty,
        "not_guilty_votes": not_guilty,
        "verdict": verdict,
        "mean": sum(usable) / len(usable) if usable else None,
        "polarization": _population_sd(usable),
    }


def _condition_headline(
    run: Mapping[str, Any],
    verdict: Mapping[str, Any],
    metrics: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    condition = _text(run.get("condition"))
    pre = checkpoints["pre_deliberation"]
    post = checkpoints["post_deliberation"]
    final_text = _verdict_text(verdict.get("verdict"))
    if condition == "solo":
        return "One decision-maker. No peer deliberation.", f"The solo run ended {final_text}."
    if condition == "independent":
        return "Five jurors decided without peer messages.", (
            f"The independent panel ended {final_text}: {_integer(verdict.get('guilty_votes'))}-"
            f"{_integer(verdict.get('not_guilty_votes'))}."
        )
    pre_tally = f"{pre['guilty_votes']}-{pre['not_guilty_votes']} {_verdict_text(pre['verdict'])}"
    post_tally = f"{post['guilty_votes']}-{post['not_guilty_votes']} {_verdict_text(post['verdict'])}"
    if pre["verdict"] != post["verdict"]:
        return "Peer exchange immediately preceded a verdict change.", f"{pre_tally} → {post_tally}."
    flips = _integer(metrics.get("vote_flips_during_deliberation"))
    if flips:
        return "Peer exchange moved votes, but not the majority.", f"{pre_tally} → {post_tally}; {flips} vote flip(s)."
    return "Communication changed the path, not the verdict.", f"{pre_tally} → {post_tally}."


def _comparison_headline(indexed: Mapping[str, Mapping[str, Any]]) -> tuple[str, str]:
    independent = indexed.get("independent")
    mesh = indexed.get("mesh")
    if not independent or not mesh:
        return "One record. Four communication conditions.", "Run independent and mesh together to compare outcomes."
    independent_verdict = _mapping(independent.get("verdict"))
    mesh_verdict = _mapping(mesh.get("verdict"))
    left = _verdict_text(independent_verdict.get("verdict"))
    right = _verdict_text(mesh_verdict.get("verdict"))
    left_tally = (
        f"{_integer(independent_verdict.get('guilty_votes'))}-{_integer(independent_verdict.get('not_guilty_votes'))}"
    )
    right_tally = f"{_integer(mesh_verdict.get('guilty_votes'))}-{_integer(mesh_verdict.get('not_guilty_votes'))}"
    if left != right:
        return "Independent and mesh ended with different verdicts.", (
            f"In these seeded runs, independent ended {left_tally} {left}; mesh ended {right_tally} {right}."
        )
    return "Mesh changed who spoke to whom, not the final verdict.", (
        f"Independent ended {left_tally}; mesh ended {right_tally}. Both were {right}."
    )


def _turning_cards(result: Mapping[str, Any], checkpoints: Mapping[str, Mapping[str, Any]]) -> str:
    events = _events(result)
    peer_events = [event for event in events if _is_peer_event(event)]
    vote_flip = next(
        (
            (event, before, after)
            for event in peer_events
            if (change := _event_vote_change(event, result)) is not None
            for before, after in (change,)
        ),
        None,
    )
    shifted = [event for event in peer_events if _number(event.get("belief_delta")) is not None]
    if not shifted:
        shifted = [event for event in events if _number(event.get("belief_delta")) is not None]
    largest = max(shifted, key=lambda event: abs(_number(event.get("belief_delta")) or 0.0), default=None)
    if vote_flip:
        event, before_vote, after_vote = vote_flip
        first_title = "First peer vote flip"
        first_body = (
            f"{_label(event.get('sender'), result)} → {_label(event.get('receiver'), result)} was followed by "
            f"{_verdict_text(before_vote)} → {_verdict_text(after_vote)}."
        )
    else:
        first_title = "No peer vote flip"
        first_body = "The categorical vote ledger records no vote change after a peer message."
    if largest:
        largest_body = (
            f"{_label(largest.get('sender'), result)} → {_label(largest.get('receiver'), result)} was followed by "
            f"{_number(largest.get('belief_delta')):+.1f} points."
        )
    else:
        largest_body = "No decision-register shift was recorded."
    pre = checkpoints["pre_deliberation"]
    post = checkpoints["post_deliberation"]
    topology_body = (
        f"{len(peer_events)} peer messages. Polarization "
        f"{_format_number(pre.get('polarization'))} → {_format_number(post.get('polarization'))}."
    )
    return (
        _turning_card("TURNING POINT", first_title, first_body)
        + _turning_card("LARGEST TEMPORAL ASSOCIATION", "Observed after-message shift", largest_body)
        + _turning_card("COMMUNICATION SHAPE", "What the topology exposed", topology_body)
    )


def _turning_card(kicker: str, title: str, body: str) -> str:
    return (
        '<article class="turning-card">'
        f'<div class="eyebrow">{_h(kicker)}</div><h3>{_h(title)}</h3><p>{_h(body)}</p></article>'
    )


def _trajectory_svg(result: Mapping[str, Any]) -> str:
    jurors = _jurors(result)
    series: list[tuple[str, Mapping[str, Any], list[Mapping[str, Any]]]] = []
    maximum = 1
    for juror_id, state in jurors.items():
        history = [
            point
            for point in _list_of_mappings(state.get("history"))
            if _number(point.get("guilt_probability")) is not None
        ]
        if not history:
            value = _number(state.get("guilt_probability"))
            if value is not None:
                history = [{"sequence": 0, "guilt_probability": value}]
        maximum = max(maximum, *(max((_integer(point.get("sequence")) for point in history), default=0),))
        series.append((juror_id, state, history))
    width, height = 980, 350
    left, right, top, bottom = 55, 135, 25, 45

    def x(sequence: float) -> float:
        return left + sequence / maximum * (width - left - right)

    def y(probability: float) -> float:
        return top + (100 - probability) / 100 * (height - top - bottom)

    grid = "".join(
        f'<line x1="{left}" x2="{width - right}" y1="{y(value):.1f}" y2="{y(value):.1f}" '
        'class="gridline"/>'
        f'<text x="{left - 8}" y="{y(value) + 4:.1f}" text-anchor="end">{value}</text>'
        for value in (0, 25, 50, 75, 100)
    )
    paths: list[str] = []
    actor_ids = list(jurors)
    for juror_id, state, history in series:
        if not history:
            continue
        points = [
            (
                x(_integer(point.get("sequence"))),
                y(_number(point.get("guilt_probability")) or 0.0),
            )
            for point in history
        ]
        color = _color(juror_id, actor_ids)
        dots = "".join(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3"><title>{_h(state.get("label", juror_id))}: '
            f"{_number(point.get('guilt_probability')):.1f}</title></circle>"
            for (px, py), point in zip(points, history, strict=True)
        )
        last_x, last_y = points[-1]
        paths.append(
            f'<g style="--series:{color}"><polyline points="'
            + " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            + f'"/>{dots}<text class="end-label" x="{last_x + 7:.1f}" y="{last_y + 4:.1f}">'
            f"{_h(_first_name(state.get('label', juror_id)))}</text></g>"
        )
    return (
        f'<div class="chart-wrap"><svg class="trajectory" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Juror guilt-register trajectories"><title>Guilt-register trajectories</title>'
        f"{grid}{''.join(paths)}</svg></div>"
    )


def _network_svg(result: Mapping[str, Any]) -> str:
    jurors = _jurors(result)
    events = _events(result)
    actor_ids = list(
        dict.fromkeys(
            [
                *(_text(event.get("sender")) for event in events),
                *(_text(event.get("receiver")) for event in events),
                *jurors,
            ]
        )
    )
    actor_ids = [actor_id for actor_id in actor_ids if actor_id]
    if not actor_ids:
        return '<p class="empty">No A2A network was recorded.</p>'
    positions = _actor_positions(actor_ids, set(jurors))
    edges: dict[tuple[str, str], int] = {}
    for event in events:
        edge = (_text(event.get("sender")), _text(event.get("receiver")))
        if all(edge):
            edges[edge] = edges.get(edge, 0) + 1
    edge_shifts = {
        (_text(edge.get("sender")), _text(edge.get("receiver"))): abs(_number(edge.get("absolute_shift")) or 0.0)
        for edge in _list_of_mappings(result.get("influence_edges"))
    }
    max_shift = max(edge_shifts.values(), default=0.0)
    lines = "".join(
        f'<line x1="{positions[sender][0]}" y1="{positions[sender][1]}" '
        f'x2="{positions[receiver][0]}" y2="{positions[receiver][1]}" '
        f'class="network-edge{" peer" if sender in jurors and receiver in jurors else ""}" '
        f'style="stroke-width:{1 + 5 * edge_shifts.get((sender, receiver), 0.0) / max(max_shift, 1.0):.2f}">'
        f"<title>{_h(_label(sender, result))} → {_h(_label(receiver, result))}: {count} message(s), "
        f"observed |Δ| {_format_number(edge_shifts.get((sender, receiver), 0.0))}</title></line>"
        for (sender, receiver), count in edges.items()
        if sender in positions and receiver in positions
    )
    nodes = "".join(
        f'<g class="network-node" transform="translate({positions[actor_id][0]} {positions[actor_id][1]})" '
        f'style="--series:{_color(actor_id, actor_ids)}"><circle r="25"/><text text-anchor="middle" y="4">'
        f"{_h(_short_label(actor_id, result))}</text></g>"
        for actor_id in actor_ids
    )
    return (
        '<svg class="network" viewBox="0 0 720 410" role="img" '
        'aria-label="Agent communication routes weighted by immediate register movement">'
        f"<title>Observed influence map</title>{lines}{nodes}</svg>"
    )


def _shift_table(result: Mapping[str, Any], scope: str) -> str:
    rows: list[str] = []
    for edge in _list_of_mappings(result.get("influence_edges")):
        edge_scope = _text(edge.get("scope") or edge.get("channel")) or (
            "peer"
            if _text(edge.get("sender")).startswith("juror_") and _text(edge.get("receiver")).startswith("juror_")
            else "courtroom"
        )
        if edge_scope != scope:
            continue
        rows.append(
            "<tr>"
            f"<td>{_h(_label(edge.get('sender'), result))} → {_h(_label(edge.get('receiver'), result))}</td>"
            f"<td>{_integer(edge.get('messages'))}</td>"
            f"<td>{_format_number(edge.get('signed_shift'), signed=True)}</td>"
            f"<td>{_format_number(edge.get('absolute_shift'))}</td></tr>"
        )
    if not rows:
        return '<p class="empty">No shifts in this scope.</p>'
    return (
        '<div class="table-wrap"><table><thead><tr><th>Route</th><th>Messages</th>'
        f"<th>Net Δ</th><th>|Δ|</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _jury_rows(result: Mapping[str, Any]) -> str:
    actor_ids = list(_jurors(result))
    rows: list[str] = []
    for juror_id, state in _jurors(result).items():
        baseline = _juror_baseline(state)
        final = _number(state.get("guilt_probability"))
        delta = final - baseline if final is not None and baseline is not None else None
        profile = _participant_profile(juror_id, result)
        details = " · ".join(
            item
            for item in (
                _text(state.get("style") or profile.get("style")) or "Juror",
                f"age {_integer(profile.get('age'))}" if profile.get("age") is not None else "",
                _text(profile.get("gender")),
            )
            if item
        )
        rows.append(
            f'<div class="jury-row" style="--series:{_color(juror_id, actor_ids)}"><i></i><div><strong>'
            f"{_h(state.get('label', juror_id))}</strong><small>{_h(details)}</small></div>"
            f"<b>{_format_number(baseline)} → {_format_number(final)}"
            f"<small>{_format_number(delta, signed=True)} points</small></b>"
            f'<span class="vote">{_h(_verdict_text(state.get("vote")))}</span></div>'
        )
    return "".join(rows) or '<p class="empty">No juror panel in this condition.</p>'


def _timeline(result: Mapping[str, Any]) -> str:
    items: list[str] = []
    for event in _events(result):
        response = _mapping(event.get("response"))
        reply = _public_response(response)
        delta = _number(event.get("belief_delta"))
        action = _mapping(event.get("authored_action"))
        action_text = " · ".join(
            value
            for value in (
                _text(action.get("action")),
                _text(action.get("public_intent")),
                _text(action.get("message") or action.get("question")),
            )
            if value
        )
        provider_model = "/".join(part for part in (_text(event.get("provider")), _text(event.get("model"))) if part)
        protocol_parts = [
            f"{_format_number(event.get('latency_ms'))} ms",
            f"{_integer(event.get('attempts'))} attempt(s)",
            provider_model,
            *[f"task {task_id}" for task_id in _strings(event.get("task_ids"))],
            *[f"warning: {warning}" for warning in _strings(event.get("warnings"))],
        ]
        protocol = " · ".join(part for part in protocol_parts if part)
        items.append(
            f'<details class="timeline-item"><summary><span>{_integer(event.get("sequence")):03d}</span>'
            f"<b>{_h(_label(event.get('sender'), result))} → {_h(_label(event.get('receiver'), result))}</b>"
            f"<em>{_h(event.get('phase', ''))}</em>"
            f"<i>{_format_number(delta, signed=True) if delta is not None else '—'}</i></summary>"
            f'<div class="timeline-content"><p>{_h(event.get("message", ""))}</p>'
            + (f"<small>Authored action</small><blockquote>{_h(action_text)}</blockquote>" if action_text else "")
            + (f"<small>Public reply</small><blockquote>{_h(reply)}</blockquote>" if reply else "")
            + f'<div class="protocol-row">{_h(protocol)}</div></div></details>'
        )
    return "".join(items) or '<p class="empty">No interaction events recorded.</p>'


def _evidence_rows(result: Mapping[str, Any]) -> str:
    evidence = _mapping(_mapping(result.get("case")).get("evidence"))
    if not evidence:
        return '<p class="empty">Evidence index unavailable.</p>'
    return (
        '<ol class="evidence">'
        + "".join(
            f"<li><code>{_h(evidence_id)}</code><span>{_h(text)}</span></li>" for evidence_id, text in evidence.items()
        )
        + "</ol>"
    )


def _legend(result: Mapping[str, Any]) -> str:
    jurors = _jurors(result)
    actor_ids = list(jurors)
    return (
        '<div class="legend">'
        + "".join(
            f'<span style="--series:{_color(juror_id, actor_ids)}"><i></i>{_h(state.get("label", juror_id))}</span>'
            for juror_id, state in jurors.items()
        )
        + "</div>"
    )


def _comparison_card(condition: str, result: Mapping[str, Any] | None) -> str:
    descriptions = {
        "solo": "1 decision-maker · no multi-agent deliberation",
        "independent": "5 jurors · no peer messages",
        "star": "5 jurors · foreperson-mediated peer exchange",
        "mesh": "5 jurors · direct peer routing",
    }
    if not result:
        return (
            '<article class="condition-card missing">'
            f'<div class="eyebrow">{_h(condition)}</div><h3>Not run</h3><p>{_h(descriptions[condition])}</p></article>'
        )
    verdict = _mapping(result.get("verdict"))
    metrics = _mapping(result.get("metrics"))
    href = f"{quote(condition, safe='')}/report.html"
    return (
        f'<a class="condition-card" href="{_h(href)}"><div class="eyebrow">{_h(condition)}</div>'
        f"<h3>{_h(_verdict_text(verdict.get('verdict')))}</h3>"
        f"<p>{_h(descriptions[condition])}</p><b>{_integer(verdict.get('guilty_votes'))}-"
        f"{_integer(verdict.get('not_guilty_votes'))} · mean "
        f"{_format_number(metrics.get('final_mean_guilt_probability'))}</b><em>Open replay →</em></a>"
    )


def _comparison_row(condition: str, result: Mapping[str, Any] | None) -> str:
    if not result:
        return f'<tr><td>{_h(condition)}</td><td colspan="8">Not run</td></tr>'
    verdict = _mapping(result.get("verdict"))
    metrics = _mapping(result.get("metrics"))
    return (
        f"<tr><td>{_h(condition)}</td><td>{_h(_verdict_text(verdict.get('verdict')))}</td>"
        f"<td>{_integer(verdict.get('guilty_votes'))}-{_integer(verdict.get('not_guilty_votes'))}</td>"
        f"<td>{_format_number(metrics.get('final_mean_guilt_probability'))}</td>"
        f"<td>{_format_number(metrics.get('final_polarization'))}</td>"
        f"<td>{_format_number(metrics.get('deliberation_consensus_gain'), signed=True)}</td>"
        f"<td>{_integer(metrics.get('a2a_messages'))}</td><td>{_integer(metrics.get('peer_messages'))}</td>"
        f"<td>{_integer(metrics.get('vote_flips_during_deliberation'))}</td></tr>"
    )


def _treatment_svg(indexed: Mapping[str, Mapping[str, Any]]) -> str:
    nodes: list[str] = []
    for index, condition in enumerate(CONDITIONS):
        x = 110 + index * 220
        result = indexed.get(condition)
        verdict = _verdict_text(_mapping(result.get("verdict")).get("verdict")) if result else "not run"
        node_class = "treatment-node" + (" missing" if not result else "")
        nodes.append(
            f'<g transform="translate({x} 100)"><circle r="43" class="{node_class}"/>'
            f'<text text-anchor="middle" y="-4">{_h(condition)}</text><text text-anchor="middle" y="15" '
            f'class="sub">{_h(verdict)}</text></g>'
        )
    return (
        '<svg class="treatment" viewBox="0 0 880 205" role="img" '
        'aria-label="Solo, independent, star, and mesh communication conditions">'
        '<line x1="110" y1="100" x2="770" y2="100" class="axis"/>'
        + "".join(nodes)
        + '<text x="440" y="190" text-anchor="middle" class="sub">'
        "increasing opportunity for A2A exchange →</text></svg>"
    )


def _actor_positions(actor_ids: list[str], juror_ids: set[str]) -> dict[str, tuple[int, int]]:
    jurors = [actor_id for actor_id in actor_ids if actor_id in juror_ids]
    others = [actor_id for actor_id in actor_ids if actor_id not in juror_ids]
    positions: dict[str, tuple[int, int]] = {}
    for index, actor_id in enumerate(others):
        positions[actor_id] = (_spread(index, len(others), 70, 650), 80 if index % 2 == 0 else 145)
    for index, actor_id in enumerate(jurors):
        positions[actor_id] = (_spread(index, len(jurors), 90, 630), 320)
    return positions


def _spread(index: int, count: int, low: int, high: int) -> int:
    if count <= 1:
        return (low + high) // 2
    return round(low + index * (high - low) / (count - 1))


def _events(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return sorted(_list_of_mappings(result.get("events")), key=lambda event: _integer(event.get("sequence")))


def _jurors(result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(key): _mapping(value) for key, value in _mapping(result.get("jurors")).items()}


def _history_value(history: list[Mapping[str, Any]], predicate: Any) -> float | None:
    value: float | None = None
    for point in sorted(history, key=lambda item: _integer(item.get("sequence"))):
        if predicate(_integer(point.get("sequence"))):
            candidate = _number(point.get("guilt_probability"))
            if candidate is not None:
                value = candidate
    return value


def _history_snapshot(
    history: list[Mapping[str, Any]],
    predicate: Any,
) -> Mapping[str, Any] | None:
    snapshot: Mapping[str, Any] | None = None
    for point in sorted(history, key=lambda item: _integer(item.get("sequence"))):
        if predicate(_integer(point.get("sequence"))):
            snapshot = point
    return snapshot


def _event_vote_change(
    event: Mapping[str, Any],
    result: Mapping[str, Any],
) -> tuple[str, str] | None:
    juror = _jurors(result).get(_text(event.get("receiver")))
    if not juror:
        return None
    event_id = _text(event.get("event_id"))
    sequence = _integer(event.get("sequence"))
    previous_vote = _normalize_vote(juror.get("baseline_vote"))
    for point in sorted(
        _list_of_mappings(juror.get("history")),
        key=lambda item: _integer(item.get("sequence")),
    ):
        point_vote = _normalize_vote(point.get("vote"))
        is_event = bool(event_id and _text(point.get("source_event_id")) == event_id)
        is_event = is_event or (not event_id and _integer(point.get("sequence")) == sequence)
        if is_event:
            if previous_vote and point_vote and previous_vote != point_vote:
                return previous_vote, point_vote
            return None
        if point_vote:
            previous_vote = point_vote
    return None


def _juror_baseline(state: Mapping[str, Any]) -> float | None:
    value = _number(state.get("baseline_guilt_probability"))
    if value is not None:
        return value
    for point in _list_of_mappings(state.get("history")):
        value = _number(point.get("guilt_probability"))
        if value is not None:
            return value
    return None


def _is_peer_event(event: Mapping[str, Any]) -> bool:
    sender = _text(event.get("sender"))
    receiver = _text(event.get("receiver"))
    return sender.startswith("juror_") and receiver.startswith("juror_")


def _public_response(response: Mapping[str, Any]) -> str:
    values = [
        _text(response.get("statement")),
        _text(response.get("public_reason")),
        _text(response.get("public_reply")),
    ]
    return "\n\n".join(dict.fromkeys(value for value in values if value))


def _label(agent_id: Any, result: Mapping[str, Any]) -> str:
    key = _text(agent_id)
    profile = _participant_profile(key, result)
    if profile:
        return _text(profile.get("label")) or key
    state = _jurors(result).get(key)
    return _text(state.get("label")) if state else key.replace("_", " ").title()


def _actor_role(agent_id: str, result: Mapping[str, Any]) -> str:
    profile = _participant_profile(agent_id, result)
    if profile:
        style = _text(profile.get("style"))
        role = _text(profile.get("role"))
        return f"{role} · {style}" if role and style else role or style or "Agent"
    state = _jurors(result).get(agent_id)
    return _text(state.get("style")) if state else "Agent"


def _actor_age(agent_id: str, result: Mapping[str, Any]) -> int | None:
    value = _participant_profile(agent_id, result).get("age")
    return _integer(value) if value is not None else None


def _actor_gender(agent_id: str, result: Mapping[str, Any]) -> str:
    return _text(_participant_profile(agent_id, result).get("gender"))


def _participant_profile(agent_id: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    profile: dict[str, Any] = {}
    try:
        profile.update(public_participant_profile(agent_id))
    except KeyError:
        pass
    state = _jurors(result).get(agent_id)
    if state:
        profile.update(state)
    recorded = _mapping(_mapping(result.get("participants")).get(agent_id))
    if recorded:
        profile.update(recorded)
    return profile


def _short_label(agent_id: str, result: Mapping[str, Any]) -> str:
    label = _label(agent_id, result)
    return _first_name(label) if agent_id.startswith("juror_") else label.split()[-1]


def _first_name(value: Any) -> str:
    parts = _text(value).split()
    if not parts:
        return "Agent"
    if parts[0].rstrip(".") in {"Dr", "Judge"} and len(parts) > 1:
        return parts[1]
    return parts[0]


def _color(actor_id: str, actor_ids: list[str]) -> str:
    try:
        index = actor_ids.index(actor_id)
    except ValueError:
        index = 0
    return COLORS[index % len(COLORS)]


def _verdict_text(value: Any) -> str:
    normalized = _text(value).lower().replace("-", "_").replace(" ", "_")
    return (normalized or "unavailable").replace("_", " ")


def _normalize_vote(value: Any) -> str:
    normalized = _text(value).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in {"guilty", "not_guilty"} else ""


def _population_sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _metric(label: str, value: str, note: str) -> str:
    return f'<div class="metric"><span>{_h(label)}</span><strong>{_h(value)}</strong><small>{_h(note)}</small></div>'


def _format_number(value: Any, *, signed: bool = False) -> str:
    numeric = _number(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:+.2f}" if signed else f"{numeric:.2f}"


def _integer(value: Any) -> int:
    numeric = _number(value)
    return int(numeric) if numeric is not None else 0


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


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
<title>{_h(title)}</title><style>{_CSS}</style></head><body>{body}
<footer>Generated by ProtoLink · fictional AI Liability Tribunal research fixture</footer>
{f"<script>{script}</script>" if script else ""}</body></html>"""


_REPLAY_SCRIPT = r"""
(() => {
  const dataNode = document.getElementById("replay-data");
  if (!dataNode) return;
  const data = JSON.parse(dataNode.textContent);
  const allFrames = data.frames || [];
  let indices = allFrames.map((_, index) => index);
  let cursor = 0;
  let timer = null;
  const $ = (id) => document.getElementById(id);
  const svgNS = "http://www.w3.org/2000/svg";
  const elements = {
    svg: $("replay-network"), kicker: $("replay-kicker"), route: $("replay-route"),
    people: $("replay-people"), transcript: $("replay-transcript"),
    message: $("replay-message"), action: $("replay-action"), actionWrap: $("action-wrap"),
    reply: $("replay-reply"), replyWrap: $("reply-wrap"), change: $("replay-change"),
    protocol: $("replay-protocol"), bars: $("replay-bars"), status: $("replay-status"),
    prev: $("replay-prev"), play: $("replay-play"), next: $("replay-next"),
    scrub: $("replay-scrub"), count: $("replay-count"), peer: $("replay-peer"), speed: $("replay-speed")
  };
  const svgElement = (name, attributes = {}) => {
    const node = document.createElementNS(svgNS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  };
  const appendSvgText = (parent, text, attributes) => {
    const node = svgElement("text", attributes);
    node.textContent = text;
    parent.appendChild(node);
  };
  const actor = (id) => data.actors[id] || {label: id, role: "Agent", x: 360, y: 200, color: "#b3bfce"};
  const actorDetails = (item) => [
    item.role,
    Number.isFinite(item.age) ? `age ${item.age}` : "",
    item.gender
  ].filter(Boolean).join(" · ");
  function renderNetwork(frame, absoluteIndex) {
    elements.svg.replaceChildren();
    const previous = allFrames.slice(Math.max(0, absoluteIndex - 3), absoluteIndex);
    previous.forEach((item) => {
      const start = actor(item.sender), end = actor(item.receiver);
      elements.svg.appendChild(svgElement("line", {
        x1: start.x, y1: start.y, x2: end.x, y2: end.y, class: "replay-edge trail"
      }));
    });
    const start = actor(frame.sender), end = actor(frame.receiver);
    elements.svg.appendChild(svgElement("line", {
      x1: start.x, y1: start.y, x2: end.x, y2: end.y, class: "replay-edge active"
    }));
    Object.values(data.actors).forEach((item) => {
      const group = svgElement("g", {transform: `translate(${item.x} ${item.y})`, class: "replay-actor"});
      const circle = svgElement("circle", {r: item.id === frame.sender || item.id === frame.receiver ? 30 : 24});
      circle.setAttribute("style", `--actor:${item.color}`);
      group.appendChild(circle);
      appendSvgText(group, item.label.split(" ")[0], {"text-anchor": "middle", y: 4});
      const title = svgElement("title");
      title.textContent = `${item.label} · ${actorDetails(item)}`;
      group.appendChild(title);
      elements.svg.appendChild(group);
    });
  }
  function renderBars(states) {
    elements.bars.replaceChildren();
    Object.values(states || {}).forEach((state) => {
      const row = document.createElement("div");
      row.className = "replay-bar";
      const label = document.createElement("span");
      label.textContent = state.label;
      const track = document.createElement("i");
      const fill = document.createElement("b");
      const probability = Number.isFinite(state.guilt_probability) ? state.guilt_probability : 0;
      fill.style.width = `${Math.max(0, Math.min(100, probability))}%`;
      track.appendChild(fill);
      const value = document.createElement("strong");
      value.textContent = Number.isFinite(state.guilt_probability) ? state.guilt_probability.toFixed(1) : "N/A";
      row.append(label, track, value);
      elements.bars.appendChild(row);
    });
  }
  function render() {
    if (!indices.length) {
      elements.status.textContent = "No replayable messages.";
      elements.kicker.textContent = "FILTERED REPLAY";
      elements.route.textContent = "No peer messages in this condition";
      elements.people.textContent = "The current filter has no matching sender or receiver.";
      elements.message.textContent = "Turn off “Peer only” to replay the public tribunal record.";
      elements.actionWrap.hidden = true;
      elements.replyWrap.hidden = true;
      elements.change.textContent = "No decision-register update";
      elements.protocol.textContent = "";
      elements.count.textContent = "0 / 0";
      elements.scrub.max = 0;
      elements.scrub.value = 0;
      elements.prev.disabled = true;
      elements.next.disabled = true;
      elements.play.disabled = true;
      elements.transcript.scrollTop = 0;
      return;
    }
    elements.play.disabled = false;
    cursor = Math.max(0, Math.min(cursor, indices.length - 1));
    const absoluteIndex = indices[cursor];
    const frame = allFrames[absoluteIndex];
    const source = actor(frame.sender), target = actor(frame.receiver);
    elements.kicker.textContent = `A2A #${String(frame.sequence).padStart(3, "0")} · ${frame.phase} · ${frame.kind}`;
    elements.route.textContent = `${source.label} → ${target.label}`;
    elements.people.textContent = `${actorDetails(source)} → ${actorDetails(target)}`;
    elements.message.textContent = frame.message || "No public message text.";
    const action = frame.authored_action;
    elements.actionWrap.hidden = !action;
    elements.action.textContent = action ?
      [
        action.action,
        action.public_intent,
        action.message,
        action.target_id && `target: ${actor(action.target_id).label}`
      ]
        .filter(Boolean).join(" · ") : "";
    elements.replyWrap.hidden = !frame.public_response;
    elements.reply.textContent = frame.public_response || "";
    if (frame.change && Number.isFinite(frame.change.after)) {
      const before = Number.isFinite(frame.change.before) ? frame.change.before.toFixed(2) : "N/A";
      const delta = Number.isFinite(frame.change.delta) ?
        `${frame.change.delta >= 0 ? "+" : ""}${frame.change.delta.toFixed(2)}` : "N/A";
      const voteChange = frame.change.vote_changed ?
        ` · vote ${String(frame.change.vote_before).replace("_", " ")} → ` +
        String(frame.change.vote_after).replace("_", " ") : "";
      elements.change.textContent = `${actor(frame.change.juror_id).label}: ${before} → ` +
        `${frame.change.after.toFixed(2)} (${delta})${voteChange}`;
    } else {
      elements.change.textContent = "No decision-register update";
    }
    elements.protocol.textContent = [
      frame.provider && frame.model ? `${frame.provider}/${frame.model}` : "",
      Number.isFinite(frame.latency_ms) ? `${frame.latency_ms.toFixed(1)} ms` : "",
      `${frame.attempts || 0} attempt(s)`,
      `${frame.tokens || 0} estimated tokens`,
      ...(frame.evidence_ids || []).map((id) => `evidence ${id}`),
      ...(frame.task_ids || []).map((id) => `task ${id}`),
      ...(frame.warnings || []).map((warning) => `warning: ${warning}`)
    ].filter(Boolean).join(" · ");
    elements.count.textContent = `${cursor + 1} / ${indices.length}`;
    elements.scrub.max = Math.max(0, indices.length - 1);
    elements.scrub.value = cursor;
    elements.prev.disabled = cursor === 0;
    elements.next.disabled = cursor === indices.length - 1;
    elements.status.textContent =
      `${source.label} sent message ${cursor + 1} of ${indices.length} to ${target.label}. ` +
      elements.change.textContent;
    elements.transcript.scrollTop = 0;
    renderNetwork(frame, absoluteIndex);
    renderBars(frame.juror_states);
  }
  function stop() {
    if (timer) window.clearInterval(timer);
    timer = null;
    elements.play.textContent = "Play";
    elements.play.setAttribute("aria-label", "Play replay");
  }
  function play() {
    if (timer) { stop(); return; }
    if (cursor >= indices.length - 1) cursor = 0;
    elements.play.textContent = "Pause";
    elements.play.setAttribute("aria-label", "Pause replay");
    timer = window.setInterval(() => {
      if (cursor >= indices.length - 1) { stop(); return; }
      cursor += 1;
      render();
    }, Number(elements.speed.value));
  }
  elements.prev?.addEventListener("click", () => { stop(); cursor -= 1; render(); });
  elements.next?.addEventListener("click", () => { stop(); cursor += 1; render(); });
  elements.play?.addEventListener("click", play);
  elements.scrub?.addEventListener("input", () => { stop(); cursor = Number(elements.scrub.value); render(); });
  elements.speed?.addEventListener("change", () => { if (timer) { stop(); play(); } });
  elements.peer?.addEventListener("change", () => {
    stop();
    indices = allFrames.map((frame, index) => frame.peer || !elements.peer.checked ? index : -1)
      .filter((index) => index >= 0);
    cursor = 0;
    render();
  });
  document.querySelector("[data-jump-turning]")?.addEventListener("click", () => {
    const found = indices.indexOf(data.turning_index || 0);
    cursor = found >= 0 ? found : 0;
    render();
  });
  document.addEventListener("keydown", (event) => {
    if (event.target?.matches("input, select, textarea, button") ||
        event.target?.closest?.("#replay-transcript")) return;
    if (event.key === "ArrowLeft") { stop(); cursor -= 1; render(); }
    if (event.key === "ArrowRight") { stop(); cursor += 1; render(); }
    if (event.key === " ") { event.preventDefault(); play(); }
  });
  render();
})();
"""


_CSS = """
:root {
  color-scheme: dark;
  --bg: #0d1118;
  --surface: #171d28;
  --surface2: #202837;
  --ink: #edf2f8;
  --muted: #9daabd;
  --line: #303a4c;
  --gold: #edbd6c;
  --up: #6bd0a8;
  --down: #ef8292;
  --radius: 18px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: radial-gradient(circle at 12% 0, #222c43 0, transparent 35rem), var(--bg);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  line-height: 1.5;
}
main { width: min(1200px, calc(100% - 30px)); margin: auto; padding: 50px 0 80px; }
h1, h2, h3, p { margin-top: 0; }
h1 {
  max-width: 900px;
  margin: 6px 0 15px;
  font: 400 clamp(2.5rem, 6vw, 5.4rem) / .98 Georgia, serif;
  letter-spacing: -.045em;
}
h2 { margin: 3px 0; font-size: 1.35rem; }
h3 { margin: 7px 0; }
a { color: inherit; }
.eyebrow {
  color: var(--gold);
  font-size: .68rem;
  font-weight: 800;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.hero {
  display: grid;
  grid-template-columns: 1fr 330px;
  gap: 38px;
  align-items: end;
  margin-bottom: 28px;
}
.comparison-hero { grid-template-columns: 1fr; }
.outcome { max-width: 800px; font-size: 1.15rem; }
.lede, .section-head p, .caveat p { color: var(--muted); }
.chips, .hero-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.chips span, .hero-actions a, .control-status {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 11px;
  font-size: .75rem;
  text-decoration: none;
}
.hero-actions a:first-child { border-color: var(--gold); }
.verdict, .panel, .turning-card, .condition-card, .metric {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(23, 29, 40, .94);
}
.verdict {
  display: flex;
  min-height: 185px;
  flex-direction: column;
  justify-content: end;
  padding: 24px;
  box-shadow: inset 0 3px var(--gold);
}
.verdict span, .verdict small { color: var(--muted); font-size: .7rem; }
.verdict strong { font: 400 2.3rem Georgia, serif; text-transform: capitalize; }
.verdict b { margin: 5px 0; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 11px; }
.metric { padding: 17px; }
.metric span, .metric small { display: block; color: var(--muted); font-size: .73rem; }
.metric strong { display: block; font-size: 1.55rem; }
.panel { padding: 24px; margin-top: 18px; }
.section-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 17px;
}
.section-head p { max-width: 470px; margin-bottom: 0; font-size: .82rem; }
.replay-layout {
  --replay-block-size: 32rem;
  display: grid;
  grid-template-columns: 1.2fr .8fr;
  align-items: stretch;
  gap: 16px;
}
@supports (height: 1svh) {
  .replay-layout { --replay-block-size: clamp(28rem, 58svh, 32rem); }
}
.replay-stage, .message-card {
  min-width: 0;
  height: var(--replay-block-size);
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--surface2);
}
.replay-stage { overflow: hidden; }
#replay-network { display: block; width: 100%; height: 100%; min-height: 0; }
.replay-edge { stroke: var(--muted); stroke-width: 2; }
.replay-edge.trail { opacity: .18; }
.replay-edge.active {
  stroke: var(--gold);
  stroke-width: 4;
  stroke-dasharray: 10 7;
  animation: dash 1.2s linear infinite;
}
.replay-actor circle {
  fill: var(--surface);
  stroke: var(--actor);
  stroke-width: 3;
  transition: r .2s;
}
.replay-actor text { fill: var(--ink); font-size: 10px; }
.message-card {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  overflow: hidden;
  padding: 20px;
}
.message-card h3 { margin-bottom: 5px; overflow-wrap: anywhere; }
.message-people {
  margin: 0;
  color: var(--muted);
  font-size: .7rem;
  overflow-wrap: anywhere;
}
.message-scroll {
  min-height: 0;
  padding-right: 7px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.message-kicker, .message-block small {
  color: var(--gold);
  font-size: .68rem;
  letter-spacing: .1em;
}
.message-block {
  margin: 14px 0;
  padding: 13px;
  border-left: 2px solid var(--gold);
  background: rgba(13, 17, 24, .4);
}
.message-block p { margin: 5px 0 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.register-change {
  padding: 12px;
  border-radius: 10px;
  background: rgba(107, 208, 168, .1);
  font-variant-numeric: tabular-nums;
}
.protocol-row { margin-top: 10px; color: var(--muted); font-size: .7rem; overflow-wrap: anywhere; }
.juror-bars {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
  gap: 8px;
  margin-top: 13px;
}
.replay-bar { display: grid; grid-template-columns: 1fr auto; gap: 5px; font-size: .7rem; }
.replay-bar i {
  position: relative;
  grid-column: 1 / -1;
  height: 7px;
  overflow: hidden;
  border-radius: 8px;
  background: #30394a;
}
.replay-bar b { display: block; height: 100%; background: var(--up); }
.replay-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 9px;
  margin-top: 15px;
}
.replay-controls button, .replay-controls select {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 7px 12px;
  background: transparent;
  color: var(--ink);
}
.replay-controls button:hover { border-color: var(--gold); }
button:focus-visible, select:focus-visible, input:focus-visible, .message-scroll:focus-visible,
.hero-actions a:focus-visible {
  outline: 2px solid var(--gold);
  outline-offset: 2px;
}
.scrubber { display: flex; flex: 1; align-items: center; gap: 7px; }
.scrubber input { width: 100%; }
.turning-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 13px;
  margin-top: 18px;
}
.turning-card { padding: 20px; }
.turning-card p { margin-bottom: 0; color: var(--muted); }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.chart-wrap, .table-wrap { overflow-x: auto; }
.trajectory { width: 100%; min-width: 720px; }
.trajectory text { fill: var(--muted); font-size: 10px; }
.trajectory .gridline { stroke: var(--line); }
.trajectory polyline { fill: none; stroke: var(--series); stroke-width: 2.6; }
.trajectory circle { fill: var(--surface); stroke: var(--series); stroke-width: 2; }
.trajectory .end-label { fill: var(--ink); }
.legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; }
.legend span { color: var(--muted); font-size: .75rem; }
.legend i, .jury-row i {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 5px;
  border-radius: 50%;
  background: var(--series);
}
.network { width: 100%; }
.network-edge { stroke: var(--muted); opacity: .26; }
.network-edge.peer { stroke: var(--gold); stroke-width: 2; opacity: .72; }
.network-node circle { fill: var(--surface2); stroke: var(--series); stroke-width: 2; }
.network-node text { fill: var(--ink); font-size: 8px; }
.jury-row {
  display: grid;
  grid-template-columns: 14px 1fr auto auto;
  gap: 9px;
  align-items: center;
  padding: 11px 0;
  border-bottom: 1px solid var(--line);
}
.jury-row small { display: block; color: var(--muted); font-size: .68rem; }
.jury-row b { text-align: right; }
.vote {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 7px;
  font-size: .67rem;
}
table { width: 100%; border-collapse: collapse; font-size: .8rem; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 10px;
  text-align: left;
  white-space: nowrap;
}
th { color: var(--muted); font-size: .65rem; text-transform: uppercase; }
.timeline-item { border-top: 1px solid var(--line); }
.timeline-item summary {
  display: grid;
  grid-template-columns: 45px 1fr 120px 55px;
  gap: 10px;
  padding: 13px 2px;
  cursor: pointer;
}
.timeline-item summary em, .timeline-item summary i { color: var(--muted); font-size: .72rem; }
.timeline-content { margin: 0 0 15px 55px; color: var(--muted); }
blockquote {
  margin: 8px 0;
  padding: 10px 13px;
  border-left: 2px solid var(--gold);
  background: var(--surface2);
  color: var(--ink);
}
.evidence { padding: 0; list-style: none; }
.evidence li {
  display: grid;
  grid-template-columns: 38px 1fr;
  gap: 9px;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
}
.evidence code, .caveat code { color: var(--gold); overflow-wrap: anywhere; }
.treatment-ladder { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.condition-card {
  display: flex;
  min-height: 195px;
  flex-direction: column;
  padding: 20px;
  text-decoration: none;
}
.condition-card h3 {
  margin-top: auto;
  font: 400 1.8rem Georgia, serif;
  text-transform: capitalize;
}
.condition-card p { color: var(--muted); font-size: .78rem; }
.condition-card em { margin-top: 8px; color: var(--gold); font-style: normal; }
.condition-card.missing { opacity: .58; }
.treatment { width: 100%; }
.treatment .axis { stroke: var(--line); }
.treatment-node { fill: var(--surface2); stroke: var(--gold); stroke-width: 2; }
.treatment-node.missing { stroke: var(--muted); stroke-dasharray: 4 4; }
.treatment text { fill: var(--ink); font-size: 12px; }
.treatment .sub { fill: var(--muted); font-size: 9px; }
.control-status { display: inline-block; margin-top: 12px; }
.control-status.warn { border-color: var(--down); color: var(--down); }
.empty, .notice { color: var(--muted); }
footer {
  padding: 28px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  text-align: center;
  font-size: .7rem;
}
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
@keyframes dash { to { stroke-dashoffset: -34; } }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .replay-edge.active { animation: none; }
}
@media (max-width: 850px) {
  .hero, .replay-layout, .split { grid-template-columns: 1fr; }
  .replay-stage {
    height: auto;
    aspect-ratio: 720 / 410;
  }
  .message-card { height: 32rem; }
  @supports (height: 1svh) {
    .message-card { height: clamp(24rem, 65svh, 32rem); }
  }
  .metric-grid, .treatment-ladder { grid-template-columns: repeat(2, 1fr); }
  .turning-grid { grid-template-columns: 1fr; }
  .section-head { align-items: start; flex-direction: column; }
}
@media (max-width: 540px) {
  main { width: calc(100% - 18px); padding-top: 28px; }
  .metric-grid, .treatment-ladder { grid-template-columns: 1fr; }
  .panel { padding: 16px; }
  .timeline-item summary { grid-template-columns: 38px 1fr auto; }
  .timeline-item summary em { display: none; }
  .timeline-content { margin-left: 40px; }
  .jury-row { grid-template-columns: 14px 1fr auto; }
  .jury-row .vote { grid-column: 2 / -1; width: max-content; }
}
"""
