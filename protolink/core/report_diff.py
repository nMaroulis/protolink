"""Normalized run-report comparison for regression testing.

The helpers in this module compare two :class:`RunReport` objects, typically
captured after their runs finish.
They do not execute agents, models, tools, transports, or side effects. Runtime
generated identifiers and timestamps are normalized inside known ProtoLink
envelopes so a fresh candidate run can be compared with a stored baseline
without hiding application-owned identifiers in tool payloads.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Literal, TypeAlias, cast

from protolink.core.events import RunEvent
from protolink.core.redaction import DEFAULT_REDACTION_POLICY, RedactionPolicy
from protolink.core.report import RunReplay, RunReport

RunReportSection = Literal[
    "context",
    "context_manifests",
    "events",
    "actions",
    "approvals",
    "artifacts",
    "metrics",
    "final_task",
    "metadata",
]
"""Sections of a durable run report that can participate in a comparison."""

RunReportDifferenceKind = Literal["added", "removed", "changed"]
"""Kinds of structural differences emitted by :func:`diff_run_reports`."""

RunReportSource: TypeAlias = RunReport | RunReplay | Mapping[str, Any] | Iterable[RunEvent | dict[str, Any]]
"""Input shapes accepted by the run-report comparison helpers."""

ALL_RUN_REPORT_SECTIONS: tuple[RunReportSection, ...] = (
    "context",
    "context_manifests",
    "events",
    "actions",
    "approvals",
    "artifacts",
    "metrics",
    "final_task",
    "metadata",
)
"""Default report sections compared by :func:`diff_run_reports`."""

_MISSING = object()
_SKIP = object()


@dataclass(frozen=True)
class RunReportTolerance:
    """Numeric tolerance applied to values at one report path.

    ``path`` is an RFC 6901 JSON Pointer pattern. The ``*`` segment extension
    matches exactly one dictionary key or list index, for example
    ``/events/*/payload/latency_ms``. Rules are evaluated in declaration order
    and the first matching rule wins.

    Args:
        path: JSON Pointer pattern identifying numeric values.
        absolute_tolerance: Maximum absolute difference accepted by
            :func:`math.isclose`.
        relative_tolerance: Maximum relative difference accepted by
            :func:`math.isclose`.
    """

    path: str
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0

    def __post_init__(self) -> None:
        """Validate the path pattern and tolerance values."""
        _parse_pointer_pattern(self.path)
        for name, value in (
            ("absolute_tolerance", self.absolute_tolerance),
            ("relative_tolerance", self.relative_tolerance),
        ):
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
            object.__setattr__(self, name, numeric)


@dataclass(frozen=True)
class RunReportDiffConfig:
    """Configuration for normalized run-report comparison.

    Args:
        sections: Report sections to compare.
        normalize_volatile: Canonicalize known runtime-generated identifiers
            and timestamps. Application-owned values inside tool payloads and
            report metadata remain exact.
        ignore_paths: Additional RFC 6901 JSON Pointer patterns to omit. A
            ``*`` segment matches exactly one key or index. Ignoring a
            container omits its complete subtree.
        tolerances: Ordered numeric tolerance rules. Booleans are never treated
            as numbers.
    """

    sections: tuple[RunReportSection, ...] = ALL_RUN_REPORT_SECTIONS
    normalize_volatile: bool = True
    ignore_paths: tuple[str, ...] = ()
    tolerances: tuple[RunReportTolerance, ...] = ()

    def __post_init__(self) -> None:
        """Normalize iterable inputs and validate public configuration."""
        sections = tuple(self.sections)
        unknown = tuple(section for section in sections if section not in ALL_RUN_REPORT_SECTIONS)
        if unknown:
            raise ValueError(f"Unknown run-report sections: {unknown!r}")
        if len(set(sections)) != len(sections):
            raise ValueError("Run-report sections must not contain duplicates")

        ignore_paths = tuple(str(path) for path in self.ignore_paths)
        for path in ignore_paths:
            _parse_pointer_pattern(path)

        tolerances = tuple(self.tolerances)
        if any(not isinstance(tolerance, RunReportTolerance) for tolerance in tolerances):
            raise TypeError("tolerances must contain RunReportTolerance objects")

        object.__setattr__(self, "sections", sections)
        object.__setattr__(self, "ignore_paths", ignore_paths)
        object.__setattr__(self, "tolerances", tolerances)


@dataclass(frozen=True)
class RunReportDifference:
    """One structured difference between normalized report projections."""

    section: RunReportSection
    path: str
    kind: RunReportDifferenceKind
    baseline: Any = field(default=_MISSING, repr=False)
    candidate: Any = field(default=_MISSING, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this difference without conflating missing and ``None``."""
        data: dict[str, Any] = {
            "section": self.section,
            "path": self.path,
            "kind": self.kind,
        }
        if self.baseline is not _MISSING:
            data["baseline"] = self.baseline
        if self.candidate is not _MISSING:
            data["candidate"] = self.candidate
        return data


@dataclass(frozen=True)
class RunReportDiff:
    """Structured result of comparing a baseline and candidate report."""

    differences: tuple[RunReportDifference, ...] = ()
    compared_sections: tuple[RunReportSection, ...] = ALL_RUN_REPORT_SECTIONS
    ignored_paths: tuple[str, ...] = ()

    @property
    def matches(self) -> bool:
        """Return whether the normalized reports contain no differences."""
        return not self.differences

    @property
    def changed_sections(self) -> tuple[RunReportSection, ...]:
        """Return changed sections in comparison order."""
        changed = {difference.section for difference in self.differences}
        return tuple(section for section in self.compared_sections if section in changed)

    def to_dict(
        self,
        *,
        redaction_policy: RedactionPolicy | None = None,
    ) -> dict[str, Any]:
        """Serialize the result, optionally masking secrets in diff values."""
        serialized_differences = [difference.to_dict() for difference in self.differences]
        if redaction_policy is not None:
            serialized_differences = [
                _redact_difference(difference, redaction_policy) for difference in serialized_differences
            ]
        data = {
            "matches": self.matches,
            "difference_count": len(self.differences),
            "changed_sections": list(self.changed_sections),
            "compared_sections": list(self.compared_sections),
            "ignored_paths": list(self.ignored_paths),
            "differences": serialized_differences,
        }
        return data

    def format(
        self,
        *,
        max_differences: int = 20,
        redaction_policy: RedactionPolicy | None = DEFAULT_REDACTION_POLICY,
    ) -> str:
        """Render a concise deterministic summary for terminals and assertions."""
        if max_differences < 0:
            raise ValueError("max_differences must be non-negative")
        if self.matches:
            return "Run reports match after normalization."

        serialized = self.to_dict(redaction_policy=redaction_policy)
        serialized_differences = serialized["differences"]
        section_text = ", ".join(self.changed_sections)
        lines = [
            f"Run reports differ: {len(self.differences)} difference(s) across {section_text}.",
        ]
        for difference in serialized_differences[:max_differences]:
            kind = str(difference["kind"]).upper()
            detail = _format_difference_values(difference)
            lines.append(f"- {kind} {difference['path']}{detail}")
        remaining = len(self.differences) - min(len(self.differences), max_differences)
        if remaining:
            lines.append(f"... {remaining} additional difference(s) omitted.")
        return "\n".join(lines)


def normalize_run_report(
    source: RunReportSource,
    *,
    config: RunReportDiffConfig | None = None,
) -> dict[str, Any]:
    """Return a deterministic report projection suitable for comparison.

    The source is never mutated. Known runtime identifiers are canonicalized
    per report so their relationships remain visible while freshly generated
    values do not create false regressions.
    """
    active_config = config or RunReportDiffConfig()
    report = _coerce_report(source)
    serialized = report.to_dict()
    projection = {section: serialized.get(section) for section in active_config.sections}
    normalizer = _ReportNormalizer(active_config)
    normalizer.prepare_identifier_occurrences(projection)
    normalized = normalizer.normalize(projection)
    if normalized is _SKIP:
        return {}
    if not isinstance(normalized, dict):  # pragma: no cover - projection is always a dict
        raise TypeError("Normalized run-report projection must be a dictionary")
    return normalized


def diff_run_reports(
    baseline: RunReportSource,
    candidate: RunReportSource,
    *,
    config: RunReportDiffConfig | None = None,
) -> RunReportDiff:
    """Compare baseline and candidate run reports after normalization."""
    active_config = config or RunReportDiffConfig()
    baseline_projection = normalize_run_report(baseline, config=active_config)
    candidate_projection = normalize_run_report(candidate, config=active_config)
    differences: list[RunReportDifference] = []
    _diff_values(
        baseline_projection,
        candidate_projection,
        path=(),
        config=active_config,
        differences=differences,
    )
    return RunReportDiff(
        differences=tuple(differences),
        compared_sections=active_config.sections,
        ignored_paths=active_config.ignore_paths,
    )


def assert_run_matches(
    baseline: RunReportSource,
    candidate: RunReportSource,
    *,
    config: RunReportDiffConfig | None = None,
) -> RunReportDiff:
    """Assert that two run reports match after normalization.

    Returns:
        The successful structured comparison result.

    Raises:
        AssertionError: The normalized reports differ.
    """
    result = diff_run_reports(baseline, candidate, config=config)
    if not result.matches:
        raise AssertionError(result.format())
    return result


class _ReportNormalizer:
    """Recursively normalize one report projection without mutating it."""

    def __init__(self, config: RunReportDiffConfig) -> None:
        self.config = config
        self.ignore_patterns = tuple(_parse_pointer_pattern(path) for path in config.ignore_paths)
        self.identifiers: dict[str, dict[str, str]] = {}
        self.identifier_occurrences: dict[tuple[str, str], int] = {}

    def prepare_identifier_occurrences(self, value: Any) -> None:
        """Count equality groups before replacing volatile identifiers."""
        self.identifier_occurrences.clear()
        self._count_identifier_occurrences(value)

    def _count_identifier_occurrences(
        self,
        value: Any,
        path: tuple[str, ...] = (),
        *,
        runtime_event: bool = False,
    ) -> None:
        if self._ignored(path):
            return

        if isinstance(value, Mapping) and len(path) == 2 and path[0] == "events":
            runtime_event = _is_runtime_event_mapping(value)

        if self.config.normalize_volatile:
            category = _volatile_identifier_category(path, runtime_event=runtime_event)
            if category is not None and value is not None:
                namespace = _identifier_namespace(category)
                key = (namespace, _canonical_json(value))
                self.identifier_occurrences[key] = self.identifier_occurrences.get(key, 0) + 1
                return

        if isinstance(value, Mapping):
            for raw_key in sorted(value, key=lambda item: str(item)):
                self._count_identifier_occurrences(
                    value[raw_key],
                    (*path, str(raw_key)),
                    runtime_event=runtime_event,
                )
            return

        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                self._count_identifier_occurrences(
                    item,
                    (*path, str(index)),
                    runtime_event=runtime_event,
                )

    def normalize(
        self,
        value: Any,
        path: tuple[str, ...] = (),
        *,
        runtime_event: bool = False,
    ) -> Any:
        """Normalize one value at ``path``."""
        if self._ignored(path):
            return _SKIP

        if isinstance(value, Mapping) and len(path) == 2 and path[0] == "events":
            runtime_event = _is_runtime_event_mapping(value)

        if self.config.normalize_volatile:
            category = _volatile_identifier_category(path, runtime_event=runtime_event)
            if category is not None and value is not None:
                return self._canonical_identifier(category, value)
            if _is_volatile_scalar(path, runtime_event=runtime_event) and value is not None:
                explicitly_tolerated = (
                    _is_number(value) and _tolerance_for_path(path, self.config.tolerances) is not None
                )
                if not explicitly_tolerated:
                    return f"<{_volatile_scalar_label(path, runtime_event=runtime_event)}>"

        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key in sorted(value, key=lambda item: str(item)):
                key = str(raw_key)
                normalized = self.normalize(
                    value[raw_key],
                    (*path, key),
                    runtime_event=runtime_event,
                )
                if normalized is not _SKIP:
                    result[key] = normalized
            return result

        if isinstance(value, (list, tuple)):
            result_list: list[Any] = []
            for index, item in enumerate(value):
                normalized = self.normalize(
                    item,
                    (*path, str(index)),
                    runtime_event=runtime_event,
                )
                if normalized is not _SKIP:
                    result_list.append(normalized)
            return result_list

        if isinstance(value, (set, frozenset)):
            normalized_items = [
                self.normalize(
                    item,
                    (*path, "*"),
                    runtime_event=runtime_event,
                )
                for item in value
            ]
            return sorted(
                (item for item in normalized_items if item is not _SKIP),
                key=_canonical_json,
            )

        return _json_compatible_scalar(value)

    def _ignored(self, path: tuple[str, ...]) -> bool:
        if not path:
            return False
        return any(_pattern_matches_prefix(pattern, path) for pattern in self.ignore_patterns)

    def _canonical_identifier(self, category: str, value: Any) -> str:
        category = _identifier_namespace(category)
        serialized = _canonical_json(value)
        if self.identifier_occurrences.get((category, serialized), 1) < 2:
            # Opaque singleton IDs do not carry a relationship. Keeping one
            # constant per namespace also prevents unrelated insertions from
            # renumbering later aligned items.
            return f"<{category}>"
        category_values = self.identifiers.setdefault(category, {})
        if serialized not in category_values:
            category_values[serialized] = f"<{category}:{len(category_values) + 1}>"
        return category_values[serialized]


def _coerce_report(source: RunReportSource) -> RunReport:
    if isinstance(source, RunReplay):
        return source.report
    if isinstance(source, RunReport):
        return source
    if isinstance(source, Mapping):
        return RunReport.from_dict({str(key): value for key, value in source.items()})
    if isinstance(source, (str, bytes)):
        raise TypeError("Run-report sources cannot be strings or bytes")
    try:
        return RunReport.from_events(source)
    except TypeError as exc:
        raise TypeError("Expected RunReport, RunReplay, serialized report mapping, or run-event iterable") from exc


def _diff_values(
    baseline: Any,
    candidate: Any,
    *,
    path: tuple[str, ...],
    config: RunReportDiffConfig,
    differences: list[RunReportDifference],
) -> None:
    if isinstance(baseline, dict) and isinstance(candidate, dict):
        keys = sorted(set(baseline).union(candidate))
        for key in keys:
            child_path = (*path, key)
            if key not in baseline:
                _append_difference(
                    differences,
                    path=child_path,
                    kind="added",
                    candidate=candidate[key],
                )
            elif key not in candidate:
                _append_difference(
                    differences,
                    path=child_path,
                    kind="removed",
                    baseline=baseline[key],
                )
            else:
                _diff_values(
                    baseline[key],
                    candidate[key],
                    path=child_path,
                    config=config,
                    differences=differences,
                )
        return

    if isinstance(baseline, list) and isinstance(candidate, list):
        if _uses_semantic_alignment(path):
            _diff_aligned_sequences(
                baseline,
                candidate,
                path=path,
                config=config,
                differences=differences,
            )
        else:
            _diff_positional_sequences(
                baseline,
                candidate,
                path=path,
                config=config,
                differences=differences,
            )
        return

    if _values_equal(baseline, candidate, path=path, config=config):
        return
    _append_difference(
        differences,
        path=path,
        kind="changed",
        baseline=baseline,
        candidate=candidate,
    )


def _diff_positional_sequences(
    baseline: Sequence[Any],
    candidate: Sequence[Any],
    *,
    path: tuple[str, ...],
    config: RunReportDiffConfig,
    differences: list[RunReportDifference],
) -> None:
    shared = min(len(baseline), len(candidate))
    for index in range(shared):
        _diff_values(
            baseline[index],
            candidate[index],
            path=(*path, str(index)),
            config=config,
            differences=differences,
        )
    for index in range(shared, len(baseline)):
        _append_difference(
            differences,
            path=(*path, str(index)),
            kind="removed",
            baseline=baseline[index],
        )
    for index in range(shared, len(candidate)):
        _append_difference(
            differences,
            path=(*path, str(index)),
            kind="added",
            candidate=candidate[index],
        )


def _diff_aligned_sequences(
    baseline: Sequence[Any],
    candidate: Sequence[Any],
    *,
    path: tuple[str, ...],
    config: RunReportDiffConfig,
    differences: list[RunReportDifference],
) -> None:
    baseline_base_keys = [_semantic_item_key(path, item) for item in baseline]
    candidate_base_keys = [_semantic_item_key(path, item) for item in candidate]
    repeated_keys = {
        key
        for key in set(baseline_base_keys).union(candidate_base_keys)
        if baseline_base_keys.count(key) > 1 or candidate_base_keys.count(key) > 1
    }
    baseline_keys = [
        (*key, _canonical_json(item)) if key in repeated_keys else key
        for key, item in zip(baseline_base_keys, baseline, strict=True)
    ]
    candidate_keys = [
        (*key, _canonical_json(item)) if key in repeated_keys else key
        for key, item in zip(candidate_base_keys, candidate, strict=True)
    ]
    matcher = SequenceMatcher(None, baseline_keys, candidate_keys, autojunk=False)

    for tag, baseline_start, baseline_end, candidate_start, candidate_end in matcher.get_opcodes():
        if tag == "equal":
            for baseline_index, candidate_index in zip(
                range(baseline_start, baseline_end),
                range(candidate_start, candidate_end),
                strict=True,
            ):
                _diff_values(
                    baseline[baseline_index],
                    candidate[candidate_index],
                    path=(*path, str(candidate_index)),
                    config=config,
                    differences=differences,
                )
            continue

        if tag == "delete":
            for baseline_index in range(baseline_start, baseline_end):
                _append_difference(
                    differences,
                    path=(*path, str(baseline_index)),
                    kind="removed",
                    baseline=baseline[baseline_index],
                )
            continue

        if tag == "insert":
            for candidate_index in range(candidate_start, candidate_end):
                _append_difference(
                    differences,
                    path=(*path, str(candidate_index)),
                    kind="added",
                    candidate=candidate[candidate_index],
                )
            continue

        baseline_indexes = list(range(baseline_start, baseline_end))
        candidate_indexes = list(range(candidate_start, candidate_end))
        shared = min(len(baseline_indexes), len(candidate_indexes))
        for offset in range(shared):
            baseline_index = baseline_indexes[offset]
            candidate_index = candidate_indexes[offset]
            _diff_values(
                baseline[baseline_index],
                candidate[candidate_index],
                path=(*path, str(candidate_index)),
                config=config,
                differences=differences,
            )
        for baseline_index in baseline_indexes[shared:]:
            _append_difference(
                differences,
                path=(*path, str(baseline_index)),
                kind="removed",
                baseline=baseline[baseline_index],
            )
        for candidate_index in candidate_indexes[shared:]:
            _append_difference(
                differences,
                path=(*path, str(candidate_index)),
                kind="added",
                candidate=candidate[candidate_index],
            )


def _append_difference(
    differences: list[RunReportDifference],
    *,
    path: tuple[str, ...],
    kind: RunReportDifferenceKind,
    baseline: Any = _MISSING,
    candidate: Any = _MISSING,
) -> None:
    if not path:
        raise ValueError("Run-report differences require a section path")
    section = cast(RunReportSection, path[0])
    differences.append(
        RunReportDifference(
            section=section,
            path=_json_pointer(path),
            kind=kind,
            baseline=baseline,
            candidate=candidate,
        )
    )


def _values_equal(
    baseline: Any,
    candidate: Any,
    *,
    path: tuple[str, ...],
    config: RunReportDiffConfig,
) -> bool:
    if _is_number(baseline) and _is_number(candidate):
        tolerance = _tolerance_for_path(path, config.tolerances)
        if tolerance is None:
            return bool(baseline == candidate)
        return _numbers_close(baseline, candidate, tolerance)

    if type(baseline) is not type(candidate):
        return False

    return bool(baseline == candidate)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numbers_close(
    baseline: int | float,
    candidate: int | float,
    tolerance: RunReportTolerance,
) -> bool:
    """Compare numeric values without coercing arbitrarily large integers."""
    if baseline == candidate:
        return True
    if isinstance(baseline, float) and not math.isfinite(baseline):
        return False
    if isinstance(candidate, float) and not math.isfinite(candidate):
        return False

    try:
        baseline_decimal = Decimal(str(baseline))
        candidate_decimal = Decimal(str(candidate))
        difference = abs(baseline_decimal - candidate_decimal)
        scale = max(abs(baseline_decimal), abs(candidate_decimal))
        allowed = max(
            Decimal(str(tolerance.absolute_tolerance)),
            Decimal(str(tolerance.relative_tolerance)) * scale,
        )
    except (InvalidOperation, ValueError):
        return False

    return difference <= allowed


def _tolerance_for_path(
    path: tuple[str, ...],
    tolerances: tuple[RunReportTolerance, ...],
) -> RunReportTolerance | None:
    for tolerance in tolerances:
        pattern = _parse_pointer_pattern(tolerance.path)
        if _pattern_matches_exact(pattern, path):
            return tolerance
    return None


def _uses_semantic_alignment(path: tuple[str, ...]) -> bool:
    return path in {
        ("context_manifests",),
        ("events",),
        ("actions",),
        ("approvals",),
        ("artifacts",),
        ("metrics",),
    }


def _semantic_item_key(path: tuple[str, ...], item: Any) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return ("value", _canonical_json(item))

    section = path[0]
    if section == "events":
        payload = item.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        action = payload_dict.get("action")
        if not isinstance(action, dict):
            request = payload_dict.get("request")
            action = request.get("action") if isinstance(request, dict) else None
        action_dict = action if isinstance(action, dict) else {}
        return tuple(
            _stable_key_part(value)
            for value in (
                "event",
                item.get("type"),
                item.get("agent_name"),
                item.get("step"),
                payload_dict.get("llm_event_type"),
                action_dict.get("kind"),
                action_dict.get("name"),
            )
        )
    if section == "actions":
        return tuple(_stable_key_part(value) for value in ("action", item.get("kind"), item.get("name")))
    if section == "approvals":
        request = item.get("request")
        request_dict = request if isinstance(request, dict) else {}
        action = request_dict.get("action")
        action_dict = action if isinstance(action, dict) else {}
        return tuple(
            _stable_key_part(value)
            for value in (
                "approval",
                item.get("type"),
                action_dict.get("kind"),
                action_dict.get("name"),
            )
        )
    if section == "artifacts":
        return tuple(
            _stable_key_part(value)
            for value in (
                "artifact",
                item.get("kind"),
                item.get("name"),
                item.get("media_type"),
            )
        )
    if section == "metrics":
        return tuple(
            _stable_key_part(value)
            for value in (
                "metric",
                item.get("step"),
                item.get("provider"),
                item.get("model"),
            )
        )
    return tuple(
        _stable_key_part(value)
        for value in (
            "manifest",
            item.get("agent_name"),
            item.get("provider"),
            item.get("model"),
        )
    )


def _stable_key_part(value: Any) -> str:
    return _canonical_json(value)


def _format_difference_values(difference: dict[str, Any]) -> str:
    values: list[str] = []
    if "baseline" in difference:
        values.append(f"baseline={_preview(difference['baseline'])}")
    if "candidate" in difference:
        values.append(f"candidate={_preview(difference['candidate'])}")
    return ": " + ", ".join(values) if values else ""


def _redact_difference(
    difference: dict[str, Any],
    policy: RedactionPolicy,
) -> dict[str, Any]:
    """Redact values while retaining the sensitive key encoded in ``path``."""
    redacted = dict(difference)
    path = str(difference.get("path") or "")
    path_segments = (
        tuple(segment.replace("~1", "/").replace("~0", "~") for segment in path[1:].split("/"))
        if path.startswith("/")
        else ()
    )
    sensitive_path = any(policy.is_sensitive_key(segment) for segment in path_segments)
    for side in ("baseline", "candidate"):
        if side not in redacted:
            continue
        if sensitive_path:
            redacted[side] = policy.replacement
        else:
            redacted[side] = policy.redact(redacted[side])
    return redacted


def _json_compatible_scalar(value: Any) -> Any:
    """Return a scalar that the CLI JSON renderer can serialize."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _ReportNormalizer(RunReportDiffConfig()).normalize(value.to_dict())
        except (TypeError, ValueError):
            return str(value)
    try:
        json.dumps(value, allow_nan=False)
        return value
    except (TypeError, ValueError):
        return str(value)


def _preview(value: Any, *, max_length: int = 180) -> str:
    rendered = _canonical_json(value)
    if len(rendered) <= max_length:
        return rendered
    return rendered[: max_length - 3] + "..."


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        return repr(value)


def _json_pointer(path: tuple[str, ...]) -> str:
    if not path:
        return ""
    return "/" + "/".join(segment.replace("~", "~0").replace("/", "~1") for segment in path)


def _parse_pointer_pattern(pattern: str) -> tuple[str, ...]:
    if not isinstance(pattern, str) or not pattern.startswith("/") or pattern == "/":
        raise ValueError("Path patterns must be non-root RFC 6901 JSON Pointers")
    raw_segments = pattern[1:].split("/")
    for segment in raw_segments:
        index = 0
        while index < len(segment):
            if segment[index] != "~":
                index += 1
                continue
            if index + 1 >= len(segment) or segment[index + 1] not in {"0", "1"}:
                raise ValueError(f"Invalid RFC 6901 escape in path pattern: {pattern!r}")
            index += 2
    return tuple(segment.replace("~1", "/").replace("~0", "~") for segment in raw_segments)


def _pattern_matches_exact(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    return len(pattern) == len(path) and all(
        expected == "*" or expected == actual for expected, actual in zip(pattern, path, strict=True)
    )


def _pattern_matches_prefix(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    if len(pattern) > len(path):
        return False
    return all(expected == "*" or expected == actual for expected, actual in zip(pattern, path, strict=False))


_IDENTIFIER_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (category, _parse_pointer_pattern(pattern))
    for category, pattern in (
        ("run", "/context/run_id"),
        ("session", "/context/session_id"),
        ("trace", "/context/trace_id"),
        ("run", "/context/parent_run_id"),
        ("run", "/context_manifests/*/run_id"),
        ("session", "/context_manifests/*/session_id"),
        ("event", "/events/*/event_id"),
        ("run", "/events/*/run_id"),
        ("task", "/events/*/task_id"),
        ("span", "/events/*/span_id"),
        ("span", "/events/*/parent_span_id"),
        ("action", "/events/*/action_id"),
        ("action", "/events/*/parent_action_id"),
        ("delegation", "/events/*/delegation_id"),
        ("event", "/events/*/payload/event_id"),
        ("run", "/events/*/payload/run_id"),
        ("task", "/events/*/payload/task_id"),
        ("span", "/events/*/payload/span_id"),
        ("span", "/events/*/payload/parent_span_id"),
        ("action", "/events/*/payload/action_id"),
        ("action", "/events/*/payload/parent_action_id"),
        ("delegation", "/events/*/payload/delegation_id"),
        ("approval", "/events/*/payload/request_id"),
        ("run", "/events/*/payload/manifest/run_id"),
        ("session", "/events/*/payload/manifest/session_id"),
        ("run", "/events/*/payload/metadata/manifest/run_id"),
        ("session", "/events/*/payload/metadata/manifest/session_id"),
        ("run", "/events/*/payload/metadata/run_id"),
        ("session", "/events/*/payload/metadata/session_id"),
        ("trace", "/events/*/payload/metadata/trace_id"),
        ("run", "/events/*/payload/metadata/run_context/run_id"),
        ("session", "/events/*/payload/metadata/run_context/session_id"),
        ("trace", "/events/*/payload/metadata/run_context/trace_id"),
        ("run", "/events/*/payload/metadata/run_context/parent_run_id"),
        ("task", "/events/*/payload/metadata/task/id"),
        ("message", "/events/*/payload/metadata/task/messages/*/id"),
        ("artifact", "/events/*/payload/metadata/task/artifacts/*/id"),
        ("action", "/events/*/payload/metadata/task/artifacts/*/action_id"),
        ("run", "/events/*/payload/metadata/task/metadata/run_id"),
        ("session", "/events/*/payload/metadata/task/metadata/session_id"),
        ("trace", "/events/*/payload/metadata/task/metadata/trace_id"),
        ("run", "/events/*/payload/metadata/task/metadata/parent_run_id"),
        ("run", "/events/*/payload/metadata/task/metadata/run_context/run_id"),
        ("session", "/events/*/payload/metadata/task/metadata/run_context/session_id"),
        ("trace", "/events/*/payload/metadata/task/metadata/run_context/trace_id"),
        ("run", "/events/*/payload/metadata/task/metadata/run_context/parent_run_id"),
        ("action", "/events/*/payload/action/action_id"),
        ("artifact", "/events/*/payload/action/artifacts/*/id"),
        ("action", "/events/*/payload/action/artifacts/*/action_id"),
        ("approval", "/events/*/payload/request/request_id"),
        ("run", "/events/*/payload/request/run_id"),
        ("action", "/events/*/payload/request/action/action_id"),
        ("artifact", "/events/*/payload/request/action/artifacts/*/id"),
        ("action", "/events/*/payload/request/action/artifacts/*/action_id"),
        ("approval", "/events/*/payload/decision/request_id"),
        ("artifact", "/events/*/payload/artifact/id"),
        ("action", "/events/*/payload/artifact/action_id"),
        ("action", "/actions/*/action_id"),
        ("artifact", "/actions/*/artifacts/*/id"),
        ("action", "/actions/*/artifacts/*/action_id"),
        ("approval", "/approvals/*/request/request_id"),
        ("run", "/approvals/*/request/run_id"),
        ("action", "/approvals/*/request/action/action_id"),
        ("artifact", "/approvals/*/request/action/artifacts/*/id"),
        ("action", "/approvals/*/request/action/artifacts/*/action_id"),
        ("approval", "/approvals/*/decision/request_id"),
        ("artifact", "/artifacts/*/id"),
        ("action", "/artifacts/*/action_id"),
        ("run", "/metrics/*/run_id"),
        ("session", "/metrics/*/session_id"),
        ("trace", "/metrics/*/trace_id"),
        ("task", "/final_task/id"),
        ("message", "/final_task/messages/*/id"),
        ("artifact", "/final_task/artifacts/*/id"),
        ("action", "/final_task/artifacts/*/action_id"),
        ("run", "/final_task/metadata/run_id"),
        ("session", "/final_task/metadata/session_id"),
        ("trace", "/final_task/metadata/trace_id"),
        ("run", "/final_task/metadata/parent_run_id"),
        ("run", "/final_task/metadata/run_context/run_id"),
        ("session", "/final_task/metadata/run_context/session_id"),
        ("trace", "/final_task/metadata/run_context/trace_id"),
        ("run", "/final_task/metadata/run_context/parent_run_id"),
    )
)

