"""IMAP UID identity, MIME limits, verified TLS, SMTP outcomes, and cancellation."""

import asyncio
import imaplib
import smtplib
import ssl
import threading
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from protolink import ApprovalRequiredError, Assistant
from protolink.tools import IMAPEmail, MailBackendError, email_tools
from protolink.tools.builtins import imap_email

MESSAGE = {"to": ["one@example.com", "two@example.com"], "subject": "Café", "body": "Meet tomorrow?"}


@pytest.fixture
def mail(monkeypatch):
    """Fake only stdlib server sessions; use real MIME serialization/parsing."""
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = "Café", "sender@example.com", "me@example.com"
    message.set_content("Hello café")
    state = SimpleNamespace(
        calls=[],
        connections=[],
        validity=b"42",
        uids=b"1 2 3 4",
        raw=message.as_bytes(),
        advertised_size=None,
        failures={},
        refused={},
        connect_wait=None,
        login_wait=None,
        entered=threading.Event(),
        closed=threading.Event(),
    )

    def record(name, *args):
        state.calls.append((name, *args))
        if name in state.failures:
            raise state.failures[name]

    class Socket:
        def shutdown(self, how):
            record("interrupt", how)
            if state.login_wait:
                state.login_wait.set()

    class IMAP:
        def __init__(self, host, port, **kwargs):
            self.sock = Socket()
            self.closed = False
            state.connections.append(self)
            record("imap", host, port, kwargs)
            if state.connect_wait:
                state.entered.set()
                assert state.connect_wait.wait(2)

        def login(self, user, password):
            record("imap.login", user, password)
            if state.login_wait:
                state.entered.set()
                assert state.login_wait.wait(2)
            return "OK", [b"logged in"]

        def select(self, mailbox, *, readonly=False):
            record("select", mailbox, readonly)
            return "OK", [b"4"]

        def response(self, name):
            record("response", name)
            return name, [state.validity]

        def uid(self, command, *args):
            record(command, *args)
            if command == "SEARCH":
                return "OK", [state.uids]
            if args[1] == "(RFC822.SIZE)":
                size = len(state.raw) if state.advertised_size is None else state.advertised_size
                return "OK", [f"1 (UID {args[0]} RFC822.SIZE {size})".encode()]
            return "OK", [(b"1 (BODY[]", state.raw), b")"]

        def append(self, *args):
            record("append", *args)
            return "OK", [b"APPEND completed"]

        def shutdown(self):
            record("imap.close")
            self.closed = True
            state.closed.set()

    class SMTP:
        def __init__(self, host, port, **kwargs):
            self.sock = Socket()
            self.closed = False
            state.connections.append(self)
            record("smtp", host, port, kwargs)

        def starttls(self, **kwargs):
            record("starttls", kwargs)
            return 220, b"ready"

        def login(self, user, password):
            record("smtp.login", user, password)
            return 235, b"logged in"

        def send_message(self, message, **kwargs):
            record("send", message, kwargs)
            return state.refused

        def close(self):
            record("smtp.close")
            self.closed = True
            state.closed.set()

    class SMTPSSL(SMTP):
        pass

    monkeypatch.setattr(imap_email, "_BoundedIMAP", IMAP)
    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPSSL)
    yield state
    assert all(connection.closed for connection in state.connections)


def backend(**options):
    return IMAPEmail("me@example.com", "private-password", **{"imap_host": "imap.example.com", **options})


