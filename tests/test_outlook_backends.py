"""Microsoft Graph wire contracts exercised through the real async HTTP client."""

import asyncio
import base64
import json

import httpx
import pytest

from protolink import ApprovalRequiredError, Assistant
from protolink.tools import MicrosoftGraphError, OutlookCalendar, OutlookEmail, calendar_tools, email_tools

START = "2026-09-19T09:00:00+02:00"
END = "2026-09-19T10:00:00+02:00"
MESSAGE = {"to": ["friend@example.com"], "subject": "Café", "body": "Meet tomorrow?"}


@pytest.fixture
def graph(monkeypatch):
    original = httpx.AsyncClient
    requests, responses, clients = [], [], []

    async def respond(request):
        requests.append(request)
        response = responses.pop(0)
        return await response(request) if callable(response) else response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        instance = original(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    yield requests, responses
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_calendar_pages_filter_and_utc_creation(graph):
    requests, responses = graph
    next_url = "https://graph.microsoft.com/v1.0/me/calendar/calendarView?$skiptoken=a%2Bb%3D&$top=1"
    responses.extend(
        [
            httpx.Response(200, json={"value": [{"subject": "Unrelated"}], "@odata.nextLink": next_url}),
            httpx.Response(200, json={"value": [{"id": "event", "subject": "CAFÉ", "isAllDay": True}]}),
            httpx.Response(201, json={"id": "created"}),
        ]
    )
    backend = OutlookCalendar("private-token")
    page = await backend.list_events(start=START, end=END, query="café", max_results=1)
    assert page["items"] == [] and page["next_page_token"]
    page = await backend.list_events(
        start=START, end=END, query="café", max_results=1, page_token=page["next_page_token"]
    )
    assert page["items"][0]["isAllDay"] and page["next_page_token"] is None
    assert str(requests[1].url) == next_url
    assert requests[0].url.params["startDateTime"] == START
    assert requests[0].url.params["$orderby"] == "start/dateTime"
    assert (await backend.create_event(title="Focus", start=START, end=END, description="Planning", location="Home"))[
        "id"
    ] == "created"
    body = json.loads(requests[2].content)
    assert requests[2].url.path == "/v1.0/me/calendar/events"
    assert body["start"] == {"dateTime": "2026-09-19T07:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-09-19T08:00:00", "timeZone": "UTC"}
    assert body["body"] == {"contentType": "Text", "content": "Planning"}
    assert "attendees" not in body


@pytest.mark.asyncio
async def test_selected_account_resource_encoding_and_refreshed_tokens(graph):
    requests, responses = graph
    responses.extend([httpx.Response(200, json={"value": []})] * 2)
    tokens = iter(["one", "two"])

    async def token():
        return next(tokens)

    calendar = OutlookCalendar(token, user_id="user@example.com", calendar_id="a/b+=")
    await calendar.list_events(start=START, end=END)
    await calendar.list_events(start=START, end=END)
    assert b"/users/user%40example.com/calendars/a%2Fb%2B%3D/calendarView" in requests[0].url.raw_path
    assert [r.headers["Authorization"] for r in requests] == ["Bearer one", "Bearer two"]


@pytest.mark.asyncio
async def test_mailbox_search_read_draft_and_send(graph):
    requests, responses = graph
    responses.extend(
        [
            httpx.Response(200, json={"value": [{"id": "mail"}]}),
            httpx.Response(
                200,
                json={
                    "id": "mail",
                    "conversationId": "thread",
                    "from": {"emailAddress": {"address": "a@example.com"}},
                    "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
                    "body": {"contentType": "text", "content": "x" * 20001},
                    "hasAttachments": True,
                },
            ),
            httpx.Response(201, json={"id": "draft", "isDraft": True}),
            httpx.Response(202),
        ]
    )
    backend = OutlookEmail(lambda: "secret", user_id="shared@example.com")
    assert (await backend.list_messages(query='subject:"project review"'))["items"] == [{"id": "mail"}]
    assert requests[0].url.params["$search"] == '"subject:\\"project review\\""'
    assert "$orderby" not in requests[0].url.params
    result = await backend.get_message(message_id="mail/+=")
    assert result["from"] == "a@example.com" and result["to"] == "b@example.com"
    assert result["thread_id"] == "thread" and result["has_attachments"]
    assert len(result["body"]) == 20000 and result["body_truncated"]
    assert b"mail%2F%2B%3D" in requests[1].url.raw_path
    assert requests[1].method == "GET" and 'outlook.body-content-type="text"' in requests[1].headers["Prefer"]
    assert (await backend.create_draft(**MESSAGE))["id"] == "draft"
    assert await backend.send_message(**MESSAGE) == {"status": "accepted"}
    draft, send = (json.loads(r.content) for r in requests[2:])
    assert draft == send["message"] and send["saveToSentItems"] is True
    assert draft["body"] == {"contentType": "Text", "content": MESSAGE["body"]}
    assert all(r.url.path.startswith("/v1.0/users/shared@example.com/") for r in requests)
    assert all('IdType="ImmutableId"' in r.headers["Prefer"] for r in requests)


@pytest.mark.asyncio
async def test_html_only_message_is_not_returned_as_plain_text(graph):
    _, responses = graph
    responses.append(
        httpx.Response(
            200, json={"id": "m", "body": {"contentType": "HTML", "content": "<b>mail</b>"}, "bodyPreview": "mail"}
        )
    )
    result = await OutlookEmail("token").get_message(message_id="m")
    assert result["body"] == "" and result["html_body_omitted"] and result["snippet"] == "mail"


@pytest.mark.asyncio
async def test_tokens_bound_to_backend_query_page_size_and_window(graph):
    requests, responses = graph
    responses.append(
        httpx.Response(
            200,
            json={
                "value": [],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/calendar/calendarView?$skiptoken=x",
            },
        )
    )
    backend = OutlookCalendar("one")
    cursor = (await backend.list_events(start=START, end=END))["next_page_token"]
    for other, overrides in [
        (OutlookCalendar("two"), {}),
        (backend, {"query": "changed"}),
        (backend, {"max_results": 10}),
        (backend, {"end": "2026-09-20T10:00:00+02:00"}),
    ]:
        with pytest.raises(ValueError, match="page token"):
            await other.list_events(**{"start": START, "end": END, "page_token": cursor, **overrides})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "next_url",
    [
        "https://attacker.example/v1.0/me/messages?$skiptoken=x",
        "http://graph.microsoft.com/v1.0/me/messages?$skiptoken=x",
        "https://graph.microsoft.com@attacker.example/v1.0/me/messages",
        "https://graph.microsoft.com/v1.0/users/other/messages",
        "https://graph.microsoft.com/v1.0/me/messages/../sendMail",
        "https://graph.microsoft.com/v1.0/me/messages#fragment",
        "https://graph.microsoft.com/v1.0/me/messages\n?$skiptoken=x",
    ],
)
async def test_next_links_cannot_change_origin_or_mailbox(graph, next_url):
    requests, responses = graph
    responses.append(httpx.Response(200, json={"value": [], "@odata.nextLink": next_url}))
    with pytest.raises(ValueError, match="continuation URL"):
        await OutlookEmail("private-token").list_messages()
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_forged_cursor_is_revalidated_before_request(graph):
    requests, responses = graph
    responses.append(
        httpx.Response(
            200, json={"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=x"}
        )
    )
    backend = OutlookEmail("token")
    page = await backend.list_messages()
    data = json.loads(base64.urlsafe_b64decode(page["next_page_token"]))
    data["value"] = "https://attacker.example/mail"
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(ValueError, match="continuation URL"):
        await backend.list_messages(page_token=forged)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_mailbox_continuation_preserves_query_and_preference_headers(graph):
    requests, responses = graph
    next_url = "https://graph.microsoft.com/v1.0/me/messages?$skip=20&$top=20"
    responses.extend(
        [
            httpx.Response(200, json={"value": [{"id": "first"}], "@odata.nextLink": next_url}),
            httpx.Response(200, json={"value": [{"id": "second"}]}),
        ]
    )
    backend = OutlookEmail("token")
    first = await backend.list_messages()
    second = await backend.list_messages(page_token=first["next_page_token"])
    assert second == {"items": [{"id": "second"}], "next_page_token": None}
    assert str(requests[1].url) == next_url
    assert requests[1].headers["Prefer"] == requests[0].headers["Prefer"]
    assert requests[0].url.params["$orderby"] == "receivedDateTime desc"


