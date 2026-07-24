"""Deterministic offline model for the fictional AI Liability Tribunal."""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar

from protolink.llms import MockLLM

from .case_data import JUROR_PROFILES, PANEL_JUROR_IDS
from .schemas import clamp, extract_json_object

REQUEST_START = "<courtroom-request>"
REQUEST_END = "</courtroom-request>"

# The reference fixture owns this decision rule. The application records the
# categorical vote returned by the agent and never derives it from probability.
_FIRM_CONVICTION_POINT = 78.0

_EVIDENCE_GUILT_SIGNAL = {
    "E1": 3.0,
    "E2": 5.0,
    "E3": 7.0,
    "E4": -6.0,
    "E5": 1.0,
    "E6": 3.0,
    "E7": 4.0,
}

_SOURCE_GUILT_SIGNAL = {
    "victim_lawyer": 2.6,
    "manufacturer": -2.6,
    "software_engineer": 1.4,
    "safety_regulator": -0.4,
    "insurance": 0.0,
    "accident_investigator": 0.8,
}

_INITIAL_FOCUS = {
    "juror_evelyn": {
        "offset": 7.0,
        "evidence_ids": ["E1", "E4", "E7"],
        "reason": (
            "The event recorder establishes the failure sequence, while the altered construction scene and replay "
            "matrix keep the causal chain from being a one-cause story."
        ),
        "uncertainty": "The physical sequence is clearer than what Aster Vale knew before deployment.",
    },
    "juror_malik": {
        "offset": 9.0,
        "evidence_ids": ["E2", "E3", "E6"],
        "reason": (
            "The warning, calibration mismatch, and known connectivity problem raise institutional-control questions, "
            "but the record still leaves room for individual scapegoating."
        ),
        "uncertainty": "A process failure does not by itself identify who knowingly accepted the risk.",
    },
    "juror_anika": {
        "offset": 10.0,
        "evidence_ids": ["E2", "E5", "E6"],
        "reason": (
            "The safety ticket and remote-operator assumption show how several people relied on safeguards that did "
            "not survive the real scene."
        ),
        "uncertainty": "Hindsight can make a distributed failure look more foreseeable than it was.",
    },
    "juror_ruben": {
        "offset": 8.0,
        "evidence_ids": ["E2", "E3", "E5"],
        "reason": (
            "A validated calibration was not the calibration deployed, and the signing path lacked isolation. That is "
            "a release-governance failure, not merely a perception bug."
        ),
        "uncertainty": "The admitted record does not show who approved or noticed the production mismatch.",
    },
    "juror_sofia": {
        "offset": 9.0,
        "evidence_ids": ["E2", "E3", "E7"],
        "reason": (
            "The warning, artifact mismatch, and reconstruction form a concerning timeline, although each document "
            "also supports a narrower innocent explanation."
        ),
        "uncertainty": "A coherent timeline can still overstate what the company actually knew.",
    },
    "juror_solo": {
        "offset": 10.0,
        "evidence_ids": ["E2", "E3", "E4", "E7"],
        "reason": (
            "The release mismatch matters, but the altered road scene and reconstruction show that software and "
            "infrastructure interacted."
        ),
        "uncertainty": "The record supports several contributors and leaves the company's state of knowledge disputed.",
    },
}

_TARGET_PREFERENCES = {
    "juror_evelyn": ("juror_ruben", "juror_anika", "juror_sofia", "juror_malik"),
    "juror_malik": ("juror_ruben", "juror_evelyn", "juror_sofia", "juror_anika"),
    "juror_anika": ("juror_malik", "juror_ruben", "juror_evelyn", "juror_sofia"),
    "juror_ruben": ("juror_sofia", "juror_anika", "juror_evelyn", "juror_malik"),
    "juror_sofia": ("juror_malik", "juror_ruben", "juror_evelyn", "juror_anika"),
}

