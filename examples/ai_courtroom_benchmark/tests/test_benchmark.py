from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from examples.ai_courtroom.courtroom.case_data import CASE as ORIGINAL_CASE
from examples.ai_courtroom.run import CONDITIONS as ORIGINAL_CONDITIONS
from examples.ai_courtroom.run import run_condition as run_original_condition
from examples.ai_courtroom_benchmark import run as benchmark_run_module
from examples.ai_courtroom_benchmark.courtroom import benchmark as benchmark_module
from examples.ai_courtroom_benchmark.courtroom import providers
from examples.ai_courtroom_benchmark.courtroom.benchmark import (
    BenchmarkSettings,
    ModelSpec,
    _aggregate_candidate_metrics,
    _fairness_audit,
    run_benchmark,
)
from examples.ai_courtroom_benchmark.courtroom.config import CaseConfig, load_case_config
from examples.ai_courtroom_benchmark.courtroom.reference_llm import (
    REQUEST_END,
    REQUEST_START,
    ReferenceBenchmarkLLM,
)
from examples.ai_courtroom_benchmark.courtroom.schemas import (
    AdvocacyStatement,
    AssessmentRecord,
    ResponseValidationError,
    recover_plain_text_statement,
)
from examples.ai_courtroom_benchmark.courtroom.simulation import AdvocacyTrial
from examples.ai_courtroom_benchmark.run import _validate_args, async_main, build_parser
from protolink.llms import MockLLM

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
C91_CASE_PATH = EXAMPLE_ROOT / "cases" / "c91_incident.json"
TEMPLATE_CASE_PATH = EXAMPLE_ROOT / "cases" / "template.json"


def _reference_specs() -> tuple[ModelSpec, ModelSpec, ModelSpec]:
    return (
        ModelSpec(
            id="candidate_alpha",
            label="Alpha candidate label",
            provider="reference",
            model="reference-evidence",
        ),
        ModelSpec(
            id="candidate_beta",
            label="Beta candidate label",
            provider="reference",
            model="reference-narrative",
        ),
        ModelSpec(
            id="control",
            label="Fixed control panel",
            provider="reference",
            model="reference-evidence",
        ),
    )


def _settings(
    *,
    benchmark_id: str,
    mode: str = "paired",
    model_a_side: str = "victim_family",
    replicates: int = 1,
) -> BenchmarkSettings:
    return BenchmarkSettings(
        benchmark_id=benchmark_id,
        mode=mode,
        model_a_side=model_a_side,
        seed=7,
        replicates=replicates,
        temperature=0.0,
        max_attempts=3,
        action_parse_attempts=3,
        agent_verbosity=0,
    )


def _run_reference_benchmark(
    output_root: Path,
    *,
    case: CaseConfig | None = None,
    benchmark_id: str = "pytest-advocacy-benchmark",
    mode: str = "paired",
    model_a_side: str = "victim_family",
    replicates: int = 1,
) -> dict[str, Any]:
    candidate_a, candidate_b, control = _reference_specs()
    return asyncio.run(
        run_benchmark(
            case=case or load_case_config(C91_CASE_PATH),
            candidate_a=candidate_a,
            candidate_b=candidate_b,
            control=control,
            settings=_settings(
                benchmark_id=benchmark_id,
                mode=mode,
                model_a_side=model_a_side,
                replicates=replicates,
            ),
            output_root=output_root,
        )
    )


