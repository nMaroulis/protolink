"""Answer text projected from the native runtime stream.

Raw model chunks can contain executable action JSON, reasoning or unfinished
escape sequences. This projection exposes only provisional answer text and
reconciles it with the completed task before declaring success.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from protolink.core.events import RunEvent
from protolink.core.redaction import RedactionPolicy

_REASONING_OPEN = re.compile(r"^\s*<(think|thought)\b[^>]*>", re.IGNORECASE)
_ESCAPES = frozenset('"\\/bfnrt')
_HEX = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class AnswerEvent:
    """One safe update to a run's user-facing answer.

    Append ``content`` for ``delta``; replace the entire displayed text for
    ``replacement``. ``completed`` carries the full authoritative answer and
    occurs only after successful task completion. Other updates are provisional:
    parsing, tool transitions and completion hooks can revise them.

    ``sequence`` belongs to this answer stream; ``source_sequence`` correlates
    the update with a native run event when one exists. Markdown, whitespace and
    Unicode are preserved, subject to the handle's explicit redaction policy.
    """

    type: Literal["delta", "replacement", "completed"]
    content: str
    sequence: int
    task_id: str
    run_id: str | None = None
    agent_name: str | None = None
    source_sequence: int | None = None
    provisional: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible update without internal model payloads."""
        return asdict(self)


class _AnswerProjector:
    """Project one root task; feed unredacted events before persisting them.

    The projector retains the incomplete provider call privately. Known secrets
    are masked across chunk boundaries by withholding a possible matching tail.
    JSON content preceding its discriminator and ambiguous prefixes stay buffered
    until they can be identified safely. No executable action is dispatched here.
    """

    def __init__(self, root_task_id: str, *, redaction_policy: RedactionPolicy | None = None) -> None:
        self.task_id = root_task_id
        self.policy = redaction_policy
        self.run_id: str | None = None
        self.agent_name: str | None = None
        self.source_sequence: int | None = None
        self._sequence = 0
        self._raw = ""
        self._visible = ""
        self._finished = False

    def feed(self, event: RunEvent) -> tuple[AnswerEvent, ...]:
        """Consume a native event and return zero or more safe answer updates."""
        if self._finished or event.task_id != self.task_id:
            return ()
        self.run_id = event.run_id or self.run_id
        self.agent_name = event.agent_name or self.agent_name
        self.source_sequence = event.sequence
        kind = event.payload.get("llm_event_type")
        if kind == "llm_call_started" or event.type == "llm.call.started":
            self._raw = ""
            return self._update("")
        if kind == "llm_chunk":
            content = event.payload.get("content")
            if not isinstance(content, str):
                return ()
            self._raw += content
            candidate = _answer_prefix(self._raw)
            return self._update(self._redact(candidate, complete=False) if candidate is not None else "")
        if kind == "llm_final":
            content = event.payload.get("content")
            if isinstance(content, str):
                # This is already validated final.content, not another action
                # envelope to parse. A JSON/code example here is literal text.
                return self._update(self._redact(self._authoritative(content), complete=True))
        if kind in {
            "llm_retry",
            "llm_parse_error",
            "tool_start",
            "agent_call_start",
            "action_denied",
        } or event.type in {"action.started", "action.denied"}:
            self._raw = ""
            return self._update("")
        return ()

    def finish(self, status: str, output: Any) -> tuple[AnswerEvent, ...]:
        """Reconcile successful text, or withdraw provisional text on failure.

        Structured values and tool results have no implicit text rendering.
        Repeated calls have no effect. Cancellation, rejection and uncertain
        transport outcomes never produce a successful completion event.
        """
        if self._finished:
            return ()
        self._finished = True
        if status != "completed" or not isinstance(output, str):
            self._raw = ""
            return self._update("")
        content = self._redact(self._authoritative(output), complete=True)
        self._raw = ""
        updates = self._update(content)
        return (*updates, self._event("completed", content, provisional=False))

    def _authoritative(self, content: str) -> str:
        # Some native-compatible servers include their reasoning prefix in the
        # final text too. Hooks may append, prepend or replace that text, so
        # equality with the raw call is not a reliable protocol discriminator.
        prefix, body = _leading_reasoning(self._raw)
        if prefix and not _explicit_final(body):
            # Remove the established private prefix even inside a hook wrapper.
            # A hook may also edit it; strip any remaining leading block then.
            content = content.replace(prefix, "", 1)
            _, content = _leading_reasoning(content)
        return content

    def _redact(self, content: str, *, complete: bool) -> str:
        if self.policy is None:
            return content
        if not complete and self.policy.sensitive_values:
            # Hold at least the longest possible incomplete secret. A complete
            # match straddling that boundary must also remain wholly private.
            boundary = max(0, len(content) - max(map(len, self.policy.sensitive_values)) + 1)
            pattern = self.policy._value_pattern
            if pattern is not None:
                for match in pattern.finditer(content):
                    if match.start() < boundary < match.end():
                        boundary = match.start()
                        break
            content = content[:boundary]
        return self.policy.redact(content)

    def _update(self, content: str) -> tuple[AnswerEvent, ...]:
        if content == self._visible:
            return ()
        previous = self._visible
        self._visible = content
        if content.startswith(previous):
            return (self._event("delta", content[len(previous) :]),)
        return (self._event("replacement", content),)

    def _event(
        self, kind: Literal["delta", "replacement", "completed"], content: str, *, provisional: bool = True
    ) -> AnswerEvent:
        self._sequence += 1
        identifiers = {"task_id": self.task_id, "run_id": self.run_id, "agent_name": self.agent_name}
        if self.policy is not None:
            identifiers = self.policy.redact(identifiers)
        return AnswerEvent(
            type=kind,
            content=content,
            sequence=self._sequence,
            task_id=str(identifiers["task_id"]),
            run_id=identifiers["run_id"],
            agent_name=identifiers["agent_name"],
            source_sequence=self.source_sequence,
            provisional=provisional,
        )


