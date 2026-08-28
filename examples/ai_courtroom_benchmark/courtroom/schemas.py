"""Dynamic application schemas for advocacy, juror state, and judgments."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from protolink.llms.parsing import decode_json_response

from .config import CaseConfig

ADVOCACY_STATEMENT_MAX_CHARS = 2400
ADVOCACY_THESIS_MAX_CHARS = 400


class ResponseValidationError(ValueError):
    """Raised when a model response cannot become an observable record."""


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a numeric value to an inclusive range."""
    return max(low, min(high, value))


def extract_json_object(value: Any) -> dict[str, Any]:
    """Decode one JSON object from provider text or accept a dictionary."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ResponseValidationError(f"Expected JSON text, received {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ResponseValidationError("Response did not contain a valid JSON object")

    decoded: Any = text
    for _ in range(2):
        try:
            decoded = decode_json_response(decoded)
        except (TypeError, ValueError):
            break
        if isinstance(decoded, dict):
            return decoded
        if not isinstance(decoded, str):
            break
    raise ResponseValidationError("Response did not contain a valid JSON object")


def recover_plain_text_statement(value: Any, *, case: CaseConfig) -> dict[str, Any]:
    """Recover prose for a public statement and extract only admitted IDs."""
    if not isinstance(value, str):
        raise ResponseValidationError(f"Expected statement text, received {type(value).__name__}")
    statement = value.strip()
    if not statement:
        raise ResponseValidationError("Plain-text statement fallback received empty text")
    if statement.startswith(("{", "[", "```", '"', "<think", "<thought")):
        raise ResponseValidationError("Structured-looking text is not eligible for statement recovery")

    evidence_ids = _mentioned_evidence_ids(statement, case=case)
    return {"statement": statement, "evidence_ids": evidence_ids}


@dataclass(frozen=True)
class AdvocacyStatement:
    """One validated public statement authored by an advocate agent."""

    statement: str
    evidence_ids: list[str]
    declared_evidence_ids: list[str]
    unmentioned_evidence_ids: list[str]
    invalid_evidence_ids: list[str]
    thesis: str = ""
    key_claims: list[str] = field(default_factory=list)
    addressed_opponent_claims: list[str] = field(default_factory=list)
    concessions: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        case: CaseConfig,
    ) -> tuple[AdvocacyStatement, list[str]]:
        """Validate a statement against the case's dynamic evidence set."""
        statement = payload.get("statement", payload.get("answer"))
        if not isinstance(statement, str) or not statement.strip():
            raise ResponseValidationError("Advocacy response needs non-empty `statement` text")
        public_statement = statement.strip()
        if len(public_statement) > ADVOCACY_STATEMENT_MAX_CHARS:
            raise ResponseValidationError(
                f"Advocacy `statement` exceeds the {ADVOCACY_STATEMENT_MAX_CHARS}-character public limit"
            )
        declared_ids, invalid_ids = _evidence_ids(payload.get("evidence_ids", []), case=case)
        mentioned_ids = _mentioned_evidence_ids(public_statement, case=case)
        unmentioned_ids = [item for item in declared_ids if item not in mentioned_ids]
        undeclared_ids = [item for item in mentioned_ids if item not in declared_ids]
        warnings = [f"Unsupported evidence id ignored: {item}" for item in invalid_ids]
        if "evidence_ids" not in payload:
            warnings.append("Missing `evidence_ids` defaulted to an empty list")
        warnings.extend(f"Declared evidence id not mentioned in public statement: {item}" for item in unmentioned_ids)
        warnings.extend(
            f"Admitted evidence id mentioned in public statement but omitted from `evidence_ids`: {item}"
            for item in undeclared_ids
        )
        thesis = str(payload.get("thesis", "")).strip()
        if len(thesis) > ADVOCACY_THESIS_MAX_CHARS:
            raise ResponseValidationError(
                f"Advocacy `thesis` exceeds the {ADVOCACY_THESIS_MAX_CHARS}-character public limit"
            )
        return (
            cls(
                statement=public_statement,
                evidence_ids=mentioned_ids,
                declared_evidence_ids=declared_ids,
                unmentioned_evidence_ids=unmentioned_ids,
                invalid_evidence_ids=invalid_ids,
                thesis=thesis,
                key_claims=_string_list(payload.get("key_claims", []), limit=5),
                addressed_opponent_claims=_string_list(
                    payload.get("addressed_opponent_claims", []),
                    limit=5,
                ),
                concessions=_string_list(payload.get("concessions", []), limit=3),
            ),
            warnings,
        )


def validate_advocacy_statement(
    payload: dict[str, Any],
    *,
    case: CaseConfig,
) -> tuple[dict[str, Any], list[str]]:
    """Return a normalized advocacy statement for an exchange validator."""
    statement, warnings = AdvocacyStatement.from_payload(payload, case=case)
    return asdict(statement), warnings