@pytest.fixture(scope="module")
def paired_run(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    output_root = tmp_path_factory.mktemp("courtroom-benchmark")
    benchmark = _run_reference_benchmark(output_root)
    return SimpleNamespace(
        root=output_root,
        case=load_case_config(C91_CASE_PATH),
        benchmark=benchmark,
    )


def _generic_case_payload() -> dict[str, Any]:
    payload = json.loads(TEMPLATE_CASE_PATH.read_text(encoding="utf-8"))
    payload["id"] = "generic-approval-case"
    payload["decision"].update(
        {
            "probability_label": "probability that approval is warranted",
            "positive_vote": "approve",
            "negative_vote": "send_back",
            "tie_vote": "send_back",
        }
    )
    payload["sides"][0]["target_vote"] = "approve"
    payload["sides"][1]["target_vote"] = "send_back"
    payload["evidence"][0]["id"] = "DOC_A"
    payload["evidence"][1]["id"] = "DOC_B"
    payload["reference_fixture"]["evidence_signals"] = {
        "DOC_A": 3.0,
        "DOC_B": -2.0,
    }
    return payload


def test_case_config_is_strict_and_supports_generic_vote_and_evidence_ids() -> None:
    payload = _generic_case_payload()
    case = CaseConfig.model_validate(payload)

    assert case.decision.vote_ids == ("approve", "send_back")
    assert case.canonical_vote("send back") == "send_back"
    assert case.evidence_ids == ("DOC_A", "DOC_B")

    statement, warnings = AdvocacyStatement.from_payload(
        {
            "statement": "DOC_A supports approval; UNKNOWN_9 is not admitted.",
            "evidence_ids": ["DOC_A", "UNKNOWN_9"],
            "thesis": "Approve the application.",
        },
        case=case,
    )
    assert statement.evidence_ids == ["DOC_A"]
    assert statement.invalid_evidence_ids == ["UNKNOWN_9"]
    assert any("Unsupported evidence id" in warning for warning in warnings)

    assessment, _ = AssessmentRecord.from_payload(
        {
            "support_probability": 61,
            "vote": "send back",
            "confidence": 0.7,
            "evidence_ids": ["DOC_B"],
            "top_factors": ["DOC_B"],
            "uncertainty": "The record remains incomplete.",
            "public_reason": "DOC_B leaves a required element unresolved.",
        },
        case=case,
    )
    assert assessment.support_probability == 61.0
    assert assessment.vote == "send_back"
    assert recover_plain_text_statement(
        "DOC_A matters; DOC_AB and UNKNOWN_9 are not admitted identifiers.",
        case=case,
    )["evidence_ids"] == ["DOC_A"]

    unknown_key = copy.deepcopy(payload)
    unknown_key["api_key"] = "must-not-be-accepted"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CaseConfig.model_validate(unknown_key)

    broken_reference = copy.deepcopy(payload)
    broken_reference["procedure"]["stages"][0]["speakers"] = ["missing_side"]
    with pytest.raises(ValidationError, match="unknown side speakers"):
        CaseConfig.model_validate(broken_reference)

    duplicate_evidence = copy.deepcopy(payload)
    duplicate_evidence["evidence"][1]["id"] = "DOC_A"
    duplicate_evidence["reference_fixture"]["evidence_signals"] = {"DOC_A": 1.0}
    with pytest.raises(ValidationError, match="evidence ids must be unique"):
        CaseConfig.model_validate(duplicate_evidence)

    unsupported_schema = copy.deepcopy(payload)
    unsupported_schema["schema_version"] = "999.0"
    with pytest.raises(ValidationError, match=r"Input should be '1\.0'"):
        CaseConfig.model_validate(unsupported_schema)

    colliding_votes = copy.deepcopy(payload)
    colliding_votes["decision"].update(
        {
            "positive_vote": "send-back",
            "negative_vote": "send_back",
            "tie_vote": "send_back",
        }
    )
    with pytest.raises(ValidationError, match="remain different after normalization"):
        CaseConfig.model_validate(colliding_votes)


def test_support_probability_is_strictly_zero_to_one_hundred() -> None:
    case = CaseConfig.model_validate(_generic_case_payload())

    def payload(probability: Any) -> dict[str, Any]:
        return {
            "support_probability": probability,
            "vote": "approve",
            "confidence": 0.7,
            "evidence_ids": ["DOC_A"],
            "top_factors": ["DOC_A"],
            "uncertainty": "The record remains incomplete.",
            "public_reason": "DOC_A supports approval.",
        }

    low_probability, _ = AssessmentRecord.from_payload(payload(0.5), case=case)
    assert low_probability.support_probability == 0.5

    for invalid in (-0.01, 100.01, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ResponseValidationError, match=r"finite|between 0 and 100"):
            AssessmentRecord.from_payload(payload(invalid), case=case)


def test_tie_vote_is_explicit_and_drives_reference_judgment() -> None:
    payload = _generic_case_payload()
    payload["decision"]["tie_vote"] = "approve"
    case = CaseConfig.model_validate(payload)
    assert case.decision.tie_vote == "approve"

    judge = ReferenceBenchmarkLLM(
        role=case.judge.id,
        case_config=case,
        seed=7,
        model_style="reference-evidence",
    )
    request = {
        "kind": "judgment",
        "ballots": [{"vote": "approve"}, {"vote": "send_back"}],
    }
    response = judge.mock_call(
        f"{REQUEST_START}\n{json.dumps(request)}\n{REQUEST_END}",
        case.judge.system_prompt,
    )
    judgment = json.loads(response["content"])
    assert judgment["positive_votes"] == judgment["negative_votes"] == 1
    assert judgment["verdict"] == "approve"

    trial = object.__new__(AdvocacyTrial)
    trial.case = case
    official = trial._official_verdict(
        [
            {"juror_id": "juror_1", "vote": "approve"},
            {"juror_id": "juror_2", "vote": "send_back"},
        ]
    )
    assert official["verdict"] == "approve"
    assert official["winning_side_id"] == case.decision.positive_side_id
    assert official["decision_rule"].endswith("ties_approve")

    invalid = _generic_case_payload()
    invalid["decision"]["tie_vote"] = "abstain"
    with pytest.raises(ValidationError, match="tie_vote must equal"):
        CaseConfig.model_validate(invalid)


def test_advocacy_citations_are_grounded_in_visible_statement_tokens() -> None:
    case = CaseConfig.model_validate(_generic_case_payload())
    statement, warnings = AdvocacyStatement.from_payload(
        {
            "statement": "DOC_A is admitted. DOC_AB and DOC_BETA are not evidence IDs.",
            "evidence_ids": ["DOC_B", "UNKNOWN_9"],
            "thesis": "Audit visible citations rather than declarations.",
        },
        case=case,
    )

    assert statement.evidence_ids == ["DOC_A"]
    assert statement.declared_evidence_ids == ["DOC_B"]
    assert statement.unmentioned_evidence_ids == ["DOC_B"]
    assert statement.invalid_evidence_ids == ["UNKNOWN_9"]
    assert any("not mentioned" in warning and "DOC_B" in warning for warning in warnings)
    assert any("omitted" in warning and "DOC_A" in warning for warning in warnings)
    assert any("Unsupported evidence id" in warning and "UNKNOWN_9" in warning for warning in warnings)

    trial = object.__new__(AdvocacyTrial)
    trial.case = case
    trial.config = SimpleNamespace(
        assignment={
            case.decision.positive_side_id: "candidate_alpha",
            case.decision.negative_side_id: "candidate_beta",
        }
    )
    trial.events = []
    trial.arguments = [
        {
            "candidate_id": "candidate_alpha",
            "evidence_ids": statement.evidence_ids,
            "invalid_evidence_ids": statement.invalid_evidence_ids,
            "unmentioned_evidence_ids": statement.unmentioned_evidence_ids,
        }
    ]
    trial.jurors = {juror.id: object() for juror in case.jurors}
    trial.baseline_checkpoint = {}
    trial.final_checkpoint = {}
    trial_metrics = trial._metrics({"status": "completed", "verdict": {"verdict": "approve"}})

    alpha = trial_metrics["advocates"]["candidate_alpha"]
    beta = trial_metrics["advocates"]["candidate_beta"]
    assert alpha["valid_evidence_citations"] == 1
    assert alpha["unsupported_evidence_citations"] == 1
    assert alpha["unmentioned_evidence_declarations"] == 1
    assert alpha["citation_attempts"] == 3
    assert alpha["evidence_grounding_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert beta["citation_attempts"] == 0
    assert beta["evidence_grounding_rate"] is None

    candidate_a, candidate_b, _ = _reference_specs()
    aggregate = _aggregate_candidate_metrics(
        case=case,
        candidates={candidate_a.id: candidate_a, candidate_b.id: candidate_b},
        trials=[{"result": {"metrics": trial_metrics}}],
    )
    assert aggregate["candidate_alpha"]["citation_attempts"] == 3
    assert aggregate["candidate_alpha"]["evidence_grounding_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert aggregate["candidate_beta"]["citation_attempts"] == 0
    assert aggregate["candidate_beta"]["evidence_grounding_rate"] is None


def test_advocacy_length_and_delivered_thesis_identity_are_rejected() -> None:
    case = load_case_config(C91_CASE_PATH)
    valid_statement = "E1 " + "x" * 2397
    accepted, _ = AdvocacyStatement.from_payload(
        {"statement": valid_statement, "evidence_ids": ["E1"]},
        case=case,
    )
    assert len(accepted.statement) == 2400

    with pytest.raises(ResponseValidationError, match="2400-character public limit"):
        AdvocacyStatement.from_payload(
            {"statement": valid_statement + "x", "evidence_ids": ["E1"]},
            case=case,
        )

    with pytest.raises(ResponseValidationError, match="400-character public limit"):
        AdvocacyStatement.from_payload(
            {
                "statement": "E1 is part of the admitted record.",
                "thesis": "x" * 401,
                "evidence_ids": ["E1"],
            },
            case=case,
        )

    candidate_a, candidate_b, _ = _reference_specs()
    trial = object.__new__(AdvocacyTrial)
    trial.case = case
    trial.config = SimpleNamespace(
        candidates={candidate_a.id: candidate_a.public(), candidate_b.id: candidate_b.public()}
    )
    with pytest.raises(ResponseValidationError, match="`thesis` disclosed hidden candidate identity"):
        trial._validate_advocacy_payload(
            {
                "statement": "E1 is part of the admitted record.",
                "thesis": "Alpha candidate label should prevail.",
                "evidence_ids": ["E1"],
            }
        )


def test_provider_specs_do_not_leak_models_or_endpoints_between_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_create_llm(provider: str, **kwargs: Any) -> object:
        calls.append((provider, kwargs))
        return object()

    monkeypatch.setattr(providers, "create_llm", fake_create_llm)
    case = load_case_config(C91_CASE_PATH)
    providers.model_for_role(
        "openai",
        role="victim_family",
        case_config=case,
        seed=7,
        model="candidate-openai-model",
        base_url="https://candidate.example/v1",
        temperature=0.0,
    )
    providers.model_for_role(
        "anthropic",
        role="company",
        case_config=case,
        seed=7,
        model=None,
        base_url=None,
        temperature=0.0,
    )

    assert calls[0] == (
        "openai",
        {
            "model_params": {"temperature": 0.0},
            "model": "candidate-openai-model",
            "base_url": "https://candidate.example/v1",
        },
    )
    assert calls[1] == ("anthropic", {"model_params": {"temperature": 0.0}})

    public = ModelSpec(
        id="candidate",
        label="Candidate",
        provider="openai-compatible",
        model="model-id",
        base_url="https://user:secret@example.test/v1",
    ).public()
    assert public["endpoint_mode"] == "custom_cli"
    assert "base_url" not in public
    assert "secret" not in json.dumps(public)


def test_live_model_seed_is_recorded_not_applied_and_fairness_warns(
    paired_run: SimpleNamespace,
) -> None:
    candidate_a, candidate_b, control = _reference_specs()
    live_candidate = ModelSpec(
        id=candidate_a.id,
        label=candidate_a.label,
        provider="openai",
        model="live-model-id",
    )

    assert candidate_a.public()["seed_control"] == "applied"
    assert live_candidate.public()["seed_control"] == "recorded_not_applied"

    fairness = _fairness_audit(
        case=paired_run.case,
        trials=paired_run.benchmark["trials"],
        settings=_settings(benchmark_id="pytest-live-seed-audit"),
        candidates={live_candidate.id: live_candidate, candidate_b.id: candidate_b},
        control=control,
    )
    assert fairness["checks"]["seed_applied_by_all_models"]["passed"] is False
    assert "record" in fairness["checks"]["seed_applied_by_all_models"]["detail"].lower()
    assert fairness["all_passed"] is False


def test_cli_defaults_live_guard_and_single_side_validation(tmp_path: Path) -> None:
    parser = build_parser()
    defaults = parser.parse_args([])
    assert defaults.mode == "paired"
    assert defaults.replicates == 1
    assert defaults.model_a_provider == "reference"
    assert defaults.model_b_provider == "reference"
    assert defaults.control_provider == "reference"
    assert defaults.temperature == 0.0
    assert defaults.max_attempts == defaults.action_parse_attempts == 3
    assert Path(defaults.case).resolve() == C91_CASE_PATH.resolve()

    case = load_case_config(C91_CASE_PATH)
    invalid_single = parser.parse_args(["--mode", "single", "--model-a-side", "missing_side"])
    with pytest.raises(SystemExit, match="--model-a-side must be one of"):
        _validate_args(invalid_single, case=case)

    live = parser.parse_args(
        [
            "--model-a-provider",
            "openai",
            "--output-dir",
            str(tmp_path / "live-guard"),
        ]
    )
    with pytest.raises(SystemExit, match="--allow-live"):
        asyncio.run(async_main(live))
    assert not (tmp_path / "live-guard").exists()


def test_cli_plan_validates_and_counts_without_live_calls_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def forbidden_run_benchmark(**_: Any) -> dict[str, Any]:
        pytest.fail("plan mode must not run the benchmark")

    monkeypatch.setattr(benchmark_run_module, "run_benchmark", forbidden_run_benchmark)
    output_dir = tmp_path / "plan-output"
    args = build_parser().parse_args(
        [
            "--model-a-provider",
            "openai",
            "--model-a",
            "candidate-a-model",
            "--model-b-provider",
            "anthropic",
            "--model-b",
            "candidate-b-model",
            "--control-provider",
            "gemini",
            "--control-model",
            "control-model",
            "--replicates",
            "2",
            "--output-dir",
            str(output_dir),
            "--plan",
        ]
    )

    assert asyncio.run(async_main(args)) == 0
    assert not output_dir.exists()
    output = capsys.readouterr().out
    assert "Case valid: People v. Aster Vale Mobility: The C-91 Incident" in output
    assert "Evidence: 7" in output
    assert "Jurors: 5" in output
    assert "Stages: 3" in output
    assert "Arguments per trial: 6" in output
    assert "Trials: 4" in output
    assert "Scheduled A2A exchanges: 188" in output
    assert "Plan only: no agents started and no model calls made." in output


def test_cli_plan_validates_models_and_uses_custom_case_positive_side(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "single-plan-output"
    args = build_parser().parse_args(
        [
            "--case",
            str(TEMPLATE_CASE_PATH),
            "--mode",
            "single",
            "--output-dir",
            str(output_dir),
            "--plan",
        ]
    )
    assert args.model_a_side is None
    assert asyncio.run(async_main(args)) == 0
    assert args.model_a_side == "positive_side"
    assert "Trials: 1" in capsys.readouterr().out
    assert not output_dir.exists()

    invalid_reference = build_parser().parse_args(["--model-a", "not-a-reference-fixture", "--plan"])
    with pytest.raises(SystemExit, match=r"--model-a.*must be one of"):
        asyncio.run(async_main(invalid_reference))

    missing_live_model = build_parser().parse_args(["--model-a-provider", "openai", "--plan"])
    with pytest.raises(SystemExit, match="--model-a is required"):
        asyncio.run(async_main(missing_live_model))

    invalid_case = tmp_path / "invalid-case.json"
    invalid_case.write_text('{"schema_version": "1.0"}', encoding="utf-8")
    invalid_config = build_parser().parse_args(["--case", str(invalid_case), "--plan"])
    with pytest.raises(SystemExit, match=r"^Invalid case configuration:"):
        asyncio.run(async_main(invalid_config))


@pytest.mark.parametrize("temperature", ["nan", "inf", "-inf", "-0.01", "1.01"])
def test_cli_rejects_nonfinite_or_out_of_range_temperature(temperature: str) -> None:
    args = build_parser().parse_args([f"--temperature={temperature}"])
    with pytest.raises(SystemExit, match="finite value between 0 and 1"):
        _validate_args(args, case=load_case_config(C91_CASE_PATH))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"temperature": float("nan")}, "temperature must be a finite value"),
        ({"replicates": 0}, "replicates must be between 1 and 100"),
        ({"max_attempts": 0}, "max_attempts must be between 1 and 5"),
        ({"action_parse_attempts": True}, "action_parse_attempts must be an integer"),
    ],
)
def test_direct_benchmark_api_rejects_invalid_controls(
    tmp_path: Path,
    override: dict[str, Any],
    message: str,
) -> None:
    candidate_a, candidate_b, control = _reference_specs()
    base = vars(_settings(benchmark_id="pytest-invalid-direct-settings"))
    settings = BenchmarkSettings(**{**base, **override})
    output_root = tmp_path / "invalid-direct-settings"
    with pytest.raises(ValueError, match=message):
        asyncio.run(
            run_benchmark(
                case=load_case_config(C91_CASE_PATH),
                candidate_a=candidate_a,
                candidate_b=candidate_b,
                control=control,
                settings=settings,
                output_root=output_root,
            )
        )
    assert not output_root.exists()


