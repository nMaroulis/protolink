"""Service wire contracts, policy previews, and compact built-in Agent presets."""

import asyncio
import base64
import json
from email import message_from_bytes, policy

import httpx
import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    ApprovalRequiredError,
    Assistant,
    CapabilityPolicy,
    CodeAssistant,
)
from protolink.tools import Gmail, GoogleAPIError, GoogleCalendar, calendar_tools, email_tools

START = "2026-09-19T09:00:00+02:00"
END = "2026-09-19T10:00:00+02:00"


def agent_with(*tools, **kwargs):
    agent = Agent(AgentCard(name="services", description="test", url="runtime://services"), verbosity=0, **kwargs)
    for tool in tools:
        agent.add_tool(tool)
    return agent


@pytest.fixture
def http_mock(monkeypatch):
    """Patch only the HTTP transport, keeping real request/response serialization."""
    original = httpx.AsyncClient
    requests = []
    responses = []
    clients = []

    async def respond(request):
        requests.append(request)
        response = responses.pop(0)
        if callable(response):
            return await response(request)
        return response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        instance = original(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    yield requests, responses
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_calendar_wire_contract_pagination_offsets_and_previews(http_mock):
    requests, responses = http_mock
    responses.extend(
        [
            httpx.Response(
                200, json={"items": [{"id": "event-1", "start": {"date": "2026-09-19"}}], "nextPageToken": "page2"}
            ),
            httpx.Response(200, json={"items": []}),
            httpx.Response(200, json={"id": "created"}),
        ]
    )
    approvals = []

    async def approve(request, context):
        approvals.append(request.action)
        return True

    backend = GoogleCalendar("private-oauth-token", calendar_id="user@example.com/selected")
    agent = agent_with(
        *calendar_tools(backend, allow_write=True),
        policy=CapabilityPolicy({"calendar.write": "require_approval"}),
        approval_handler=approve,
    )
    page = await agent.call_tool("list_calendar_events", start=START, end=END, query="meeting", max_results=3)
    assert page["next_page_token"] == "page2" and page["items"][0]["start"] == {"date": "2026-09-19"}
    await agent.call_tool("list_calendar_events", start=START, end=END, page_token=page["next_page_token"])
    result = await agent.call_tool("create_calendar_event", title="Focus", start=START, end=END)
    assert result == {"id": "created"}
    first = requests[0]
    assert first.url.host == "www.googleapis.com"
    assert b"user%40example.com%2Fselected" in first.url.raw_path
    assert first.url.params["timeMin"] == START
    assert first.url.params["orderBy"] == "startTime" and first.url.params["singleEvents"] == "true"
    assert requests[1].url.params["pageToken"] == "page2"
    assert requests[2].method == "POST"
    body = json.loads(requests[2].content)
    assert body["start"] == {"dateTime": START} and "attendees" not in body
    preview = approvals[0].artifacts[0].parts[0].content
    assert preview["title"] == "Focus" and preview["description"] == ""
    assert "private-oauth-token" not in json.dumps(agent.to_dict())
    assert "private-oauth-token" not in str(approvals)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (END, START),
        (START, START),
        ("2026-09-19", END),
        ("bad", END),
        ("2026-09-19T09:00:00", END),
    ],
)
async def test_invalid_calendar_intervals_are_rejected_before_approval(http_mock, start, end):
    requests, _ = http_mock
    approvals = []

    async def approve(request, context):
        approvals.append(request)
        return True

    agent = agent_with(
        *calendar_tools(GoogleCalendar("token"), allow_write=True),
        policy=CapabilityPolicy({"calendar.write": "require_approval"}),
        approval_handler=approve,
    )
    with pytest.raises(ValueError):
        await agent.call_tool("create_calendar_event", title="Bad", start=start, end=end)
    assert requests == approvals == []


