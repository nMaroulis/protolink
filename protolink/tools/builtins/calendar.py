"""Calendar listing and event creation with replaceable application-owned backends."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Protocol
from urllib.parse import quote

from pydantic import Field

from protolink.tools.builtins._google import GoogleAPI, GoogleToken
from protolink.tools.builtins._integration import integration_tool
from protolink.tools.prepared import PreparedTool

_Time = Annotated[
    str, Field(description="ISO 8601 timestamp with an explicit UTC offset, e.g. 2026-09-19T09:00:00+02:00.")
]
_Limit = Annotated[int, Field(ge=1, le=100, description="Maximum events on this page (1-100).")]
_Title = Annotated[str, Field(min_length=1, max_length=1000, description="Event title.")]


def _interval(start: str, end: str) -> tuple[str, str]:
    """Normalize timezone-aware timestamps and reject empty or reversed intervals."""
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        raise ValueError("start and end must be ISO 8601 timestamps with UTC offsets") from None
    if first.utcoffset() is None or last.utcoffset() is None or first >= last:
        raise ValueError("start and end require UTC offsets and end must be after start")
    return first.isoformat(), last.isoformat()


class CalendarBackend(Protocol):
    """Async integration contract; implementations own credentials and service access.

    Methods return JSON objects. Lists use ``items`` and ``next_page_token``;
    creation returns an event containing its service ``id``. Calls must honor
    coroutine cancellation; never automatically retry writes with unknown outcomes.
    """

    async def list_events(
        self,
        *,
        start: str,
        end: str,
        query: str,
        max_results: int,
        page_token: str | None,
    ) -> dict[str, Any]:
        """List events overlapping [start, end), preserving pagination information."""
        ...

    async def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        description: str,
        location: str,
    ) -> dict[str, Any]:
        """Create one timed personal event; this contract does not send invitations."""
        ...


class GoogleCalendar:
    """Google Calendar backend using an application-supplied OAuth access token.

    Args:
        token: Access token or sync/async callback returning a fresh one. OAuth
            consent, refresh, and secure storage belong to the application.
        calendar_id: Fixed calendar identifier; defaults to ``primary``.

    Install ``protolink[integrations]``. Reading needs ``calendar.events.readonly``
    (or broader); creation needs ``calendar.events``. No network request occurs
    at construction. Events returned by Google retain their original fields,
    including date-only all-day events. Creation supports timed personal events
    without attendees, recurrence, attachments, or invitations.
    """

    query_help = "Query is Google's free-text event search; empty query lists all events in the interval."

    def __init__(self, token: GoogleToken, *, calendar_id: str = "primary") -> None:
        if not calendar_id.strip():
            raise ValueError("calendar_id must not be blank")
        self._api = GoogleAPI(token, "https://www.googleapis.com/calendar/v3")
        self._path = f"/calendars/{quote(calendar_id, safe='')}/events"
        self.calendar_id = calendar_id

    async def list_events(
        self,
        *,
        start: str,
        end: str,
        query: str = "",
        max_results: int = 20,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded page, expanding recurring events and sorting by start."""
        start, end = _interval(start, end)
        params = {
            "timeMin": start,
            "timeMax": end,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
            "q": query,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        data = await self._api.request("GET", self._path, params=params)
        return {"items": data.get("items", []), "next_page_token": data.get("nextPageToken")}

    async def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Create one personal timed event with explicit offsets and no attendees."""
        start, end = _interval(start, end)
        return await self._api.request(
            "POST",
            self._path,
            params={"sendUpdates": "none"},
            body={
                "summary": title,
                "start": {"dateTime": start},
                "end": {"dateTime": end},
                "description": description,
                "location": location,
            },
        )


def calendar_tools(
    backend: CalendarBackend,
    *,
    allow_write: bool = False,
    timeout_seconds: float = 30.0,
) -> tuple[PreparedTool, ...]:
    """Create ``list_calendar_events`` and optionally ``create_calendar_event``.

    Args:
        backend: ``GoogleCalendar``, ``OutlookCalendar``, or an application
            implementing ``CalendarBackend``. Optional ``query_help`` text is
            included in the model-facing listing tool description.
        allow_write: Include event creation, requiring ``calendar.write`` policy.
            Listing requires ``calendar.read``. The default exposes only reading.
        timeout_seconds: Positive finite limit per operation, bounded by run budgets.

    Register each returned tool on an Agent. Arguments and the fixed backend target
    are previewed before authorization. Tokens stay in the backend, outside tool
    arguments/events/serialization. Reattach backends after loading Agent dict/YAML.
    Pagination is explicit: preserve backend, interval, query, and page size to continue.
    Failed or canceled writes may already have occurred remotely; inspect the
    calendar before retrying. Applications own timezone choice and conflict checks.
    """

    async def list_calendar_events(
        start: _Time,
        end: _Time,
        query: str = "",
        max_results: _Limit = 20,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List events overlapping a time interval. Follow next_page_token for more results."""
        start, end = _interval(start, end)
        return await backend.list_events(
            start=start, end=end, query=query, max_results=max_results, page_token=page_token
        )

    async def create_calendar_event(
        title: _Title,
        start: _Time,
        end: _Time,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Create a personal timed event without invitations. Check the user's timezone and existing events first."""
        start, end = _interval(start, end)
        if not title.strip():
            raise ValueError("title must not be blank")
        return await backend.create_event(title=title, start=start, end=end, description=description, location=location)

    query_help = getattr(backend, "query_help", "Query uses the configured provider's search syntax.")
    list_calendar_events.__doc__ = (
        f"{list_calendar_events.__doc__} {query_help} "
        "Keep the same interval, query, and max_results when continuing; an empty page can have a next token."
    )

    def validate(arguments: dict[str, Any]) -> None:
        arguments["start"], arguments["end"] = _interval(arguments["start"], arguments["end"])
        if "title" in arguments and not arguments["title"].strip():
            raise ValueError("title must not be blank")

    target = f"{type(backend).__name__}:{getattr(backend, 'calendar_id', 'configured calendar')}"
    tools = [
        integration_tool(
            list_calendar_events,
            capability="calendar.read",
            target=target,
            timeout_seconds=timeout_seconds,
            validate=validate,
        )
    ]
    if allow_write:
        tools.append(
            integration_tool(
                create_calendar_event,
                capability="calendar.write",
                target=target,
                timeout_seconds=timeout_seconds,
                validate=validate,
            )
        )
    return tuple(tools)