_DELIBERATION_MOVES: dict[str, tuple[dict[str, Any], ...]] = {
    "juror_evelyn": (
        {
            "action": "challenge_claim",
            "message": (
                "Walk me through why E3 proves a knowing company decision rather than a bad automated deployment. E4 "
                "shows the crash scene itself was materially different from the approved map."
            ),
            "evidence_ids": ["E3", "E4"],
            "public_intent": "Test whether the release-control failure establishes corporate knowledge.",
        },
        {
            "action": "seek_clarification",
            "message": (
                "E7 changes sharply across both calibration and map conditions. Which link in that interaction was "
                "Aster Vale realistically able to prevent before the collision?"
            ),
            "evidence_ids": ["E7"],
            "public_intent": "Separate physical contribution from a preventable company decision.",
        },
    ),
    "juror_malik": (
        {
            "action": "ask_question",
            "message": (
                "E3 shows a shared signing token, but it does not name the person who selected C-91. Does that make "
                "the company more accountable for weak controls, or does it leave too much uncertainty for guilt?"
            ),
            "evidence_ids": ["E3"],
            "public_intent": "Test whether systemic control and proof of knowledge are being conflated.",
        },
        {
            "action": "challenge_claim",
            "message": (
                "Regulatory approval in E5 reviewed the disclosed design, not the C-91 mismatch. Why should that "
                "approval excuse a production system that differed from the validated safety report?"
            ),
            "evidence_ids": ["E3", "E5"],
            "public_intent": "Challenge the use of regulatory approval as a complete defence.",
        },
    ),
    "juror_anika": (
        {
            "action": "seek_clarification",
            "message": (
                "The permit in E6 depended on a rapid human response, yet earlier outages were already known. At what "
                "point does continued reliance on that safeguard become foreseeable organizational risk?"
            ),
            "evidence_ids": ["E6"],
            "public_intent": "Clarify whether reliance on the remote operator remained reasonable.",
        },
        {
            "action": "concede",
            "message": (
                "Your point about E4 is fair: the road scene materially contributed. I still think E2 and E6 ask "
                "whether Aster Vale normalized warnings instead of containing them."
            ),
            "evidence_ids": ["E2", "E4", "E6"],
            "public_intent": "Acknowledge a shared cause while testing the remaining governance concern.",
        },
    ),
    "juror_ruben": (
        {
            "action": "share_evidence",
            "message": (
                "E2 says the release was cleared after C-90 passed, but E3 says production ran C-91 through a shared "
                "token. The safeguard did not merely fail; the release path bypassed the artifact that was validated."
            ),
            "evidence_ids": ["E2", "E3"],
            "public_intent": "Focus the discussion on deployment governance rather than a single model error.",
        },
        {
            "action": "attempt_persuasion",
            "message": (
                "E5 shows Aster Vale deliberately let vision veto radar, and E1 shows that exact arbitration delayed "
                "braking. Approval may explain the choice, but it does not erase ownership of the safety control."
            ),
            "evidence_ids": ["E1", "E5"],
            "public_intent": "Connect the disclosed design choice to the observed braking failure.",
        },
    ),
    "juror_sofia": (
        {
            "action": "attempt_persuasion",
            "message": (
                "E7 is not a story about software or roadworks alone: the unsafe result becomes dominant when C-91 "
                "meets the crash-scene map. E3 asks why the unvalidated half of that interaction reached production."
            ),
            "evidence_ids": ["E3", "E7"],
            "public_intent": "Synthesize the interaction evidence and return attention to company control.",
        },
        {
            "action": "ask_question",
            "message": (
                "E4 gives us a serious outside contributor, while E6 gives us earlier notice that another safeguard "
                "could disappear. Which fact most changes whether the combined risk was foreseeable?"
            ),
            "evidence_ids": ["E4", "E6"],
            "public_intent": "Surface the jury's central disagreement about foreseeability.",
        },
    ),
}


