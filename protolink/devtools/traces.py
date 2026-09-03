"""Bounded JSONL inspection helpers for local Protolink telemetry.

Local trace files are append-only in normal operation and may grow for the
entire lifetime of an application.  The helpers in this module therefore read
recent records from the end of the file, return compact summaries, and expose
full records only through an opaque offset token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

DEFAULT_TRACE_PAGE_LIMIT = 50
MAX_TRACE_PAGE_LIMIT = 200
DEFAULT_MAX_TRACE_LINE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_TRACE_SCAN_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_TRACE_SCAN_LINES = 5000
_REVERSE_READ_CHUNK_BYTES = 64 * 1024


class TraceFileError(ValueError):
    """Base error raised while inspecting a local trace file."""


class InvalidTraceTokenError(TraceFileError):
    """Raised when an opaque trace cursor or record token is invalid."""


class StaleTraceTokenError(TraceFileError):
    """Raised when a token refers to a replaced or truncated trace file."""


class TraceRecordTooLargeError(TraceFileError):
    """Raised when a record exceeds the configured detail-size safeguard."""


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True)
class _LineBounds:
    start: int
    end: int
    next_boundary: int
    consumed_bytes: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class _CursorState:
    before: int
    skipped_line_bytes: int = 0
    partial_tail: bool = False


@dataclass(frozen=True)
class _SkipLineResult:
    boundary: int | None
    consumed_bytes: int
    skipped_bytes: int


class TraceJsonlReader:
    """Read recent JSONL trace records without loading an entire file.

    Pages are returned newest first.  Their cursors point to a byte boundary
    before the oldest record in the current page, so a cursor remains valid
    when the same append-only file grows.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_page_size: int = MAX_TRACE_PAGE_LIMIT,
        max_line_bytes: int = DEFAULT_MAX_TRACE_LINE_BYTES,
        max_scan_bytes: int = DEFAULT_MAX_TRACE_SCAN_BYTES,
        max_scan_lines: int = DEFAULT_MAX_TRACE_SCAN_LINES,
    ) -> None:
        self.path = Path(path).expanduser()
        self.max_page_size = max(1, int(max_page_size))
        self.max_line_bytes = max(1, int(max_line_bytes))
        self.max_scan_bytes = max(1, int(max_scan_bytes))
        self.max_scan_lines = max(1, int(max_scan_lines))
        if self.max_scan_bytes < self.max_line_bytes:
            raise ValueError("max_scan_bytes must be greater than or equal to max_line_bytes")

    def page(
        self,
        *,
        limit: int = DEFAULT_TRACE_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded recent-first page of trace summaries."""
        page_limit = max(1, min(int(limit), self.max_page_size))
        source = self.source_metadata()
        response: dict[str, Any] = {
            **source,
            "records": [],
            "limit": page_limit,
            "next_cursor": None,
            "malformed_count": 0,
            "oversized_count": 0,
            "partial_tail": False,
            "scan_exhausted": False,
            "error": None,
        }
        if not source["exists"]:
            return response
        if not source["is_file"]:
            raise TraceFileError(f"Telemetry path is not a regular file: {self.path}")

        stat = self.path.stat()
        identity = _identity(stat)
        cursor_state = (
            _CursorState(before=stat.st_size)
            if cursor is None
            else _decode_cursor(
                cursor,
                identity=identity,
                size=stat.st_size,
                path=self.path,
            )
        )
        boundary = cursor_state.before
        skipped_line_bytes = cursor_state.skipped_line_bytes
        skipped_partial_tail = cursor_state.partial_tail
        tail_without_newline = cursor is None and boundary > 0 and not _ends_with_newline(self.path, boundary)
        response["partial_tail"] = tail_without_newline or cursor_state.partial_tail
        first_physical_record = True
        scanned_bytes = 0
        scanned_lines = 0
        unsafe_boundary = False

        with self.path.open("rb") as file:
            while (
                boundary > 0
                and len(response["records"]) < page_limit
                and scanned_bytes < self.max_scan_bytes
                and scanned_lines < self.max_scan_lines
            ):
                remaining_budget = self.max_scan_bytes - scanned_bytes
                if skipped_line_bytes:
                    skipped = _skip_to_previous_line_boundary(
                        file,
                        before=boundary,
                        max_search_bytes=remaining_budget,
                    )
                    scanned_bytes += skipped.consumed_bytes
                    skipped_line_bytes += skipped.skipped_bytes
                    if skipped.boundary is None:
                        boundary = max(0, boundary - skipped.skipped_bytes)
                        if boundary > 0:
                            response["next_cursor"] = _encode_skip_cursor(
                                identity,
                                boundary,
                                skipped_line_bytes=skipped_line_bytes,
                                partial_tail=skipped_partial_tail,
                                anchor=_cursor_anchor(self.path, boundary),
                            )
                            response["scan_exhausted"] = True
                        elif not skipped_partial_tail:
                            if skipped_line_bytes > self.max_line_bytes:
                                response["oversized_count"] += 1
                            else:
                                response["malformed_count"] += 1
                        break

                    boundary = skipped.boundary
                    scanned_lines += 1
                    if not skipped_partial_tail:
                        if skipped_line_bytes > self.max_line_bytes:
                            response["oversized_count"] += 1
                        else:
                            response["malformed_count"] += 1
                    skipped_line_bytes = 0
                    skipped_partial_tail = False
                    first_physical_record = False
                    continue

                bounds, unsafe_boundary, search_consumed = _previous_line_bounds(
                    file,
                    before=boundary,
                    max_search_bytes=remaining_budget,
                )
                scanned_bytes += search_consumed
                if bounds is None:
                    if unsafe_boundary:
                        skipped_line_bytes = search_consumed
                        skipped_partial_tail = first_physical_record and tail_without_newline
                        boundary = max(0, boundary - search_consumed)
                        response["scan_exhausted"] = True
                        if boundary > 0:
                            response["next_cursor"] = _encode_skip_cursor(
                                identity,
                                boundary,
                                skipped_line_bytes=skipped_line_bytes,
                                partial_tail=skipped_partial_tail,
                                anchor=_cursor_anchor(self.path, boundary),
                            )
                        elif not skipped_partial_tail:
                            if skipped_line_bytes > self.max_line_bytes:
                                response["oversized_count"] += 1
                            else:
                                response["malformed_count"] += 1
                    else:
                        boundary = 0
                    break

                boundary = bounds.next_boundary
                scanned_lines += 1
                if first_physical_record and tail_without_newline:
                    first_physical_record = False
                    continue
                if bounds.length <= 0:
                    first_physical_record = False
                    continue
                if bounds.length > self.max_line_bytes:
                    response["oversized_count"] += 1
                    first_physical_record = False
                    continue

                file.seek(bounds.start)
                raw_line = file.read(bounds.length)
                if not raw_line.strip():
                    first_physical_record = False
                    continue
                try:
                    record = _strict_json_loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
                    response["malformed_count"] += 1
                    first_physical_record = False
                    continue
                first_physical_record = False
                if not isinstance(record, dict):
                    response["malformed_count"] += 1
                    continue

                record_id = _encode_record_id(
                    identity,
                    bounds.start,
                    bounds.length,
                    digest=_record_digest(raw_line),
                )
                response["records"].append(_trace_summary(record, record_id=record_id))

        if (
            response["next_cursor"] is None
            and boundary > 0
            and not unsafe_boundary
            and (
                scanned_bytes >= self.max_scan_bytes
                or scanned_lines >= self.max_scan_lines
                or len(response["records"]) >= page_limit
            )
        ):
            response["next_cursor"] = _encode_cursor(
                identity,
                boundary,
                anchor=_cursor_anchor(self.path, boundary),
            )
        if (
            len(response["records"]) < page_limit
            and boundary > 0
            and not unsafe_boundary
            and response["next_cursor"] is not None
            and (scanned_bytes >= self.max_scan_bytes or scanned_lines >= self.max_scan_lines)
        ):
            response["scan_exhausted"] = True

        response["scanned_bytes"] = scanned_bytes
        response["scanned_lines"] = scanned_lines
        return response

    def detail(self, record_id: str) -> dict[str, Any]:
        """Load one full trace record identified by an opaque page token."""
        stat = self.path.stat()
        identity = _identity(stat)
        offset, length, expected_digest = _decode_record_id(record_id, identity=identity, size=stat.st_size)
        if length > self.max_line_bytes:
            raise TraceRecordTooLargeError(
                f"Trace record is {length} bytes; the configured detail limit is {self.max_line_bytes} bytes"
            )

        with self.path.open("rb") as file:
            if offset > 0:
                file.seek(offset - 1)
                if file.read(1) != b"\n":
                    raise StaleTraceTokenError("Trace record token no longer points to a JSONL line boundary")
            if offset + length >= stat.st_size:
                raise StaleTraceTokenError("Trace record is no longer terminated by a JSONL newline")
            file.seek(offset + length)
            delimiter = file.read(1)
            if delimiter == b"\r":
                delimiter += file.read(1)
            if delimiter not in {b"\n", b"\r\n"}:
                raise StaleTraceTokenError("Trace record token no longer points to a complete JSONL line")
            file.seek(offset)
            raw_line = file.read(length)

        if _record_digest(raw_line) != expected_digest:
            raise StaleTraceTokenError("Trace record changed; refresh the telemetry source")
        try:
            record = _strict_json_loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise StaleTraceTokenError("Trace record is no longer valid UTF-8 JSON") from exc
        if not isinstance(record, dict):
            raise StaleTraceTokenError("Trace record is not a JSON object")

        return {
            "record_id": record_id,
            "summary": _trace_summary(record, record_id=record_id),
            "trace": record,
        }

    def source_metadata(self) -> dict[str, Any]:
        """Return safe file metadata used by dashboard source indicators."""
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return {
                "path": str(self.path),
                "configured": True,
                "exists": False,
                "is_file": False,
                "size_bytes": 0,
                "modified_at": None,
            }
        return {
            "path": str(self.path),
            "configured": True,
            "exists": True,
            "is_file": self.path.is_file(),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        }


def empty_trace_page(path: str | Path | None = None) -> dict[str, Any]:
    """Return the dashboard telemetry shape when no trace file is configured."""
    if path is not None:
        return TraceJsonlReader(path).page()
    return {
        "path": None,
        "configured": False,
        "exists": False,
        "is_file": False,
        "size_bytes": 0,
        "modified_at": None,
        "records": [],
        "limit": DEFAULT_TRACE_PAGE_LIMIT,
        "next_cursor": None,
        "malformed_count": 0,
        "oversized_count": 0,
        "partial_tail": False,
        "scan_exhausted": False,
        "error": None,
    }


def list_trace_records(
    path: str | Path,
    *,
    limit: int = DEFAULT_TRACE_PAGE_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return a recent-first page from one local telemetry JSONL file."""
    return TraceJsonlReader(path).page(limit=limit, cursor=cursor)


def load_trace_record(path: str | Path, record_id: str) -> dict[str, Any]:
    """Load one complete trace record from an opaque page identifier."""
    return TraceJsonlReader(path).detail(record_id)


def _trace_summary(record: dict[str, Any], *, record_id: str) -> dict[str, Any]:
    spans = _as_list(record.get("spans"))
    events = _as_list(record.get("events"))
    metadata = _as_dict(record.get("metadata"))
    raw_metrics = _as_dict(metadata.get("llm_metrics"))
    metric_keys = (
        "call_count",
        "total_latency_ms",
        "total_input_tokens",
        "total_output_tokens",
        "total_tokens",
        "estimated_token_calls",
        "total_cost",
        "currency",
        "max_context_used_percent",
        "max_context_used_tokens",
        "context_window_tokens",
    )
    metrics = {key: value for key in metric_keys if (value := _summary_scalar(raw_metrics.get(key))) is not None}
    span_kinds = Counter(
        _bounded_text(span.get("kind"), fallback="unknown", max_chars=128) for span in spans if isinstance(span, dict)
    )
    event_types = Counter(
        _bounded_text(event.get("type"), fallback="event", max_chars=128) for event in events if isinstance(event, dict)
    )
    models: list[str] = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        model = _as_dict(span.get("metadata")).get("model")
        if model:
            bounded_model = _bounded_text(model, max_chars=256)
            if bounded_model not in models:
                models.append(bounded_model)
        if len(models) >= 20:
            break
    return {
        "record_id": record_id,
        "trace_id": _optional_text(record.get("trace_id")),
        "task_id": _optional_text(record.get("task_id")),
        "agent_name": _optional_text(record.get("agent_name")),
        "started_at": _optional_text(record.get("started_at")),
        "ended_at": _optional_text(record.get("ended_at")),
        "status": _optional_text(record.get("status")) or "unknown",
        "duration_ms": _optional_number(record.get("duration_ms")),
        "span_count": len(spans),
        "event_count": len(events),
        "span_kinds": dict(span_kinds.most_common(32)),
        "event_types": dict(event_types.most_common(64)),
        "models": models,
        "final_state": _optional_text(metadata.get("final_state")),
        "retry_count": _optional_number(metadata.get("retry_count")),
        "llm_metrics": metrics,
    }


def _previous_line_bounds(
    file: BinaryIO,
    *,
    before: int,
    max_search_bytes: int,
) -> tuple[_LineBounds | None, bool, int]:
    """Locate the prior physical line within a bounded reverse scan.

    The boolean result is true only when the byte budget ended inside a line,
    where emitting a follow-up cursor would incorrectly treat a fragment as a
    standalone JSON record.
    """
    if before <= 0 or max_search_bytes <= 0:
        return None, before > 0, 0

    end = before
    position = before
    consumed = 0
    trimming_delimiters = True
    trimmed_suffix = False
    while position > 0 and consumed < max_search_bytes:
        read_size = min(
            _REVERSE_READ_CHUNK_BYTES,
            position,
            max_search_bytes - consumed,
        )
        chunk_start = position - read_size
        file.seek(chunk_start)
        chunk = file.read(read_size)
        consumed += read_size
        search_end = len(chunk)
        if trimming_delimiters:
            search_end = len(chunk.rstrip(b"\r\n"))
            trimmed_suffix = trimmed_suffix or search_end < len(chunk)
            end = chunk_start + search_end
            if search_end == 0:
                position = chunk_start
                continue
            trimming_delimiters = False

        newline_index = chunk.rfind(b"\n", 0, search_end)
        if newline_index >= 0:
            start = chunk_start + newline_index + 1
            return (
                _LineBounds(
                    start=start,
                    end=end,
                    next_boundary=start,
                    consumed_bytes=consumed,
                ),
                False,
                consumed,
            )
        position = chunk_start

    if position == 0:
        if trimming_delimiters:
            return None, False, consumed
        return (
            _LineBounds(
                start=0,
                end=end,
                next_boundary=0,
                consumed_bytes=consumed,
            ),
            False,
            consumed,
        )
    if trimming_delimiters:
        return (
            _LineBounds(
                start=position,
                end=position,
                next_boundary=position,
                consumed_bytes=consumed,
            ),
            False,
            consumed,
        )
    if trimmed_suffix:
        return (
            _LineBounds(
                start=end,
                end=end,
                next_boundary=end,
                consumed_bytes=consumed,
            ),
            False,
            consumed,
        )
    return None, True, consumed


def _skip_to_previous_line_boundary(
    file: BinaryIO,
    *,
    before: int,
    max_search_bytes: int,
) -> _SkipLineResult:
    """Continue skipping a physical line that exceeded an earlier scan page."""
    position = before
    consumed = 0
    while position > 0 and consumed < max_search_bytes:
        read_size = min(
            _REVERSE_READ_CHUNK_BYTES,
            position,
            max_search_bytes - consumed,
        )
        chunk_start = position - read_size
        file.seek(chunk_start)
        chunk = file.read(read_size)
        consumed += read_size
        newline_index = chunk.rfind(b"\n")
        if newline_index >= 0:
            boundary = chunk_start + newline_index + 1
            return _SkipLineResult(
                boundary=boundary,
                consumed_bytes=consumed,
                skipped_bytes=before - boundary,
            )
        position = chunk_start
    if position == 0:
        return _SkipLineResult(
            boundary=0,
            consumed_bytes=consumed,
            skipped_bytes=before,
        )
    return _SkipLineResult(
        boundary=None,
        consumed_bytes=consumed,
        skipped_bytes=before - position,
    )


def _ends_with_newline(path: Path, size: int) -> bool:
    with path.open("rb") as file:
        file.seek(size - 1)
        return file.read(1) == b"\n"


def _identity(stat: Any) -> _FileIdentity:
    return _FileIdentity(device=int(stat.st_dev), inode=int(stat.st_ino))


def _encode_cursor(identity: _FileIdentity, before: int, *, anchor: str) -> str:
    return _encode_token("c1", identity.device, identity.inode, before, anchor)


def _encode_skip_cursor(
    identity: _FileIdentity,
    before: int,
    *,
    skipped_line_bytes: int,
    partial_tail: bool,
    anchor: str,
) -> str:
    return _encode_token(
        "s1",
        identity.device,
        identity.inode,
        before,
        skipped_line_bytes,
        int(partial_tail),
        anchor,
    )


def _decode_cursor(
    token: str,
    *,
    identity: _FileIdentity,
    size: int,
    path: Path | None = None,
) -> _CursorState:
    try:
        parts = _decode_token(token, prefix="c1", count=5)
    except InvalidTraceTokenError:
        parts = _decode_token(token, prefix="s1", count=7)
    device, inode, before = (_parse_token_int(value) for value in parts[1:4])
    if parts[0] == "s1":
        skipped_line_bytes = _parse_token_int(parts[4])
        partial_tail_raw = _parse_token_int(parts[5])
        if skipped_line_bytes <= 0 or partial_tail_raw not in {0, 1}:
            raise InvalidTraceTokenError("Invalid trace token")
        expected_anchor = parts[6]
    else:
        skipped_line_bytes = 0
        partial_tail_raw = 0
        expected_anchor = parts[4]
    _validate_identity(device, inode, identity)
    if before < 0 or before > size:
        raise StaleTraceTokenError("Trace cursor points outside the current file")
    if path is not None and _cursor_anchor(path, before) != expected_anchor:
        raise StaleTraceTokenError("Trace file changed before this cursor; refresh the telemetry source")
    return _CursorState(
        before=before,
        skipped_line_bytes=skipped_line_bytes,
        partial_tail=bool(partial_tail_raw),
    )


def _encode_record_id(
    identity: _FileIdentity,
    offset: int,
    length: int,
    *,
    digest: str,
) -> str:
    return _encode_token("r1", identity.device, identity.inode, offset, length, digest)


def _decode_record_id(
    token: str,
    *,
    identity: _FileIdentity,
    size: int,
) -> tuple[int, int, str]:
    parts = _decode_token(token, prefix="r1", count=6)
    device, inode, offset, length = (_parse_token_int(value) for value in parts[1:5])
    expected_digest = parts[5]
    _validate_identity(device, inode, identity)
    if offset < 0 or length <= 0 or offset + length > size:
        raise StaleTraceTokenError("Trace record token points outside the current file")
    if len(expected_digest) != 16:
        raise InvalidTraceTokenError("Invalid trace token")
    return offset, length, expected_digest


def _encode_token(prefix: str, *values: int | str) -> str:
    raw = ":".join([prefix, *(str(value) for value in values)]).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_token(token: str, *, prefix: str, count: int) -> list[str]:
    if not token or len(token) > 256:
        raise InvalidTraceTokenError("Invalid trace token")
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.b64decode(token + padding, altchars=b"-_", validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidTraceTokenError("Invalid trace token") from exc
    parts = raw.split(":")
    if len(parts) != count or parts[0] != prefix:
        raise InvalidTraceTokenError("Invalid trace token")
    return parts


def _parse_token_int(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise InvalidTraceTokenError("Invalid trace token") from exc


def _validate_identity(device: int, inode: int, current: _FileIdentity) -> None:
    if device != current.device or inode != current.inode:
        raise StaleTraceTokenError("Trace file was replaced; refresh the telemetry source")


def _record_digest(raw_line: bytes) -> str:
    return hashlib.blake2s(raw_line, digest_size=8).hexdigest()


def _cursor_anchor(path: Path, before: int) -> str:
    anchor_length = min(64, before)
    with path.open("rb") as file:
        file.seek(before - anchor_length)
        anchor = file.read(anchor_length)
    return _record_digest(anchor)


def _optional_text(value: Any) -> str | None:
    return _bounded_text(value, max_chars=512) if value is not None and value != "" else None


def _optional_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _summary_scalar(value: Any) -> str | int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, str):
        return _bounded_text(value, max_chars=128)
    return None


def _bounded_text(value: Any, *, fallback: str = "", max_chars: int) -> str:
    text = str(value) if value is not None else fallback
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strict_json_loads(raw: bytes) -> Any:
    """Decode standards-compliant JSON and reject NaN/Infinity constants."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}")

    def parse_finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"Non-finite JSON number: {value}")
        return parsed

    return json.loads(
        raw,
        parse_constant=reject_constant,
        parse_float=parse_finite_float,
    )
