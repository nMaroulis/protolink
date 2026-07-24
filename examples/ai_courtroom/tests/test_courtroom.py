from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import pytest

from examples.ai_courtroom.compare import build_comparison_markdown
from examples.ai_courtroom.courtroom.case_data import JUROR_PROFILES, juror_system_prompt
from examples.ai_courtroom.courtroom.reference_llm import (
    REQUEST_END,
    REQUEST_START,
    ReferenceCourtroomLLM,
)
from examples.ai_courtroom.courtroom.schemas import (
    DecisionRecord,
    DeliberationAction,
    ResponseValidationError,
    extract_json_object,
)
from examples.ai_courtroom.run import _resolve_juror_backend, run_condition


def _reference_args() -> argparse.Namespace:
    return argparse.Namespace(
        provider="reference",
        model=None,
        base_url=None,
        juror_provider=None,
        juror_model=None,
        juror_base_url=None,
        temperature=0.2,
        seed=7,
        evidence_order="standard",
        rounds=1,
        max_attempts=2,
        run_id="pytest-ghost-lane-four",
    )


def test_extract_json_object_accepts_fenced_provider_text() -> None:
    payload = extract_json_object('Result:\n```json\n{"guilt_probability": 41}\n```')
    assert payload["guilt_probability"] == 41


def test_decision_vote_is_authored_and_evidence_is_grounded() -> None:
    record, warnings = DecisionRecord.from_payload(
        {
            "guilt_probability": 0.63,
            "vote": "not_guilty",
            "confidence": 80,
            "evidence_ids": ["E1", "E99"],
            "top_factors": ["E1"],
            "uncertainty": "The release decision remains disputed.",
            "public_reason": "The physical failure is clearer than the organizational attribution.",
            "public_reply": "I still need proof of who accepted the risk.",
            "stated_influences": [],
        }
    )
    assert record.guilt_probability == 63.0
    assert record.vote == "not_guilty"
    assert record.confidence == 0.8
    assert record.evidence_ids == ["E1"]
    assert record.invalid_evidence_ids == ["E99"]
    assert any("Unsupported evidence id" in warning for warning in warnings)


def test_deliberation_action_must_be_authored_inside_topology() -> None:
    action, warnings = DeliberationAction.from_payload(
        {
            "action": "ask",
            "target_id": "juror_ruben",
            "message": "Who controlled the C-91 deployment safeguard?",
            "evidence_ids": ["E3"],
            "public_intent": "Clarify organizational control.",
        },
        sender_id="juror_anika",
        allowed_target_ids=["juror_ruben", "juror_sofia"],
    )
    assert action.action == "ask_question"
    assert action.target_id == "juror_ruben"
    assert any("normalized" in warning for warning in warnings)

    with pytest.raises(ResponseValidationError):
        DeliberationAction.from_payload(
            {
                "action": "challenge_claim",
                "target_id": "juror_anika",
                "message": "Self-targeting should fail.",
                "evidence_ids": [],
                "public_intent": "Invalid.",
            },
            sender_id="juror_anika",
            allowed_target_ids=["juror_anika", "juror_ruben"],
        )


def test_juror_identity_prompts_do_not_assign_numeric_opinions() -> None:
    for juror_id in JUROR_PROFILES:
        prompt = juror_system_prompt(juror_id)
        assert not re.search(r"\b\d+(?:\.\d+)?\s*/\s*100\b", prompt)
        assert "starting register" not in prompt.lower()
        assert "communication_goal" not in prompt
        assert "reference_prior" not in prompt


def test_reference_fixture_changes_its_authored_move_across_rounds() -> None:
    model = ReferenceCourtroomLLM(role="juror_anika", seed=7)

    def plan(round_index: int) -> dict[str, object]:
        request = {
            "kind": "deliberation_plan",
            "speaker_id": "juror_anika",
            "round_index": round_index,
            "request_id": f"mesh_round_{round_index + 1}:juror_anika",
            "allowed_target_ids": ["juror_evelyn", "juror_malik", "juror_ruben", "juror_sofia"],
        }
        raw = model.mock_call(
            f"{REQUEST_START}\n{json.dumps(request)}\n{REQUEST_END}",
            "",
        )
        return json.loads(raw["content"])

    first = plan(0)
    second = plan(1)
    assert first["message"] != second["message"]
    assert first["action"] != second["action"]


def test_mixed_juror_provider_does_not_inherit_another_backends_model() -> None:
    args = argparse.Namespace(
        provider="openai",
        model="gpt-example",
        base_url="https://openai.example/v1",
        juror_provider="anthropic",
        juror_model=None,
        juror_base_url=None,
    )
    assert _resolve_juror_backend(args) == ("anthropic", None, None)

    args.juror_model = "claude-example"
    args.juror_base_url = "https://anthropic.example"
    assert _resolve_juror_backend(args) == (
        "anthropic",
        "claude-example",
        "https://anthropic.example",
    )