@pytest.mark.asyncio
async def test_email_wire_contract_mime_and_pagination(http_mock):
    requests, responses = http_mock
    responses.extend(
        [
            httpx.Response(200, json={"messages": [{"id": "msg", "threadId": "thread"}], "nextPageToken": "next"}),
            httpx.Response(200, json={"messages": []}),
            httpx.Response(200, json={"id": "draft"}),
            httpx.Response(200, json={"id": "sent", "threadId": "thread"}),
        ]
    )
    tokens = iter(["one", "two", "three", "four"])

    async def token():
        return next(tokens)

    backend = Gmail(token, sender="sender@example.com")
    agent = agent_with(*email_tools(backend, allow_write=True, allow_send=True))
    result = await agent.call_tool("list_email_messages", query="is:unread", max_results=2)
    assert result["items"] == [{"id": "msg", "threadId": "thread"}]
    await agent.call_tool("list_email_messages", query="is:unread", page_token=result["next_page_token"])
    message = {"to": ["first@example.com", "second@example.com"], "subject": "Hello Zürich", "body": "A café meeting"}
    assert (await agent.call_tool("create_email_draft", **message))["id"] == "draft"
    assert (await agent.call_tool("send_email", **message))["id"] == "sent"
    assert requests[0].url.params["q"] == "is:unread"
    assert requests[1].url.params["pageToken"] == "next"
    assert [r.headers["Authorization"] for r in requests] == [f"Bearer {t}" for t in ("one", "two", "three", "four")]
    assert requests[2].url.path.endswith("/drafts")
    draft = json.loads(requests[2].content)["message"]["raw"]
    sent = json.loads(requests[3].content)["raw"]
    assert draft == sent
    decoded = message_from_bytes(base64.urlsafe_b64decode(sent), policy=policy.default)
    assert str(decoded["Subject"]) == message["subject"]
    assert decoded["From"] == "sender@example.com"
    assert decoded.get_content().strip() == message["body"]


@pytest.mark.asyncio
async def test_email_multipart_charset_attachments_and_truncation(http_mock):
    _, responses = http_mock
    encoded = base64.urlsafe_b64encode(("café" + "x" * 20000).encode("iso-8859-1")).decode().rstrip("=")
    responses.append(
        httpx.Response(
            200,
            json={
                "id": "msg",
                "payload": {
                    "mimeType": "multipart/mixed",
                    "headers": [{"name": "Subject", "value": "A subject"}],
                    "parts": [
                        {
                            "mimeType": "multipart/alternative",
                            "parts": [
                                {
                                    "mimeType": "text/plain",
                                    "headers": [{"name": "Content-Type", "value": "text/plain; charset=iso-8859-1"}],
                                    "body": {"data": encoded},
                                },
                                {"mimeType": "text/html", "body": {"data": "PGI+aGk8L2I+"}},
                            ],
                        },
                        {"filename": "secret.txt", "mimeType": "text/plain", "body": {"data": "c2VjcmV0"}},
                    ],
                },
            },
        )
    )
    result = await agent_with(*email_tools(Gmail("token"))).call_tool("read_email", message_id="msg")
    assert result["body"].startswith("café") and len(result["body"]) == 20000
    assert result["body_truncated"] and result["has_attachments"]
    assert "secret" not in result["body"] and not result["html_body_omitted"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"to": ["user@example.com\r\nBcc: attacker@example.com"]},
        {"to": ["User <user@example.com>"]},
        {"to": ["not-an-address"]},
        {"to": ["<x>"]},
        {"to": ["x@@y.com"]},
        {"subject": "hello\nBcc: attacker@example.com"},
        {"body": " "},
        {"to": []},
    ],
)
async def test_email_validation_precedes_approval_and_network(http_mock, fields):
    requests, _ = http_mock
    approvals = []

    async def approve(request, context):
        approvals.append(request)
        return True

    agent = agent_with(
        *email_tools(Gmail("token", sender="me@example.com"), allow_send=True),
        policy=CapabilityPolicy({"email.send": "require_approval"}),
        approval_handler=approve,
    )
    message = {"to": ["user@example.com"], "subject": "Hello", "body": "Test", **fields}
    with pytest.raises(ValueError):
        await agent.call_tool("send_email", **message)
    assert requests == approvals == []