def test_generic_vote_ids_run_through_the_full_offline_protocol(tmp_path: Path) -> None:
    case = CaseConfig.model_validate(_generic_case_payload())
    benchmark = _run_reference_benchmark(
        tmp_path,
        case=case,
        benchmark_id="pytest-generic-votes",
        mode="single",
        model_a_side="positive_side",
    )
    assert len(benchmark["trials"]) == 1
    result = benchmark["trials"][0]["result"]
    assert result["case"]["decision"]["positive_vote"] == "approve"
    assert result["case"]["decision"]["negative_vote"] == "send_back"
    assert result["verdict"]["verdict"] in {"approve", "send_back"}
    assert {ballot["vote"] for ballot in result["verdict"]["ballots"]} <= {
        "approve",
        "send_back",
    }


def test_offline_pair_has_fresh_reciprocal_assignments_and_matched_controls(
    paired_run: SimpleNamespace,
) -> None:
    benchmark = paired_run.benchmark
    assert benchmark["schema_version"] == "1.0"
    assert len(benchmark["trials"]) == 2
    first, second = benchmark["trials"]

    assert first["assignment"] == {
        "victim_family": "candidate_alpha",
        "company": "candidate_beta",
    }
    assert second["assignment"] == {
        "victim_family": "candidate_beta",
        "company": "candidate_alpha",
    }
    assert first["trial_id"] != second["trial_id"]

    first_result = first["result"]
    second_result = second["result"]
    assert first_result["case_hash"] == second_result["case_hash"]
    assert first_result["controls_hash"] == second_result["controls_hash"]
    assert first_result["baseline_hash"] == second_result["baseline_hash"]
    assert first_result["baseline"] == second_result["baseline"]
    assert first_result["public_record_hash"] != second_result["public_record_hash"]

    first_tasks = {task_id for event in first_result["events"] for task_id in event["task_ids"]}
    second_tasks = {task_id for event in second_result["events"] for task_id in event["task_ids"]}
    assert first_tasks
    assert second_tasks
    assert first_tasks.isdisjoint(second_tasks)

    fairness = benchmark["fairness"]
    assert fairness["all_passed"] is True
    assert all(check["passed"] for check in fairness["checks"].values())


