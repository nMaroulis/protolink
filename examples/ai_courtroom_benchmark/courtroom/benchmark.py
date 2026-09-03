"""Paired role-swap orchestration for the advocacy benchmark."""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from protolink import Agent, AgentCard, LocalTraceRecorder, LocalTraceTelemetry

from .config import CaseConfig
from .providers import model_for_role
from .reporting import write_benchmark_artifacts
from .simulation import AdvocacyTrial, TrialConfig, stable_hash

_TRIAL_DIRECTORY = re.compile(r"^replicate-\d+-leg-(?:a|b|single)$")


@dataclass(frozen=True)
class ModelSpec:
    """One candidate or fixed control backend without credentials."""

    id: str
    label: str
    provider: str
    model: str | None
    base_url: str | None = None

    def public(self) -> dict[str, Any]:
        """Return reproducibility metadata without endpoint contents or secrets."""
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "model": self.model or "provider-default",
            "endpoint_mode": "custom_cli" if self.base_url else "provider_default_or_environment",
            "seed_control": "applied" if self.provider == "reference" else "recorded_not_applied",
        }


@dataclass(frozen=True)
class BenchmarkSettings:
    """Controls shared by all fresh trials in one benchmark run."""

    benchmark_id: str
    mode: str
    model_a_side: str
    seed: int
    replicates: int
    temperature: float
    max_attempts: int
    action_parse_attempts: int
    agent_verbosity: int