@pytest.mark.asyncio
async def test_google_failure_redacts_body_never_retries_or_follows_redirects(http_mock):
    requests, responses = http_mock
    responses.extend(
        [
            httpx.Response(401, text="leaked-token-and-private-data"),
            httpx.Response(302, headers={"Location": "https://attacker.example"}),
            httpx.Response(503, text="uncertain send"),
        ]
    )
    backend = Gmail("private-token", sender="me@example.com")
    with pytest.raises(GoogleAPIError) as exc:
        await backend.list_messages()
    assert exc.value.status_code == 401 and "leaked" not in str(exc.value)
    with pytest.raises(GoogleAPIError) as exc:
        await backend.list_messages()
    assert exc.value.status_code == 302
    with pytest.raises(GoogleAPIError):
        await backend.send_message(to=["a@example.com"], subject="Hello", body="Test")
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_service_cancellation_closes_http_and_does_not_retry(http_mock):
    requests, responses = http_mock
    waiting = asyncio.Event()
    cleaned = asyncio.Event()

    async def respond(request):
        waiting.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    responses.append(respond)
    agent = agent_with(*email_tools(Gmail("token")))
    pending = asyncio.create_task(agent.call_tool("list_email_messages"))
    await asyncio.wait_for(waiting.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert cleaned.is_set() and len(requests) == 1


@pytest.mark.asyncio
async def test_presets_use_standard_agent_tools_and_gate_mutations(http_mock, tmp_path):
    requests, _ = http_mock
    assistant = Assistant(
        calendar=GoogleCalendar("token"),
        email=Gmail("token", sender="me@example.com"),
        allow_write=True,
        allow_send=True,
        verbosity=0,
    )
    assert isinstance(assistant, Agent)
    assert {
        "current_datetime",
        "calculator",
        "list_calendar_events",
        "read_email",
        "send_email",
    } <= assistant.tools.keys()
    with pytest.raises(ApprovalRequiredError):
        await assistant.call_tool("send_email", to=["a@example.com"], subject="Hello", body="Test")
    with pytest.raises(ApprovalRequiredError):
        await assistant.call_tool("create_calendar_event", title="Focus", start=START, end=END)
    assert requests == []
    readonly = Assistant(calendar=GoogleCalendar("token"), email=Gmail("token"), verbosity=0)
    assert "create_calendar_event" not in readonly.tools and "send_email" not in readonly.tools
    coder = CodeAssistant(cwd=tmp_path, verbosity=0)
    assert {"run_shell", "git", "calculator"} == coder.tools.keys()
    with pytest.raises(ApprovalRequiredError):
        await coder.call_tool("run_shell", command="touch forbidden")
    assert not (tmp_path / "forbidden").exists()
    denied = Assistant(email=Gmail("token"), policy=CapabilityPolicy({"email.read": "deny"}), verbosity=0)
    with pytest.raises(ActionDeniedError):
        await denied.call_tool("list_email_messages")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
    ],
)
async def test_google_rejects_oversized_or_invalid_responses(http_mock, response):
    requests, responses = http_mock
    responses.append(response)
    with pytest.raises(ValueError):
        await Gmail("token").list_messages()
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_none_policy_keeps_preset_approval_defaults(http_mock, tmp_path):
    assistant = Assistant(email=Gmail("token", sender="me@example.com"), allow_send=True, policy=None, verbosity=0)
    with pytest.raises(ApprovalRequiredError):
        await assistant.call_tool("send_email", to=["user@example.com"], subject="Test", body="Hello")
    coder = CodeAssistant(cwd=tmp_path, policy=None, verbosity=0)
    with pytest.raises(ApprovalRequiredError):
        await coder.call_tool("run_shell", command="true")