def _leading_reasoning(raw: str) -> tuple[str, str]:
    """Split recognized leading reasoning; an unclosed block has no answer."""
    candidate = raw
    while (opening := _REASONING_OPEN.match(candidate)) is not None:
        closing = re.search(rf"</{opening.group(1)}\s*>", candidate[opening.end() :], re.IGNORECASE)
        if closing is None:
            return raw, ""
        candidate = candidate[opening.end() + closing.end() :]
    return raw[: len(raw) - len(candidate)], candidate


def _explicit_final(raw: str) -> bool:
    """Recognize an explicit content boundary after a provider reasoning block."""
    candidate = raw.strip()
    if candidate.startswith("```") and "\n" in candidate and candidate.endswith("```"):
        first, body = candidate.split("\n", 1)
        if first.rstrip("\r ").lower() in {"```", "```json"}:
            candidate = body[:-3].strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and data.get("type") == "final" and isinstance(data.get("content"), str)


def _answer_prefix(raw: str) -> str | None:
    """Return an identifiable answer prefix, withholding ambiguous syntax."""
    candidate = raw
    while True:
        stripped = candidate.lstrip()
        if not stripped:
            return None
        lower = stripped.lower()
        if any(tag.startswith(lower) for tag in ("<think", "<thought")):
            return None
        opening = _REASONING_OPEN.match(candidate)
        if opening is None:
            if lower.startswith(("<think", "<thought")):
                return None  # Incomplete opening tag.
            break
        closing = re.search(rf"</{opening.group(1)}\s*>", candidate[opening.end() :], re.IGNORECASE)
        if closing is None:
            return None
        candidate = candidate[opening.end() + closing.end() :]
    stripped = candidate.lstrip()
    if stripped in {"`", "``"}:
        return None
    if stripped.startswith("```"):
        if "\n" not in stripped:
            return None
        first, body = stripped.split("\n", 1)
        if first.rstrip("\r ").lower() in {"```", "```json"}:
            if not body.strip():
                return None
            if body.lstrip().startswith("{"):
                return _json_answer_prefix(body)
    if stripped.startswith("{"):
        return _json_answer_prefix(stripped)
    return candidate


def _json_answer_prefix(raw: str) -> str | None:
    """Read only root final.content; never search nested objects for answers."""
    decoder = json.JSONDecoder()
    index = len(raw) - len(raw.lstrip()) + 1
    action_type: Any = None
    content: str | None = None
    while index < len(raw):
        index = _skip_space(raw, index)
        if index >= len(raw) or raw[index] in "}":
            break
        try:
            key, index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            break
        if not isinstance(key, str):
            break
        index = _skip_space(raw, index)
        if index >= len(raw) or raw[index] != ":":
            break
        index = _skip_space(raw, index + 1)
        if key == "content" and index < len(raw) and raw[index] == '"':
            content = _json_string_prefix(raw, index)
        try:
            value, index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            break
        if key == "type":
            action_type = value
        index = _skip_space(raw, index)
        if index >= len(raw) or raw[index] != ",":
            break
        index += 1
    return content if action_type == "final" else None


def _skip_space(raw: str, index: int) -> int:
    while index < len(raw) and raw[index] in " \t\r\n":
        index += 1
    return index


def _json_string_prefix(raw: str, start: int) -> str:
    """Decode complete string characters, holding split escapes/surrogate pairs."""
    index = start + 1
    while index < len(raw):
        char = raw[index]
        if char == '"':
            break
        if ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF:
            break
        if char != "\\":
            index += 1
            continue
        if index + 1 >= len(raw):
            break
        escaped = raw[index + 1]
        if escaped in _ESCAPES:
            index += 2
            continue
        if escaped != "u" or index + 6 > len(raw):
            break
        digits = raw[index + 2 : index + 6]
        if any(char not in _HEX for char in digits):
            break
        value = int(digits, 16)
        width = 6
        if 0xD800 <= value <= 0xDBFF:
            if raw[index + 6 : index + 8] != "\\u" or index + 12 > len(raw):
                break
            digits = raw[index + 8 : index + 12]
            if any(char not in _HEX for char in digits):
                break
            low = int(digits, 16)
            if not 0xDC00 <= low <= 0xDFFF:
                break
            width = 12
        elif 0xDC00 <= value <= 0xDFFF:
            break
        index += width
    return json.loads('"' + raw[start + 1 : index] + '"')