@pytest.mark.asyncio
async def test_readonly_pagination_scoped_ids_and_no_seen(mail):
    email = backend(mailbox='Projects "2026"')
    assert mail.calls == []
    first = await email.list_messages(query='project "review"', max_results=2)
    assert [item["id"].rsplit(":", 1)[1] for item in first["items"]] == ["4", "3"]
    mail.uids = b"1 2 3 4 5"  # New arrivals must not leak into later pages.
    second = await email.list_messages(query='project "review"', max_results=2, page_token=first["next_page_token"])
    assert [item["id"].rsplit(":", 1)[1] for item in second["items"]] == ["2", "1"]
    assert second["next_page_token"] is None
    assert ("SEARCH", "TEXT", '"project \\"review\\""', "UID", "1:2") in mail.calls
    result = await email.get_message(message_id=first["items"][0]["id"])
    assert result["subject"] == "Café" and result["body"].strip() == "Hello café"
    assert result["id"] == first["items"][0]["id"]
    assert ("FETCH", "4", "(RFC822.SIZE)") in mail.calls and ("FETCH", "4", "(BODY.PEEK[])") in mail.calls
    assert all(call[2] is True for call in mail.calls if call[0] == "select")
    assert ("select", '"Projects \\"2026\\""', True) in mail.calls
    connection = next(call for call in mail.calls if call[0] == "imap")
    context = connection[3]["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert connection[2] == 993


@pytest.mark.asyncio
async def test_stale_uidvalidity_rejects_read_and_page(mail):
    email = backend()
    first = await email.list_messages(max_results=1)
    mail.validity = b"43"
    with pytest.raises(ValueError, match="UIDVALIDITY"):
        await email.get_message(message_id=first["items"][0]["id"])
    with pytest.raises(ValueError, match="UIDVALIDITY"):
        await email.list_messages(max_results=1, page_token=first["next_page_token"])
    assert not any(call[0] == "FETCH" for call in mail.calls)
    assert sum(call[0] == "SEARCH" for call in mail.calls) == 1


@pytest.mark.asyncio
async def test_foreign_ids_changed_queries_and_malformed_tokens_rejected_before_io(mail):
    email = backend()
    first = await email.list_messages(max_results=1)
    count = len(mail.calls)
    with pytest.raises(ValueError, match="account/mailbox"):
        await backend(mailbox="Archive").get_message(message_id=first["items"][0]["id"])
    with pytest.raises(ValueError, match="page token"):
        await email.list_messages(max_results=1, query="changed", page_token=first["next_page_token"])
    with pytest.raises(ValueError, match="page token"):
        await backend(imap_host="another.example.com").list_messages(max_results=1, page_token=first["next_page_token"])
    with pytest.raises(ValueError, match="page token"):
        await email.list_messages(page_token="not-a-cursor")
    assert len(mail.calls) == count


@pytest.mark.asyncio
async def test_mime_charsets_attached_messages_and_body_limit(mail):
    message = EmailMessage()
    message["Subject"] = "Résumé"
    message.set_content("café" + "x" * 20000, charset="iso-8859-1")
    message.add_alternative("<b>café</b>", subtype="html")
    message.add_attachment(b"private attachment", maintype="text", subtype="plain", filename="file.txt")
    forwarded = EmailMessage()
    forwarded.set_content("private forwarded content")
    message.add_attachment(forwarded)
    mail.raw = message.as_bytes()
    email = backend()
    message_id = (await email.list_messages())["items"][0]["id"]
    result = await email.get_message(message_id=message_id)
    assert result["subject"] == "Résumé" and result["body"].startswith("café")
    assert len(result["body"]) == 20000 and result["body_truncated"] and result["has_attachments"]
    assert "private" not in result["body"] and not result["html_body_omitted"]


def test_html_only_and_unknown_charset_decoding():
    result = IMAPEmail._decode(b"Content-Type: text/html\r\n\r\n<b>Hello</b>", "id")
    assert result["html_body_omitted"] and result["body"] == ""
    result = IMAPEmail._decode(b"Content-Type: text/plain; charset=unknown\r\n\r\nhello", "id")
    assert result["body"] == "hello"


@pytest.mark.asyncio
async def test_oversized_messages_rejected_before_body_fetch(mail):
    email = backend(max_message_bytes=10)
    message_id = (await email.list_messages())["items"][0]["id"]
    with pytest.raises(ValueError, match="not fetched"):
        await email.get_message(message_id=message_id)
    assert not any("(BODY.PEEK[])" in call for call in mail.calls)
    mail.advertised_size = 1  # A dishonest size response cannot bypass the byte cap.
    with pytest.raises(MailBackendError, match="oversized"):
        await email.get_message(message_id=message_id)


def test_imap_literal_limit_applies_before_allocation():
    connection = imap_email._BoundedIMAP.__new__(imap_email._BoundedIMAP)
    connection._max_literal_bytes = 10
    with pytest.raises(MailBackendError, match="literal exceeds"):
        connection.read(11)


@pytest.mark.asyncio
async def test_draft_appends_unsent_mime_to_explicit_folder(mail):
    result = await backend(drafts_mailbox="[Gmail]/Drafts").create_draft(**MESSAGE)
    call = next(call for call in mail.calls if call[0] == "append")
    assert call[1:4] == ('"[Gmail]/Drafts"', r"\Draft", None)
    message = BytesParser(policy=policy.default).parsebytes(call[4])
    assert str(message["Subject"]) == MESSAGE["subject"] and message.get_content().strip() == MESSAGE["body"]
    assert message["From"] == "me@example.com" and message["Date"]
    assert result == {"status": "drafted", "message_id": str(message["Message-ID"]), "mailbox": "[Gmail]/Drafts"}
    assert not any(call[0] == "smtp" for call in mail.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("starttls", [False, True])
async def test_smtp_tls_precedes_login_and_submission(mail, starttls):
    async def password():
        return "fresh-password"

    email = IMAPEmail(
        "me@example.com", password, imap_host="imap.example.com", smtp_host="smtp.example.com", smtp_starttls=starttls
    )
    result = await email.send_message(**MESSAGE)
    names = [call[0] for call in mail.calls]
    assert names == (
        ["smtp", "starttls", "smtp.login", "send", "smtp.close"]
        if starttls
        else ["smtp", "smtp.login", "send", "smtp.close"]
    )
    assert mail.calls[0][2] == (587 if starttls else 465)
    context = mail.calls[1][1]["context"] if starttls else mail.calls[0][3]["context"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert ("smtp.login", "me@example.com", "fresh-password") in mail.calls
    submission = next(call for call in mail.calls if call[0] == "send")
    assert submission[2] == {"from_addr": "me@example.com", "to_addrs": MESSAGE["to"]}
    assert result["status"] == "accepted" and result["accepted"] == MESSAGE["to"] and result["refused"] == []
    assert result["message_id"] == str(submission[1]["Message-ID"])


@pytest.mark.asyncio
async def test_starttls_failure_never_logs_in_or_sends(mail):
    mail.failures["starttls"] = smtplib.SMTPNotSupportedError("private details")
    with pytest.raises(MailBackendError, match="no automatic retry") as caught:
        await backend(smtp_host="smtp.example.com", smtp_starttls=True).send_message(**MESSAGE)
    assert "private" not in str(caught.value)
    assert [call[0] for call in mail.calls] == ["smtp", "starttls", "smtp.close"]


@pytest.mark.asyncio
async def test_partial_and_total_recipient_refusal(mail):
    email = backend(smtp_host="smtp.example.com")
    mail.refused = {"two@example.com": (550, b"private error text")}
    result = await email.send_message(**MESSAGE)
    assert result["status"] == "partially_accepted" and result["accepted"] == ["one@example.com"]
    assert result["refused"] == [{"address": "two@example.com", "code": 550}]
    mail.failures["send"] = smtplib.SMTPRecipientsRefused(dict.fromkeys(MESSAGE["to"], (550, b"private")))
    result = await email.send_message(**MESSAGE)
    assert result["status"] == "rejected" and result["accepted"] == [] and len(result["refused"]) == 2
    assert "private" not in str(result)
    assert sum(call[0] == "send" for call in mail.calls) == 2


@pytest.mark.asyncio
async def test_auth_errors_close_without_leaking_server_details(mail):
    mail.failures["imap.login"] = imaplib.IMAP4.error("private-password provider response")
    with pytest.raises(MailBackendError) as caught:
        await backend().list_messages()
    assert "private-password" not in str(caught.value)
    assert [call[0] for call in mail.calls] == ["imap", "imap.login", "imap.close"]


@pytest.mark.asyncio
async def test_uncertain_smtp_error_is_not_retried(mail):
    mail.failures["send"] = smtplib.SMTPServerDisconnected("private server detail")
    with pytest.raises(MailBackendError, match="no automatic retry"):
        await backend(smtp_host="smtp.example.com").send_message(**MESSAGE)
    assert sum(call[0] == "send" for call in mail.calls) == 1


@pytest.mark.asyncio
async def test_native_timeout_interrupts_imap_before_mutation(mail):
    mail.login_wait = threading.Event()

    async def approve(request, context):
        return True

    email = backend(drafts_mailbox="Drafts")
    assistant = Assistant(approval_handler=approve, verbosity=0)
    for tool in email_tools(email, allow_write=True, timeout_seconds=0.05):
        assistant.add_tool(tool)
    try:
        with pytest.raises(TimeoutError):
            await assistant.call_tool("create_email_draft", **MESSAGE)
    finally:
        mail.login_wait.set()
        assert await asyncio.to_thread(mail.closed.wait, 1)
    assert not any(call[0] == "append" for call in mail.calls)


def test_literal_search_guidance_reaches_model_tool_description():
    assert "literal ASCII text" in email_tools(backend())[0].description


@pytest.mark.asyncio
@pytest.mark.parametrize("validity", [None, b"", b"bad", b"0"])
async def test_invalid_uidvalidity_is_not_used_for_message_identity(mail, validity):
    mail.validity = validity
    with pytest.raises(MailBackendError, match="UIDVALIDITY"):
        await backend().list_messages()
    assert not any(call[0] == "SEARCH" for call in mail.calls)


@pytest.mark.asyncio
async def test_password_callback_errors_before_connection(mail):
    async def password():
        return "invalid\npassword"

    email = IMAPEmail("me@example.com", password, imap_host="imap.example.com")
    with pytest.raises(ValueError, match="Password callback"):
        await email.list_messages()
    assert mail.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("during_connection", [False, True])
async def test_cancel_interrupts_worker_and_prevents_late_draft(mail, during_connection):
    release = threading.Event()
    if during_connection:
        mail.connect_wait = release
    else:
        mail.login_wait = release
    task = asyncio.create_task(backend(drafts_mailbox="Drafts").create_draft(**MESSAGE))
    try:
        assert await asyncio.to_thread(mail.entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(mail.closed.wait, 1)
    assert not any(call[0] == "append" for call in mail.calls)
    if during_connection:
        assert not any(call[0] == "imap.login" for call in mail.calls)
    assert any(call[0] == "interrupt" for call in mail.calls)


@pytest.mark.asyncio
async def test_assistant_policy_prevents_smtp_connection(mail):
    assistant = Assistant(email=backend(smtp_host="smtp.example.com"), allow_send=True, verbosity=0)
    with pytest.raises(ApprovalRequiredError):
        await assistant.call_tool("send_email", **MESSAGE)
    assert mail.calls == []


@pytest.mark.asyncio
async def test_optional_write_configuration_and_input_validation_precede_io(mail):
    email = backend()
    with pytest.raises(ValueError, match="drafts_mailbox"):
        await email.create_draft(**MESSAGE)
    with pytest.raises(ValueError, match="smtp_host"):
        await email.send_message(**MESSAGE)
    for query in ["hello\nALL", "café"]:
        with pytest.raises(ValueError, match="ASCII"):
            await email.list_messages(query=query)
    with pytest.raises(ValueError):
        await backend(smtp_host="smtp.example.com").send_message(
            **{**MESSAGE, "subject": "hello\r\nBcc: attacker@example.com"}
        )
    with pytest.raises(ValueError, match="exceeds"):
        await backend(smtp_host="smtp.example.com", max_message_bytes=1).send_message(**MESSAGE)
    assert mail.calls == []


@pytest.mark.parametrize(
    "options",
    [
        {"imap_host": ""},
        {"mailbox": ""},
        {"imap_port": 0},
        {"smtp_port": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"max_message_bytes": True},
        {"max_message_bytes": -1},
        {"drafts_mailbox": "Drafts\nINBOX"},
    ],
)
def test_invalid_configuration(options):
    with pytest.raises(ValueError):
        backend(**options)
