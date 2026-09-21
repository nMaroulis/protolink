"""TLS-only IMAP/SMTP email using the Python standard library."""

from __future__ import annotations

import asyncio
import contextlib
import imaplib
import inspect
import math
import re
import smtplib
import socket
import ssl
import threading
from collections.abc import Awaitable, Callable
from email import policy
from email.message import EmailMessage, MIMEPart
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from typing import Any, TypeVar

from protolink.tools.builtins._pagination import decode_cursor, encode_cursor, scope_key
from protolink.tools.builtins.email import _address, _message_fields

_T = TypeVar("_T")
_C = TypeVar("_C", bound=imaplib.IMAP4_SSL | smtplib.SMTP)
MailPassword = str | Callable[[], str | Awaitable[str]]
"""Password/app-password or application callback resolving one before connection."""


class MailBackendError(RuntimeError):
    """A mail server failed; private server responses and credentials are omitted."""


class _BoundedIMAP(imaplib.IMAP4_SSL):
    def __init__(self, *args: Any, max_literal_bytes: int, **kwargs: Any) -> None:
        self._max_literal_bytes = max_literal_bytes
        super().__init__(*args, **kwargs)

    def read(self, size: int) -> bytes:
        if size > self._max_literal_bytes:
            raise MailBackendError("IMAP literal exceeds the configured message byte limit")
        return super().read(size)


