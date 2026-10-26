"""Application acceptance: one native team, private context and correlated evidence."""

import asyncio
import json
import threading

import httpx2
import pytest

from examples.application_runtime import PageService, create_app
from protolink import current_request_context
from protolink.transport.runtime_transport import RuntimeTransport


async def wait_until_set(event: threading.Event) -> None:
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_concurrent_app_requests_freeze_team_models_and_keep_dependencies_private(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class BlockingService(PageService):
        def read(self, page: str, *, delay: float = 0.1):
            if page == "overview":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the blocking service")
            return super().read(page, delay=0)

    app = create_app(tmp_path / "application.sqlite")
    urls = []
    async with app.router.lifespan_context(app):
        app.state.service = BlockingService()
        urls = [a.card.url for a in app.state.group.agents.values()]
        discovered = await app.state.group.registry.discover()
        assert {a.url for a in discovered} == set(urls)
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://app") as client:
            first = asyncio.create_task(client.post("/runs", json={"session_id": "alice", "page": "overview"}))
            try:
                await wait_until_set(entered)
                app.state.models = {role: f"mock-{role}-v2" for role in app.state.models}
                # A blocking reader on Alice's run leaves Bob's run responsive.
                second = await asyncio.wait_for(
                    client.post("/runs", json={"session_id": "bob", "page": "metrics", "delay": 0}), 3
                )
                assert not first.done()
            finally:
                release.set()
            first_response = await asyncio.wait_for(first, 3)

            for response, page, version in ((first_response, "overview", "v1"), (second, "metrics", "v2")):
                response.raise_for_status()
                events = [json.loads(line) for line in response.text.splitlines()]
                assert events[-1]["final"] is True
                assert not any(e["payload"].get("llm_event_type") == "llm_chunk" for e in events)
                for role in ("reader", "analyst", "coordinator"):
                    assert f"mock-{role}-{version}" in response.text
                run_id = response.headers["X-Run-ID"]
                evidence_response = await client.get(f"/runs/{run_id}/evidence")
                evidence_response.raise_for_status()
                evidence = evidence_response.json()
                assert len(evidence) == 2
                lookup = next(item for item in evidence if item["tool_name"] == "read_page")
                assert lookup["result"]["page"] == page
                assert lookup["outcome"] == "completed"
                assert lookup["action_id"] and lookup["parent_action_id"] and lookup["delegation_id"]
                assert lookup["run_id"] != run_id
                assert lookup["duration_seconds"] is not None
                assert "example-private-service-token" not in response.text + evidence_response.text
                saved = app.state.store.get_report(run_id)
                assert "example-private-service-token" not in json.dumps(saved.to_dict())

        for agent in app.state.group.agents.values():
            assert "example-private-service-token" not in json.dumps(agent.storage.load())
            assert agent._state.conversation.to_dict()
        assert not current_request_context()
    assert all(RuntimeTransport.get_transport(url) is None for url in urls)


@pytest.mark.asyncio
async def test_cancel_blocking_tool_keeps_one_canceled_receipt_after_thread_returns(tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    class BlockingService(PageService):
        def read(self, page: str, *, delay: float = 0.1):
            entered.set()
            try:
                if not release.wait(5):
                    raise TimeoutError("Test did not release the blocking service")
                return super().read(page, delay=0)
            finally:
                finished.set()

    app = create_app(tmp_path / "cancellation.sqlite")
    async with app.router.lifespan_context(app):
        app.state.service = BlockingService()
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://app") as client:
            pending = asyncio.create_task(client.post("/runs", json={"session_id": "cancel-me"}))
            try:
                await wait_until_set(entered)
                (run_id,) = app.state.runs
                handle = app.state.runs[run_id]
                response = await asyncio.wait_for(client.delete(f"/runs/{run_id}"), 2)
                assert response.json() == {"status": "canceled"}
                result = await handle.result()
                assert [e.outcome for e in result.tool_evidence] == ["canceled"]
                assert not finished.is_set()  # Cancellation cannot kill a Python thread.
                stream = await asyncio.wait_for(pending, 2)
                stream.raise_for_status()
            finally:
                release.set()
                await wait_until_set(finished)
                await pending
        await asyncio.sleep(0)
        saved = app.state.store.get_report(handle.context.run_id)
        assert [e.outcome for e in saved.tool_evidence] == ["canceled"]
        assert not any(e.type == "action.completed" for e in handle.report.events)


@pytest.mark.asyncio
async def test_app_reopens_native_conversation_storage(tmp_path):
    database = tmp_path / "sessions.sqlite"
    app = create_app(database)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://app") as client:
            response = await client.post("/runs", json={"session_id": "saved-session", "delay": 0})
            response.raise_for_status()
    reopened = create_app(database)
    async with reopened.router.lifespan_context(reopened):
        coordinator = next(a for a in reopened.state.group.agents.values() if a.subagents)
        history = coordinator._state.conversation.get_history("saved-session")
        assert any(message["role"] == "user" for message in history.messages)
        assert any("coordinator finished" in str(message.get("content")) for message in history.messages)
