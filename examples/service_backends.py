"""Exercise every calendar/email backend without accounts, sockets, or real delivery.

Run: python examples/service_backends.py
Requires: pip install 'protolink[integrations]'

The main function shows the public API. The fixtures below replace only network
transports; real backends, MIME handling, tools, and Agent approval still execute.
Replace these fixtures with your credentials to use live services. Never use this
demo's automatic approval callback for a real mailbox.
"""

from __future__ import annotations

import asyncio
import base64
import json
import smtplib
from contextlib import contextmanager
from email.message import EmailMessage
from unittest.mock import patch

import httpx

from protolink import Assistant
from protolink.tools import Gmail, GoogleCalendar, IMAPEmail, OutlookCalendar, OutlookEmail
from protolink.tools.builtins import imap_email

START, END = "2026-09-19T09:00:00+02:00", "2026-09-19T10:00:00+02:00"
MESSAGE = {"to": ["reviewer@example.com"], "subject": "Review", "body": "Please review the agenda."}


async def main() -> None:
    """Run the same tools against Google, Microsoft, and standard mail protocols."""

    async def approve(request, context):
        # Safe only because every service transport is replaced below.
        assert request.action.capabilities <= {"calendar.write", "email.write", "email.send"}
        return True

    with offline_services() as calls:
        backends = [
            (GoogleCalendar("demo-token"), Gmail("demo-token", sender="me@example.com")),
            (OutlookCalendar("demo-token"), OutlookEmail("demo-token")),
            (
                None,
                IMAPEmail(
                    "me@example.com",
                    "demo-password",
                    imap_host="imap.example.com",
                    smtp_host="smtp.example.com",
                    drafts_mailbox="Drafts",
                ),
            ),
        ]
        for calendar, email in backends:
            assistant = Assistant(
                calendar=calendar, email=email, allow_write=True, allow_send=True, approval_handler=approve, verbosity=0
            )
            if calendar:
                page = await assistant.call_tool("list_calendar_events", start=START, end=END)
                assert page["items"][0]["id"] == "event" and page["next_page_token"] is None
                created = await assistant.call_tool("create_calendar_event", title="Focus", start=START, end=END)
                assert created["id"] == "created"
            page = await assistant.call_tool("list_email_messages")
            assert len(page["items"]) == 1 and page["next_page_token"] is None
            message = await assistant.call_tool("read_email", message_id=page["items"][0]["id"])
            assert message["body"].strip() == "Review the agenda."
            draft = await assistant.call_tool("create_email_draft", **MESSAGE)
            sent = await assistant.call_tool("send_email", **MESSAGE)
            assert draft.get("id") == "draft" or draft.get("status") == "drafted"
            assert sent.get("id") == "sent" or sent.get("status") == "accepted"
            print(f"{type(email).__name__}: list, read, draft, send passed")
        assert calls == {
            "google.calendar.list",
            "google.calendar.create",
            "google.email.list",
            "google.email.read",
            "google.email.draft",
            "google.email.send",
            "outlook.calendar.list",
            "outlook.calendar.create",
            "outlook.email.list",
            "outlook.email.read",
            "outlook.email.draft",
            "outlook.email.send",
            "imap.list",
            "imap.read",
            "imap.draft",
            "smtp.send",
        }
    print("All five backends passed through Assistant; no network or email delivery occurred.")


@contextmanager
def offline_services():
    """Small deterministic HTTP/IMAP/SMTP fixtures, scoped to this demonstration."""
    calls = set()
    original_client = httpx.AsyncClient
    mime = EmailMessage()
    mime["From"], mime["To"], mime["Subject"] = "sender@example.com", "me@example.com", "Agenda"
    mime.set_content("Review the agenda.")
    raw = mime.as_bytes()

    def respond(request):
        path, method = request.url.path, request.method
        google = request.url.host in {"www.googleapis.com", "gmail.googleapis.com"}
        provider = "google" if google else "outlook"
        assert google or request.url.host == "graph.microsoft.com"
        assert request.headers["Authorization"] == "Bearer demo-token"
        if "/calendar" in path:
            operation = "list" if method == "GET" else "create"
            calls.add(f"{provider}.calendar.{operation}")
            if operation == "list":
                return httpx.Response(200, json={"items" if google else "value": [{"id": "event"}]})
            return httpx.Response(201, json={"id": "created"})
        if method == "GET":
            if path.endswith("/messages"):
                calls.add(f"{provider}.email.list")
                return httpx.Response(200, json={"messages" if google else "value": [{"id": "message"}]})
            assert path.endswith("/messages/message")
            calls.add(f"{provider}.email.read")
            body = "Review the agenda."
            data = (
                {
                    "payload": {
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
                    }
                }
                if google
                else {"body": {"contentType": "text", "content": body}}
            )
            return httpx.Response(200, json={"id": "message", **data})
        assert method == "POST"
        operation = "send" if path.endswith(("/sendMail", "/messages/send")) else "draft"
        calls.add(f"{provider}.email.{operation}")
        assert json.loads(request.content)
        return (
            httpx.Response(202)
            if not google and operation == "send"
            else httpx.Response(200, json={"id": "sent" if operation == "send" else "draft"})
        )

    class DemoIMAP:
        def __init__(self, *args, **kwargs):
            assert kwargs["ssl_context"].check_hostname

        def login(self, username, password):
            assert password == "demo-password"
            return "OK", []

        def select(self, mailbox, *, readonly=False):
            assert readonly
            return "OK", [b"1"]

        def response(self, name):
            return name, [b"42"]

        def uid(self, command, *args):
            if command == "SEARCH":
                calls.add("imap.list")
                return "OK", [b"1"]
            assert command == "FETCH"
            if args[1] == "(RFC822.SIZE)":
                return "OK", [f"1 (RFC822.SIZE {len(raw)})".encode()]
            assert args[1] == "(BODY.PEEK[])"
            calls.add("imap.read")
            return "OK", [(b"1 (BODY[]", raw)]

        def append(self, mailbox, flags, date, message):
            assert mailbox == '"Drafts"' and flags == r"\Draft" and b"reviewer@example.com" in message
            calls.add("imap.draft")
            return "OK", []

        def shutdown(self):
            pass

    class DemoSMTP(smtplib.SMTP):
        def __init__(self, *args, **kwargs):
            assert kwargs["context"].check_hostname

        def login(self, username, password, **kwargs):
            assert password == "demo-password"

        def send_message(self, message, **kwargs):
            assert kwargs["to_addrs"] == MESSAGE["to"]
            calls.add("smtp.send")
            return {}

        def close(self):
            pass

    with (
        patch.object(
            httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs)
        ),
        patch.object(imap_email, "_BoundedIMAP", DemoIMAP),
        patch.object(smtplib, "SMTP_SSL", DemoSMTP),
    ):
        yield calls


if __name__ == "__main__":
    asyncio.run(main())
