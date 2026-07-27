"""Small application schemas for observable courtroom state and the event ledger."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from protolink.llms.parsing import decode_json_response

from .case_data import CASE

VERDICTS = frozenset({"guilty", "not_guilty"})
DELIBERATION_ACTIONS = frozenset(
    {
        "ask_question",
        "challenge_claim",
        "share_evidence",
        "seek_clarification",
        "attempt_persuasion",
        "concede",
    }
)
_ACTION_ALIASES = {
    "ask": "ask_question",
    "challenge": "challenge_claim",
    "clarify": "seek_clarification",
    "persuade": "attempt_persuasion",
    "concession": "concede",
}
_EVIDENCE_REFERENCE = re.compile(r"(?<![A-Za-z0-9])E\d+(?![A-Za-z0-9])")


class ResponseValidationError(ValueError):
    """Raised when a model response cannot become an observable record."""


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a numeric value to an inclusive range."""
    return max(low, min(high, value))


def extract_json_object(value: Any) -> dict[str, Any]:
    """Decode exactly one JSON object from provider text or accept a dictionary."""
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


def recover_plain_text_statement(value: Any) -> dict[str, Any]:
    """Recover observable prose only for a public-statement contract.

    Decisions and deliberation routes must never call this helper. Structured-
    looking text is rejected so malformed JSON is repaired by the model rather
    than published as testimony. Evidence references are limited to exact,
    admitted identifiers found in the prose.
    """
    if not isinstance(value, str):
        raise ResponseValidationError(f"Expected statement text, received {type(value).__name__}")
    statement = value.strip()
    if not statement:
        raise ResponseValidationError("Plain-text statement fallback received empty text")
    if statement.startswith(("{", "[", "```", '"', "<think", "<thought")):
        raise ResponseValidationError("Structured-looking response is not eligible for plain-text statement recovery")

    evidence_ids: list[str] = []
    for match in _EVIDENCE_REFERENCE.findall(statement):
        evidence_id = match.upper()
        if evidence_id in CASE["evidence"] and evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    return {"statement": statement, "evidence_ids": evidence_ids}


