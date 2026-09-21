"""Exercise all v0.7.2 tools and both Agent presets without accounts or model APIs.

Run: python examples/builtin_assistants.py
Requires a POSIX shell and Git. Only a temporary repository is modified. The
calendar/mailbox are in-memory test adapters; no real email is sent. Replace the
adapters with GoogleCalendar(token) and Gmail(token, sender=...) in an application.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

from protolink import ApprovalDecision, Assistant, CodeAssistant, create_llm
from protolink.tools import UserInputRequest


class DemoServices:
    """Small deterministic implementation of both service backend protocols."""

    calendar_id = "demo-calendar"
    sender = "demo@example.test"

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []

    async def list_events(self, *, start, end, query, max_results, page_token):
        return {"items": self.events[:max_results], "next_page_token": None}

    async def create_event(self, **fields):
        event = {"id": f"event-{len(self.events) + 1}", **fields}
        self.events.append(event)
        return event

    async def list_messages(self, *, query, max_results, page_token):
        return {"items": [{"id": "incoming-1"}], "next_page_token": None}

    async def get_message(self, *, message_id):
        return {"id": message_id, "subject": "Planning", "body": "Please reserve time for a code review."}

    async def create_draft(self, **fields):
        draft = {"id": f"draft-{len(self.drafts) + 1}", **fields}
        self.drafts.append(draft)
        return draft

    async def send_message(self, **fields):
        sent = {"id": f"sent-{len(self.sent) + 1}", **fields}
        self.sent.append(sent)
        return sent


async def feedback(request: UserInputRequest) -> str:
    """A deterministic UI adapter; real applications await their user's answer."""
    print(f"Question: {request.question} Suggested answers: {request.options}")
    await asyncio.sleep(0)  # The inference loop awaits this response.
    return "Review the tests first"


async def approve_demo(request, context) -> ApprovalDecision:
    """Approve only this example's temporary host work and in-memory service calls."""
    print(f"Preview: {request.action.name}")
    return ApprovalDecision(approved=True, request_id=request.request_id, decided_by="offline-demo")


async def main() -> None:
    """Verify shell/Git, user feedback, calendar/email, and normal Agent inference."""
    env = {
        "PATH": os.defpath,
        "GIT_AUTHOR_NAME": "Demo",
        "GIT_AUTHOR_EMAIL": "demo@example.test",
        "GIT_COMMITTER_NAME": "Demo",
        "GIT_COMMITTER_EMAIL": "demo@example.test",
    }
    with tempfile.TemporaryDirectory(prefix="protolink-assistants-") as directory:
        coder = CodeAssistant(cwd=directory, env=env, allow_git_write=True, approval_handler=approve_demo, verbosity=0)
        result = await coder.call_tool("run_shell", command="git init -q && printf 'hello\\n' | cat > note.txt")
        assert result.exit_code == 0, result.stderr
        assert "note.txt" in (await coder.call_tool("git", operation="status")).stdout
        assert (await coder.call_tool("git", operation="add", paths=["note.txt"])).exit_code == 0
        assert "+hello" in (await coder.call_tool("git", operation="diff", staged=True)).stdout
        assert (await coder.call_tool("git", operation="commit", message="Example commit")).exit_code == 0
        assert "Example commit" in (await coder.call_tool("git", operation="log", max_count=1)).stdout
        assert "+hello" in (await coder.call_tool("git", operation="show")).stdout
        coder.llm = create_llm(
            "mock",
            sequential_responses=[
                {"type": "tool_call", "tool": "git", "args": {"operation": "status"}},
                {"type": "final", "content": "Repository inspected."},
            ],
        )
        assert await coder.invoke("Inspect repository status") == "Repository inspected."

    services = DemoServices()
    model_calls = 0

    def model(history, system_prompt):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return {
                "type": "tool_call",
                "tool": "ask_user",
                "args": {
                    "question": "What should I focus on?",
                    "options": ["Review tests", "Review docs"],
                },
            }
        assert "Review the tests first" in str(history.messages)
        return {"type": "final", "content": "I will review the tests first."}

    assistant = Assistant(
        llm=create_llm("mock", response_callback=model),
        calendar=services,
        email=services,
        ask_user=feedback,
        allow_write=True,
        allow_send=True,
        approval_handler=approve_demo,
        verbosity=0,
    )
    assert await assistant.invoke("Ask for my preference before continuing.") == "I will review the tests first."
    assert model_calls == 2
    interval = {"start": "2026-09-19T09:00:00+02:00", "end": "2026-09-19T10:00:00+02:00"}
    assert (await assistant.call_tool("list_calendar_events", **interval))["items"] == []
    assert (await assistant.call_tool("create_calendar_event", title="Code review", **interval))["id"] == "event-1"
    assert len((await assistant.call_tool("list_calendar_events", **interval))["items"]) == 1
    assert (await assistant.call_tool("list_email_messages", query="is:unread"))["items"][0]["id"] == "incoming-1"
    assert "code review" in (await assistant.call_tool("read_email", message_id="incoming-1"))["body"]
    message = {"to": ["colleague@example.test"], "subject": "Review", "body": "I will review the tests first."}
    assert (await assistant.call_tool("create_email_draft", **message))["id"] == "draft-1"
    assert services.sent == []  # Drafting did not deliver anything.
    assert (await assistant.call_tool("send_email", **message))["id"] == "sent-1"
    assert len(services.drafts) == len(services.sent) == 1
    assert (await assistant.call_tool("current_datetime"))["timezone"] == "UTC"
    assert (await assistant.call_tool("calculator", expression="6 * 7"))["result"] == 42
    print("All v0.7.2 tools and both assistant presets passed (offline).")


if __name__ == "__main__":
    asyncio.run(main())