_VOLATILE_SCALAR_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (label, _parse_pointer_pattern(pattern))
    for label, pattern in (
        ("timestamp", "/context/created_at"),
        ("timestamp", "/context_manifests/*/created_at"),
        ("timestamp", "/events/*/timestamp"),
        ("sequence", "/events/*/sequence"),
        ("timestamp", "/events/*/payload/timestamp"),
        ("timestamp", "/events/*/payload/created_at"),
        ("timestamp", "/events/*/payload/updated_at"),
        ("timestamp", "/events/*/payload/manifest/created_at"),
        ("timestamp", "/events/*/payload/metadata/manifest/created_at"),
        ("timestamp", "/events/*/payload/metadata/run_context/created_at"),
        ("timestamp", "/events/*/payload/metadata/task/created_at"),
        ("timestamp", "/events/*/payload/metadata/task/messages/*/timestamp"),
        ("timestamp", "/events/*/payload/metadata/task/artifacts/*/timestamp"),
        ("timestamp", "/events/*/payload/metadata/task/metadata/state_history/*/timestamp"),
        ("timestamp", "/events/*/payload/metadata/task/metadata/run_context/created_at"),
        ("timestamp", "/events/*/payload/action/created_at"),
        ("timestamp", "/events/*/payload/action/artifacts/*/timestamp"),
        ("timestamp", "/events/*/payload/request/created_at"),
        ("timestamp", "/events/*/payload/request/action/created_at"),
        ("timestamp", "/events/*/payload/request/action/artifacts/*/timestamp"),
        ("timestamp", "/events/*/payload/decision/decided_at"),
        ("timestamp", "/events/*/payload/artifact/timestamp"),
        ("timestamp", "/actions/*/created_at"),
        ("timestamp", "/actions/*/artifacts/*/timestamp"),
        ("timestamp", "/approvals/*/request/created_at"),
        ("timestamp", "/approvals/*/request/action/created_at"),
        ("timestamp", "/approvals/*/request/action/artifacts/*/timestamp"),
        ("timestamp", "/approvals/*/decision/decided_at"),
        ("timestamp", "/artifacts/*/timestamp"),
        ("timestamp", "/final_task/created_at"),
        ("timestamp", "/final_task/messages/*/timestamp"),
        ("timestamp", "/final_task/artifacts/*/timestamp"),
        ("timestamp", "/final_task/metadata/state_history/*/timestamp"),
        ("timestamp", "/final_task/metadata/run_context/created_at"),
    )
)


