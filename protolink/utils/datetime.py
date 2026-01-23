from datetime import datetime, timezone
from typing import overload


@overload
def utc_now(*, iso: bool = False) -> datetime: ...
@overload
def utc_now(*, iso: bool = True) -> str: ...


def utc_now(*, iso: bool = True) -> datetime | str:
    """Get the current UTC datetime with timezone awareness.

    This function provides a standardized way to get the current time
    across the entire Protolink codebase. It always returns a timezone-aware
    datetime object in UTC, avoiding common datetime pitfalls.

    Returns:
        datetime: Current UTC datetime with tzinfo=timezone.utc

    Examples:
        >>> now = utc_now()
        >>> now.tzinfo
        datetime.timezone.utc
        >>> now.isoformat()
        '2024-01-01T12:00:00+00:00'

    Note:
        This function should be used instead of datetime.now() to ensure
        consistent timezone handling throughout the application.
    """
    dt = datetime.now(timezone.utc)

    return dt.isoformat() if iso else dt


def format_iso8601(dt: datetime | None = None) -> str:
    """Format a datetime as ISO8601 string with UTC timezone.

    Args:
        dt: DateTime to format. If None, uses current UTC time.

    Returns:
        str: ISO8601 formatted datetime string

    Examples:
        >>> format_iso8601()
        '2024-01-01T12:00:00+00:00'
        >>> format_iso8601(utc_now(iso=False))
        '2024-01-01T12:00:00+00:00'
    """
    if dt is None:
        dt = utc_now(iso=False)
    elif dt.tzinfo is None:
        # If naive datetime, assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        # Convert to UTC if different timezone
        dt = dt.astimezone(timezone.utc)

    return dt.isoformat()


def parse_iso8601(timestamp: str) -> datetime:
    """Parse an ISO8601 timestamp string to a timezone-aware datetime.

    Args:
        timestamp: ISO8601 formatted timestamp string

    Returns:
        datetime: Timezone-aware datetime object

    Raises:
        ValueError: If timestamp cannot be parsed

    Examples:
        >>> dt = parse_iso8601('2024-01-01T12:00:00+00:00')
        >>> dt.tzinfo
        datetime.timezone.utc
    """
    try:
        dt = datetime.fromisoformat(timestamp)
        if dt.tzinfo is None:
            # Assume UTC if no timezone info
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as e:
        raise ValueError(f"Invalid ISO8601 timestamp: {timestamp}") from e
