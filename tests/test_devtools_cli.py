import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from protolink import RunContext, RunEvent, RunReport, SQLiteRunStore, Task
from protolink.__version__ import __version__
from protolink.cli import main as cli_main
from protolink.devtools import (
    build_run_diff_view,
    build_run_replay_view,
    chat_with_agent,
    list_run_store_records,
    ping_agent,
)
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


def test_cli_run_diff_matches_after_volatile_normalization(tmp_path: Path, capsys):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)
    _seed_candidate_report(store_path, run_id="run_cli_match", model="mock")

    args = ["run", "diff", "run_cli", "run_cli_match", "--store", str(store_path)]
    assert cli_main(args) == 0
    output = capsys.readouterr().out

    assert "Normalized run report diff: run_cli -> run_cli_match" in output
    assert "Result: MATCH" in output

    assert cli_main([*args, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["baseline_run_id"] == "run_cli"
    assert payload["candidate_run_id"] == "run_cli_match"
    assert payload["status"] == "match"
    assert payload["matches"] is True
    assert payload["changed_sections"] == []
    assert payload["differences"] == []


def test_cli_run_diff_emits_text_and_json_for_behavior_changes(tmp_path: Path, capsys):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)
    _seed_candidate_report(store_path, run_id="run_cli_changed", model="mock-v2")

    args = ["run", "diff", "run_cli", "run_cli_changed", "--store", str(store_path)]
    assert cli_main(args) == 1
    output = capsys.readouterr().out

    assert "Normalized run report diff: run_cli -> run_cli_changed" in output
    assert "Result: CHANGED" in output
    assert "events" in output

    assert cli_main([*args, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "changed"
    assert payload["matches"] is False
    assert "events" in payload["changed_sections"]
    assert any(
        difference.get("baseline") == "mock" and difference.get("candidate") == "mock-v2"
        for difference in payload["differences"]
    )


def test_cli_run_diff_requires_two_reports_without_task_fallback(tmp_path: Path, capsys):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)
    store = SQLiteRunStore(store_path)
    task = Task.create_infer(prompt="task snapshots are not reports")
    context = RunContext(run_id="run_task_only")
    context.attach_to_task(task)
    task.complete("done")
    store.save_task(task, context=context, agent_name="cli_agent")

    view = build_run_diff_view(store_path, "run_cli", "run_task_only")
    assert view.status == "missing"
    assert view.missing_run_ids == ("run_task_only",)

    args = ["run", "diff", "run_cli", "run_task_only", "--store", str(store_path)]
    assert cli_main(args) == 2
    assert capsys.readouterr().out.strip() == "Run report not found: run_task_only"

    assert cli_main([*args, "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "baseline_run_id": "run_cli",
        "candidate_run_id": "run_task_only",
        "status": "missing",
        "missing_run_ids": ["run_task_only"],
        "matches": None,
        "difference_count": 0,
        "changed_sections": [],
        "compared_sections": [],
        "ignored_paths": [],
        "differences": [],
    }


def test_cli_run_diff_json_redacts_secret_values(tmp_path: Path, capsys):
    store_path = tmp_path / "runs.db"
    store = SQLiteRunStore(store_path)
    for run_id, secret in (
        ("run_secret_baseline", "baseline-secret"),
        ("run_secret_candidate", "candidate-secret"),
    ):
        context = RunContext(run_id=run_id)
        report = RunReport.from_events(
            [],
            context=context,
            metadata={"credentials": {"client_id": secret}},
        )
        store.save_report(report)

    assert (
        cli_main(
            [
                "run",
                "diff",
                "run_secret_baseline",
                "run_secret_candidate",
                "--store",
                str(store_path),
                "--json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    difference = payload["differences"][0]

    assert difference["baseline"] == "[REDACTED]"
    assert difference["candidate"] == "[REDACTED]"
    assert "baseline-secret" not in json.dumps(payload)
    assert "candidate-secret" not in json.dumps(payload)


def test_devtools_helpers_project_store_records(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)

    records = list_run_store_records(store_path)
    view = build_run_replay_view(store_path, "run_cli")

    assert records["tasks"][0]["run_id"] == "run_cli"
    assert view.source == "report"
    assert [item.event_type for item in view.items] == ["task.status", "llm.call.completed"]


def test_run_replay_kind_disambiguates_report_and_task_ids(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    store = SQLiteRunStore(store_path)
    shared_id = "shared_run_and_task_id"

    task = Task(id=shared_id)
    task_context = RunContext(run_id="task_only_run", session_id="task_session")
    task_context.attach_to_task(task)
    task.complete("task result")
    store.save_task(task, context=task_context, agent_name="task_agent")

    report_task = Task.create_infer(prompt="report result")
    report_context = RunContext(run_id=shared_id, session_id="report_session")
    report_context.attach_to_task(report_task)
    report_task.complete("report result")
    store.save_report(
        RunReport.from_events([], context=report_context, final_task=report_task.to_dict()),
        agent_name="report_agent",
    )

    assert build_run_replay_view(store_path, shared_id).source == "report"
    assert build_run_replay_view(store_path, shared_id, kind="report").agent_name == "report_agent"
    task_view = build_run_replay_view(store_path, shared_id, kind="task")
    assert task_view.source == "task"
    assert task_view.agent_name == "task_agent"
    assert task_view.final_task is not None
    assert task_view.final_task["id"] == shared_id

    invalid_kind: Any = "unknown"
    with pytest.raises(ValueError, match="kind"):
        build_run_replay_view(store_path, shared_id, kind=invalid_kind)


def test_compact_run_index_does_not_decode_full_payloads(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    task_id = _seed_run_store(store_path)
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE protolink_tasks SET task_json = ?, metadata_json = ? WHERE task_id = ?",
            ("[]", "[]", task_id),
        )
        connection.execute(
            "UPDATE protolink_run_reports SET report_json = ?, metadata_json = ? WHERE run_id = ?",
            ("[]", "[]", "run_cli"),
        )

    compact = list_run_store_records(store_path, read_only=True, compact=True)

    assert compact["tasks"][0]["task_id"] == task_id
    assert "task" not in compact["tasks"][0]
    assert compact["reports"][0]["run_id"] == "run_cli"
    assert compact["reports"][0]["state"] is None
    assert compact["reports"][0]["event_count"] is None

    with pytest.raises(ValueError, match="task payload must be a JSON object"):
        list_run_store_records(store_path, read_only=True)
    with pytest.raises(ValueError, match="run-report payload must be a JSON object"):
        build_run_replay_view(store_path, "run_cli", read_only=True, kind="report")


def test_dashboard_static_output_includes_active_studio_builder(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)
    dashboard_path = tmp_path / "dashboard.html"

    assert cli_main(["dashboard", "--store", str(store_path), "--output", str(dashboard_path)]) == 0

    dashboard_html = dashboard_path.read_text(encoding="utf-8")

    assert "Protolink Dashboard" in dashboard_html
    assert "window.__PROTOLINK_SNAPSHOT__" in dashboard_html
    assert "window.__PROTOLINK_LIVE__ = false;" in dashboard_html
    assert "window.location.protocol" not in dashboard_html
    assert "/api/agents/ping" in dashboard_html
    assert "/api/agents/chat" in dashboard_html
    assert "Ping all" in dashboard_html
    assert "Agent chat" in dashboard_html
    assert "https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/logo_sm.png" in dashboard_html
    assert 'data-icon="refresh"' in dashboard_html
    assert dashboard_html.index('id="nav-registry"') < dashboard_html.index('id="nav-runs"')
    assert "dashboard-registry-summary" in dashboard_html
    assert "For full agent details, schemas, transports, and security metadata" in dashboard_html
    assert "dashboardAgentActions" in dashboard_html
    assert "transport-badge" in dashboard_html
    assert "capability-badge" in dashboard_html
    assert "badge-row" in dashboard_html
    assert "store-state" in dashboard_html
    assert "Recent tasks" not in dashboard_html
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
    assert "Protolink Studio is coming soon" not in dashboard_html
    assert "Visual runtime builder" in dashboard_html
    assert "studio-canvas" in dashboard_html
    assert "studio-node-layer" in dashboard_html
    assert "Generate Python" in dashboard_html
    assert "Restore starter" in dashboard_html
    assert "Clear canvas" in dashboard_html
    assert "Import JSON" in dashboard_html
    assert "Export JSON" in dashboard_html
    assert '<dialog class="studio-output-dialog"' in dashboard_html
    assert 'id="studio-open-code"' in dashboard_html
    assert 'id="studio-open-logs"' in dashboard_html
    assert 'aria-controls="studio-output-dialog"' in dashboard_html
    assert 'id="studio-close-output"' in dashboard_html
    assert 'aria-label="Close output panel"' in dashboard_html
    assert 'class="studio-output"' not in dashboard_html
    assert "studioOpenOutput" in dashboard_html
    assert "studioCloseOutput" in dashboard_html
    assert "studioClearProject" in dashboard_html
    assert "studioGenerateCode" in dashboard_html
    assert "studioRunProject" in dashboard_html
    assert "/api/studio/generate" in dashboard_html
    assert "/api/studio/run" in dashboard_html
    assert 'id="nav-telemetry"' in dashboard_html
    assert 'id="view-telemetry"' in dashboard_html
    assert "Open JSONL" in dashboard_html
    assert "Span waterfall" in dashboard_html
    assert "Event replay" in dashboard_html
    assert "readUploadTracePage" in dashboard_html
    assert "const maxScannedLines = 5000;" in dashboard_html
    assert "result.line_scan_exhausted" in dashboard_html
    assert "/api/traces/" in dashboard_html
    assert "TELEMETRY_SUMMARY_CAP" in dashboard_html
    assert 'id="registry-source-input"' in dashboard_html
    assert 'id="runs-source-input"' in dashboard_html
    assert "/api/sources/registry" in dashboard_html
    assert "/api/sources/runs" in dashboard_html
    assert 'id="side-version"' in dashboard_html
    assert f'"version": "{__version__}"' in dashboard_html
    assert "run-record-list" in dashboard_html
    assert "run-replay-hero" in dashboard_html
    assert "data-span-key" in dashboard_html
    assert "handleTelemetrySpanKeydown" in dashboard_html


@pytest.mark.parametrize("trace_flag", ["--traces", "--telemetry"])
def test_dashboard_cli_embeds_bounded_telemetry_summary(tmp_path: Path, trace_flag: str):
    trace_path = tmp_path / "traces.jsonl"
    dashboard_path = tmp_path / f"dashboard-{trace_flag.removeprefix('--')}.html"
    trace_path.write_text(
        json.dumps(
            {
                "trace_id": "trace_dashboard",
                "task_id": "task_dashboard",
                "agent_name": "dashboard_agent",
                "status": "ok",
                "metadata": {"llm_metrics": {"total_tokens": 42}},
                "spans": [],
                "events": [],
                "private_payload": "must stay lazy",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        cli_main(
            [
                "dashboard",
                "--store",
                str(tmp_path / "runs.db"),
                trace_flag,
                str(trace_path),
                "--output",
                str(dashboard_path),
            ]
        )
        == 0
    )

    dashboard_html = dashboard_path.read_text(encoding="utf-8")
    assert "task_dashboard" in dashboard_html
    assert str(trace_path) in dashboard_html
    assert "must stay lazy" not in dashboard_html


def test_cli_studio_without_blueprint_serves_default(monkeypatch):
    served_args = {}

    def fake_serve_dashboard(**kwargs):
        served_args.update(kwargs)

    monkeypatch.setattr("protolink.cli.serve_dashboard", fake_serve_dashboard)

    assert cli_main(["studio"]) == 0
    assert served_args["start_tab"] == "studio"
    assert served_args["project_loaded"] is False
    assert served_args["blueprint"] is None


def test_cli_studio_loads_custom_blueprint_and_serves(tmp_path: Path, monkeypatch):
    blueprint_path = tmp_path / "custom_mesh.json"
    custom_blueprint = {
        "version": 1,
        "project": {
            "name": "custom_loaded_topology",
            "description": "A loaded custom mesh.",
        },
        "nodes": [
            {
                "id": "agent-custom",
                "kind": "agent",
                "label": "Custom Worker",
                "x": 100,
                "y": 100,
                "config": {
                    "name": "custom_worker",
                    "description": "A custom worker.",
                    "url": "runtime://custom_worker",
                    "transport": "runtime",
                },
            }
        ],
        "edges": [],
    }
    blueprint_path.write_text(json.dumps(custom_blueprint), encoding="utf-8")

    served_args = {}

    def fake_serve_dashboard(**kwargs):
        served_args.update(kwargs)

    monkeypatch.setattr("protolink.cli.serve_dashboard", fake_serve_dashboard)

    assert cli_main(["studio", str(blueprint_path)]) == 0
    assert served_args["start_tab"] == "studio"
    assert served_args["project_loaded"] is True
    assert served_args["host"] == "127.0.0.1"
    assert served_args["port"] == 8765
    assert served_args["blueprint"]["project"]["name"] == "custom_loaded_topology"
    assert served_args["blueprint"]["nodes"][0]["id"] == "agent-custom"

    # Test with custom --ip and --port
    assert cli_main(["studio", str(blueprint_path), "--ip", "0.0.0.0", "--port", "9999"]) == 0
    assert served_args["host"] == "0.0.0.0"
    assert served_args["port"] == 9999

    # Test with --host alias
    assert cli_main(["studio", str(blueprint_path), "--host", "127.0.0.2", "--port", "8888"]) == 0
    assert served_args["host"] == "127.0.0.2"
    assert served_args["port"] == 8888


def test_cli_studio_rejects_non_json_missing_or_invalid_blueprint(tmp_path: Path, capsys):
    non_json_path = tmp_path / "mesh.yaml"
    non_json_path.write_text("{}", encoding="utf-8")
    assert cli_main(["studio", str(non_json_path)]) == 1
    err = capsys.readouterr().err
    assert "Failed to load Studio blueprint" in err
    assert ".json" in err

    missing_path = tmp_path / "non_existent.json"
    assert cli_main(["studio", str(missing_path)]) == 1
    err = capsys.readouterr().err
    assert "Failed to load Studio blueprint" in err
    assert "not found" in err

    invalid_json_path = tmp_path / "broken.json"
    invalid_json_path.write_text("not json content {", encoding="utf-8")
    assert cli_main(["studio", str(invalid_json_path)]) == 1
    err = capsys.readouterr().err
    assert "Failed to load Studio blueprint" in err
    assert "Invalid JSON" in err

    invalid_blueprint_path = tmp_path / "invalid_blueprint.json"
    invalid_blueprint_path.write_text(
        json.dumps({"version": 1, "nodes": "not a list"}),
        encoding="utf-8",
    )
    assert cli_main(["studio", str(invalid_blueprint_path)]) == 1
    err = capsys.readouterr().err
    assert "Failed to load Studio blueprint" in err
    assert "nodes must be an array" in err


def test_dashboard_snapshot_and_renderer_include_registry_and_store(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)

    snapshot = build_dashboard_snapshot(store_path=store_path)
    html = DevtoolsHtmlRenderer().render_dashboard(snapshot)

    assert snapshot["runs"]["reports"][0]["run_id"] == "run_cli"
    assert snapshot["runs"]["reports"][0]["state"] is None
    assert snapshot["runs"]["reports"][0]["event_count"] is None
    assert "report" not in snapshot["runs"]["reports"][0]
    assert "task" not in snapshot["runs"]["tasks"][0]
    assert snapshot["runs"]["configured"] is True
    assert snapshot["registry"]["configured"] is False
    assert snapshot["version"] == __version__
    assert "run_cli" in html
    assert "Protolink Studio" in html
    assert "Selected agent" in html


def test_dashboard_without_store_does_not_create_default_database(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output_path = tmp_path / "dashboard.html"

    assert cli_main(["dashboard", "--output", str(output_path)]) == 0

    assert output_path.is_file()
    assert not (tmp_path / "runs.db").exists()
    assert "No run store connected" in output_path.read_text(encoding="utf-8")


def test_dashboard_auto_discovers_existing_default_store(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store_path = tmp_path / "runs.db"
    _seed_run_store(store_path)
    output_path = tmp_path / "dashboard.html"

    assert cli_main(["dashboard", "--output", str(output_path)]) == 0

    dashboard_html = output_path.read_text(encoding="utf-8")
    assert "run_cli" in dashboard_html
    assert '"store": "runs.db"' in dashboard_html


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


def _seed_candidate_report(store_path: Path, *, run_id: str, model: str) -> None:
    store = SQLiteRunStore(store_path)
    task = Task.create_infer(prompt="hello")
    context = RunContext(
        run_id=run_id,
        session_id="session_cli",
        trace_id="trace_cli",
        agent_chain=["client"],
    )
    context.attach_to_task(task)
    task.complete("done")
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
                payload={"provider": "mock", "model": model},
            ),
        ],
        context=context,
        final_task=task.to_dict(),
    )
    store.save_report(report, agent_name="cli_agent")