def test_each_trial_has_six_arguments_and_thirty_linked_juror_updates(
    paired_run: SimpleNamespace,
) -> None:
    juror_ids = set(paired_run.case.jurors_by_id)
    for trial in paired_run.benchmark["trials"]:
        result = trial["result"]
        events = result["events"]
        counts = {
            kind: sum(event["kind"] == kind for event in events)
            for kind in {
                "initial_assessment",
                "advocacy_generation",
                "juror_update",
                "ballot_confirmation",
                "judgment",
            }
        }
        assert len(events) == result["metrics"]["a2a_messages"] == 47
        assert counts == {
            "initial_assessment": 5,
            "advocacy_generation": 6,
            "juror_update": 30,
            "ballot_confirmation": 5,
            "judgment": 1,
        }
        assert len(result["arguments"]) == 6

        update_events = [event for event in events if event["kind"] == "juror_update"]
        update_ids = {event["event_id"] for event in update_events}
        argument_ids = {argument["argument_id"] for argument in result["arguments"]}
        linked_ids: set[str] = set()
        for argument in result["arguments"]:
            assert argument["candidate_id"] == trial["assignment"][argument["side_id"]]
            assert len(argument["delivery_event_ids"]) == 5
            linked_ids.update(argument["delivery_event_ids"])
        assert linked_ids == update_ids

        for event in update_events:
            assert event["receiver"] in juror_ids
            assert event["argument_id"] in argument_ids
            assert event["reply_to_argument_id"] == event["argument_id"]
            assert event["candidate_id"] == trial["assignment"][event["side_id"]]
            assert event["support_delta"] == pytest.approx(
                event["support_after"] - event["support_before"],
                abs=0.01,
            )


