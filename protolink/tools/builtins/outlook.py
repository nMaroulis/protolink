"""Microsoft Graph calendar and email backends for the existing assistant tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

from protolink.tools.builtins._oauth import OAuthJSONAPI, OAuthToken
from protolink.tools.builtins._pagination import decode_cursor, encode_cursor, scope_key
from protolink.tools.builtins.calendar import _interval
from protolink.tools.builtins.email import _message_fields


class MicrosoftGraphError(RuntimeError):
    """Microsoft rejected a request, without exposing response bodies or tokens."""

    def __init__(self, status_code: int) -> None:
        """Expose the HTTP status for application-owned authentication/error handling."""
        self.status_code = status_code
        super().__init__(f"Microsoft Graph request failed (HTTP {status_code}); no automatic retry was attempted")


def _resource(value: str) -> str:
    """Encode one resource identifier without permitting path traversal."""
    if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(c in value for c in "\r\n\x00"):
        raise ValueError("Resource identifiers must be nonblank and contain no control characters or dot segments")
    return quote(value, safe="")


def _user_path(user_id: str) -> str:
    return "/me" if user_id == "me" else f"/users/{_resource(user_id)}"


class _GraphAPI(OAuthJSONAPI):
    def __init__(self, token: OAuthToken) -> None:
        self._cursor_scope = uuid4().hex
        super().__init__(
            token, "https://graph.microsoft.com/v1.0", provider="Microsoft Graph", error_type=MicrosoftGraphError
        )

    @staticmethod
    def _continuation(url: str, path: str) -> str:
        """Permit continuation only on the original HTTPS origin and collection."""
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "graph.microsoft.com"
                or parsed.path != "/v1.0" + path
                or parsed.fragment
                or any(c in url for c in "\r\n\x00")
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("Microsoft Graph returned an invalid continuation URL") from None
        return path + ("?" + parsed.query if parsed.query else "")

    async def page(
        self,
        path: str,
        params: dict[str, Any],
        page_token: str | None,
        *,
        headers: dict[str, str] | None = None,
        query_scope: str = "",
    ) -> dict[str, Any]:
        scope = scope_key("graph", self._cursor_scope, path, params, query_scope)
        request_path = path
        request_params: dict[str, Any] | None = params
        if page_token is not None:
            url = decode_cursor(page_token, scope)
            if not isinstance(url, str):
                raise ValueError("Invalid Microsoft Graph page token")
            request_path = self._continuation(url, path)
            request_params = None  # Preserve the server's encoded query exactly.
        data = await self.request("GET", request_path, params=request_params, headers=headers)
        items = data.get("value", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("Microsoft Graph collection must contain objects")
        next_url = data.get("@odata.nextLink")
        if next_url is not None:
            if not isinstance(next_url, str):
                raise ValueError("Invalid Microsoft Graph continuation URL")
            self._continuation(next_url, path)
        return {"items": items, "next_page_token": encode_cursor(scope, next_url) if next_url else None}


class OutlookCalendar:
    """Microsoft 365/Outlook calendar using the global Microsoft Graph endpoint.

    Args:
        token: OAuth access token or sync/async callback returning one per request.
            Consent, refresh, and storage are application-owned.
        calendar_id: Calendar ID; ``None`` selects the user's default calendar.
        user_id: ``me`` for delegated tokens, or a user ID/UPN for application
            tokens and explicitly authorized shared access.

    Install ``protolink[integrations]``. Use ``Calendars.Read`` for full event
    details and ``Calendars.ReadWrite`` for creation. Registration performs no
    network requests. National-cloud endpoints are not supported. Creation makes
    personal timed events without invitations; existing events are not modified.
    """

    query_help = "Query matches a case-insensitive substring in subject, preview, or location within each page."

    def __init__(self, token: OAuthToken, *, calendar_id: str | None = None, user_id: str = "me") -> None:
        self._api = _GraphAPI(token)
        self._path = _user_path(user_id) + (
            f"/calendars/{_resource(calendar_id)}" if calendar_id is not None else "/calendar"
        )
        self.calendar_id = f"{user_id}/{calendar_id or 'default'}"

    async def list_events(
        self,
        *,
        start: str,
        end: str,
        query: str = "",
        max_results: int = 20,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List recurring instances/all-day events in a window, ordered by start.

        Query is a case-insensitive substring in subject, preview, or location,
        filtered locally within each page. Empty pages can have a continuation;
        follow every token to finish a search. Tokens require the same backend
        instance, interval, query, and page size. Event fields retain Graph's shape.
        """
        start, end = _interval(start, end)
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        page = await self._api.page(
            self._path + "/calendarView",
            {
                "startDateTime": start,
                "endDateTime": end,
                "$top": max_results,
                "$orderby": "start/dateTime",
            },
            page_token,
            query_scope=query,
        )
        if query:
            needle = query.casefold()
            page["items"] = [
                item
                for item in page["items"]
                if needle
                in " ".join(
                    [
                        str(item.get("subject", "")),
                        str(item.get("bodyPreview", "")),
                        str((item.get("location") or {}).get("displayName", "")),
                    ]
                ).casefold()
            ]
        return page

    async def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Create a personal event, preserving instants by converting offsets to UTC."""
        start, end = _interval(start, end)
        if not title.strip():
            raise ValueError("title must not be blank")

        def boundary(value: str) -> dict[str, str]:
            utc = datetime.fromisoformat(value).astimezone(UTC).replace(tzinfo=None)
            return {"dateTime": utc.isoformat(), "timeZone": "UTC"}

        return await self._api.request(
            "POST",
            self._path + "/events",
            body={
                "subject": title,
                "start": boundary(start),
                "end": boundary(end),
                "body": {"contentType": "Text", "content": description},
                "location": {"displayName": location},
            },
        )


class OutlookEmail:
    """Microsoft 365/Outlook mailbox using the existing EmailBackend contract.

    Args:
        token: OAuth access token or sync/async token callback; applications own
            authentication and refresh.
        user_id: ``me`` for delegated access, or user ID/UPN for application tokens
            or authorized shared mailboxes. All operations use this fixed mailbox.

    Requires ``protolink[integrations]``. Use ``Mail.Read`` for reading,
    ``Mail.ReadWrite`` for drafts, and ``Mail.Send`` for sending (shared mailboxes
    may require additional delegated permissions). Plain-text composition only.
    Sending returns ``status='accepted'`` without a fabricated server message ID:
    Graph's 202 response does not confirm delivery. Requests are never retried.
    """

    query_help = (
        "Use Microsoft Graph message search syntax, e.g. subject:review or from:user@example.com. "
        "Search is capped at 1,000 results; empty query lists all messages by received time."
    )

    def __init__(self, token: OAuthToken, *, user_id: str = "me") -> None:
        self._api = _GraphAPI(token)
        self._path = _user_path(user_id)
        self.sender = user_id  # Display the selected mailbox in native approval previews.
        self._headers = {"Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"'}

    async def list_messages(
        self,
        *,
        query: str = "",
        max_results: int = 20,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Search a page with Graph's message $search syntax (e.g. subject:review).

        Microsoft caps $search results at 1,000 messages. Empty queries list the
        mailbox by received time. Keep the same backend instance, query, and page
        size when continuing. A token callback must keep the same account.
        """
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        params: dict[str, Any] = {"$top": max_results, "$select": "id,conversationId,subject,receivedDateTime"}
        if query:
            if any(c in query for c in "\r\n\x00"):
                raise ValueError("query must not contain control characters")
            params["$search"] = '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"'
        else:
            params["$orderby"] = "receivedDateTime desc"
        return await self._api.page(self._path + "/messages", params, page_token, headers=self._headers)

    async def get_message(self, *, message_id: str) -> dict[str, Any]:
        """Read plain text without marking read, bounded to 20,000 body characters."""
        data = await self._api.request(
            "GET",
            self._path + "/messages/" + _resource(message_id),
            headers=self._headers,
            params={
                "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,"
                "body,bodyPreview,hasAttachments"
            },
        )
        content = data.get("body") or {}
        is_html = str(content.get("contentType", "")).lower() == "html"
        body = "" if is_html else str(content.get("content", ""))
        return {
            "id": data.get("id"),
            "thread_id": data.get("conversationId"),
            "from": (data.get("from") or {}).get("emailAddress", {}).get("address", ""),
            "to": ", ".join(item.get("emailAddress", {}).get("address", "") for item in data.get("toRecipients", [])),
            "subject": data.get("subject", ""),
            "date": data.get("receivedDateTime", ""),
            "snippet": data.get("bodyPreview", ""),
            "body": body[:20000],
            "body_truncated": len(body) > 20000,
            "has_attachments": bool(data.get("hasAttachments")),
            "html_body_omitted": is_html,
        }

    @staticmethod
    def _message(to: list[str], subject: str, body: str) -> dict[str, Any]:
        _message_fields(to, subject, body)
        return {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": address}} for address in to],
        }

    async def create_draft(self, *, to: list[str], subject: str, body: str) -> dict[str, Any]:
        """Create an unsent message in Drafts and return its Graph-assigned ID."""
        return await self._api.request(
            "POST", self._path + "/messages", body=self._message(to, subject, body), headers=self._headers
        )

    async def send_message(self, *, to: list[str], subject: str, body: str) -> dict[str, Any]:
        """Submit mail once and save it in Sent Items; acceptance is not delivery."""
        await self._api.request(
            "POST",
            self._path + "/sendMail",
            body={
                "message": self._message(to, subject, body),
                "saveToSentItems": True,
            },
            headers=self._headers,
        )
        return {"status": "accepted"}
