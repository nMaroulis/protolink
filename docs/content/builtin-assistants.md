# Built-in assistants and service tools

Version 0.7.2 adds small `Assistant` and `CodeAssistant` presets. Both are ordinary `Agent` subclasses:
they register tools and set a role prompt and default policy. They use the same `invoke`, `call_tool`,
streaming, cancellation, state, storage, and transport APIs as any other agent. They do not choose a model,
connect an account, or start a server for you. `invoke()` is the general conversation entry point;
`ask()` retains the existing knowledge/RAG contract.

```python
from protolink import Assistant, CodeAssistant, create_llm
from protolink.tools import Gmail, GoogleCalendar

# Use any configured ProtoLink model.
model = create_llm("mock", default_response="Ready")

coder = CodeAssistant(llm=model, cwd=".")
print(await coder.invoke("Explain what you can do."))

# token is an application-owned OAuth access token or token callback.
assistant = Assistant(calendar=GoogleCalendar(token), email=Gmail(token))
events = await assistant.call_tool(
    "list_calendar_events",
    start="2026-09-19T00:00:00+02:00",
    end="2026-09-20T00:00:00+02:00",
)
```

Use a separate model instance per concurrently running agent if the model retains mutable state.
The Google and Microsoft adapters need `pip install 'protolink[integrations]'` (HTTPX).
`IMAPEmail`, the backend interfaces, and all other new tools add no base dependencies.
Shell and Git need host executables.

| Backend | Service | Authentication |
| --- | --- | --- |
| `GoogleCalendar` | Google Calendar | OAuth access token or token callback |
| `Gmail` | Gmail | OAuth access token or token callback |
| `OutlookCalendar` | Microsoft 365 / Outlook calendar | OAuth access token or token callback |
| `OutlookEmail` | Microsoft 365 / Outlook mailbox | OAuth access token or token callback |
| `IMAPEmail` | Standard TLS IMAP and optional SMTP | Password/app-password or password callback |

All backends work with the same `Assistant`, `calendar_tools()`, and `email_tools()` APIs.
You can mix services, such as a Microsoft calendar and an IMAP mailbox. Construction never connects
to an account. The tool descriptions tell the model which search syntax the selected backend uses.

## Assistant

```python
assistant = Assistant(
    llm=model,  # Optional for direct call_tool usage.
    calendar=GoogleCalendar(token),  # Omit a service to exclude its tools.
    email=Gmail(token, sender="me@example.com"),
    ask_user=handle_question,  # Optional async user-feedback callback.
    allow_write=True,  # Calendar creation and email drafts.
    allow_send=True,  # Separately opt into email delivery.
    approval_handler=approve,  # Normal Agent approval callback.
    state=["conversation"],
)
```

`handle_question`, `approve`, and `token` are application-supplied dependencies. Clock and calculator
are always included. Reads and user questions are allowed by the preset's default policy; calendar
creation, drafts, and delivery require approval. Both write flags default to `False`. Omitting an
approval handler leaves approval-gated calls blocked by the existing runtime; it never auto-approves.
Question answers clarify intent; they do not authorize a write.

Pass a custom `card=AgentCard(...)` for a different name/URL. Other constructor keywords pass directly
to `Agent`, including `policy`, `system_prompt`, `transport`, `knowledge`, `storage`, and `run_store`.
A supplied policy replaces the preset policy. New capabilities are denied by the preset's default policy;
explicitly configure them when adding more tools.

## CodeAssistant

```python
coder = CodeAssistant(
    llm=model,
    cwd="/absolute/workspace",
    env={"PATH": "/usr/bin:/bin"},
    ask_user=handle_question,
    allow_git_write=True,
    approval_handler=approve,
)
print(await coder.invoke("Inspect the changes and run the relevant tests."))
```

The preset includes `run_shell`, `git`, and `calculator`, plus `ask_user` when a callback is supplied.
Git reads and questions are allowed; shell commands and Git writes require approval. Git writes also
need `allow_git_write=True` (default `False`). Shell execution can mutate host resources even when
Git writes are disabled. A working directory does not provide filesystem or network isolation.