@dataclass(frozen=True)
class AssessmentRecord:
    """One public juror assessment using the configured positive vote."""

    support_probability: float
    vote: str
    confidence: float
    evidence_ids: list[str]
    invalid_evidence_ids: list[str]
    top_factors: list[str]
    uncertainty: str
    public_reason: str
    public_reply: str = ""
    stated_influences: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        case: CaseConfig,
    ) -> tuple[AssessmentRecord, list[str]]:
        """Normalize a provider response without deriving its vote."""
        raw_probability = payload.get(
            "support_probability",
            payload.get("probability", payload.get("probability_of_positive_vote")),
        )
        if isinstance(raw_probability, bool):
            raise ResponseValidationError("Support probability must be numeric")
        try:
            probability = float(raw_probability)
        except (TypeError, ValueError) as exc:
            raise ResponseValidationError("Missing numeric `support_probability`") from exc
        if not math.isfinite(probability):
            raise ResponseValidationError("Support probability must be finite")
        if probability < 0.0 or probability > 100.0:
            raise ResponseValidationError("Support probability must be between 0 and 100 inclusive")

        warnings: list[str] = []
        probability = round(probability, 2)

        raw_vote = payload.get("vote", payload.get("recommended_vote"))
        vote = case.canonical_vote(raw_vote)
        if vote is None:
            allowed = " or ".join(f"`{item}`" for item in case.decision.vote_ids)
            raise ResponseValidationError(f"Vote must be {allowed}")

        raw_confidence = payload.get("confidence", 0.5)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.5
            warnings.append("Invalid confidence replaced with 0.5")
        if not math.isfinite(confidence):
            confidence = 0.5
            warnings.append("Nonfinite confidence replaced with 0.5")
        elif 1.0 < confidence <= 100.0:
            confidence /= 100.0
        clamped_confidence = clamp(confidence, 0.0, 1.0)
        if clamped_confidence != confidence:
            warnings.append(f"Confidence clamped from {confidence} to {clamped_confidence}")
        confidence = round(clamped_confidence, 3)

        evidence_ids, invalid_ids = _evidence_ids(payload.get("evidence_ids", []), case=case)
        warnings.extend(f"Unsupported evidence id ignored: {item}" for item in invalid_ids)
        if "evidence_ids" not in payload:
            warnings.append("Missing `evidence_ids` defaulted to an empty list")
        top_factors = _string_list(payload.get("top_factors", payload.get("key_reasons", [])), limit=4)
        if not top_factors:
            top_factors = evidence_ids[:3]
            if "top_factors" not in payload and "key_reasons" not in payload:
                warnings.append("Missing `top_factors` used cited evidence")

        uncertainty_value = payload.get("uncertainty", "Evidence remains incomplete.")
        if isinstance(uncertainty_value, list):
            uncertainty = "; ".join(str(item) for item in uncertainty_value[:3])
        else:
            uncertainty = str(uncertainty_value)
        public_reason = str(payload.get("public_reason", payload.get("public_rationale", ""))).strip()
        public_reply = str(payload.get("public_reply", payload.get("reply", ""))).strip()
        if not public_reason:
            public_reason = public_reply or "I updated my public assessment using the admitted record."
            warnings.append("Missing public reason replaced with a neutral fallback")

        return (
            cls(
                support_probability=probability,
                vote=vote,
                confidence=confidence,
                evidence_ids=evidence_ids,
                invalid_evidence_ids=invalid_ids,
                top_factors=top_factors,
                uncertainty=uncertainty[:400],
                public_reason=public_reason[:700],
                public_reply=public_reply[:700],
                stated_influences=_string_list(payload.get("stated_influences", []), limit=8),
            ),
            warnings,
        )

    @property
    def probability(self) -> float:
        """Compatibility alias for generic shift calculations."""
        return self.support_probability


def validate_assessment(
    payload: dict[str, Any],
    *,
    case: CaseConfig,
) -> tuple[dict[str, Any], list[str]]:
    """Return a normalized juror assessment for an exchange validator."""
    record, warnings = AssessmentRecord.from_payload(payload, case=case)
    return asdict(record), warnings