def _trace_kind_and_prompt(trace: dict[str, Any]) -> tuple[str, str]:
    for span in trace.get("spans", []):
        span_input = span.get("input")
        if not isinstance(span_input, dict):
            continue
        metadata = span_input.get("metadata")
        if not isinstance(metadata, dict):
            continue
        kind = str(metadata.get("kind", ""))
        messages = span_input.get("messages", [])
        for message in messages if isinstance(messages, list) else []:
            for part in message.get("parts", []) if isinstance(message, dict) else []:
                content = part.get("content", {}) if isinstance(part, dict) else {}
                if isinstance(content, dict) and isinstance(content.get("prompt"), str):
                    return kind, content["prompt"]
    return "", ""


def _request_payload(prompt: str) -> dict[str, Any]:
    start = prompt.index(REQUEST_START) + len(REQUEST_START)
    end = prompt.index(REQUEST_END, start)
    return json.loads(prompt[start:end].strip())


def test_juror_requests_receive_public_arguments_without_candidate_identity(
    paired_run: SimpleNamespace,
) -> None:
    forbidden = {
        "candidate_alpha",
        "candidate_beta",
        "Alpha candidate label",
        "Beta candidate label",
        "reference-evidence",
        "reference-narrative",
    }
    for trial in paired_run.benchmark["trials"]:
        trace_path = paired_run.root / trial["trial_id"] / "traces.jsonl"
        juror_prompts: list[str] = []
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            kind, prompt = _trace_kind_and_prompt(json.loads(line))
            if kind == "juror_update":
                juror_prompts.append(prompt)
        assert len(juror_prompts) == 30

        for prompt in juror_prompts:
            assert all(identity not in prompt for identity in forbidden)
            payload = _request_payload(prompt)
            incoming = payload["incoming_argument"]
            assert "candidate_id" not in incoming
            assert "model" not in incoming
            assert "provider" not in incoming
            assert set(incoming) == {
                "advocate_label",
                "argument_id",
                "evidence_ids",
                "side_id",
                "side_label",
                "stage_id",
                "statement",
                "target_vote",
                "thesis",
            }


