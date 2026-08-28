"""Deterministic offline models for exercising the benchmark end to end."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, ClassVar

from protolink.llms import MockLLM

from .config import CaseConfig, EvidenceConfig, JurorConfig, ProcedureStageConfig, SideConfig
from .schemas import clamp, extract_json_object

REQUEST_START = "<courtroom-benchmark-request>"
REQUEST_END = "</courtroom-benchmark-request>"
SUPPORTED_REFERENCE_MODELS = ("reference-evidence", "reference-narrative")


class ReferenceBenchmarkLLM(MockLLM):
    """Case-aware deterministic model used for offline demos and tests.

    The two reference model styles are deliberately simple fixtures. They
    exercise role swaps, evidence validation, opinion trajectories, and report
    generation; they are not claims about real model persuasion quality.
    """

    provider: ClassVar[str] = "reference"

    def __init__(
        self,
        *,
        role: str,
        case_config: CaseConfig,
        seed: int,
        model_style: str = "reference-evidence",
    ) -> None:
        if model_style not in SUPPORTED_REFERENCE_MODELS:
            allowed = ", ".join(SUPPORTED_REFERENCE_MODELS)
            raise ValueError(f"Unknown reference model `{model_style}`; choose one of: {allowed}")
        super().__init__(model=model_style)
        self.role = role
        self.case = case_config
        self.seed = seed
        self.model_style = model_style

    def mock_call(self, last_user_msg: str, system_prompt: str) -> dict[str, Any]:
        """Return one valid ProtoLink final action containing application JSON."""
        del system_prompt
        request = _request_from_prompt(last_user_msg)
        kind = str(request.get("kind", "")).strip().lower()
        handlers = {
            "advocacy_statement": lambda: self._advocacy_statement(request),
            "initial_assessment": lambda: self._initial_assessment(request),
            "belief_update": lambda: self._belief_update(request),
            "ballot": lambda: self._ballot(request),
            "judgment": lambda: self._judgment(request),
        }
        handler = handlers.get(kind)
        if handler is None:
            payload = {
                "statement": f"The reference fixture received unsupported request kind `{kind}`.",
                "evidence_ids": [],
            }
        else:
            payload = handler()
        return {"type": "final", "content": json.dumps(payload, sort_keys=True)}

    def _advocacy_statement(self, request: dict[str, Any]) -> dict[str, Any]:
        side = self._side(str(request.get("side_id", self.role)))
        stage = self._stage(request)
        evidence = self._select_evidence(side, stage)
        target = side.target_vote.replace("_", " ")
        prior_arguments = request.get("prior_arguments", request.get("public_arguments", []))
        has_prior = isinstance(prior_arguments, list) and bool(prior_arguments)

        if self.model_style == "reference-evidence":
            record_points = "; ".join(
                f"{item.id} ({item.title}) records {_excerpt(item.text, 120)}" for item in evidence
            )
            response_clause = (
                " The opposing account does not displace those admitted facts."
                if stage.include_prior_arguments and has_prior
                else ""
            )
            statement = (
                f"For {side.label}, the admitted record is the center of this {stage.label.lower()}: "
                f"{record_points}.{response_clause} The configured question should be answered with a "
                f"{target} vote because {side.objective.rstrip('.')}."
            )
        else:
            evidence_phrase = " ".join(
                f"{item.id} adds this concrete detail: {_excerpt(item.text, 145)}." for item in evidence
            )
            response_clause = (
                " Even after hearing the other side, that central account remains coherent."
                if stage.include_prior_arguments and has_prior
                else ""
            )
            statement = (
                f"The central story for {side.label} begins with {_excerpt(self.case.summary, 210)}. "
                f"{evidence_phrase}{response_clause} That is why this side asks for a {target} vote."
            )

        addressed_claims = []
        if stage.include_prior_arguments and has_prior:
            addressed_claims = ["The strongest opposing argument already present in the public record."]
        return {
            "statement": " ".join(statement.split()),
            "evidence_ids": [item.id for item in evidence],
            "thesis": side.objective,
            "key_claims": [
                side.objective,
                *(f"{item.id}: {item.title}" for item in evidence[:3]),
            ],
            "addressed_opponent_claims": addressed_claims,
            "concessions": ["The admitted record contains material uncertainty and competing causal accounts."],
        }

    def _initial_assessment(self, request: dict[str, Any]) -> dict[str, Any]:
        juror = self._juror()
        request_id = _request_id(request, "initial")
        probability = round(
            clamp(
                juror.reference_prior + _stable_noise(self.role, request_id, self.seed, amplitude=0.5),
                0.0,
                100.0,
            ),
            2,
        )
        evidence_ids = _incoming_evidence_ids(request, case=self.case)
        return self._assessment_payload(
            juror=juror,
            probability=probability,
            evidence_ids=evidence_ids,
            public_reason=(
                f"My initial register reflects the case summary and the configured burden for "
                f"{self.case.decision.probability_label.lower()}."
            ),
            public_reply="",
            uncertainty="No advocacy statement has been tested against the full record yet.",
            stated_influences=[],
        )

    def _belief_update(self, request: dict[str, Any]) -> dict[str, Any]:
        juror = self._juror()
        current = _current_state(request)
        current_probability = _number(current.get("support_probability"), juror.reference_prior)
        incoming = _incoming_message(request)
        evidence_ids = [
            item for item in _string_list(incoming.get("evidence_ids", [])) if item in self.case.evidence_by_id
        ]
        source_id = str(incoming.get("side_id", incoming.get("source", ""))).strip()
        source_side = self.case.sides_by_id.get(source_id)

        signals = self.case.reference_fixture.evidence_signals if self.case.reference_fixture else {}
        cited_signals = [float(signals[item]) for item in evidence_ids if item in signals]
        if cited_signals:
            content_signal = sum(cited_signals) / max(math.sqrt(len(cited_signals)), 1.0)
        elif source_side is not None:
            content_signal = 1.4 if source_side.target_vote == self.case.decision.positive_vote else -1.4
        else:
            content_signal = 0.0

        # The evidence-centered fixture cites more independent record items; the
        # narrative fixture remains persuasive but receives no hidden identity
        # bonus. Jurors react only to the observable statement and citations.
        statement = str(incoming.get("statement", ""))
        observable_grounding = min(len(evidence_ids), 3) * 0.18
        if source_side is not None and source_side.target_vote == self.case.decision.negative_vote:
            observable_grounding *= -1.0
        if "admitted record" not in statement.lower():
            observable_grounding *= 0.55

        message_id = str(incoming.get("message_id", _request_id(request, "message")))
        delta = (content_signal + observable_grounding) * juror.reference_receptiveness
        delta += _stable_noise(self.role, message_id, self.seed, amplitude=0.18)
        delta = round(clamp(delta, -8.0, 8.0), 2)
        probability = round(clamp(current_probability + delta, 0.0, 100.0), 2)

        previous_evidence = _string_list(current.get("evidence_ids", []))
        merged_evidence = list(dict.fromkeys([*previous_evidence, *evidence_ids]))[-6:]
        source_label = str(incoming.get("source_label", source_id.replace("_", " ").title()))
        direction = "increased" if delta > 0.15 else "decreased" if delta < -0.15 else "did not change"
        public_reply = (
            f"{source_label}, I registered the cited evidence and the limits of your claim."
            if source_id
            else "I registered the public statement and its cited evidence."
        )
        return self._assessment_payload(
            juror=juror,
            probability=probability,
            evidence_ids=merged_evidence,
            public_reason=(
                f"After the public statement from {source_label}, my support register {direction}. "
                "The shift reflects admitted citations rather than the advocate's model identity."
            ),
            public_reply=public_reply,
            uncertainty="An observed after-message shift is not by itself proof of causal persuasion.",
            stated_influences=[message_id] if abs(delta) >= 0.15 else [],
        )

    def _ballot(self, request: dict[str, Any]) -> dict[str, Any]:
        juror = self._juror()
        current = _current_state(request)
        probability = _number(current.get("support_probability"), juror.reference_prior)
        vote = self.case.canonical_vote(current.get("vote")) or self._vote(juror, probability)
        return {
            "support_probability": round(clamp(probability, 0.0, 100.0), 2),
            "vote": vote,
            "confidence": round(clamp(_number(current.get("confidence"), 0.6), 0.0, 1.0), 3),
            "evidence_ids": [
                item for item in _string_list(current.get("evidence_ids", [])) if item in self.case.evidence_by_id
            ],
            "top_factors": _string_list(current.get("top_factors", []))[:4],
            "uncertainty": str(current.get("uncertainty", "The public record remains contestable.")),
            "public_reason": str(current.get("public_reason", "I confirm my frozen public assessment.")),
            "public_reply": str(current.get("public_reply", "")),
            "stated_influences": _string_list(current.get("stated_influences", []))[:8],
        }

    def _judgment(self, request: dict[str, Any]) -> dict[str, Any]:
        raw_ballots = request.get("ballots", [])
        ballots = raw_ballots if isinstance(raw_ballots, list) else []
        positive = sum(
            1
            for ballot in ballots
            if isinstance(ballot, dict)
            and self.case.canonical_vote(ballot.get("vote")) == self.case.decision.positive_vote
        )
        negative = len(ballots) - positive
        if positive > negative:
            verdict = self.case.decision.positive_vote
        elif negative > positive:
            verdict = self.case.decision.negative_vote
        else:
            verdict = self.case.decision.tie_vote
        return {
            "statement": (
                f"The controlled jury returns {positive} {self.case.decision.positive_vote.replace('_', ' ')} "
                f"and {negative} {self.case.decision.negative_vote.replace('_', ' ')} ballots. "
                f"The procedural verdict is {verdict.replace('_', ' ')}."
            ),
            "verdict": verdict,
            "positive_votes": positive,
            "negative_votes": negative,
            "evidence_ids": [],
        }

    def _assessment_payload(
        self,
        *,
        juror: JurorConfig,
        probability: float,
        evidence_ids: list[str],
        public_reason: str,
        public_reply: str,
        uncertainty: str,
        stated_influences: list[str],
    ) -> dict[str, Any]:
        probability = round(clamp(probability, 0.0, 100.0), 2)
        distance = abs(probability - juror.reference_threshold)
        confidence = round(clamp(0.55 + distance / 100.0, 0.5, 0.9), 3)
        return {
            "support_probability": probability,
            "vote": self._vote(juror, probability),
            "confidence": confidence,
            "evidence_ids": evidence_ids,
            "top_factors": evidence_ids[-4:],
            "uncertainty": uncertainty,
            "public_reason": public_reason,
            "public_reply": public_reply,
            "stated_influences": stated_influences,
        }

    def _vote(self, juror: JurorConfig, probability: float) -> str:
        return (
            self.case.decision.positive_vote
            if probability >= juror.reference_threshold
            else self.case.decision.negative_vote
        )

    def _side(self, side_id: str) -> SideConfig:
        try:
            return self.case.sides_by_id[side_id]
        except KeyError as exc:
            raise ValueError(f"Reference role `{side_id}` is not a configured advocacy side") from exc

    def _juror(self) -> JurorConfig:
        try:
            return self.case.jurors_by_id[self.role]
        except KeyError as exc:
            raise ValueError(f"Reference role `{self.role}` is not a configured juror") from exc

    def _stage(self, request: dict[str, Any]) -> ProcedureStageConfig:
        raw_stage = request.get("stage", {})
        if isinstance(raw_stage, dict):
            stage_id = str(raw_stage.get("id", request.get("stage_id", "")))
        else:
            stage_id = str(request.get("stage_id", raw_stage))
        for stage in self.case.procedure.stages:
            if stage.id == stage_id:
                return stage
        return self.case.procedure.stages[0]

    def _select_evidence(self, side: SideConfig, stage: ProcedureStageConfig) -> list[EvidenceConfig]:
        signals = self.case.reference_fixture.evidence_signals if self.case.reference_fixture else {}
        direction = 1.0 if side.target_vote == self.case.decision.positive_vote else -1.0
        ranked = sorted(
            enumerate(self.case.evidence),
            key=lambda item: (direction * float(signals.get(item[1].id, 0.0)), -item[0]),
            reverse=True,
        )
        count = min(3 if self.model_style == "reference-evidence" else 2, len(ranked))
        selected = [item for _, item in ranked[:count]]
        if selected:
            offset = _stable_index(f"{self.role}|{self.model_style}", stage.id, self.seed, len(selected))
            selected = selected[offset:] + selected[:offset]
        return selected


def _current_state(request: dict[str, Any]) -> dict[str, Any]:
    state = request.get("current_state", request.get("prior_public_state", {}))
    return state if isinstance(state, dict) else {}


def _incoming_message(request: dict[str, Any]) -> dict[str, Any]:
    raw = request.get(
        "incoming_argument",
        request.get("message", request.get("incoming_message", {})),
    )
    if isinstance(raw, str):
        return {"statement": raw, "evidence_ids": []}
    return raw if isinstance(raw, dict) else {}


def _incoming_evidence_ids(request: dict[str, Any], *, case: CaseConfig) -> list[str]:
    incoming = _incoming_message(request)
    return [item for item in _string_list(incoming.get("evidence_ids", [])) if item in case.evidence_by_id]


def _request_from_prompt(prompt: str) -> dict[str, Any]:
    start = prompt.find(REQUEST_START)
    end = prompt.find(REQUEST_END)
    if start < 0 or end < 0 or end <= start:
        return {}
    raw = prompt[start + len(REQUEST_START) : end].strip()
    try:
        return extract_json_object(raw)
    except ValueError:
        return {}


def _request_id(request: dict[str, Any], fallback: str) -> str:
    incoming = _incoming_message(request)
    return str(
        request.get(
            "message_id",
            request.get(
                "event_id",
                request.get("request_id", incoming.get("argument_id", fallback)),
            ),
        )
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _number(value: Any, fallback: float) -> float:
    if isinstance(value, bool) or value is None:
        return float(fallback)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return parsed if math.isfinite(parsed) else float(fallback)


def _excerpt(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact.rstrip(".")
    return compact[: limit - 1].rstrip() + "…"


def _stable_noise(role: str, message_id: str, seed: int, *, amplitude: float) -> float:
    digest = hashlib.sha256(f"{role}|{message_id}|{seed}".encode()).digest()
    unit = int.from_bytes(digest[:4], "big") / (2**32 - 1)
    return round((unit - 0.5) * amplitude, 4)


def _stable_index(role: str, message_id: str, seed: int, size: int) -> int:
    digest = hashlib.sha256(f"index|{role}|{message_id}|{seed}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % max(size, 1)


__all__ = [
    "REQUEST_END",
    "REQUEST_START",
    "SUPPORTED_REFERENCE_MODELS",
    "ReferenceBenchmarkLLM",
]