`env=None` supplies only `PATH=os.defpath`; it does not copy the parent environment. Configure
credentials and author identity explicitly when needed. Tool factories offer timeout, output-limit,
executable, and backend settings; replace a preset's tool with a configured factory for those options.
See [shell, Git, and user interaction](execution-tools.md#shell-and-git-tools).

## Calendar integration

```python
from protolink.tools import GoogleCalendar, calendar_tools

for tool in calendar_tools(GoogleCalendar(token, calendar_id="primary"), allow_write=True):
    agent.add_tool(tool)
```

`calendar_tools(backend, *, allow_write=False, timeout_seconds=30)` returns prepared tools:

| Tool | Arguments | Capability |
| --- | --- | --- |
| `list_calendar_events` | `start`, `end`, `query=""`, `max_results=20`, `page_token=None` | `calendar.read` |
| `create_calendar_event` | `title`, `start`, `end`, `description=""`, `location=""` | `calendar.write` |

Start/end are ISO 8601 timestamps with explicit offsets; end must follow start. Listing returns events
overlapping the interval, including recurring instances and all-day events. `max_results` is 1–100.
Results use `items` and `next_page_token`; keep the same backend, interval, query, and page size for
another page. An empty page can still have a next token. Google and Microsoft event objects retain
their original service fields, including their different representations of all-day boundaries.

Creation returns the service event object with its `id`. This version creates personal timed events:
it does not invite attendees, create recurring/all-day events, modify existing events, or delete events.
Applications choose the user's timezone and check scheduling conflicts. Invalid intervals are rejected
before an approval is requested or a backend is called.

Implement the small async `CalendarBackend` protocol to use another service. Its two methods are
`list_events(*, start, end, query, max_results, page_token)` and
`create_event(*, title, start, end, description, location)`, both returning JSON-compatible dictionaries.
The offline example implements this interface without any account.

## Email integration

```python
from protolink.tools import Gmail, email_tools

for tool in email_tools(Gmail(token, sender="me@example.com"), allow_write=True, allow_send=True):
    agent.add_tool(tool)
```

`email_tools(backend, *, allow_write=False, allow_send=False, timeout_seconds=30)` returns:

| Tool | Arguments | Capability |
| --- | --- | --- |
| `list_email_messages` | `query=""`, `max_results=20`, `page_token=None` | `email.read` |
| `read_email` | `message_id` | `email.read` |
| `create_email_draft` | `to`, `subject`, `body` | `email.write` |
| `send_email` | `to`, `subject`, `body` | `email.send` |

`allow_write` includes drafts, and `allow_send` independently includes sending. Drafting never delivers
mail. Queries use provider syntax, such as Gmail's `is:unread newer_than:7d`. Lists return one page of
message identifiers in `items`, with `next_page_token`; keep the same backend, query, and page size
while continuing, and fetch content with `read_email`. Reads do not mark mail read. All built-in
backends return selected headers, snippet, a plain-text `body` capped at 20,000 characters,
`body_truncated`, `has_attachments`, and `html_body_omitted`. Gmail and IMAP decode nested MIME text
parts and declared charsets; Outlook requests plain text from Graph. Attachment content is never
returned to the model. IMAP fetches the bounded MIME message including attachment bytes; the HTTP
backends do not request attachments separately. HTML-only MIME bodies are omitted.

Compose operations accept 1–50 bare ASCII recipient addresses, a nonblank subject up to 1,000
characters, and a nonblank plain-text body up to 200,000 characters. Header injection is rejected
before approval. Gmail's fixed `sender` is required for composing and must be the authenticated
address or a configured send-as alias. This version does not compose attachments, CC/BCC, HTML,
or threaded replies. Gmail sending returns service message/thread IDs; draft creation returns draft
and message identifiers. Other backends return the statuses described below. None claims delivery
to the recipient's inbox.

Implement `EmailBackend` for another service: async `list_messages(*, query, max_results, page_token)`,
`get_message(*, message_id)`, `create_draft(*, to, subject, body)`, and
`send_message(*, to, subject, body)`, returning JSON-compatible dictionaries. Read-only adapters need
only implement the methods enabled in their tool bundle. An optional `query_help` string on either
backend protocol's implementation adds search guidance to the model-facing tool description.

## Microsoft 365 and Outlook

```python
from protolink import Assistant
from protolink.tools import OutlookCalendar, OutlookEmail

# token is your access token or a sync/async callback returning one.
assistant = Assistant(calendar=OutlookCalendar(token), email=OutlookEmail(token))

# Select an explicit user and calendar when needed.
calendar = OutlookCalendar(token, user_id="me@example.com", calendar_id="calendar-id")
email = OutlookEmail(token, user_id="me@example.com")
```

Both constructors default to `user_id="me"` for delegated OAuth access. Application tokens require
an explicit user ID or principal name. `calendar_id=None` selects that user's default calendar.
All calls stay on the global `graph.microsoft.com/v1.0` endpoint; national-cloud endpoints are not
supported. Grant access to the selected user/calendar/mailbox in your application registration:

| Operation | Microsoft Graph permission |
| --- | --- |
| Calendar reading | `Calendars.Read` |
| Calendar creation | `Calendars.ReadWrite` |
| Email reading/search | `Mail.Read` |
| Email drafts | `Mail.ReadWrite` |
| Email sending | `Mail.Send` |

Shared resources can require additional delegated permissions or mailbox access rights. Permissions,
consent, and token refresh are application-owned; a token callback must keep the same account.

Calendar listing uses [calendarView](https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0)
to expand recurring occurrences within the requested interval. `query` filters each returned page by
a case-insensitive substring in subject, body preview, or location. Follow `next_page_token` even
when filtering produces an empty page. Creating an event converts the supplied offsets to equivalent
UTC instants and sends a personal event with no attendees.

Email queries use [Microsoft Graph message search](https://learn.microsoft.com/en-us/graph/search-query-parameter),
for example `subject:review` or `from:person@example.com`. Search is capped at 1,000 matching messages;
an empty query lists the mailbox in descending received-time order. Message requests use immutable
IDs, and reads request plain text without changing read status.

Microsoft continuation tokens belong to the existing backend instance, selected resource, and query
arguments. Restart listing after recreating a backend or changing those arguments. Continuation links
are validated against the original HTTPS host and collection before use. They cannot switch users,
calendars, or mailboxes.

Draft creation returns the Graph draft object and `id`. Sending saves a copy to Sent Items and returns
`{"status": "accepted"}`. Microsoft's [sendMail response](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
is HTTP 202 with no message ID and does not confirm completed delivery.

## Standard IMAP and SMTP

```python
import os

from protolink import Assistant
from protolink.tools import IMAPEmail

mail = IMAPEmail(
    "me@example.com",
    lambda: os.environ["MAIL_PASSWORD"],
    imap_host="imap.example.com",
    smtp_host="smtp.example.com",  # Omit for read/draft-only access.
    drafts_mailbox="Drafts",  # Explicit existing folder; omit if drafts aren't needed.
)
assistant = Assistant(email=mail)
# To expose drafts/sending, supply allow_write/allow_send and an approval handler.
```

`IMAPEmail` uses only the Python standard library. Passwords can be strings or no-argument sync/async
callbacks, resolved once per operation. Use an app password if your provider requires one and supports
this authentication method. OAuth-only accounts should use `Gmail` or `OutlookEmail`.

IMAP always uses implicit TLS, normally port 993. SMTP uses implicit TLS on port 465 by default.
For submission servers on port 587, set `smtp_starttls=True`; STARTTLS must succeed before login.
Override `imap_port` or `smtp_port` for other TLS endpoints. Default TLS contexts validate server
certificates and hostnames; an optional `ssl_context` lets your application supply its own trust
configuration. There is no plaintext fallback.

`sender` defaults to the login username; supply a bare ASCII address when your login name is not an
address or when using an authorized alias. `mailbox="INBOX"` selects the folder being read.
Mailbox names and usernames must be ASCII; encode international mailbox names as IMAP modified UTF-7.
`drafts_mailbox` names an existing folder: the backend does not discover or create it. `smtp_host` is
required only for sending, and SMTP submission does not itself append a second copy to Sent.

Search is literal ASCII text across headers and body; it is not Gmail or raw IMAP search syntax.
Empty query means all messages. Pages descend by UID; subsequent pages exclude new arrivals, while
expunged messages may disappear. IDs and cursors include the selected account/folder's identity and
UIDVALIDITY. A changed UIDVALIDITY rejects stale IDs/tokens so they cannot silently reference another
message. Use IDs from `list_email_messages` with the same account and folder.

Reads select the mailbox read-only, fetch size first, and use `BODY.PEEK[]` without setting Seen.
`max_message_bytes=2097152` caps both fetched MIME bytes and composed message bytes; oversized messages
are rejected. Returned plain text is additionally capped at 20,000 characters. These behaviors use
Python's [IMAP](https://docs.python.org/3/library/imaplib.html) and
[SMTP](https://docs.python.org/3/library/smtplib.html) interfaces.

Drafts are appended with the Draft flag and return `status="drafted"`, `mailbox`, and an RFC Message-ID
in `message_id`. This local header value is not an IMAP ID for `read_email`. Sending returns:

```python
{
    "status": "partially_accepted",  # Or "accepted" or "rejected".
    "message_id": "<generated-rfc-message-id@example.com>",
    "accepted": ["one@example.com"],
    "refused": [{"address": "two@example.com", "code": 550}],
}
```

Acceptance means the SMTP server accepted those recipients; it is not final delivery confirmation.
Partial rejection does not undo accepted recipients, and nothing is automatically resent. Private
server response text is excluded from results and `MailBackendError` exceptions.

## Authentication, policy, and lifecycle

Google and Microsoft adapters accept an access-token string or a no-argument sync/async callback that returns a fresh
access token for each request. OAuth consent, scopes, refreshing, secure storage, and account selection
belong to the application. Tokens are never model arguments, approval previews, or serialized agent
configuration. Keep callbacks on the same account when refreshing credentials.
For Google, use these scopes (prefixed by `https://www.googleapis.com/auth/`):

| Operation | Scope |
| --- | --- |
| Calendar reading | `calendar.events.readonly` or `calendar.events` |
| Calendar creation | `calendar.events` |
| Email reading/search | `gmail.readonly` |
| Email drafts | `gmail.compose` |
| Email sending | `gmail.send` or `gmail.compose` |

For provider details, see Google's [event listing](https://developers.google.com/workspace/calendar/api/v3/reference/events/list),
[event creation](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[message listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), and
[message sending](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send) contracts.

Factories do not contact accounts. All tools must execute through an Agent's native policy pipeline;
direct prepared-tool calls fail closed. Configured targets and exact arguments are attached as previews.
Unlike the assistant presets, the ordinary `Agent` policy remains allow-by-default: configure it explicitly
when registering tool bundles yourself. For example:

```python
from protolink import CapabilityPolicy

policy = CapabilityPolicy(
    {
        "calendar.read": "allow",
        "email.read": "allow",
        "calendar.write": "require_approval",
        "email.write": "require_approval",
        "email.send": "require_approval",
        "user.interact": "allow",
    },
    default_effect="deny",
)
```

Each operation has a timeout, further bounded by the remaining run budget. Google and Microsoft HTTP clients close
on success, errors, timeout, and cancellation, reject redirects, cap response data at 2 MiB, and never
retry automatically. `GoogleAPIError.status_code` and `MicrosoftGraphError.status_code` expose HTTP
failures without copying remote error bodies into exceptions.

IMAP/SMTP operations run on worker threads with fresh connections, closed after each operation.
`timeout_seconds=15` on `IMAPEmail` bounds individual socket operations; the tool factory's timeout
bounds the overall await. Cancellation interrupts an established socket. DNS/connection setup can
finish later; workers check cancellation before login and writes, including after connection setup.
A timed-out/canceled write may already have occurred remotely: inspect the calendar/mailbox before
retrying. Provider errors do not imply an unchanged account.

Service content is untrusted data and can enter model history and reports. Apply the existing run/store
redaction policy for sensitive application data. Configured tool closures, tokens, backends, and question
callbacks are not restored from dict/YAML. Load with `Agent.from_dict/from_yaml`, then re-register the
configured factories; the simple parameterless built-ins keep their existing round-trip behavior.

## One complete offline example

```bash
python examples/builtin_assistants.py
```

[`builtin_assistants.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_assistants.py)
asserts shell pipelines, all six Git operations, live model question/answer continuation, calendar
listing/creation, mailbox search/read, draft creation, and sending to an in-memory backend. It exercises
both presets and existing clock/calculator tools. Only a temporary repository is changed; no account,
external model, or real email delivery is used. Its automatic approval callback is specific to this demo.

To exercise all five concrete service backends through the same `Assistant` tools:

```bash
pip install 'protolink[integrations]'
python examples/service_backends.py
```

[`service_backends.py`](https://github.com/nMaroulis/protolink/blob/main/examples/service_backends.py)
tests Google and Outlook calendars, Gmail, Outlook email, and IMAP/SMTP in one run. It replaces HTTP
and mail-server transports with local fixtures, preserving the real backend serialization, MIME
handling, native tool execution, and approval path. It does not use sockets or contact live accounts.