class ReferenceCourtroomLLM(MockLLM):
    """Role-specific fixture that exercises real ProtoLink inference and A2A calls."""

    provider: ClassVar[str] = "reference"

    def __init__(self, *, role: str, seed: int) -> None:
        super().__init__(model="courtroom-reference-v2")
        self.role = role
        self.seed = seed

    def mock_call(self, last_user_msg: str, system_prompt: str) -> dict[str, Any]:
        """Return one valid ProtoLink final action with JSON application content."""
        del system_prompt
        request = _request_from_prompt(last_user_msg)
        kind = str(request.get("kind", "")).strip().lower()
        handlers = {
            "opening": lambda: self._opening(),
            "closing": lambda: self._closing(),
            "examination": lambda: self._examination(request),
            "initial_assessment": lambda: self._initial_assessment(request),
            "belief_update": lambda: self._belief_update(request),
            "deliberation_plan": lambda: self._deliberation_turn(request),
            "deliberation_turn": lambda: self._deliberation_turn(request),
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

    def _opening(self) -> dict[str, Any]:
        if self.role == "victim_lawyer":
            return {
                "statement": (
                    "This was not an unknowable bolt from the blue. Aster Vale had a blocked safety ticket, deployed a "
                    "different calibration from the one it validated, and kept relying on remote intervention after "
                    "earlier outages. The question is not whether roadworks contributed; it is whether the company "
                    "knowingly sent an inadequately controlled release onto public streets."
                ),
                "evidence_ids": ["E2", "E3", "E6"],
                "thesis": (
                    "Aster Vale controlled the safeguards and accepted warning signs that those safeguards failed."
                ),
            }
        return {
            "statement": (
                "Lina Ortega's death was tragic, but tragedy is not guilt. The reported defect was cleared when C-90 "
                "passed every rerun, the braking design was disclosed and approved, and an unreported road change plus "
                "a network outage defeated separate safeguards. The evidence supports an interacting accident, not a "
                "criminally negligent deployment."
            ),
            "evidence_ids": ["E2", "E4", "E5", "E6"],
            "thesis": "Approved safeguards encountered an unforeseeable combination of external failures.",
        }

    def _closing(self) -> dict[str, Any]:
        if self.role == "victim_lawyer":
            return {
                "statement": (
                    "The company cleared C-90 and deployed C-91. Its release path let a shared automation token select "
                    "an unvalidated artifact, while the fleet continued through known connectivity gaps. Roadworks "
                    "contributed, but E7 shows that C-91 made that known class of difficult scene dramatically less "
                    "safe. Organizational complexity is not a defence when the organization controlled the release."
                ),
                "evidence_ids": ["E2", "E3", "E6", "E7"],
            }
        return {
            "statement": (
                "The record never identifies who selected C-91 or proves that a decision-maker knew it differed from "
                "the validated bundle. The regulator approved the disclosed braking architecture, the contractor "
                "altered the scene, and the network removed remote support. Those are not excuses; they are reasonable "
                "doubts about the charged company's state of knowledge."
            ),
            "evidence_ids": ["E3", "E4", "E5", "E6"],
        }

    def _examination(self, request: dict[str, Any]) -> dict[str, Any]:
        examiner = str(request.get("examiner", "")).strip().lower()
        examination_type = str(request.get("examination_type", "")).strip().lower()
        direct = examiner in {"victim_lawyer", "prosecution"} or examination_type == "direct"

        if self.role == "software_engineer":
            if direct:
                return {
                    "statement": (
                        "I filed E2 because the late-braking pattern was safety-relevant. I agreed the ticket could be "
                        "closed after C-90 passed the reruns. E3 shows the collision vehicle instead received C-91. My "
                        "credential appears because the build bot used a token issued in my name; that record does not "
                        "show that I selected or approved C-91."
                    ),
                    "evidence_ids": ["E2", "E3"],
                    "credibility_note": "The engineer separates her warning from an organizational release decision.",
                }
            return {
                "statement": (
                    "Yes, the defect I reported was successfully rerun with C-90, so the original ticket was not "
                    "simply ignored. I cannot testify that any executive knew C-91 was on this vehicle. I can say that "
                    "allowing automation to deploy through a shared signing token made that question needlessly hard "
                    "to answer."
                ),
                "evidence_ids": ["E2", "E3"],
                "credibility_note": "The engineer confirms both remediation evidence and weak release attribution.",
            }

        if self.role == "safety_regulator":
            if direct:
                return {
                    "statement": (
                        "The permit accepted the radar-veto rule in E5 only as part of a safety case that included "
                        "remote operator escalation. E6 shows that escalation did not arrive in time. We received "
                        "aggregate outage data, but Aster Vale did not identify this site as having repeated losses of "
                        "coverage."
                    ),
                    "evidence_ids": ["E5", "E6"],
                    "credibility_note": "The regulator describes approval as conditional on a wider safety system.",
                }
            return {
                "statement": (
                    "Aster Vale disclosed the braking architecture, and our review found a legitimate benefit from "
                    "fewer phantom emergency stops. The permit did not require a perfect network. At the time, the "
                    "aggregate outage report did not establish that this particular collision scenario was imminent."
                ),
                "evidence_ids": ["E5", "E6"],
                "credibility_note": (
                    "The regulator confirms disclosure and the limited specificity of prior outage data."
                ),
            }

        if self.role == "insurance":
            if direct:
                return {
                    "statement": (
                        "Our company funded E7, and that financial interest should be visible. The protocol was fixed "
                        "before testing and the raw runs are available. The crash combination stopped safely in only 6 "
                        "of 20 trials, while C-90 on the corrected map stopped in 19. Both calibration and scene data "
                        "materially changed the result."
                    ),
                    "evidence_ids": ["E7"],
                    "credibility_note": (
                        "The insurer discloses sponsorship and relies on reproducible comparative results."
                    ),
                }
            return {
                "statement": (
                    "The same reconstruction also shows why a software-only account is incomplete. C-90 fell from 19 "
                    "safe stops to 14 under the crash-scene map, and C-91 improved from 6 to 16 when the map was "
                    "corrected. Our testing allocates contributing risk; it does not identify anyone's state of mind."
                ),
                "evidence_ids": ["E4", "E7"],
                "credibility_note": (
                    "The insurer acknowledges that infrastructure changes independently affected safety."
                ),
            }

        if self.role == "accident_investigator":
            if direct:
                return {
                    "statement": (
                        "E1 establishes the sequence: vision grouped Lina with the work zone, radar detected motion, "
                        "and the arbitration rule delayed braking. E7 reproduces the highest failure rate when C-91 "
                        "and the crash-scene map are combined. That supports an interacting technical cause rather "
                        "than an unexplained sensor anomaly."
                    ),
                    "evidence_ids": ["E1", "E7"],
                    "credibility_note": "The investigator identifies the immediate mechanism without assigning guilt.",
                }
            return {
                "statement": (
                    "E4 is a material contributor. Moving the arrow board and omitting the map update reduced usable "
                    "observation, and even C-90 performed worse with the crash-scene map. I cannot infer corporate "
                    "knowledge from physical reconstruction, and I cannot reduce this collision to a single root cause."
                ),
                "evidence_ids": ["E4", "E7"],
                "credibility_note": "The investigator distinguishes causal contribution from legal culpability.",
            }

        return {
            "statement": "This reference witness has no role-specific testimony for the requested examination.",
            "evidence_ids": [],
        }

    def _initial_assessment(self, request: dict[str, Any]) -> dict[str, Any]:
        profile = self._juror_profile()
        focus = _INITIAL_FOCUS[self.role]
        request_id = _request_id(request, "initial")
        probability = clamp(
            float(profile["reference_prior"])
            + float(focus["offset"])
            + _stable_noise(self.role, request_id, self.seed),
            1.0,
            99.0,
        )
        return _decision_payload(
            probability=probability,
            vote=_fixture_vote(probability),
            evidence_ids=list(focus["evidence_ids"]),
            public_reason=str(focus["reason"]),
            public_reply="",
            uncertainty=str(focus["uncertainty"]),
            stated_influences=[],
        )

    def _belief_update(self, request: dict[str, Any]) -> dict[str, Any]:
        profile = self._juror_profile()
        current_state = _current_state(request)
        current_probability = _current_probability(current_state, profile)
        incoming = _incoming_message(request)
        message_id = str(incoming["message_id"])
        peer_message = _is_peer_message(incoming)

        if peer_message:
            delta = _peer_content_delta(incoming, profile)
        else:
            delta = _public_record_delta(incoming, profile, request)
        delta += _stable_noise(self.role, message_id, self.seed, amplitude=0.36)
        probability = round(clamp(current_probability + delta, 1.0, 99.0), 2)

        previous_evidence = _string_list(current_state.get("evidence_ids", []))
        evidence_ids = list(dict.fromkeys([*previous_evidence, *incoming["evidence_ids"]]))[-5:]
        if not evidence_ids:
            evidence_ids = list(_INITIAL_FOCUS[self.role]["evidence_ids"])
        direction = "raises" if delta > 0.35 else "reduces" if delta < -0.35 else "does not materially change"
        source_label = str(incoming["source_label"])
        evidence_phrase = ", ".join(evidence_ids[-3:])

        if peer_message:
            public_reason = (
                f"{source_label}'s authored message {direction} my concern. Its useful part is the claim grounded in "
                f"{evidence_phrase}, not any unstated confidence or vote."
            )
            if delta > 0.35:
                public_reply = (
                    f"{source_label}, that connection makes the company-control evidence harder to dismiss. I am "
                    "giving the cited record more weight."
                )
            elif delta < -0.35:
                public_reply = (
                    f"{source_label}, your distinction between contribution and proof of knowledge is persuasive. It "
                    "weakens the inference I was drawing."
                )
            else:
                public_reply = (
                    f"{source_label}, I understand the point, but it does not resolve the remaining conflict in "
                    f"{evidence_phrase}."
                )
            uncertainty = "A peer's argument can expose an assumption, but agreement itself is not new evidence."
        else:
            public_reason = (
                f"After the public statement from {source_label}, {evidence_phrase} {direction} my assessment of "
                "whether Aster Vale knowingly accepted the deployment risk."
            )
            public_reply = ""
            uncertainty = (
                "The admitted record still separates a serious systems failure from proof of firm culpability."
            )

        influence_ids = [message_id] if abs(delta) >= 0.35 else []
        return _decision_payload(
            probability=probability,
            vote=_fixture_vote(probability),
            evidence_ids=evidence_ids,
            public_reason=public_reason,
            public_reply=public_reply,
            uncertainty=uncertainty,
            stated_influences=influence_ids,
        )

    def _deliberation_turn(self, request: dict[str, Any]) -> dict[str, Any]:
        self._juror_profile()
        allowed_targets = _allowed_target_ids(request, sender_id=self.role)
        if not allowed_targets:
            allowed_targets = [juror_id for juror_id in PANEL_JUROR_IDS if juror_id != self.role]
        target_id = _choose_target(self.role, allowed_targets, request, self.seed)
        moves = _DELIBERATION_MOVES.get(self.role, _DELIBERATION_MOVES["juror_sofia"])
        round_index = _round_index(request)
        move = moves[round_index % len(moves)]
        return {
            "action": move["action"],
            "target_id": target_id,
            "message": move["message"],
            "evidence_ids": list(move["evidence_ids"]),
            "public_intent": move["public_intent"],
        }

    def _ballot(self, request: dict[str, Any]) -> dict[str, Any]:
        profile = self._juror_profile()
        current = _current_state(request)
        probability = _current_probability(current, profile)
        raw_vote = str(current.get("vote", "")).strip().lower().replace("-", "_").replace(" ", "_")
        vote = raw_vote if raw_vote in {"guilty", "not_guilty"} else _fixture_vote(probability)
        evidence_ids = _string_list(current.get("evidence_ids", [])) or list(_INITIAL_FOCUS[self.role]["evidence_ids"])
        return _decision_payload(
            probability=probability,
            vote=vote,
            evidence_ids=evidence_ids,
            public_reason=str(current.get("public_reason") or _INITIAL_FOCUS[self.role]["reason"]),
            public_reply=str(current.get("public_reply", "")),
            uncertainty=str(current.get("uncertainty") or _INITIAL_FOCUS[self.role]["uncertainty"]),
            stated_influences=_string_list(current.get("stated_influences", [])),
            confidence=_optional_float(current.get("confidence")),
        )

    @staticmethod
    def _judgment(request: dict[str, Any]) -> dict[str, Any]:
        ballots = request.get("ballots", [])
        if not isinstance(ballots, list):
            ballots = []
        guilty = sum(1 for ballot in ballots if isinstance(ballot, dict) and ballot.get("vote") == "guilty")
        not_guilty = len(ballots) - guilty
        verdict = "guilty" if guilty > not_guilty else "not_guilty"
        return {
            "statement": (
                f"The jury returns {guilty} guilty and {not_guilty} not guilty. The procedural verdict is "
                f"{verdict.replace('_', ' ')}. This is the result of the admitted record and the communication "
                "process, not proof that the panel observed the synthetic ground truth."
            ),
            "evidence_ids": [],
            "verdict": verdict,
            "guilty_votes": guilty,
            "not_guilty_votes": not_guilty,
        }

    def _juror_profile(self) -> dict[str, Any]:
        if self.role not in JUROR_PROFILES:
            raise ValueError(f"Reference role `{self.role}` is not a juror")
        return JUROR_PROFILES[self.role]


def _decision_payload(
    *,
    probability: float,
    vote: str,
    evidence_ids: list[str],
    public_reason: str,
    public_reply: str,
    uncertainty: str,
    stated_influences: list[str],
    confidence: float | None = None,
) -> dict[str, Any]:
    probability = round(clamp(float(probability), 0.0, 100.0), 2)
    if confidence is None:
        confidence = clamp(0.56 + abs(probability - _FIRM_CONVICTION_POINT) / 100.0, 0.54, 0.90)
    return {
        "guilt_probability": probability,
        "vote": vote,
        "confidence": round(clamp(float(confidence), 0.0, 1.0), 3),
        "evidence_ids": list(dict.fromkeys(evidence_ids))[-5:],
        "top_factors": list(dict.fromkeys(evidence_ids))[-3:],
        "uncertainty": uncertainty,
        "public_reason": public_reason,
        "public_reply": public_reply,
        "stated_influences": list(dict.fromkeys(stated_influences))[-6:],
    }


def _fixture_vote(probability: float) -> str:
    return "guilty" if probability >= _FIRM_CONVICTION_POINT else "not_guilty"


def _current_state(request: dict[str, Any]) -> dict[str, Any]:
    state = request.get("current_state", request.get("prior_public_state", {}))
    return state if isinstance(state, dict) else {}


def _current_probability(current_state: dict[str, Any], profile: dict[str, Any]) -> float:
    value = current_state.get(
        "guilt_probability",
        current_state.get("probability_of_guilt", current_state.get("probability")),
    )
    if isinstance(value, bool) or value is None:
        return float(profile["reference_prior"])
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(profile["reference_prior"])


def _incoming_message(request: dict[str, Any]) -> dict[str, Any]:
    raw = request.get("message", request.get("incoming_message", {}))
    if isinstance(raw, str):
        raw = {"statement": raw}
    if not isinstance(raw, dict):
        raw = {}

    authored: dict[str, Any] = {}
    for candidate in (
        request.get("authored_action"),
        request.get("incoming_action"),
        raw.get("authored_action"),
        raw.get("action_payload"),
        raw.get("action") if isinstance(raw.get("action"), dict) else None,
    ):
        if isinstance(candidate, dict):
            authored = candidate
            break

    statement = authored.get("message")
    if not isinstance(statement, str) or not statement.strip():
        statement = raw.get("statement", raw.get("content", raw.get("message", "")))
    if not isinstance(statement, str):
        statement = str(statement)

    raw_evidence = authored.get("evidence_ids", raw.get("evidence_ids", []))
    source = str(
        raw.get(
            "source",
            raw.get("source_id", request.get("sender_id", request.get("source", "public_record"))),
        )
    )
    source_label = str(raw.get("source_label", raw.get("sender_label", source.replace("_", " ").title())))
    message_type = str(raw.get("type", request.get("message_type", request.get("event_kind", ""))))
    action_name = authored.get("action", raw.get("action", ""))
    if isinstance(action_name, dict):
        action_name = action_name.get("action", "")

    return {
        "source": source,
        "source_label": source_label,
        "type": message_type,
        "statement": statement.strip(),
        "evidence_ids": _string_list(raw_evidence),
        "action": str(action_name),
        "public_intent": str(authored.get("public_intent", raw.get("public_intent", ""))),
        "message_id": raw.get(
            "message_id",
            authored.get("message_id", request.get("message_id", request.get("event_id", "message"))),
        ),
    }


def _is_peer_message(incoming: dict[str, Any]) -> bool:
    source = str(incoming["source"])
    message_type = str(incoming["type"]).lower()
    return source.startswith("juror_") or "peer" in message_type or bool(incoming["action"])


def _public_record_delta(
    incoming: dict[str, Any],
    profile: dict[str, Any],
    request: dict[str, Any],
) -> float:
    source = _source_role(str(incoming["source"]), str(incoming["type"]))
    source_signal = _SOURCE_GUILT_SIGNAL.get(source, 0.0)
    evidence_signal = _average_evidence_signal(incoming["evidence_ids"])
    source_weight = float(profile.get("reference_weights", {}).get(source, 1.0))
    message_type = str(incoming["type"]).lower()
    stage_bonus = 0.0
    if "closing" in message_type:
        stage_bonus = 1.2 if source == "victim_lawyer" else -1.2 if source == "manufacturer" else 0.0
    position = _integer(request.get("order_position"), 0)
    total = max(_integer(request.get("order_total"), 1), 1)
    recency = 1.0 if total <= 1 else 0.90 + 0.20 * position / max(total - 1, 1)
    return clamp((source_signal + evidence_signal * 0.55 + stage_bonus) * source_weight * recency, -7.0, 7.0)


def _peer_content_delta(incoming: dict[str, Any], profile: dict[str, Any]) -> float:
    # Intentionally use only the authored message, action, and cited evidence.
    # Speaker probability, confidence, and vote are neither read nor accepted as inputs.
    text = f"{incoming['statement']} {incoming['public_intent']}".lower()
    evidence_signal = _average_evidence_signal(incoming["evidence_ids"]) * 0.72
    guilt_terms = (
        "release control",
        "release path",
        "unvalidated",
        "c-91",
        "block release",
        "known outage",
        "earlier outage",
        "company control",
        "owned",
        "safeguard",
        "foreseeable",
        "bypassed",
        "different calibration",
    )
    doubt_terms = (
        "road scene",
        "roadwork",
        "contractor",
        "map",
        "approved",
        "regulatory approval",
        "resolved",
        "does not name",
        "does not identify",
        "uncertainty for guilt",
        "single cause",
        "outside contributor",
    )
    lexical_signal = 0.72 * sum(term in text for term in guilt_terms)
    lexical_signal -= 0.72 * sum(term in text for term in doubt_terms)
    receptiveness = float(profile.get("reference_receptiveness", 0.5))
    return clamp((evidence_signal + lexical_signal) * receptiveness, -6.0, 6.0)


def _average_evidence_signal(evidence_ids: list[str]) -> float:
    signals = [_EVIDENCE_GUILT_SIGNAL[item] for item in evidence_ids if item in _EVIDENCE_GUILT_SIGNAL]
    return sum(signals) / len(signals) if signals else 0.0


def _source_role(source: str, message_type: str) -> str:
    haystack = f"{source} {message_type}".lower()
    for role in _SOURCE_GUILT_SIGNAL:
        if role in haystack:
            return role
    if "prosecution" in haystack:
        return "victim_lawyer"
    if "defense" in haystack:
        return "manufacturer"
    return source


def _allowed_target_ids(request: dict[str, Any], *, sender_id: str) -> list[str]:
    candidates = request.get(
        "allowed_target_ids",
        request.get("allowed_targets", request.get("targets", [])),
    )
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, (list, tuple, set)):
        return []
    targets: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            target = candidate.get("id", candidate.get("target_id", candidate.get("juror_id", "")))
        else:
            target = candidate
        target_id = str(target).strip()
        if target_id and target_id != sender_id and target_id not in targets:
            targets.append(target_id)
    return targets


