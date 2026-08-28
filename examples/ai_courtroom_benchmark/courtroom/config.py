"""Validated, portable configuration for the courtroom benchmark."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EVIDENCE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


class _ConfigModel(BaseModel):
    """Base class that rejects misspelled or credential-like extra keys."""

    model_config = ConfigDict(extra="forbid")


def _validate_id(value: str, *, field_name: str = "id") -> str:
    normalized = value.strip()
    if not _ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must start with a lowercase letter and contain only "
            "lowercase letters, digits, underscores, or hyphens"
        )
    return normalized


def _canonical_id(value: str) -> str:
    """Normalize a configured ID the same way provider-authored votes are matched."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class DecisionConfig(_ConfigModel):
    """Binary decision vocabulary used throughout one benchmark case."""

    probability_label: str
    positive_vote: str
    negative_vote: str
    tie_vote: str
    positive_side_id: str
    negative_side_id: str

    @field_validator("probability_label")
    @classmethod
    def _nonempty_probability_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("probability_label cannot be empty")
        return value

    @field_validator(
        "positive_vote",
        "negative_vote",
        "tie_vote",
        "positive_side_id",
        "negative_side_id",
    )
    @classmethod
    def _ids(cls, value: str, info: Any) -> str:
        return _validate_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _distinct_values(self) -> DecisionConfig:
        if self.positive_vote == self.negative_vote:
            raise ValueError("positive_vote and negative_vote must be different")
        if _canonical_id(self.positive_vote) == _canonical_id(self.negative_vote):
            raise ValueError("positive_vote and negative_vote must remain different after normalization")
        if self.tie_vote not in self.vote_ids:
            raise ValueError("tie_vote must equal positive_vote or negative_vote")
        if self.positive_side_id == self.negative_side_id:
            raise ValueError("positive_side_id and negative_side_id must be different")
        return self

    @property
    def vote_ids(self) -> tuple[str, str]:
        """Return the positive and negative vote IDs in stable order."""
        return self.positive_vote, self.negative_vote