class _Session:
    """Interrupt connected workers and prevent late connections from starting work."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._connection: imaplib.IMAP4_SSL | smtplib.SMTP | None = None

    def check(self) -> None:
        if self._stopped.is_set():
            raise MailBackendError("Mail operation canceled")

    def attach(self, connection: _C) -> _C:
        # Only socket shutdown happens on the event-loop thread. The worker owns
        # protocol cleanup, file handles, and all normal protocol operations.
        with self._lock:
            self._connection = connection
            if self._stopped.is_set():
                self._interrupt()
        self.check()
        return connection

    def _interrupt(self) -> None:
        sock = getattr(self._connection, "sock", None)
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def cancel(self) -> None:
        self._stopped.set()
        with self._lock:
            self._interrupt()

    def close(self) -> None:
        connection = self._connection
        if connection is not None:
            with contextlib.suppress(OSError, imaplib.IMAP4.error):
                if isinstance(connection, smtplib.SMTP):
                    connection.close()
                else:
                    connection.shutdown()


async def _in_worker(operation: Callable[[_Session], _T]) -> _T:
    """Run blocking mail IO without blocking asyncio or retrying uncertain writes."""
    session = _Session()

    def run() -> _T:
        try:
            session.check()
            return operation(session)
        except (OSError, imaplib.IMAP4.error, smtplib.SMTPException):
            raise MailBackendError("Mail server operation failed; no automatic retry was attempted") from None
        finally:
            session.close()

    worker = asyncio.create_task(asyncio.to_thread(run))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        session.cancel()
        # DNS/connection setup cannot always be interrupted. A late connection
        # observes the stop signal before login or mutation. Consume its result.
        worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        raise


def _quote(value: str) -> str:
    """Quote an ASCII IMAP string as data, never as raw search syntax."""
    if any(c in value for c in "\r\n\x00") or not value.isascii():
        raise ValueError("IMAP strings must be ASCII without CR, LF, or NUL; encode mailbox names as modified UTF-7")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ok(response: tuple[str, list[Any]]) -> list[Any]:
    if response[0] != "OK":
        raise MailBackendError("IMAP command was rejected; private server details omitted")
    return response[1]


def _validity(connection: imaplib.IMAP4_SSL) -> str:
    values = connection.response("UIDVALIDITY")[1]
    if not values or not isinstance(values[0], bytes) or not re.fullmatch(rb"[1-9][0-9]*", values[0]):
        raise MailBackendError("IMAP server did not supply a valid UIDVALIDITY")
    return values[0].decode("ascii")


class IMAPEmail:
    """IMAP reading/drafts and optional SMTP sending, with verified TLS by default.

    Args:
        username: Account login (ASCII); also used as sender unless overridden.
        password: Password/app-password or sync/async resolver. OAuth mechanisms
            are not implemented; use Gmail/OutlookEmail for OAuth-only accounts.
        imap_host: Fixed IMAP server hostname; implicit TLS is always required.
        smtp_host: Optional SMTP server; sending is unavailable when omitted.
        sender: Bare ASCII From address; defaults to username.
        mailbox: Selected mailbox, default INBOX. Non-ASCII mailbox names must
            use IMAP modified UTF-7. Message IDs are bound to this account/folder.
        drafts_mailbox: Explicit destination for drafts, e.g. Drafts or
            [Gmail]/Drafts. Omitted means draft creation is unavailable.
        imap_port: IMAP TLS port, default 993.
        smtp_port: Defaults to 465 for implicit TLS or 587 with smtp_starttls.
        smtp_starttls: Require STARTTLS before login instead of implicit TLS.
        timeout_seconds: Positive socket-operation timeout, default 15 seconds.
        max_message_bytes: Maximum fetched message/literal bytes, default 2 MiB.
        ssl_context: Optional application-owned TLS context; default verifies
            server certificates and hostnames using system trust.

    No extra dependencies or connections at construction. Every operation uses a
    fresh connection on a worker thread. Cancellation shuts down an active socket;
    DNS/connection setup may finish later; workers check cancellation before login
    and writes, including after a connection finishes.
    In-flight SMTP/APPEND may already have succeeded and are never retried.

    Search is literal ASCII text across headers/body (empty means all messages),
    not raw IMAP syntax. Pages descend by UID and exclude new arrivals while
    continuing. Expunged messages can disappear; UIDVALIDITY changes reject stale
    message IDs/tokens. Reads use BODY.PEEK and do not set Seen. Full MIME messages
    are fetched within the byte cap, including attachment bytes, but only decoded
    plain text is returned. SMTP delivery does not append a copy to Sent itself.
    """

    query_help = (
        "Query is literal ASCII text across headers and body, not Gmail/IMAP search syntax. "
        "Empty query lists all messages, newest UID first."
    )

    def __init__(
        self,
        username: str,
        password: MailPassword,
        *,
        imap_host: str,
        smtp_host: str | None = None,
        sender: str | None = None,
        mailbox: str = "INBOX",
        drafts_mailbox: str | None = None,
        imap_port: int = 993,
        smtp_port: int | None = None,
        smtp_starttls: bool = False,
        timeout_seconds: float = 15.0,
        max_message_bytes: int = 2 * 1024 * 1024,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if not username or not imap_host.strip() or (smtp_host is not None and not smtp_host.strip()):
            raise ValueError("username and configured server hostnames must not be empty")
        _quote(username)
        _quote(mailbox)
        if not mailbox or drafts_mailbox == "":
            raise ValueError("Mailbox names must not be empty")
        if drafts_mailbox is not None:
            _quote(drafts_mailbox)
        if not callable(password) and (not isinstance(password, str) or not password):
            raise ValueError("password must be nonempty or a password callback")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if isinstance(max_message_bytes, bool) or not isinstance(max_message_bytes, int) or max_message_bytes < 1:
            raise ValueError("max_message_bytes must be a positive integer")
        smtp_port = smtp_port if smtp_port is not None else (587 if smtp_starttls else 465)
        if any(
            isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
            for port in (imap_port, smtp_port)
        ):
            raise ValueError("Mail ports must be integers between 1 and 65535")
        self.sender = _address(sender if sender is not None else username)
        self._username, self._password = username, password
        self._imap_host, self._smtp_host = imap_host, smtp_host
        self._mailbox, self._drafts_mailbox = mailbox, drafts_mailbox
        self._imap_port, self._smtp_port, self._smtp_starttls = imap_port, smtp_port, smtp_starttls
        self._timeout, self._max_bytes = timeout_seconds, max_message_bytes
        self._tls = ssl_context if ssl_context is not None else ssl.create_default_context()
        self._scope = scope_key("imap", imap_host, imap_port, username, mailbox)

    async def _secret(self) -> str:
        value = self._password() if callable(self._password) else self._password
        if inspect.isawaitable(value):
            value = await value
        if not isinstance(value, str) or not value or any(c in value for c in "\r\n\x00"):
            raise ValueError("Password callback must return nonempty text without CR, LF, or NUL")
        return value

    def _connect(self, session: _Session, password: str) -> imaplib.IMAP4_SSL:
        session.check()
        connection = session.attach(
            _BoundedIMAP(
                self._imap_host,
                self._imap_port,
                ssl_context=self._tls,
                timeout=self._timeout,
                max_literal_bytes=self._max_bytes,
            )
        )
        session.check()
        _ok(connection.login(_quote(self._username), password))
        session.check()
        return connection

    def _message_id(self, validity: str, uid: int) -> str:
        return f"{self._scope}:{validity}:{uid}"

    async def list_messages(
        self,
        *,
        query: str = "",
        max_results: int = 20,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List a newest-first page of stable IDs using a literal ASCII TEXT search."""
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        quoted = _quote(query)
        scope = scope_key(self._scope, query, max_results)
        cursor = decode_cursor(page_token, scope) if page_token is not None else None
        if cursor is not None and (
            not isinstance(cursor, dict)
            or not isinstance(cursor.get("before"), int)
            or cursor["before"] < 1
            or not isinstance(cursor.get("validity"), str)
        ):
            raise ValueError("Invalid IMAP page token")
        password = await self._secret()

        def operation(session: _Session) -> dict[str, Any]:
            connection = self._connect(session, password)
            _ok(connection.select(_quote(self._mailbox), readonly=True))
            validity = _validity(connection)
            if cursor is not None and cursor["validity"] != validity:
                raise ValueError("Mailbox UIDVALIDITY changed; restart pagination")
            criteria = ["ALL"] if not query else ["TEXT", quoted]
            if cursor is not None:
                criteria += ["UID", f"1:{cursor['before']}"]
            session.check()
            data = _ok(connection.uid("SEARCH", *criteria))
            try:
                uids = sorted(
                    {int(uid) for part in data if isinstance(part, bytes) for uid in part.split()}, reverse=True
                )
            except ValueError:
                raise MailBackendError("IMAP search returned invalid UIDs") from None
            uids = [uid for uid in uids if uid > 0 and (cursor is None or uid <= cursor["before"])]
            selected = uids[:max_results]
            next_page = None
            if len(uids) > max_results and selected[-1] > 1:
                next_page = encode_cursor(scope, {"validity": validity, "before": selected[-1] - 1})
            return {
                "items": [{"id": self._message_id(validity, uid)} for uid in selected],
                "next_page_token": next_page,
            }

        return await _in_worker(operation)

    async def get_message(self, *, message_id: str) -> dict[str, Any]:
        """Fetch a bounded MIME message without Seen and return only plain-text content."""
        match = re.fullmatch(re.escape(self._scope) + r":([1-9][0-9]*):([1-9][0-9]*)", message_id)
        if match is None:
            raise ValueError("Message ID does not belong to this IMAP account/mailbox")
        expected_validity, uid = match.groups()
        password = await self._secret()

        def operation(session: _Session) -> dict[str, Any]:
            connection = self._connect(session, password)
            _ok(connection.select(_quote(self._mailbox), readonly=True))
            if _validity(connection) != expected_validity:
                raise ValueError("Mailbox UIDVALIDITY changed; list messages again")
            session.check()
            sizes = _ok(connection.uid("FETCH", uid, "(RFC822.SIZE)"))
            size = next(
                (
                    re.search(rb"RFC822.SIZE ([0-9]+)", item)
                    for item in sizes
                    if isinstance(item, bytes) and b"RFC822.SIZE" in item
                ),
                None,
            )
            if size is None:
                raise MailBackendError("Message no longer exists or the server omitted its size")
            if int(size[1]) > self._max_bytes:
                raise ValueError("Message exceeds max_message_bytes; content was not fetched")
            session.check()
            data = _ok(connection.uid("FETCH", uid, "(BODY.PEEK[])"))
            raw = next((item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)), None)
            if raw is None or len(raw) > self._max_bytes:
                raise MailBackendError("IMAP returned missing or oversized message content")
            return self._decode(raw, message_id)

        return await _in_worker(operation)

    @staticmethod
    def _decode(raw: bytes, message_id: str) -> dict[str, Any]:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        texts: list[str] = []
        attachments = html = False
        pending: list[MIMEPart] = [message]
        while pending:
            part = pending.pop()
            if part.get_filename() or part.get_content_disposition() == "attachment":
                attachments = True
                continue
            if part.is_multipart():
                pending.extend(reversed(list(part.iter_parts())))
            elif part.get_content_type() == "text/plain":
                content = part.get_payload(decode=True)
                if not isinstance(content, bytes):
                    continue
                try:
                    texts.append(content.decode(part.get_content_charset() or "utf-8", errors="replace"))
                except LookupError:
                    texts.append(content.decode("utf-8", errors="replace"))
            elif part.get_content_type() == "text/html":
                html = True
        body = "\n".join(texts)
        return {
            "id": message_id,
            "thread_id": None,
            "from": str(message.get("From", "")),
            "to": str(message.get("To", "")),
            "subject": str(message.get("Subject", "")),
            "date": str(message.get("Date", "")),
            "snippet": body[:200],
            "body": body[:20000],
            "body_truncated": len(body) > 20000,
            "has_attachments": attachments,
            "html_body_omitted": html and not texts,
        }

    def _compose(self, to: list[str], subject: str, body: str) -> EmailMessage:
        _message_fields(to, subject, body)
        message = EmailMessage(policy=policy.SMTP)
        message["From"], message["To"], message["Subject"] = self.sender, ", ".join(to), subject
        message["Date"], message["Message-ID"] = (
            formatdate(localtime=False),
            make_msgid(domain=self.sender.rsplit("@", 1)[1]),
        )
        message.set_content(body)
        return message

    async def create_draft(self, *, to: list[str], subject: str, body: str) -> dict[str, Any]:
        """APPEND one unsent Draft message; do not create missing folders or deliver it."""
        if self._drafts_mailbox is None:
            raise ValueError("IMAPEmail(drafts_mailbox=...) is required for drafts")
        message = self._compose(to, subject, body)
        raw = message.as_bytes()
        if len(raw) > self._max_bytes:
            raise ValueError("Draft exceeds max_message_bytes")
        password = await self._secret()

        def operation(session: _Session) -> dict[str, Any]:
            connection = self._connect(session, password)
            session.check()
            _ok(connection.append(_quote(self._drafts_mailbox or ""), r"\Draft", None, raw))
            return {"status": "drafted", "message_id": str(message["Message-ID"]), "mailbox": self._drafts_mailbox}

        return await _in_worker(operation)

    async def send_message(self, *, to: list[str], subject: str, body: str) -> dict[str, Any]:
        """Submit SMTP once; return accepted/refused recipients without claiming delivery."""
        if self._smtp_host is None:
            raise ValueError("IMAPEmail(smtp_host=...) is required for sending")
        message = self._compose(to, subject, body)
        if len(message.as_bytes()) > self._max_bytes:
            raise ValueError("Message exceeds max_message_bytes")
        password = await self._secret()

        def operation(session: _Session) -> dict[str, Any]:
            session.check()
            if self._smtp_starttls:
                connection = session.attach(smtplib.SMTP(self._smtp_host or "", self._smtp_port, timeout=self._timeout))
                session.check()
                connection.starttls(context=self._tls)
            else:
                connection = session.attach(
                    smtplib.SMTP_SSL(self._smtp_host or "", self._smtp_port, timeout=self._timeout, context=self._tls)
                )
            session.check()
            connection.login(self._username, password)
            session.check()
            try:
                refused = connection.send_message(message, from_addr=self.sender, to_addrs=to)
            except smtplib.SMTPRecipientsRefused as exc:
                refused = exc.recipients
            accepted = [address for address in to if address not in refused]
            status = "accepted" if not refused else "partially_accepted" if accepted else "rejected"
            return {
                "status": status,
                "message_id": str(message["Message-ID"]),
                "accepted": accepted,
                "refused": [{"address": address, "code": int(details[0])} for address, details in refused.items()],
            }

        return await _in_worker(operation)