def _choose_target(role: str, allowed_targets: list[str], request: dict[str, Any], seed: int) -> str:
    preferences = [target for target in _TARGET_PREFERENCES.get(role, ()) if target in allowed_targets]
    pool = preferences or sorted(allowed_targets)
    if not pool:
        raise ValueError(f"No deliberation target is available to `{role}`")
    offset = _stable_index(role, _request_id(request, "deliberation"), seed, len(pool))
    return pool[offset]


def _round_index(request: dict[str, Any]) -> int:
    for key in ("round_index", "round", "turn_index"):
        if key in request:
            value = _integer(request.get(key), 0)
            return max(0, value - 1) if key == "round" and value > 0 else max(0, value)
    return 0


def _request_id(request: dict[str, Any], fallback: str) -> str:
    return str(request.get("message_id", request.get("event_id", request.get("request_id", fallback))))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


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


def _stable_noise(
    role: str,
    message_id: str,
    seed: int,
    *,
    amplitude: float = 0.8,
) -> float:
    digest = hashlib.sha256(f"{role}|{message_id}|{seed}".encode()).digest()
    unit = int.from_bytes(digest[:4], "big") / (2**32 - 1)
    return round((unit - 0.5) * amplitude, 3)


def _stable_index(role: str, message_id: str, seed: int, size: int) -> int:
    digest = hashlib.sha256(f"target|{role}|{message_id}|{seed}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % size
