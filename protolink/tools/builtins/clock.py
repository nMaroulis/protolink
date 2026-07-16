"""Timezone-aware current date and time tool."""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from datetime import timezone as datetime_timezone
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from protolink.tools.tool import Tool

_TimezoneName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        description="IANA timezone name such as UTC, Europe/Zurich, or America/New_York.",
    ),
]


def _now(zone: tzinfo) -> datetime:
    """Return the current instant in ``zone`` through a patchable clock seam."""
    return datetime.now(zone)


def _format_offset(offset: timedelta | None) -> str:
    """Format a UTC offset as an ISO-style signed hour/minute string."""
    if offset is None:
        raise ValueError("timezone did not provide a UTC offset")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


async def _run_current_datetime(timezone: _TimezoneName = "UTC") -> dict[str, Any]:
    """Return the current date and time in an IANA timezone."""
    timezone_name = timezone.strip()
    if not timezone_name:
        raise ValueError("timezone must not be empty")
    if timezone_name == "UTC":
        zone: tzinfo = datetime_timezone.utc
    else:
        try:
            zone = ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(
                f"unknown or unavailable IANA timezone: {timezone_name!r}; install tzdata on hosts without a "
                "system timezone database"
            ) from exc

    current = _now(zone)
    return {
        "timezone": timezone_name,
        "iso8601": current.isoformat(timespec="seconds"),
        "date": current.date().isoformat(),
        "time": current.time().isoformat(timespec="seconds"),
        "weekday": current.strftime("%A"),
        "utc_offset": _format_offset(current.utcoffset()),
        "unix_timestamp": int(current.timestamp()),
    }


def current_datetime() -> Tool:
    """Create a timezone-aware current date and time tool.

    The model may request any IANA timezone installed on the host. UTC is the
    default and requires no third-party service or network access.

    Returns:
        A fresh :class:`~protolink.tools.Tool` named ``current_datetime``.
    """
    tool = Tool(
        name="current_datetime",
        description=(
            "Return the current date, time, weekday, UTC offset, and Unix timestamp for an IANA timezone. "
            "Use this when the answer depends on the actual current time."
        ),
        input_schema=None,
        output_schema={
            "type": "object",
            "properties": {
                "timezone": {"type": "string"},
                "iso8601": {"type": "string", "format": "date-time"},
                "date": {"type": "string", "format": "date"},
                "time": {"type": "string", "format": "time"},
                "weekday": {"type": "string"},
                "utc_offset": {"type": "string"},
                "unix_timestamp": {"type": "integer"},
            },
            "required": ["timezone", "iso8601", "date", "time", "weekday", "utc_offset", "unix_timestamp"],
            "additionalProperties": False,
        },
        tags=["builtin", "datetime", "read-only"],
        examples=[{"timezone": "Europe/Zurich"}],
        capabilities=(),
        func=_run_current_datetime,
    )
    tool._protolink_builtin_id = "current_datetime"
    return tool