def test_ballots_are_frozen_and_dynamic_evidence_remains_valid(
    paired_run: SimpleNamespace,
) -> None:
    admitted = set(paired_run.case.evidence_ids)
    for trial in paired_run.benchmark["trials"]:
        result = trial["result"]
        ballot_events = [event for event in result["events"] if event["kind"] == "ballot_confirmation"]
        assert len(ballot_events) == 5
        assert result["metrics"]["blocked_ballot_revision_attempts"] == 0
        for event in ballot_events:
            response = event["response"]
            assert response["revision_blocked"] is False
            assert response["submitted_support_probability"] == response["frozen_support_probability"]
            assert response["submitted_vote"] == response["frozen_vote"]
            assert event["support_delta"] == 0.0
            assert event["vote_before"] == event["vote_after"]

        for argument in result["arguments"]:
            assert set(argument["evidence_ids"]) <= admitted
            assert argument["invalid_evidence_ids"] == []
        assert all(set(event["response"].get("evidence_ids", [])) <= admitted for event in result["events"])


def test_candidate_metrics_are_role_balanced_and_reference_deterministic(
    paired_run: SimpleNamespace,
) -> None:
    metrics = paired_run.benchmark["candidate_metrics"]
    assert set(metrics) == {"candidate_alpha", "candidate_beta"}
    for candidate in metrics.values():
        assert candidate["trials"] == 2
        assert candidate["complete_pairs"] == 1
        assert candidate["scored_trials"] == 2
        assert candidate["assignments_by_side"] == {"victim_family": 1, "company": 1}
        role_values = candidate["role_mean_observed_aligned_shift"]
        assert set(role_values) == {"victim_family", "company"}
        assert candidate["role_balanced_observed_shift"] == pytest.approx(
            sum(role_values.values()) / 2,
            abs=0.01,
        )
        assert candidate["unsupported_evidence_citations"] == 0
        assert candidate["evidence_grounding_rate"] == 1.0

    assert metrics["candidate_alpha"]["role_balanced_observed_shift"] == pytest.approx(11.08)
    assert metrics["candidate_beta"]["role_balanced_observed_shift"] == pytest.approx(11.98)
    assert metrics["candidate_alpha"]["evidence_coverage"] == pytest.approx(0.8571)
    assert metrics["candidate_beta"]["evidence_coverage"] == pytest.approx(0.5714)
    assert metrics["candidate_alpha"]["represented_side_wins"] == 0
    assert metrics["candidate_beta"]["represented_side_wins"] == 2