def validate_statement(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate a public lawyer or witness statement."""
    statement = payload.get("statement", payload.get("answer"))
    if not isinstance(statement, str) or not statement.strip():
        raise ResponseValidationError("Statement response needs non-empty `statement` or `answer` text")
    evidence_ids, invalid = _evidence_ids(payload.get("evidence_ids", []))
    normalized = {
        **payload,
        "statement": statement.strip(),
        "evidence_ids": evidence_ids,
        "invalid_evidence_ids": invalid,
    }
    warnings = [f"Unsupported evidence id ignored: {item}" for item in invalid]
    if "evidence_ids" not in payload:
        warnings.append("Missing `evidence_ids` defaulted to an empty list")
    return normalized, warnings


@dataclass(frozen=True)
class DeliberationAction:
    """One agent-authored, application-validated deliberation move."""

    action: str
    target_id: str
    message: str
    evidence_ids: list[str]
    public_intent: str

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        sender_id: str,
        allowed_target_ids: list[str] | tuple[str, ...] | set[str] | frozenset[str],
    ) -> tuple[DeliberationAction, list[str]]:
        """Validate an authored move against the communication topology."""
        warnings: list[str] = []
        raw_move = str(payload.get("move", "")).strip().lower().replace("-", "_").replace(" ", "_")
        action = _ACTION_ALIASES.get(raw_move, raw_move)
        if action != raw_move:
            warnings.append(f"Move `{raw_move}` normalized to `{action}`")
        if action not in DELIBERATION_ACTIONS:
            allowed = ", ".join(sorted(DELIBERATION_ACTIONS))
            raise ResponseValidationError(f"Unknown deliberation move `{raw_move}`; choose one of: {allowed}")

        target_id = str(payload.get("target_id", payload.get("target", ""))).strip()
        allowed_targets = tuple(
            dict.fromkeys(
                str(candidate).strip()
                for candidate in allowed_target_ids
                if str(candidate).strip() and str(candidate).strip() != sender_id
            )
        )
        if not allowed_targets:
            raise ResponseValidationError(f"No valid deliberation targets are available to `{sender_id}`")
        if target_id == sender_id:
            raise ResponseValidationError("A deliberation action cannot target its sender")
        if target_id not in allowed_targets:
            raise ResponseValidationError(
                f"Target `{target_id}` is not available; choose one of: {', '.join(allowed_targets)}"
            )

        message_value = payload.get("message", payload.get("question"))
        if not isinstance(message_value, str) or not message_value.strip():
            raise ResponseValidationError("Deliberation action needs a non-empty `message`")
        message = message_value.strip()
        if len(message) > 700:
            message = message[:700]
            warnings.append("Deliberation message truncated to 700 characters")

        intent_value = payload.get("public_intent", payload.get("intent"))
        if not isinstance(intent_value, str) or not intent_value.strip():
            raise ResponseValidationError("Deliberation action needs a non-empty `public_intent`")
        public_intent = intent_value.strip()
        if len(public_intent) > 240:
            public_intent = public_intent[:240]
            warnings.append("Public intent truncated to 240 characters")

        evidence_ids, invalid_ids = _evidence_ids(payload.get("evidence_ids", []))
        warnings.extend(f"Unsupported evidence id ignored: {item}" for item in invalid_ids)
        if "evidence_ids" not in payload:
            warnings.append("Missing `evidence_ids` defaulted to an empty list")

        return (
            cls(
                action=action,
                target_id=target_id,
                message=message,
                evidence_ids=evidence_ids,
                public_intent=public_intent,
            ),
            warnings,
        )


def validate_deliberation_action(
    payload: dict[str, Any],
    *,
    sender_id: str,
    allowed_target_ids: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> tuple[dict[str, Any], list[str]]:
    """Return a normalized action dictionary suitable for an exchange validator."""
    action, warnings = DeliberationAction.from_payload(
        payload,
        sender_id=sender_id,
        allowed_target_ids=allowed_target_ids,
    )
    return asdict(action), warnings


@dataclass
class DecisionRecord:
    """One public, application-validated juror decision snapshot."""

    guilt_probability: float
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
    ) -> tuple[DecisionRecord, list[str]]:
        """Normalize a provider record while preserving protocol warnings."""
        raw_probability = payload.get("guilt_probability", payload.get("probability_of_guilt"))
        if isinstance(raw_probability, bool):
            raise ResponseValidationError("Guilt probability must be numeric")
        try:
            probability = float(raw_probability)
        except (TypeError, ValueError) as exc:
            raise ResponseValidationError("Missing numeric `guilt_probability`") from exc
        if not math.isfinite(probability):
            raise ResponseValidationError("Guilt probability must be finite")
        if 0.0 <= probability <= 1.0:
            probability *= 100.0
        warnings: list[str] = []
        required_fields = {
            "confidence": ("confidence",),
            "evidence_ids": ("evidence_ids",),
            "top_factors": ("top_factors", "key_reasons"),
            "uncertainty": ("uncertainty", "uncertainties"),
            "public_reason": ("public_reason", "public_rationale"),
            "stated_influences": ("stated_influences",),
        }
        for field_name, aliases in required_fields.items():
            if not any(alias in payload for alias in aliases):
                warnings.append(f"Missing `{field_name}` used a normalized fallback")
        clamped = clamp(probability, 0.0, 100.0)
        if clamped != probability:
            warnings.append(f"Probability clamped from {probability} to {clamped}")
        probability = round(clamped, 2)

        raw_confidence = payload.get("confidence", 0.5)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.5
            warnings.append("Invalid confidence replaced with 0.5")
        if confidence > 1.0 and confidence <= 100.0:
            confidence /= 100.0
        confidence = round(clamp(confidence, 0.0, 1.0), 3)

        evidence_ids, invalid_ids = _evidence_ids(payload.get("evidence_ids", []))
        warnings.extend(f"Unsupported evidence id ignored: {item}" for item in invalid_ids)
        top_factors = _string_list(payload.get("top_factors", payload.get("key_reasons", [])), limit=4)
        if not top_factors:
            top_factors = evidence_ids[:3]
        uncertainty_value = payload.get("uncertainty", payload.get("uncertainties", "Evidence remains incomplete."))
        if isinstance(uncertainty_value, list):
            uncertainty = "; ".join(str(item) for item in uncertainty_value[:3])
        else:
            uncertainty = str(uncertainty_value)
        public_reason = str(payload.get("public_reason", payload.get("public_rationale", ""))).strip()
        public_reply = str(
            payload.get("public_reply", payload.get("reply", payload.get("message_to_peers", "")))
        ).strip()
        if not public_reason:
            public_reason = public_reply or "I updated my public assessment using the cited admitted evidence."
            warnings.append("Missing public reason replaced with a neutral fallback")
        raw_vote = payload.get("vote", payload.get("recommended_vote"))
        if not isinstance(raw_vote, str) or not raw_vote.strip():
            raise ResponseValidationError("Decision response needs categorical `vote`")
        vote = raw_vote.strip().lower().replace("-", "_").replace(" ", "_")
        if vote not in VERDICTS:
            raise ResponseValidationError("Vote must be `guilty` or `not_guilty`")

        return (
            cls(
                guilt_probability=probability,
                vote=vote,
                confidence=confidence,
                evidence_ids=evidence_ids,
                invalid_evidence_ids=invalid_ids,
                top_factors=top_factors,
                uncertainty=uncertainty[:400],
                public_reason=public_reason[:700],
                public_reply=public_reply[:700],
                stated_influences=_string_list(payload.get("stated_influences", []), limit=6),
            ),
            warnings,
        )

    @property
    def probability(self) -> float:
        """Compatibility accessor for generic belief-delta calculations."""
        return self.guilt_probability


@dataclass
class JurorState:
    """Mutable application-owned state for one juror."""

    juror_id: str
    label: str
    style: str
    age: int
    gender: str
    baseline_guilt_probability: float | None = None
    baseline_vote: str | None = None
    guilt_probability: float | None = None
    confidence: float | None = None
    vote: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    top_factors: list[str] = field(default_factory=list)
    uncertainty: str = "No assessment has been elicited yet."
    public_reason: str = ""
    public_reply: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self, *, sequence: int, phase: str, source_event_id: str | None = None) -> dict[str, Any]:
        """Return a serializable point on this juror's trajectory."""
        probability = round(self.guilt_probability, 2) if self.guilt_probability is not None else None
        confidence = round(self.confidence, 3) if self.confidence is not None else None
        return {
            "sequence": sequence,
            "phase": phase,
            "source_event_id": source_event_id,
            "guilt_probability": probability,
            "vote": self.vote,
            "confidence": confidence,
            "public_reason": self.public_reason,
            "public_reply": self.public_reply,
        }

    def apply(self, record: DecisionRecord, *, sequence: int, phase: str, event_id: str) -> None:
        """Apply one validated decision record and append its snapshot."""
        if self.baseline_guilt_probability is None:
            self.baseline_guilt_probability = record.guilt_probability
            self.baseline_vote = record.vote
        self.guilt_probability = record.guilt_probability
        self.vote = record.vote
        self.confidence = record.confidence
        self.evidence_ids = list(record.evidence_ids)
        self.top_factors = list(record.top_factors)
        self.uncertainty = record.uncertainty
        self.public_reason = record.public_reason
        self.public_reply = record.public_reply
        self.history.append(self.snapshot(sequence=sequence, phase=phase, source_event_id=event_id))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the current state and full observable trajectory."""
        return asdict(self)

    @property
    def probability(self) -> float | None:
        """Compatibility accessor for generic belief-delta calculations."""
        return self.guilt_probability

    @probability.setter
    def probability(self, value: float | None) -> None:
        self.guilt_probability = value

    @property
    def initial_probability(self) -> float | None:
        """Compatibility accessor for the first model-elicited assessment."""
        return self.baseline_guilt_probability


@dataclass
class InteractionEvent:
    """One conceptual A2A exchange in the application ledger."""

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
    authored_action: dict[str, Any] | None = None
    routing_fallback: bool = False
    routing_fallback_reason: str | None = None
    reply_to_event_id: str | None = None
    reply_metadata: dict[str, Any] = field(default_factory=dict)
    belief_before: float | None = None
    belief_after: float | None = None
    belief_delta: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize one event for JSON, reporting, and comparison."""
        return asdict(self)


def _evidence_ids(value: Any) -> tuple[list[str], list[str]]:
    values = _string_list(value, limit=12)
    valid: list[str] = []
    invalid: list[str] = []
    for item in values:
        if item in CASE["evidence"]:
            if item not in valid:
                valid.append(item)
        else:
            invalid.append(item)
    return valid, invalid


def _string_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values[:limit] if str(item).strip()]