def test_provider_search_guidance_reaches_model_tool_descriptions():
    assert "subject:review" in email_tools(OutlookEmail("token"))[0].description
    assert "case-insensitive substring" in calendar_tools(OutlookCalendar("token"))[0].description


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 429, 503])
async def test_errors_redact_service_body_and_do_not_retry(graph, status):
    requests, responses = graph
    responses.append(
        httpx.Response(status, text="private provider details", headers={"Location": "https://attacker.example"})
    )
    with pytest.raises(MicrosoftGraphError) as caught:
        await OutlookEmail("secret-token").send_message(**MESSAGE)
    assert caught.value.status_code == status
    assert "private" not in str(caught.value) and "secret-token" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,reason",
    [
        (httpx.Response(200, text="not json"), "invalid JSON"),
        (httpx.Response(200, json=[]), "JSON object"),
        (httpx.Response(200, json={"value": [1]}), "contain objects"),
        (httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)), "2 MiB"),
    ],
)
async def test_malformed_or_oversized_responses(graph, response, reason):
    _, responses = graph
    responses.append(response)
    with pytest.raises(ValueError, match=reason):
        await OutlookEmail("token").list_messages()


@pytest.mark.asyncio
async def test_cancellation_closes_client(graph):
    _, responses = graph
    started = asyncio.Event()

    async def pending(request):
        started.set()
        await asyncio.Event().wait()

    responses.append(pending)
    task = asyncio.create_task(OutlookEmail("token").list_messages())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_assistant_uses_existing_policy_and_keeps_tokens_private(graph):
    requests, responses = graph
    approvals = []

    async def approve(request, context):
        approvals.append(request.action)
        return True

    assistant = Assistant(
        calendar=OutlookCalendar("private-token"),
        email=OutlookEmail("private-token"),
        allow_write=True,
        allow_send=True,
        verbosity=0,
    )
    with pytest.raises(ApprovalRequiredError):
        await assistant.call_tool("send_email", **MESSAGE)
    assert requests == []
    assistant = Assistant(email=OutlookEmail("private-token"), allow_send=True, approval_handler=approve, verbosity=0)
    responses.append(httpx.Response(202))
    assert await assistant.call_tool("send_email", **MESSAGE) == {"status": "accepted"}
    assert "private-token" not in json.dumps(assistant.to_dict()) + str(approvals)
    preview = approvals[0].artifacts[0].parts[0].content
    assert preview["to"] == MESSAGE["to"] and preview["target"] == "OutlookEmail:me"


@pytest.mark.asyncio
async def test_validation_before_authentication_or_network(graph):
    requests, _ = graph

    def secret():
        pytest.fail("Invalid inputs must not request credentials")

    with pytest.raises(ValueError):
        OutlookEmail(secret, user_id="..")
    with pytest.raises(ValueError):
        await OutlookEmail(secret).get_message(message_id="..")
    with pytest.raises(ValueError):
        await OutlookEmail(secret).list_messages(query="hello\r\nInjected")
    with pytest.raises(ValueError):
        await OutlookEmail(secret).send_message(**{**MESSAGE, "subject": "hello\r\nInjected"})
    with pytest.raises(ValueError):
        await OutlookCalendar(secret).create_event(title="Bad", start=END, end=START)
    assert requests == []
