import json
from pathlib import Path

import pytest

from protolink import RunContext, RunEvent, RunReport, SQLiteRunStore, Task
from protolink.cli import main as cli_main
from protolink.devtools import build_run_replay_view, chat_with_agent, list_run_store_records, ping_agent
from protolink.devtools.server import build_dashboard_snapshot
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer


def test_cli_doctor_emits_structured_json(capsys):
    assert cli_main(["doctor", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] in {"ok", "warn"}
    assert any(check["name"] == "protolink" for check in payload["checks"])


def test_cli_run_list_and_replay_use_sqlite_run_store(tmp_path: Path, capsys):
    store_path = tmp_path / "runs.db"
    task_id = _seed_run_store(store_path)

    assert cli_main(["run", "list", "--store", str(store_path), "--json"]) == 0
    records = json.loads(capsys.readouterr().out)

    assert records["tasks"][0]["task_id"] == task_id
    assert records["reports"][0]["run_id"] == "run_cli"

    assert cli_main(["run", "replay", "run_cli", "--store", str(store_path)]) == 0
    output = capsys.readouterr().out

    assert "Run replay: run_cli" in output
    assert "llm.call.completed" in output


def test_devtools_helpers_project_store_records(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)

    records = list_run_store_records(store_path)
    view = build_run_replay_view(store_path, "run_cli")

    assert records["tasks"][0]["run_id"] == "run_cli"
    assert view.source == "report"
    assert [item.event_type for item in view.items] == ["task.status", "llm.call.completed"]


def test_dashboard_static_output_includes_disabled_studio_preview(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)
    dashboard_path = tmp_path / "dashboard.html"

    assert cli_main(["dashboard", "--store", str(store_path), "--output", str(dashboard_path)]) == 0

    dashboard_html = dashboard_path.read_text(encoding="utf-8")

    assert "Protolink Dashboard" in dashboard_html
    assert "window.__PROTOLINK_SNAPSHOT__" in dashboard_html
    assert "/api/agents/ping" in dashboard_html
    assert "/api/agents/chat" in dashboard_html
    assert "Ping all" in dashboard_html
    assert "Agent chat" in dashboard_html
    assert 'data-icon="refresh"' in dashboard_html
    assert "handleChatKeydown" in dashboard_html
    assert "toggleChatDebug" in dashboard_html
    assert "resetChat" in dashboard_html
    assert "Last latency" in dashboard_html
    assert "Average latency" in dashboard_html
    assert "Messages sent" in dashboard_html
    assert "Uptime" in dashboard_html
    assert "Skills and schemas" in dashboard_html
    assert "Studio Preview" not in dashboard_html
    assert "Protolink Studio" in dashboard_html
    assert "Protolink Studio is coming soon" in dashboard_html
    assert "studio-canvas" in dashboard_html


def test_cli_studio_command_is_not_public():
    with pytest.raises(SystemExit):
        cli_main(["studio", "--output", "studio.html"])


def test_dashboard_snapshot_and_renderer_include_registry_and_store(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)

    snapshot = build_dashboard_snapshot(store_path=store_path)
    html = DevtoolsHtmlRenderer().render_dashboard(snapshot)

    assert snapshot["runs"]["reports"][0]["run_id"] == "run_cli"
    assert "run_cli" in html
    assert "Protolink Studio" in html
    assert "Selected agent" in html


def test_dashboard_agent_actions_use_http_contracts(monkeypatch):
    calls = []

    class FakeResponse:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return self.body

    def fake_ping_urlopen(request, timeout):
        calls.append((request.full_url, timeout, getattr(request, "data", None)))
        return FakeResponse(b"<html><script>let startTime = 1000;</script></html>")

    monkeypatch.setattr("protolink.devtools.agents.urlopen", fake_ping_urlopen)

    ping = ping_agent("http://agent.local/", timeout=1.25)

    assert ping["ok"] is True
    assert ping["url"] == "http://agent.local/status"
    assert ping["start_time"] == 1000.0
    assert ping["uptime_seconds"] > 0
    assert calls[0] == ("http://agent.local/status", 1.25, None)

    def fake_chat_urlopen(request, timeout):
        calls.append((request.full_url, timeout, json.loads(request.data.decode("utf-8"))))
        return FakeResponse(b'{"response":"hello from agent"}')

    monkeypatch.setattr("protolink.devtools.agents.urlopen", fake_chat_urlopen)

    chat = chat_with_agent("http://agent.local", "hello", session_id="session_dev", timeout=5.0)

    assert chat["response"] == "hello from agent"
    assert calls[-1] == (
        "http://agent.local/chat",
        5.0,
        {"message": "hello", "session_id": "session_dev"},
    )


def test_dashboard_agent_actions_reject_non_http_urls():
    with pytest.raises(ValueError):
        ping_agent("runtime://agent")

    with pytest.raises(ValueError):
        chat_with_agent("runtime://agent", "hello")


def _seed_run_store(store_path: Path) -> str:
    store = SQLiteRunStore(store_path)
    task = Task.create_infer(prompt="hello")
    context = RunContext(run_id="run_cli", session_id="session_cli", trace_id="trace_cli", agent_chain=["client"])
    context.attach_to_task(task)
    task.complete("done")
    store.save_task(task, context=context, agent_name="cli_agent")

    report = RunReport.from_events(
        [
            RunEvent(
                type="task.status",
                run_id=context.run_id,
                task_id=task.id,
                agent_name="cli_agent",
                payload={"previous_state": "working", "new_state": "completed"},
            ),
            RunEvent(
                type="llm.call.completed",
                run_id=context.run_id,
                task_id=task.id,
                agent_name="cli_agent",
                payload={"provider": "mock", "model": "mock"},
            ),
        ],
        context=context,
        final_task=task.to_dict(),
    )
    store.save_report(report, agent_name="cli_agent")
    return task.id