@dataclass
class JurorState:
    """Application-owned observable state for one controlled juror."""

    juror_id: str
    label: str
    background: str
    baseline_support_probability: float | None = None
    baseline_vote: str | None = None
    support_probability: float | None = None
    confidence: float | None = None
    vote: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    top_factors: list[str] = field(default_factory=list)
    uncertainty: str = "No assessment has been elicited yet."
    public_reason: str = ""
    public_reply: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self, *, sequence: int, phase: str, source_event_id: str | None = None) -> dict[str, Any]:
        """Return one serializable point on the public opinion trajectory."""
        return {
            "sequence": sequence,
            "phase": phase,
            "source_event_id": source_event_id,
            "support_probability": (
                round(self.support_probability, 2) if self.support_probability is not None else None
            ),
            "vote": self.vote,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "public_reason": self.public_reason,
            "public_reply": self.public_reply,
        }

    def apply(self, record: AssessmentRecord, *, sequence: int, phase: str, event_id: str) -> None:
        """Apply a validated assessment and append its trajectory snapshot."""
        if self.baseline_support_probability is None:
            self.baseline_support_probability = record.support_probability
            self.baseline_vote = record.vote
        self.support_probability = record.support_probability
        self.vote = record.vote
        self.confidence = record.confidence
        self.evidence_ids = list(record.evidence_ids)
        self.top_factors = list(record.top_factors)
        self.uncertainty = record.uncertainty
        self.public_reason = record.public_reason
        self.public_reply = record.public_reply
        self.history.append(self.snapshot(sequence=sequence, phase=phase, source_event_id=event_id))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the current state and complete public history."""
        return asdict(self)

    @property
    def probability(self) -> float | None:
        """Compatibility alias for generic shift calculations."""
        return self.support_probability


@dataclass(frozen=True)
class JudgmentRecord:
    """A judge's validated public announcement of an application tally."""

    statement: str
    verdict: str
    positive_votes: int
    negative_votes: int
    evidence_ids: list[str]
    invalid_evidence_ids: list[str]

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        case: CaseConfig,
    ) -> tuple[JudgmentRecord, list[str]]:
        """Validate a judgment response using the configured vote vocabulary."""
        statement = payload.get("statement", payload.get("announcement"))
        if not isinstance(statement, str) or not statement.strip():
            raise ResponseValidationError("Judgment response needs non-empty `statement` text")
        verdict = case.canonical_vote(payload.get("verdict"))
        if verdict is None:
            raise ResponseValidationError("Judgment verdict is not one of the configured votes")
        positive_votes = _nonnegative_int(payload.get("positive_votes"), field_name="positive_votes")
        negative_votes = _nonnegative_int(payload.get("negative_votes"), field_name="negative_votes")
        evidence_ids, invalid_ids = _evidence_ids(payload.get("evidence_ids", []), case=case)
        warnings = [f"Unsupported evidence id ignored: {item}" for item in invalid_ids]
        return (
            cls(
                statement=statement.strip()[:1200],
                verdict=verdict,
                positive_votes=positive_votes,
                negative_votes=negative_votes,
                evidence_ids=evidence_ids,
                invalid_evidence_ids=invalid_ids,
            ),
            warnings,
        )


def validate_judgment(
    payload: dict[str, Any],
    *,
    case: CaseConfig,
) -> tuple[dict[str, Any], list[str]]:
    """Return a normalized judgment for an exchange validator."""
    record, warnings = JudgmentRecord.from_payload(payload, case=case)
    return asdict(record), warnings


@dataclass
class InteractionEvent:
    """One replayable A2A exchange in a benchmark leg."""

    event_id: str
    sequence: int
    phase: str
    kind: str
    sender: str
    receiver: str
    message: str
    response: dict[str, Any]
    evidence_ids: list[str]
    task_ids: list[str]
    attempts: int
    latency_ms: float
    input_tokens_estimate: int
    output_tokens_estimate: int
    provider: str
    model: str
    side_id: str | None = None
    candidate_id: str | None = None
    argument_id: str | None = None
    reply_to_argument_id: str | None = None
    support_before: float | None = None
    support_after: float | None = None
    support_delta: float | None = None
    vote_before: str | None = None
    vote_after: str | None = None
    status: str = "completed"
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize one event for JSON and standalone reports."""
        return asdict(self)


def _evidence_ids(value: Any, *, case: CaseConfig) -> tuple[list[str], list[str]]:
    values = _string_list(value, limit=max(12, len(case.evidence)))
    admitted = set(case.evidence_ids)
    valid: list[str] = []
    invalid: list[str] = []
    for item in values:
        if item in admitted:
            if item not in valid:
                valid.append(item)
        else:
            invalid.append(item)
    return valid, invalid


def _mentioned_evidence_ids(statement: str, *, case: CaseConfig) -> list[str]:
    """Return admitted IDs visibly present as complete public tokens."""
    ordered_ids = sorted(case.evidence_ids, key=len, reverse=True)
    alternatives = "|".join(re.escape(item) for item in ordered_ids)
    if not alternatives:
        return []
    pattern = re.compile(rf"(?<![A-Za-z0-9_])(?:{alternatives})(?![A-Za-z0-9_])")
    mentioned: list[str] = []
    for match in pattern.finditer(statement):
        evidence_id = match.group(0)
        if evidence_id not in mentioned:
            mentioned.append(evidence_id)
    return mentioned


def _string_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values[:limit] if str(item).strip()]


def _nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ResponseValidationError(f"{field_name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ResponseValidationError(f"{field_name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ResponseValidationError(f"{field_name} must be a non-negative integer")
    return parsed


__all__ = [
    "ADVOCACY_STATEMENT_MAX_CHARS",
    "ADVOCACY_THESIS_MAX_CHARS",
    "AdvocacyStatement",
    "AssessmentRecord",
    "InteractionEvent",
    "JudgmentRecord",
    "JurorState",
    "ResponseValidationError",
    "clamp",
    "extract_json_object",
    "recover_plain_text_statement",
    "validate_advocacy_statement",
    "validate_assessment",
    "validate_judgment",
]