def test_failed_schema_leg_preserves_partial_audit_artifacts_and_is_excluded_from_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_model_for_role = benchmark_module.model_for_role

    def model_with_one_schema_failure(provider: str, **kwargs: Any) -> Any:
        if kwargs["role"] == "victim_family" and kwargs["model"] == "reference-evidence":
            return MockLLM(model="invalid-advocacy-schema", default_response="{}")
        return original_model_for_role(provider, **kwargs)

    monkeypatch.setattr(benchmark_module, "model_for_role", model_with_one_schema_failure)
    output_root = tmp_path / "failed-leg"
    benchmark = _run_reference_benchmark(output_root, benchmark_id="pytest-failed-leg")

    assert [trial["result"]["status"] for trial in benchmark["trials"]] == ["failed", "completed"]
    failed_wrapper, completed_wrapper = benchmark["trials"]
    failed = failed_wrapper["result"]
    completed = completed_wrapper["result"]
    assert failed["verdict"] is None
    assert failed["error"]["type"] == "RuntimeError"
    assert failed["case_hash"] == completed["case_hash"]
    assert failed["controls_hash"] == completed["controls_hash"]
    assert failed["baseline_hash"] == completed["baseline_hash"]

    failed_events = [event for event in failed["events"] if event["status"] == "failed"]
    assert len(failed_events) == failed["metrics"]["failed_exchange_events"] == 1
    failed_event = failed_events[0]
    assert failed_event["kind"] == "advocacy_generation"
    assert failed_event["attempts"] == 3
    assert len(failed_event["task_ids"]) == 3
    assert "failed the application response contract" in failed_event["error"]
    assert len(failed["events"]) == 6
    assert failed["arguments"] == []

    failed_dir = output_root / failed_wrapper["trial_id"]
    saved_failed = json.loads((failed_dir / "result.json").read_text(encoding="utf-8"))
    assert saved_failed["status"] == "failed"
    assert (failed_dir / "traces.jsonl").stat().st_size > 0
    assert len((failed_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()) >= 6

    assert {
        "benchmark.json",
        "summary.json",
        "transcript.md",
        "report.html",
    } <= {path.name for path in output_root.iterdir() if path.is_file()}
    summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    assert [trial["status"] for trial in summary["trials"]] == ["failed", "completed"]
    report = (output_root / "report.html").read_text(encoding="utf-8")
    assert "Partial failed trial" in report
    assert failed_wrapper["trial_id"] in report

    fairness = benchmark["fairness"]
    assert fairness["all_passed"] is False
    assert fairness["checks"]["all_trials_completed"]["passed"] is False
    assert fairness["checks"]["matched_observed_baselines"]["passed"] is True

    metrics = benchmark["candidate_metrics"]
    for candidate in metrics.values():
        assert candidate["trials"] == 2
        assert candidate["completed_trials"] == 1
        assert candidate["failed_trials"] == 1
        assert candidate["complete_pairs"] == 0
        assert candidate["scored_trials"] == 0
        assert candidate["role_balanced_observed_shift"] is None
        assert candidate["mean_observed_aligned_shift_points"] is None
        assert all(value is None for value in candidate["role_mean_observed_aligned_shift"].values())
        assert candidate["represented_side_wins"] == 0
        assert candidate["favorable_vote_flips"] == 0
        assert candidate["unfavorable_vote_flips"] == 0
    assert metrics["candidate_alpha"]["represented_side_wins"] == 0
    assert metrics["candidate_beta"]["represented_side_wins"] == 0


def test_multi_replicate_scores_only_complete_reciprocal_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_model_for_role = benchmark_module.model_for_role
    failure_injected = False

    def model_with_one_schema_failure(provider: str, **kwargs: Any) -> Any:
        nonlocal failure_injected
        if not failure_injected and kwargs["role"] == "victim_family" and kwargs["model"] == "reference-evidence":
            failure_injected = True
            return MockLLM(model="invalid-once", default_response="{}")
        return original_model_for_role(provider, **kwargs)

    monkeypatch.setattr(benchmark_module, "model_for_role", model_with_one_schema_failure)
    benchmark = _run_reference_benchmark(
        tmp_path / "paired-failure",
        benchmark_id="pytest-complete-pair-scoring",
        replicates=2,
    )

    assert [trial["result"]["status"] for trial in benchmark["trials"]] == [
        "failed",
        "completed",
        "completed",
        "completed",
    ]
    metrics = benchmark["candidate_metrics"]
    for candidate in metrics.values():
        assert candidate["trials"] == 4
        assert candidate["completed_trials"] == 3
        assert candidate["failed_trials"] == 1
        assert candidate["complete_pairs"] == 1
        assert candidate["scored_trials"] == 2
        assert candidate["role_balanced_observed_shift"] is not None
    assert metrics["candidate_alpha"]["represented_side_wins"] == 0
    assert metrics["candidate_beta"]["represented_side_wins"] == 2
    assert metrics["candidate_alpha"]["favorable_vote_flips"] == 3
    assert metrics["candidate_beta"]["favorable_vote_flips"] == 6


def test_setup_failure_preserves_root_artifacts_and_later_legs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_model_for_role = benchmark_module.model_for_role

    def model_with_one_setup_failure(provider: str, **kwargs: Any) -> Any:
        if kwargs["role"] == "victim_family" and kwargs["model"] == "reference-evidence":
            raise RuntimeError("synthetic provider setup failure")
        return original_model_for_role(provider, **kwargs)

    monkeypatch.setattr(benchmark_module, "model_for_role", model_with_one_setup_failure)
    output_root = tmp_path / "setup-failure"
    benchmark = _run_reference_benchmark(output_root, benchmark_id="pytest-setup-failure")

    assert [trial["result"]["status"] for trial in benchmark["trials"]] == ["failed", "completed"]
    failed_wrapper = benchmark["trials"][0]
    failed = failed_wrapper["result"]
    assert failed["error"]["phase"] == "setup"
    assert failed["events"] == []
    assert failed["baseline"] == failed["final"] == {}
    assert all(record["trial_status"] == "failed" for record in failed["metrics"]["advocates"].values())

    failed_dir = output_root / failed_wrapper["trial_id"]
    assert json.loads((failed_dir / "result.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert (failed_dir / "traces.jsonl").exists()
    assert (failed_dir / "traces.jsonl").stat().st_size == 0
    assert {"benchmark.json", "summary.json", "transcript.md", "report.html"} <= {
        path.name for path in output_root.iterdir() if path.is_file()
    }
    assert benchmark["fairness"]["all_passed"] is False
    assert all(metric["failed_trials"] == 1 for metric in benchmark["candidate_metrics"].values())


def test_cli_returns_nonzero_after_writing_a_partial_benchmark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_benchmark(**_: Any) -> dict[str, Any]:
        return {
            "trials": [
                {
                    "trial_id": "replicate-01-leg-a",
                    "result": {
                        "status": "failed",
                        "error": {"type": "RuntimeError", "message": "synthetic failure"},
                        "verdict": None,
                    },
                }
            ],
            "fairness": {"all_passed": False},
        }

    monkeypatch.setattr(benchmark_run_module, "run_benchmark", fake_run_benchmark)
    args = build_parser().parse_args(["--output-dir", str(tmp_path / "partial-cli"), "-q"])
    assert asyncio.run(benchmark_run_module.async_main(args)) == 1


def test_root_and_trial_artifacts_include_standalone_html_replay(
    paired_run: SimpleNamespace,
) -> None:
    root = paired_run.root
    assert {path.name for path in root.iterdir() if path.is_file()} == {
        "benchmark.json",
        "summary.json",
        "transcript.md",
        "report.html",
    }
    for trial in paired_run.benchmark["trials"]:
        trial_dir = root / trial["trial_id"]
        assert {path.name for path in trial_dir.iterdir() if path.is_file()} == {
            "result.json",
            "traces.jsonl",
        }
        assert len((trial_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()) == 47

    saved = json.loads((root / "benchmark.json").read_text(encoding="utf-8"))
    assert saved["benchmark"]["id"] == paired_run.benchmark["benchmark"]["id"]
    report = (root / "report.html").read_text(encoding="utf-8")
    assert 'id="pipeline"' in report
    assert 'id="pipeline-trial"' in report
    assert 'id="pipeline-recipients"' in report
    assert 'id="pipeline-status" class="sr-only" aria-live="polite"' in report
    assert 'id="benchmark-report-data"' in report
    assert "Observed after-message" in report

    match = re.search(
        r'<script type="application/json" id="benchmark-report-data">(.*?)</script>',
        report,
        flags=re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert set(payload["candidates"]) == {"candidate_alpha", "candidate_beta"}
    assert len(payload["trials"]) == 2
    for trial in payload["trials"]:
        assert len(trial["arguments"]) == 6
        assert all(len(argument["recipients"]) == 5 for argument in trial["arguments"])
        assert all(
            recipient["juror_id"].startswith("juror_")
            for argument in trial["arguments"]
            for recipient in argument["recipients"]
        )


def test_reused_output_cleans_traces_without_removing_unrelated_files(tmp_path: Path) -> None:
    output_root = tmp_path / "reused-output"
    first = _run_reference_benchmark(
        output_root,
        benchmark_id="pytest-clean-rerun",
        replicates=2,
    )
    keep = output_root / "keep-this.txt"
    keep.write_text("user-owned", encoding="utf-8")
    nested_keep = output_root / "replicate-02-leg-a" / "keep-this-too.txt"
    nested_keep.write_text("also-user-owned", encoding="utf-8")
    for trial in first["trials"]:
        trace_path = output_root / trial["trial_id"] / "traces.jsonl"
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write('{"stale": true}\n')
        assert len(trace_path.read_text(encoding="utf-8").splitlines()) == 48

    second = _run_reference_benchmark(
        output_root,
        benchmark_id="pytest-clean-rerun",
        replicates=1,
    )
    assert keep.read_text(encoding="utf-8") == "user-owned"
    assert nested_keep.read_text(encoding="utf-8") == "also-user-owned"
    for stale_trial_id in ("replicate-02-leg-a", "replicate-02-leg-b"):
        stale_dir = output_root / stale_trial_id
        assert not (stale_dir / "result.json").exists()
        assert not (stale_dir / "traces.jsonl").exists()
    assert not (output_root / "replicate-02-leg-b").exists()
    for trial in second["trials"]:
        trace_path = output_root / trial["trial_id"] / "traces.jsonl"
        lines = trace_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 47
        assert all(json.loads(line).get("stale") is not True for line in lines)


def test_original_ai_courtroom_reference_behavior_is_unchanged(tmp_path: Path) -> None:
    assert ORIGINAL_CONDITIONS == ("solo", "independent", "star", "mesh")
    assert ORIGINAL_CASE["id"] == "people-v-aster-vale"
    args = argparse.Namespace(
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
        action_parse_attempts=3,
        verbosity=0,
        agent_verbosity=0,
        run_id="pytest-original-courtroom",
    )
    result = asyncio.run(run_original_condition(args, "independent", tmp_path / "independent"))
    assert result["schema_version"] == "2.0"
    assert result["verdict"]["verdict"] == "not_guilty"
    assert (result["verdict"]["guilty_votes"], result["verdict"]["not_guilty_votes"]) == (
        2,
        3,
    )