def test_reference_mesh_uses_authored_direct_a2a_and_clean_reruns(tmp_path: Path) -> None:
    args = _reference_args()
    mesh_dir = tmp_path / "mesh"
    result = asyncio.run(run_condition(args, "mesh", mesh_dir))

    assert result["schema_version"] == "2.0"
    assert result["run"]["condition"] == "mesh"
    assert result["metrics"]["a2a_messages"] > 40
    assert result["metrics"]["peer_messages"] == 5
    assert result["metrics"]["accepted_first_attempt_rate"] == 1.0
    assert result["metrics"]["protocol_clean_first_attempt_rate"] == 1.0
    assert result["metrics"]["blocked_ballot_revision_attempts"] == 0
    assert result["run"]["temperature"] == 0.2
    assert result["run"]["max_attempts"] == 2
    assert len(result["jurors"]) == 5
    assert len(result["record_hash"]) == 64
    assert len(result["pre_deliberation_snapshot_hash"]) == 64

    plans = [event for event in result["events"] if event["kind"] == "deliberation_plan"]
    peer_events = [event for event in result["events"] if event["kind"] == "peer_message"]
    assert len(plans) == len(peer_events) == 5
    assert all(event["authored_action"] for event in peer_events)
    assert all(event["reply_to_event_id"] for event in peer_events)
    assert all(
        set(event["authored_action"]).isdisjoint({"speaker_probability", "speaker_confidence", "speaker_vote"})
        for event in peer_events
    )
    assert all(event["belief_delta"] == 0.0 for event in result["events"] if event["kind"] == "private_ballot")
    assert all(event["task_ids"] for event in result["events"])
    assert (mesh_dir / "result.json").exists()
    assert (mesh_dir / "summary.json").exists()
    assert (mesh_dir / "report.html").exists()
    report = (mesh_dir / "report.html").read_text(encoding="utf-8")
    assert 'id="replay-data"' in report
    assert "Replay" in report

    trace_path = mesh_dir / "traces.jsonl"
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "integrity alert identifying the C-91 mismatch" not in trace_text
    assert "speaker_probability" not in trace_text
    assert "speaker_confidence" not in trace_text
    assert "speaker_vote" not in trace_text
    first_trace_count = len(trace_text.splitlines())
    assert first_trace_count == result["metrics"]["a2a_calls_including_repairs"]
    asyncio.run(run_condition(args, "mesh", mesh_dir))
    second_trace_count = len(trace_path.read_text(encoding="utf-8").splitlines())
    assert second_trace_count == first_trace_count


def test_reference_conditions_share_record_and_solo_is_nullable(tmp_path: Path) -> None:
    args = _reference_args()
    independent = asyncio.run(run_condition(args, "independent", tmp_path / "independent"))
    star = asyncio.run(run_condition(args, "star", tmp_path / "star"))
    mesh = asyncio.run(run_condition(args, "mesh", tmp_path / "mesh"))
    solo = asyncio.run(run_condition(args, "solo", tmp_path / "solo"))

    assert independent["record_hash"] == star["record_hash"] == mesh["record_hash"] == solo["record_hash"]
    assert independent["verdict"]["verdict"] == "not_guilty"
    assert (independent["verdict"]["guilty_votes"], independent["verdict"]["not_guilty_votes"]) == (2, 3)
    assert independent["metrics"]["peer_messages"] == 0
    assert star["verdict"]["verdict"] == "not_guilty"
    assert (star["verdict"]["guilty_votes"], star["verdict"]["not_guilty_votes"]) == (2, 3)
    assert star["metrics"]["peer_messages"] == 5
    assert star["metrics"]["vote_flips_during_deliberation"] == 0
    assert mesh["verdict"]["verdict"] == "guilty"
    assert (mesh["verdict"]["guilty_votes"], mesh["verdict"]["not_guilty_votes"]) == (3, 2)
    assert mesh["metrics"]["vote_flips_during_deliberation"] == 1
    assert mesh["metrics"]["peer_messages"] == 5
    assert len(solo["jurors"]) == 1
    assert solo["metrics"]["peer_messages"] == 0
    assert solo["metrics"]["final_polarization"] is None
    assert solo["metrics"]["deliberation_consensus_gain"] is None
    assert solo["verdict"]["guilty_votes"] + solo["verdict"]["not_guilty_votes"] == 1

    summary_records: list[tuple[Path, dict[str, object]]] = []
    for condition in ("solo", "independent", "star", "mesh"):
        path = tmp_path / condition / "summary.json"
        summary_records.append((path, json.loads(path.read_text(encoding="utf-8"))))
    comparison = build_comparison_markdown(summary_records)
    assert "AI Liability Tribunal" in comparison
    assert "Guilty verdict rate" in comparison
    assert "N/A" in comparison
