"""Inventory is private/read-only; controls reconnect an explicit application."""

import asyncio
import json
import threading

import httpx2
import pytest

from protolink import (
    Agent,
    DurableExecutionError,
    RunInterrupted,
    RunManager,
    SQLiteDurableStore,
    Task,
    UncertainExecutionError,
)
from protolink.cli import main
from protolink.llms import MockLLM
from protolink.tools import ask_user_tool


def make_agent(path, responses=None):
    return Agent(
        name="managed",
        durability=path,
        tools=[ask_user_tool()],
        verbosity=0,
        llm=MockLLM(
            sequential_responses=responses
            or [{"type": "tool_call", "tool": "ask_user", "args": {"question": "Format?"}}, "done"]
        ),
    )


@pytest.mark.asyncio
async def test_inventory_readonly_resume_and_completed_run_do_not_reexecute(tmp_path, capsys, monkeypatch):
    path = tmp_path / "checkpoints.sqlite"
    agent = make_agent(path)
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("choose")
    pause = raised.value
    read_only = SQLiteDurableStore(path, read_only=True)
    assert len(read_only.list(status="input-required", agent_name="managed")) == 1
    with pytest.raises(DurableExecutionError, match="read-only"):
        read_only.acquire(pause.run_id, "managed", {})
    assert main(["run", "pending", "--durability", str(path), "--json"]) == 0
    inventory = json.loads(capsys.readouterr().out)
    assert inventory[0]["run_id"] == pause.run_id and "history" not in json.dumps(inventory)
    manager = RunManager(make_agent(path, ["done"]))
    with pytest.raises(DurableExecutionError):
        await manager.resume(pause.run_id, request_id="stale", answer="CSV")
    completed = await manager.resume(
        pause.run_id, request_id=pause.interruption.request_id, fingerprint=pause.interruption.fingerprint, answer="CSV"
    )
    assert completed["run"]["status"] == "completed"
    assert (await manager.resume(pause.run_id))["run"]["status"] == "completed"


@pytest.mark.asyncio
async def test_cancel_scopes_owner_and_refuses_uncertain_effects(tmp_path):
    path = tmp_path / "checkpoints.sqlite"
    agent = make_agent(path)
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("choose")
    run_id = raised.value.run_id
    manager = RunManager(agent)
    record = agent.durability.get(run_id)
    token, _ = agent.durability.acquire(run_id, "managed", record.data)
    key = next(iter(record.data["actions"]))
    record.data["actions"][key]["state"] = "uncertain"
    failed_task = Task.from_dict(record.data["task"])
    failed_task.fail("Interrupted after an external effect")
    record.data["task"] = failed_task.to_dict()
    agent.durability.save(run_id, token, "input-required", record.data)
    agent.durability.release(run_id, token)
    with pytest.raises(UncertainExecutionError):
        manager.cancel(run_id)
    manager.reconcile(
        run_id, record.data["actions"][key]["action"]["action_id"], result={"status": "answered", "answer": "CSV"}
    )
    assert manager.cancel(run_id)["status"] == "canceled"
    with pytest.raises(DurableExecutionError, match="roster"):
        manager.inspect("outside")


def test_missing_inventory_does_not_create_database(tmp_path, capsys):
    path = tmp_path / "missing.sqlite"
    assert main(["run", "pending", "--durability", str(path)]) == 1
    assert not path.exists()
    assert "failed" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_dashboard_continuation_and_origin_protection(tmp_path, monkeypatch):
    import protolink.devtools.server as module

    path = tmp_path / "checkpoints.sqlite"
    agent = make_agent(path)
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("choose")
    pause = raised.value
    manager = RunManager(make_agent(path, ["done"]))
    application_loop = asyncio.get_running_loop()

    async def application_answer():
        """Represent a service on the embedding application's running loop."""
        await asyncio.sleep(0)
        return "done"

    def respond(_history, _prompt):
        return asyncio.run_coroutine_threadsafe(application_answer(), application_loop).result(timeout=5)

    manager.agents["managed"].llm.response_callback = respond
    created, ready = [], threading.Event()
    original = module.ThreadingHTTPServer

    class CapturingServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        def serve_forever(self, *args, **kwargs):
            ready.set()
            return super().serve_forever(*args, **kwargs)

    monkeypatch.setattr(module, "ThreadingHTTPServer", CapturingServer)
    thread = threading.Thread(target=module.serve_dashboard, kwargs={"port": 0, "run_manager": manager}, daemon=True)
    thread.start()
    assert await asyncio.to_thread(ready.wait, 3)
    server = created[0]
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        # Blocking urlopen here starves the application's loop while the
        # dashboard resumes work in another thread. Keep the test asynchronous
        # and allow enough request time for loaded CI runners.
        async with httpx2.AsyncClient(base_url=base, timeout=10, trust_env=False) as client:
            response = await client.get("/api/snapshot")
            response.raise_for_status()
            assert response.json()["durable"]["runs"][0]["status"] == "input-required"
            url = f"/api/durable/{pause.run_id}/resume"
            body = {
                "request_id": pause.interruption.request_id,
                "fingerprint": pause.interruption.fingerprint,
                "answer": "CSV",
            }
            denied = await client.post(url, json=body, headers={"Origin": "https://outside.invalid"})
            assert denied.status_code == 403
            cancel_url = f"/api/durable/{pause.run_id}/cancel"
            malformed = await client.post(
                cancel_url, content=b"{broken", headers={"Content-Type": "application/json", "Origin": base}
            )
            assert malformed.status_code == 422
            assert manager.inspect(pause.run_id)["status"] == "input-required"
            response = await client.post(url, json=body, headers={"Origin": base})
            response.raise_for_status()
            result = response.json()
            assert result["run"]["status"] == "completed"
            assert Task.from_dict(result["task"]).get_output() == "done"
    finally:
        await asyncio.to_thread(server.shutdown)
        await asyncio.to_thread(thread.join, 3)