class EvidenceConfig(_ConfigModel):
    """One ordered item of admitted evidence."""

    id: str
    title: str
    text: str

    @field_validator("id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        value = value.strip()
        if not _EVIDENCE_ID_PATTERN.fullmatch(value):
            raise ValueError("evidence id contains unsupported characters")
        return value

    @field_validator("title", "text")
    @classmethod
    def _nonempty_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value


class SideConfig(_ConfigModel):
    """One advocacy side and the vote it is trying to obtain."""

    id: str
    label: str
    advocate_label: str
    objective: str
    target_vote: str
    system_prompt: str

    @field_validator("id", "target_vote")
    @classmethod
    def _ids(cls, value: str, info: Any) -> str:
        return _validate_id(value, field_name=info.field_name)

    @field_validator("label", "advocate_label", "objective", "system_prompt")
    @classmethod
    def _nonempty_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value


class JudgeConfig(_ConfigModel):
    """The neutral judge agent used by every paired leg."""

    id: str
    label: str
    system_prompt: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("label", "system_prompt")
    @classmethod
    def _nonempty_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value


class JurorConfig(_ConfigModel):
    """A fixed evaluator persona plus reference-fixture controls."""

    id: str
    label: str
    background: str
    system_prompt: str
    reference_prior: float = Field(ge=0.0, le=100.0)
    reference_receptiveness: float = Field(ge=0.0, le=1.0)
    reference_threshold: float = Field(ge=0.0, le=100.0)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("label", "background", "system_prompt")
    @classmethod
    def _nonempty_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value


class ProcedureStageConfig(_ConfigModel):
    """One stage in which the configured side agents may speak."""

    id: str
    label: str
    instruction: str
    speakers: list[str] = Field(min_length=1)
    include_prior_arguments: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("label", "instruction")
    @classmethod
    def _nonempty_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value

    @field_validator("speakers")
    @classmethod
    def _speaker_ids(cls, values: list[str]) -> list[str]:
        normalized = [_validate_id(value, field_name="speaker id") for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("stage speakers must be unique")
        return normalized


class ProcedureConfig(_ConfigModel):
    """Ordered advocacy stages for each leg of the benchmark."""

    stages: list[ProcedureStageConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_stage_ids(self) -> ProcedureConfig:
        stage_ids = [stage.id for stage in self.stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("procedure stage ids must be unique")
        return self


class ReferenceFixtureConfig(_ConfigModel):
    """Optional signed evidence effects used only by the offline fixture."""

    evidence_signals: dict[str, float] = Field(default_factory=dict)

    @field_validator("evidence_signals")
    @classmethod
    def _finite_signals(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("reference_fixture evidence signals must be finite")
        return values


class CaseConfig(_ConfigModel):
    """Complete portable definition of one binary courtroom case."""

    schema_version: Literal["1.0"] = "1.0"
    id: str
    title: str
    summary: str
    question: str
    charge: str
    burden: str
    elements: list[str] = Field(min_length=1)
    decision: DecisionConfig
    evidence: list[EvidenceConfig] = Field(min_length=1)
    sides: list[SideConfig] = Field(min_length=2, max_length=2)
    judge: JudgeConfig
    jurors: list[JurorConfig] = Field(min_length=1)
    procedure: ProcedureConfig
    reference_fixture: ReferenceFixtureConfig | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @field_validator("schema_version", "title", "summary", "question", "charge", "burden")
    @classmethod
    def _nonempty_text(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value

    @field_validator("elements")
    @classmethod
    def _elements(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("case elements cannot be empty")
        return normalized

    @model_validator(mode="after")
    def _cross_references(self) -> CaseConfig:
        evidence_ids = [item.id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence ids must be unique")

        side_ids = [side.id for side in self.sides]
        if len(set(side_ids)) != 2:
            raise ValueError("a case must contain exactly two distinct sides")
        if set(side_ids) != {self.decision.positive_side_id, self.decision.negative_side_id}:
            raise ValueError("decision side ids must name the two configured sides")

        sides = {side.id: side for side in self.sides}
        if sides[self.decision.positive_side_id].target_vote != self.decision.positive_vote:
            raise ValueError("positive_side_id must target positive_vote")
        if sides[self.decision.negative_side_id].target_vote != self.decision.negative_vote:
            raise ValueError("negative_side_id must target negative_vote")
        if {side.target_vote for side in self.sides} != set(self.decision.vote_ids):
            raise ValueError("the two sides must target different configured votes")

        participant_ids = [self.judge.id, *side_ids, *(juror.id for juror in self.jurors)]
        if len(set(participant_ids)) != len(participant_ids):
            raise ValueError("judge, side, and juror ids must be globally unique")

        side_id_set = set(side_ids)
        for stage in self.procedure.stages:
            unknown_speakers = sorted(set(stage.speakers).difference(side_id_set))
            if unknown_speakers:
                raise ValueError(f"stage `{stage.id}` references unknown side speakers: {', '.join(unknown_speakers)}")
            if set(stage.speakers) != side_id_set:
                raise ValueError(f"stage `{stage.id}` must give both configured sides one speaking opportunity")

        if self.reference_fixture is not None:
            unknown_evidence = sorted(set(self.reference_fixture.evidence_signals).difference(evidence_ids))
            if unknown_evidence:
                raise ValueError("reference_fixture contains unknown evidence ids: " + ", ".join(unknown_evidence))
        return self

    @property
    def evidence_by_id(self) -> dict[str, EvidenceConfig]:
        """Return admitted evidence indexed without losing source ordering."""
        return {item.id: item for item in self.evidence}

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        """Return admitted evidence IDs in configured order."""
        return tuple(item.id for item in self.evidence)

    @property
    def sides_by_id(self) -> dict[str, SideConfig]:
        """Return the two advocacy sides indexed by stable ID."""
        return {side.id: side for side in self.sides}

    @property
    def jurors_by_id(self) -> dict[str, JurorConfig]:
        """Return the controlled juror panel indexed by stable ID."""
        return {juror.id: juror for juror in self.jurors}

    def canonical_vote(self, value: Any) -> str | None:
        """Normalize a provider vote to one configured ID, if possible."""
        if not isinstance(value, str):
            return None
        normalized = _canonical_id(value)
        votes = {_canonical_id(vote): vote for vote in self.decision.vote_ids}
        return votes.get(normalized)


def load_case_config(path: str | Path) -> CaseConfig:
    """Load and validate a case JSON file without reading credentials."""
    source = Path(path).expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read case config `{source}`: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Case config `{source}` is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Case config must contain one top-level JSON object")
    return CaseConfig.model_validate(raw)


load_case = load_case_config


__all__ = [
    "CaseConfig",
    "DecisionConfig",
    "EvidenceConfig",
    "JudgeConfig",
    "JurorConfig",
    "ProcedureConfig",
    "ProcedureStageConfig",
    "ReferenceFixtureConfig",
    "SideConfig",
    "load_case",
    "load_case_config",
]