def _volatile_identifier_category(
    path: tuple[str, ...],
    *,
    runtime_event: bool,
) -> str | None:
    if not runtime_event and _is_event_payload_path(path):
        return None
    for category, pattern in _IDENTIFIER_PATHS:
        if _pattern_matches_exact(pattern, path):
            return category
    return None


def _is_volatile_scalar(
    path: tuple[str, ...],
    *,
    runtime_event: bool,
) -> bool:
    if not runtime_event and _is_event_payload_path(path):
        return False
    if _is_runtime_summary_path(path):
        return runtime_event
    if _is_runtime_duration_path(path):
        return path[0] == "metrics" or runtime_event
    return any(_pattern_matches_exact(pattern, path) for _, pattern in _VOLATILE_SCALAR_PATHS)


def _volatile_scalar_label(
    path: tuple[str, ...],
    *,
    runtime_event: bool,
) -> str:
    if _is_runtime_summary_path(path) and runtime_event:
        return "summary"
    if _is_runtime_duration_path(path) and (path[0] == "metrics" or runtime_event):
        return "duration"
    for label, pattern in _VOLATILE_SCALAR_PATHS:
        if _pattern_matches_exact(pattern, path):
            return label
    return "volatile"


def _is_runtime_event_mapping(value: Mapping[str, Any]) -> bool:
    """Return whether an event was normalized from a task-stream envelope."""
    metadata = value.get("metadata")
    return isinstance(metadata, Mapping) and bool(metadata.get("source_type"))


def _is_event_payload_path(path: tuple[str, ...]) -> bool:
    return len(path) >= 3 and path[0] == "events" and path[2] == "payload"


def _identifier_namespace(category: str) -> str:
    if category in {"action", "delegation", "span"}:
        # Runtime agent calls intentionally reuse one correlation value across
        # these fields, so their equality belongs to one namespace.
        return "correlation"
    return category


def _is_runtime_summary_path(path: tuple[str, ...]) -> bool:
    return len(path) == 3 and path[0] == "events" and path[2] == "summary"


def _is_runtime_duration_path(path: tuple[str, ...]) -> bool:
    if not path or path[-1] not in {"latency_ms", "runtime_seconds"}:
        return False
    if path[0] == "metrics":
        return True
    return len(path) >= 5 and path[0] == "events" and path[2] == "payload" and path[3] == "metadata"