async def run_benchmark(
    *,
    case: CaseConfig,
    candidate_a: ModelSpec,
    candidate_b: ModelSpec,
    control: ModelSpec,
    settings: BenchmarkSettings,
    output_root: Path,
    progress: Any = None,
) -> dict[str, Any]:
    """Run fresh paired or single trials, aggregate them, and write artifacts."""
    if settings.mode not in {"paired", "single"}:
        raise ValueError("Benchmark mode must be `paired` or `single`")
    if isinstance(settings.replicates, bool) or not isinstance(settings.replicates, int):
        raise ValueError("Benchmark replicates must be an integer")
    if not 1 <= settings.replicates <= 100:
        raise ValueError("Benchmark replicates must be between 1 and 100")
    if (
        isinstance(settings.temperature, bool)
        or not isinstance(settings.temperature, (int, float))
        or not math.isfinite(settings.temperature)
        or not 0.0 <= settings.temperature <= 1.0
    ):
        raise ValueError("Benchmark temperature must be a finite value between 0 and 1")
    if isinstance(settings.max_attempts, bool) or not isinstance(settings.max_attempts, int):
        raise ValueError("Benchmark max_attempts must be an integer")
    if not 1 <= settings.max_attempts <= 5:
        raise ValueError("Benchmark max_attempts must be between 1 and 5")
    if isinstance(settings.action_parse_attempts, bool) or not isinstance(settings.action_parse_attempts, int):
        raise ValueError("Benchmark action_parse_attempts must be an integer")
    if not 1 <= settings.action_parse_attempts <= 5:
        raise ValueError("Benchmark action_parse_attempts must be between 1 and 5")
    if candidate_a.id == candidate_b.id:
        raise ValueError("Candidate IDs must be distinct")
    if settings.mode == "single" and settings.model_a_side not in case.sides_by_id:
        raise ValueError(f"Unknown Model A side `{settings.model_a_side}`")

    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    _clean_known_artifacts(destination)
    for artifact in ("benchmark.json", "summary.json", "transcript.md", "report.html"):
        (destination / artifact).unlink(missing_ok=True)

    started_at = datetime.now(UTC).isoformat()
    candidates = {candidate_a.id: candidate_a, candidate_b.id: candidate_b}
    candidate_public = {candidate_id: spec.public() for candidate_id, spec in candidates.items()}
    case_hash = stable_hash(case.model_dump(mode="json"))
    base_control_payload = {
        "protocol_version": "advocate-benchmark-v1",
        "case_hash": case_hash,
        "judge": case.judge.model_dump(mode="json"),
        "jurors": [juror.model_dump(mode="json") for juror in case.jurors],
        "procedure": case.procedure.model_dump(mode="json"),
        "control_model": control.public(),
        "temperature": settings.temperature,
        "max_attempts": settings.max_attempts,
        "action_parse_attempts": settings.action_parse_attempts,
    }
    benchmark_controls_hash = stable_hash(
        {**base_control_payload, "seed_schedule": [settings.seed + index for index in range(settings.replicates)]}
    )

    trial_wrappers: list[dict[str, Any]] = []
    for replicate_index in range(settings.replicates):
        replicate = replicate_index + 1
        replicate_seed = settings.seed + replicate_index
        assignments = _assignments(
            case=case,
            candidate_a_id=candidate_a.id,
            candidate_b_id=candidate_b.id,
            mode=settings.mode,
            model_a_side=settings.model_a_side,
        )
        for leg_index, assignment in enumerate(assignments):
            leg = chr(ord("A") + leg_index) if settings.mode == "paired" else "single"
            trial_id = f"replicate-{replicate:02d}-leg-{str(leg).lower()}"
            trial_dir = destination / trial_id
            trial_dir.mkdir(parents=True, exist_ok=True)
            (trial_dir / "result.json").unlink(missing_ok=True)
            (trial_dir / "traces.jsonl").unlink(missing_ok=True)
            controls_hash = stable_hash({**base_control_payload, "seed": replicate_seed})
            if progress is not None:
                progress(1, f"Starting {trial_id}: {_assignment_label(case, assignment, candidates)}")
            result = await _run_trial(
                case=case,
                candidates=candidates,
                control=control,
                assignment=assignment,
                settings=settings,
                replicate=replicate,
                seed=replicate_seed,
                trial_id=trial_id,
                case_hash=case_hash,
                controls_hash=controls_hash,
                output_dir=trial_dir,
                progress=progress,
            )
            wrapper = {
                "trial_id": trial_id,
                "leg": leg,
                "replicate": replicate,
                "seed": replicate_seed,
                "assignment": dict(assignment),
                "result": result,
            }
            trial_wrappers.append(wrapper)

    finished_at = datetime.now(UTC).isoformat()
    candidate_metrics = _aggregate_candidate_metrics(
        case=case,
        candidates=candidates,
        trials=trial_wrappers,
        mode=settings.mode,
    )
    candidate_public = _resolved_candidate_metadata(
        candidates=candidates,
        trials=trial_wrappers,
    )
    control_public = _resolved_control_metadata(control=control, trials=trial_wrappers)
    fairness = _fairness_audit(
        case=case,
        trials=trial_wrappers,
        settings=settings,
        candidates=candidates,
        control=control,
    )
    benchmark: dict[str, Any] = {
        "schema_version": "1.0",
        "benchmark": {
            "id": settings.benchmark_id,
            "title": (
                "The same case. The models switch sides."
                if settings.mode == "paired"
                else "One case. One controlled assignment."
            ),
            "protocol_version": "advocate-benchmark-v1",
            "mode": settings.mode,
            "case": _public_case_metadata(case),
            "case_hash": case_hash,
            "controls_hash": benchmark_controls_hash,
            "candidates": candidate_public,
            "control": control_public,
            "temperature": settings.temperature,
            "base_seed": settings.seed,
            "seed_policy": (
                "The deterministic reference fixture applies the seed; live providers only record it "
                "unless their adapter exposes an explicit seeded-generation contract."
            ),
            "replicates": settings.replicates,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "trials": trial_wrappers,
        "fairness": fairness,
        "candidate_metrics": candidate_metrics,
        "caveats": _caveats(mode=settings.mode),
    }
    (destination / "benchmark.json").write_text(
        json.dumps(benchmark, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_benchmark_artifacts(benchmark, destination)
    return benchmark


async def _run_trial(
    *,
    case: CaseConfig,
    candidates: dict[str, ModelSpec],
    control: ModelSpec,
    assignment: dict[str, str],
    settings: BenchmarkSettings,
    replicate: int,
    seed: int,
    trial_id: str,
    case_hash: str,
    controls_hash: str,
    output_dir: Path,
    progress: Any,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    namespace = _slug(f"{settings.benchmark_id}-{trial_id}")
    agents: dict[str, Agent] = {}
    started: list[Agent] = []
    trial: AdvocacyTrial | None = None
    failure_phase = "setup"
    try:
        recorder = LocalTraceRecorder(path=output_dir / "traces.jsonl", max_traces=2000)
        telemetry = LocalTraceTelemetry(recorder=recorder, capture_payloads=True)

        judge = case.judge
        agents[judge.id] = Agent(
            card=AgentCard(
                name=judge.id,
                description=f"Fixed neutral benchmark judge: {judge.label}.",
                url=f"runtime://courtroom-benchmark/{namespace}/{judge.id}",
                capabilities={"delegation": True, "has_llm": True},
                tags=["courtroom-benchmark", "control", "judge"],
            ),
            transport="runtime",
            llm=model_for_role(
                control.provider,
                role=judge.id,
                case_config=case,
                seed=seed,
                model=control.model,
                base_url=control.base_url,
                temperature=settings.temperature,
            ),
            system_prompt=_judge_prompt(case),
            telemetry=telemetry,
            expose_chat=False,
            verbosity=settings.agent_verbosity,
        )

        for side in case.sides:
            candidate = candidates[assignment[side.id]]
            agents[side.id] = Agent(
                card=AgentCard(
                    name=side.id,
                    description=f"Advocate for {side.label}: {side.advocate_label}.",
                    url=f"runtime://courtroom-benchmark/{namespace}/{side.id}",
                    capabilities={"delegation": True, "has_llm": True, "multi_step_reasoning": True},
                    tags=["courtroom-benchmark", "advocate", side.id],
                ),
                transport="runtime",
                llm=model_for_role(
                    candidate.provider,
                    role=side.id,
                    case_config=case,
                    seed=seed,
                    model=candidate.model,
                    base_url=candidate.base_url,
                    temperature=settings.temperature,
                ),
                system_prompt=_advocate_prompt(case, side.id),
                telemetry=telemetry,
                expose_chat=False,
                verbosity=settings.agent_verbosity,
            )

        for juror in case.jurors:
            agents[juror.id] = Agent(
                card=AgentCard(
                    name=juror.id,
                    description=f"Fixed independent evaluator juror: {juror.label}.",
                    url=f"runtime://courtroom-benchmark/{namespace}/{juror.id}",
                    capabilities={"delegation": True, "has_llm": True},
                    tags=["courtroom-benchmark", "control", "juror", "independent"],
                ),
                transport="runtime",
                llm=model_for_role(
                    control.provider,
                    role=juror.id,
                    case_config=case,
                    seed=seed,
                    model=control.model,
                    base_url=control.base_url,
                    temperature=settings.temperature,
                ),
                system_prompt=_juror_prompt(case, juror.id),
                telemetry=telemetry,
                expose_chat=False,
                verbosity=settings.agent_verbosity,
            )

        for agent in agents.values():
            agent.llm.max_parse_failures = settings.action_parse_attempts

        trial = AdvocacyTrial(
            case=case,
            agents=agents,
            config=TrialConfig(
                benchmark_id=settings.benchmark_id,
                trial_id=trial_id,
                replicate=replicate,
                seed=seed,
                temperature=settings.temperature,
                max_attempts=settings.max_attempts,
                action_parse_attempts=settings.action_parse_attempts,
                agent_verbosity=settings.agent_verbosity,
                case_hash=case_hash,
                controls_hash=controls_hash,
                assignment=dict(assignment),
                candidates={candidate_id: spec.public() for candidate_id, spec in candidates.items()},
                control=control.public(),
            ),
            progress=progress,
        )
        failure_phase = "startup"
        for agent in agents.values():
            agent.start(background=True)
            started.append(agent)
        failure_phase = "execution"
        result = await trial.run()
    except Exception as exc:
        if progress is not None:
            progress(
                1,
                f"{trial_id} failed during {failure_phase}; preserving partial artifacts: {type(exc).__name__}",
            )
        if trial is not None:
            result = trial.failure_result(exc)
            if isinstance(result.get("error"), dict):
                result["error"]["phase"] = failure_phase
        else:
            result = _setup_failure_result(
                case=case,
                candidates=candidates,
                control=control,
                assignment=assignment,
                settings=settings,
                replicate=replicate,
                seed=seed,
                trial_id=trial_id,
                case_hash=case_hash,
                controls_hash=controls_hash,
                started_at=started_at,
                agents=agents,
                error=exc,
            )
    finally:
        for agent in reversed(started):
            try:
                agent.stop()
            except Exception:
                if progress is not None:
                    progress(1, f"Cleanup warning while stopping agent `{agent.card.name}`")
    (output_dir / "traces.jsonl").touch(exist_ok=True)
    result["treatment_hash"] = stable_hash(
        {
            "assignment": assignment,
            "candidates": {candidate_id: spec.public() for candidate_id, spec in candidates.items()},
            "public_record_hash": result["public_record_hash"],
        }
    )
    (output_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


def _setup_failure_result(
    *,
    case: CaseConfig,
    candidates: dict[str, ModelSpec],
    control: ModelSpec,
    assignment: dict[str, str],
    settings: BenchmarkSettings,
    replicate: int,
    seed: int,
    trial_id: str,
    case_hash: str,
    controls_hash: str,
    started_at: str,
    agents: dict[str, Agent],
    error: Exception,
) -> dict[str, Any]:
    """Build a report-compatible failed leg when setup cannot create a trial."""
    finished_at = datetime.now(UTC).isoformat()
    error_message = " ".join(str(error).split())
    if len(error_message) > 500:
        error_message = f"{error_message[:497]}..."

    advocate_metrics: dict[str, dict[str, Any]] = {}
    for side in case.sides:
        candidate_id = assignment[side.id]
        advocate_metrics[candidate_id] = {
            "trial_status": "failed",
            "side_id": side.id,
            "side_label": side.label,
            "target_vote": side.target_vote,
            "represented_side_won": None,
            "arguments": 0,
            "observed_aligned_shift_points": 0.0,
            "mean_aligned_shift_per_delivery": 0.0,
            "favorable_vote_flips": 0,
            "unfavorable_vote_flips": 0,
            "valid_evidence_citations": 0,
            "unsupported_evidence_citations": 0,
            "unmentioned_evidence_declarations": 0,
            "citation_attempts": 0,
            "evidence_grounding_rate": None,
            "evidence_coverage": 0.0,
            "unique_evidence_ids": [],
            "application_schema_repair_events": 0,
            "application_first_attempt_success_rate": None,
            "blocked_candidate_identity_disclosures": 0,
            "generation_latency_ms": 0.0,
            "generation_task_input_tokens_estimate": 0,
            "generation_task_output_tokens_estimate": 0,
        }

    jurors = {
        juror.id: {
            "juror_id": juror.id,
            "label": juror.label,
            "background": juror.background,
            "baseline_support_probability": None,
            "baseline_vote": None,
            "support_probability": None,
            "confidence": None,
            "vote": None,
            "evidence_ids": [],
            "top_factors": [],
            "uncertainty": "No assessment was elicited because trial setup failed.",
            "public_reason": "",
            "public_reply": "",
            "history": [],
        }
        for juror in case.jurors
    }
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "failed",
        "error": {
            "type": type(error).__name__,
            "message": error_message,
            "phase": "setup",
        },
        "case": _public_case_metadata(case),
        "case_hash": case_hash,
        "controls_hash": controls_hash,
        "baseline_hash": None,
        "run": {
            "benchmark_id": settings.benchmark_id,
            "trial_id": trial_id,
            "replicate": replicate,
            "seed": seed,
            "temperature": settings.temperature,
            "max_attempts": settings.max_attempts,
            "action_parse_attempts": settings.action_parse_attempts,
            "agent_verbosity": settings.agent_verbosity,
            "assignment": dict(assignment),
            "candidates": {candidate_id: spec.public() for candidate_id, spec in candidates.items()},
            "control": control.public(),
            "started_at": started_at,
            "finished_at": finished_at,
            "agent_models": {
                agent_id: {
                    "provider": str(getattr(agent.llm, "provider", "unknown")),
                    "model": str(getattr(agent.llm, "model", "unknown")),
                }
                for agent_id, agent in agents.items()
            },
        },
        "participants": {
            "judge": {
                "id": case.judge.id,
                "label": case.judge.label,
                "role": "judge",
            },
            "sides": {
                side.id: {
                    "id": side.id,
                    "label": side.label,
                    "advocate_label": side.advocate_label,
                    "target_vote": side.target_vote,
                    "candidate_id": assignment[side.id],
                }
                for side in case.sides
            },
            "jurors": {
                juror.id: {
                    "id": juror.id,
                    "label": juror.label,
                    "background": juror.background,
                }
                for juror in case.jurors
            },
        },
        "baseline": {},
        "final": {},
        "arguments": [],
        "jurors": jurors,
        "events": [],
        "verdict": None,
        "metrics": {
            "a2a_messages": 0,
            "application_a2a_calls_including_repairs": 0,
            "application_schema_repair_events": 0,
            "failed_exchange_events": 0,
            "protocol_warning_events": 0,
            "latency_ms_total": 0.0,
            "task_input_tokens_estimate": 0,
            "task_output_tokens_estimate": 0,
            "baseline_mean_support_probability": None,
            "final_mean_support_probability": None,
            "net_mean_support_change": None,
            "baseline_polarization": None,
            "final_polarization": None,
            "vote_flips_from_baseline": 0,
            "blocked_ballot_revision_attempts": 0,
            "advocates": advocate_metrics,
        },
    }
    result["public_record_hash"] = stable_hash(result["arguments"])
    return result


def _clean_known_artifacts(destination: Path) -> None:
    """Remove stale generated trial files while preserving unrelated files."""
    for child in destination.iterdir():
        if not child.is_dir() or _TRIAL_DIRECTORY.fullmatch(child.name) is None:
            continue
        for artifact in ("result.json", "traces.jsonl"):
            (child / artifact).unlink(missing_ok=True)
        try:
            child.rmdir()
        except OSError:
            pass


def _resolved_candidate_metadata(
    *,
    candidates: dict[str, ModelSpec],
    trials: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Attach runtime-resolved model IDs without exposing endpoint contents."""
    resolved: dict[str, dict[str, Any]] = {candidate_id: spec.public() for candidate_id, spec in candidates.items()}
    models: dict[str, set[str]] = {candidate_id: set() for candidate_id in candidates}
    providers: dict[str, set[str]] = {candidate_id: set() for candidate_id in candidates}
    for trial in trials:
        result = trial.get("result", {})
        agent_models = result.get("run", {}).get("agent_models", {})
        for side_id, candidate_id in trial.get("assignment", {}).items():
            agent_model = agent_models.get(side_id, {})
            if agent_model.get("model"):
                models[candidate_id].add(str(agent_model["model"]))
            if agent_model.get("provider"):
                providers[candidate_id].add(str(agent_model["provider"]))
    for candidate_id, metadata in resolved.items():
        metadata["resolved_models"] = sorted(models[candidate_id])
        metadata["resolved_providers"] = sorted(providers[candidate_id])
        if metadata["model"] == "provider-default" and len(models[candidate_id]) == 1:
            metadata["model"] = next(iter(models[candidate_id]))
    return resolved


def _resolved_control_metadata(
    *,
    control: ModelSpec,
    trials: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach resolved judge and juror model IDs to fixed-control metadata."""
    metadata = control.public()
    models: set[str] = set()
    providers: set[str] = set()
    for trial in trials:
        result = trial.get("result", {})
        agent_models = result.get("run", {}).get("agent_models", {})
        advocate_ids = set(trial.get("assignment", {}))
        for agent_id, agent_model in agent_models.items():
            if agent_id in advocate_ids:
                continue
            if agent_model.get("model"):
                models.add(str(agent_model["model"]))
            if agent_model.get("provider"):
                providers.add(str(agent_model["provider"]))
    metadata["resolved_models"] = sorted(models)
    metadata["resolved_providers"] = sorted(providers)
    if metadata["model"] == "provider-default" and len(models) == 1:
        metadata["model"] = next(iter(models))
    return metadata


def _assignments(
    *,
    case: CaseConfig,
    candidate_a_id: str,
    candidate_b_id: str,
    mode: str,
    model_a_side: str,
) -> list[dict[str, str]]:
    positive_side = case.decision.positive_side_id
    negative_side = case.decision.negative_side_id
    if mode == "paired":
        return [
            {positive_side: candidate_a_id, negative_side: candidate_b_id},
            {positive_side: candidate_b_id, negative_side: candidate_a_id},
        ]
    other_side = next(side.id for side in case.sides if side.id != model_a_side)
    return [{model_a_side: candidate_a_id, other_side: candidate_b_id}]


def _aggregate_candidate_metrics(
    *,
    case: CaseConfig,
    candidates: dict[str, ModelSpec],
    trials: list[dict[str, Any]],
    mode: str | None = None,
) -> dict[str, Any]:
    benchmark_mode = mode or (
        "paired" if any(str(trial.get("leg", "")).lower() in {"a", "b"} for trial in trials) else "single"
    )
    if benchmark_mode not in {"paired", "single"}:
        raise ValueError("Aggregate mode must be `paired` or `single`")

    complete_pairs = 0
    scored_trial_objects: set[int] = set()
    if benchmark_mode == "paired":
        replicate_groups: dict[Any, list[dict[str, Any]]] = {}
        for trial in trials:
            replicate_groups.setdefault(trial.get("replicate"), []).append(trial)
        for group in replicate_groups.values():
            if (
                len(group) == 2
                and all(_trial_completed(trial) for trial in group)
                and _assignments_are_reversed(group[0].get("assignment", {}), group[1].get("assignment", {}))
            ):
                complete_pairs += 1
                scored_trial_objects.update(id(trial) for trial in group)
    else:
        scored_trial_objects.update(id(trial) for trial in trials if _trial_completed(trial))

    aggregated: dict[str, Any] = {}
    for candidate_id in candidates:
        records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for trial in trials:
            metrics = trial["result"]["metrics"]["advocates"].get(candidate_id)
            if isinstance(metrics, dict):
                records.append((trial, metrics))
        all_records = [record for _, record in records]
        valid_citations = sum(int(record["valid_evidence_citations"]) for record in all_records)
        invalid_citations = sum(int(record["unsupported_evidence_citations"]) for record in all_records)
        unmentioned_citations = sum(int(record["unmentioned_evidence_declarations"]) for record in all_records)
        citation_attempts = valid_citations + invalid_citations + unmentioned_citations
        completed_records = [record for record in all_records if record.get("trial_status") == "completed"]
        scored_records = [
            record
            for trial, record in records
            if id(trial) in scored_trial_objects and record.get("trial_status") == "completed"
        ]
        role_shifts: dict[str, list[float]] = {side.id: [] for side in case.sides}
        wins_by_side = {side.id: 0 for side in case.sides}
        assignments_by_side = {side.id: 0 for side in case.sides}
        all_evidence: set[str] = set()
        for record in all_records:
            side_id = str(record["side_id"])
            assignments_by_side[side_id] += 1
            all_evidence.update(str(item) for item in record["unique_evidence_ids"])
        for record in scored_records:
            side_id = str(record["side_id"])
            role_shifts[side_id].append(float(record["observed_aligned_shift_points"]))
            wins_by_side[side_id] += int(bool(record["represented_side_won"]))
        role_means = {
            side_id: round(statistics.fmean(values), 2) if values else None for side_id, values in role_shifts.items()
        }
        balanced_values = [value for value in role_means.values() if value is not None]
        aggregated[candidate_id] = {
            "trials": len(all_records),
            "completed_trials": len(completed_records),
            "failed_trials": len(all_records) - len(completed_records),
            "complete_pairs": complete_pairs,
            "scored_trials": len(scored_records),
            "represented_side_wins": sum(int(bool(record["represented_side_won"])) for record in scored_records),
            "wins_by_side": wins_by_side,
            "assignments_by_side": assignments_by_side,
            "role_mean_observed_aligned_shift": role_means,
            "role_balanced_observed_shift": (
                round(statistics.fmean(balanced_values), 2)
                if benchmark_mode == "paired" and complete_pairs > 0 and len(balanced_values) == len(case.sides)
                else None
            ),
            "mean_observed_aligned_shift_points": (
                round(
                    statistics.fmean(float(record["observed_aligned_shift_points"]) for record in scored_records),
                    2,
                )
                if scored_records
                else None
            ),
            "favorable_vote_flips": sum(int(record["favorable_vote_flips"]) for record in scored_records),
            "unfavorable_vote_flips": sum(int(record["unfavorable_vote_flips"]) for record in scored_records),
            "valid_evidence_citations": valid_citations,
            "unsupported_evidence_citations": invalid_citations,
            "unmentioned_evidence_declarations": unmentioned_citations,
            "citation_attempts": citation_attempts,
            "evidence_grounding_rate": (round(valid_citations / citation_attempts, 4) if citation_attempts else None),
            "evidence_coverage": round(len(all_evidence) / len(case.evidence), 4),
            "application_schema_repair_events": sum(
                int(record["application_schema_repair_events"]) for record in all_records
            ),
            "blocked_candidate_identity_disclosures": sum(
                int(record["blocked_candidate_identity_disclosures"]) for record in all_records
            ),
            "generation_latency_ms": round(
                sum(float(record["generation_latency_ms"]) for record in all_records),
                2,
            ),
            "generation_task_input_tokens_estimate": sum(
                int(record["generation_task_input_tokens_estimate"]) for record in all_records
            ),
            "generation_task_output_tokens_estimate": sum(
                int(record["generation_task_output_tokens_estimate"]) for record in all_records
            ),
        }
    return aggregated


def _trial_completed(trial: dict[str, Any]) -> bool:
    """Return whether a trial wrapper contains a completed result."""
    result = trial.get("result", {})
    status = result.get("status")
    if status is not None:
        return status == "completed"
    advocates = result.get("metrics", {}).get("advocates", {})
    return bool(advocates) and all(
        isinstance(record, dict) and record.get("trial_status") == "completed" for record in advocates.values()
    )


def _fairness_audit(
    *,
    case: CaseConfig,
    trials: list[dict[str, Any]],
    settings: BenchmarkSettings,
    candidates: dict[str, ModelSpec],
    control: ModelSpec,
) -> dict[str, Any]:
    paired_groups: list[list[dict[str, Any]]] = []
    for replicate in range(1, settings.replicates + 1):
        paired_groups.append([trial for trial in trials if int(trial["replicate"]) == replicate])

    expected_group_size = 2 if settings.mode == "paired" else 1
    all_trials_completed = all(trial["result"].get("status") == "completed" for trial in trials)
    case_hashes = sorted({trial["result"]["case_hash"] for trial in trials})
    control_matches = all(
        len(group) == expected_group_size and len({trial["result"]["controls_hash"] for trial in group}) == 1
        for group in paired_groups
    )
    baseline_matches = all(
        len(group) == expected_group_size
        and all(trial["result"].get("baseline_hash") for trial in group)
        and len({trial["result"]["baseline_hash"] for trial in group}) == 1
        for group in paired_groups
    )
    role_swap_complete = settings.mode == "paired" and all(
        len(group) == 2 and _assignments_are_reversed(group[0]["assignment"], group[1]["assignment"])
        for group in paired_groups
    )
    all_specs = [*candidates.values(), control]
    seed_applied = all(spec.provider == "reference" for spec in all_specs)
    blocked_identity_disclosures = sum(
        "hidden candidate identity" in warning.lower()
        for trial in trials
        for event in trial["result"].get("events", [])
        for warning in event.get("warnings", [])
    )
    checks = {
        "all_trials_completed": {
            "passed": all_trials_completed,
            "detail": (
                "Every scheduled leg completed."
                if all_trials_completed
                else "At least one leg failed; partial events and traces were preserved."
            ),
        },
        "same_case_configuration": {
            "passed": len(case_hashes) == 1,
            "values": case_hashes,
            "detail": "All legs must use the same validated case configuration.",
        },
        "paired_role_swap": {
            "passed": role_swap_complete,
            "detail": (
                "Each candidate occupied each advocacy side once per replicate."
                if role_swap_complete
                else "Single mode or an incomplete reciprocal assignment does not control side advantage."
            ),
        },
        "matched_non_advocate_controls": {
            "passed": control_matches,
            "detail": (
                "Judge, jurors, procedure, temperature, and retry policy match within each pair."
                if settings.mode == "paired"
                else "Judge, jurors, procedure, temperature, and retry policy were recorded for this assignment."
            ),
        },
        "seed_applied_by_all_models": {
            "passed": seed_applied,
            "detail": (
                "The deterministic reference fixture applied the recorded seed."
                if seed_applied
                else "Live provider adapters in this example record the seed but do not apply it."
            ),
        },
        "matched_observed_baselines": {
            "passed": baseline_matches,
            "values": [[trial["result"]["baseline_hash"] for trial in group] for group in paired_groups],
            "detail": (
                (
                    "The independent jury produced the same baseline within each pair."
                    if settings.mode == "paired"
                    else "The independent jury baseline was recorded for this assignment."
                )
                + " Live providers may vary even at temperature zero."
            ),
        },
        "fresh_agents_per_leg": {
            "passed": True,
            "detail": "Every trial used a new runtime namespace and fresh agent instances.",
        },
        "independent_jury": {
            "passed": True,
            "detail": "Jurors received advocacy statements but no juror-to-juror messages.",
        },
        "matched_stage_snapshots": {
            "passed": True,
            "detail": "Both advocates generated each stage from the same immutable pre-stage record snapshot.",
        },
        "candidate_metadata_not_delivered": {
            "passed": True,
            "values": {"blocked_disclosure_attempts": blocked_identity_disclosures},
            "detail": (
                "Candidate IDs, labels, providers, and model IDs were omitted from evaluator payloads; "
                "explicit disclosures in advocacy text are rejected before delivery."
            ),
        },
    }
    all_passed = all(bool(check["passed"]) for check in checks.values())
    return {
        "all_passed": all_passed,
        "summary": "All paired controls matched." if all_passed else "One or more fairness checks need attention.",
        "checks": checks,
    }


def _assignments_are_reversed(first: dict[str, str], second: dict[str, str]) -> bool:
    if set(first) != set(second) or len(first) != 2:
        return False
    side_ids = list(first)
    return first[side_ids[0]] == second[side_ids[1]] and first[side_ids[1]] == second[side_ids[0]]


def _public_case_metadata(case: CaseConfig) -> dict[str, Any]:
    return {
        "id": case.id,
        "title": case.title,
        "summary": case.summary,
        "question": case.question,
        "charge": case.charge,
        "burden": case.burden,
        "elements": list(case.elements),
        "decision": case.decision.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in case.evidence],
        "sides": [
            {
                "id": side.id,
                "label": side.label,
                "advocate_label": side.advocate_label,
                "target_vote": side.target_vote,
            }
            for side in case.sides
        ],
        "judge": {"id": case.judge.id, "label": case.judge.label},
        "jurors": [{"id": juror.id, "label": juror.label, "background": juror.background} for juror in case.jurors],
    }


def _judge_prompt(case: CaseConfig) -> str:
    return (
        f"{case.judge.system_prompt}\n\n"
        "You are a fixed control agent in a controlled advocacy benchmark. Candidate identities and model "
        "families are hidden "
        "from the evaluator panel. Apply only the configured case, procedure, and tally."
    )


def _advocate_prompt(case: CaseConfig, side_id: str) -> str:
    side = case.sides_by_id[side_id]
    return (
        f"{side.system_prompt}\n\n"
        f"Case question: {case.question}\n"
        f"Configured burden: {case.burden}\n"
        "Your provider or model identity is not part of the case and must not be mentioned. "
        "Return the requested public JSON artifact only."
    )


def _juror_prompt(case: CaseConfig, juror_id: str) -> str:
    juror = case.jurors_by_id[juror_id]
    return (
        f"{juror.system_prompt}\n\n"
        f"Case question: {case.question}\n"
        f"Configured burden: {case.burden}\n"
        f"The public register is `{case.decision.probability_label}` on a 0 to 100 scale. "
        f"The only categorical votes are `{case.decision.positive_vote}` and "
        f"`{case.decision.negative_vote}`. The application never derives your vote from a numeric threshold. "
        "Candidate model identities are hidden and irrelevant. Keep public reasons concise."
    )


def _assignment_label(
    case: CaseConfig,
    assignment: dict[str, str],
    candidates: dict[str, ModelSpec],
) -> str:
    return "; ".join(
        f"{case.sides_by_id[side_id].label}={candidates[candidate_id].label}"
        for side_id, candidate_id in assignment.items()
    )


def _caveats(*, mode: str) -> list[str]:
    assignment_caveat = (
        "A reciprocal A/B and B/A pair controls obvious side assignment bias but changes both advocates at once."
        if mode == "paired"
        else "A single assignment does not control side advantage and should not be used for a model ranking."
    )
    return [
        "Observed after-message register movement is descriptive and does not establish causal persuasion.",
        assignment_caveat,
        "Five model jurors are a synthetic evaluator panel, not a sample of people.",
        "Live control models may be stochastic at temperature zero and may prefer familiar model styles.",
        "The recorded seed is applied by the offline reference fixture; live adapters in this example do not apply it.",
        "Citation grounding requires a visible admitted ID, but does not prove that a claim follows from the exhibit.",
        "A favorable verdict measures persuasion under this protocol, not truth, safety, or general intelligence.",
        "Logical quality requires a separate blinded claim-to-evidence rubric and should be reported independently.",
        "Candidate metadata is omitted and explicit disclosures are blocked, but writing style may still be "
        "recognizable.",
        "Application-schema retries and task-level token estimates do not include ProtoLink's internal action "
        "parsing calls.",
        "Failed legs retain partial results and traces but are excluded from outcome and role-balanced movement "
        "scores.",
        "The offline reference models are deterministic fixtures built to exercise the benchmark, not competitors.",
        "The protocol never requests private chain-of-thought; raw traces may retain unvalidated provider responses.",
    ]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


__all__ = ["BenchmarkSettings", "ModelSpec", "run_benchmark"]
