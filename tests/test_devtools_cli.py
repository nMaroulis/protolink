import json
from pathlib import Path

import pytest

from protolink import RunContext, RunEvent, RunReport, SQLiteRunStore, Task
from protolink.cli import main as cli_main
from protolink.devtools import build_run_replay_view, list_run_store_records
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
    assert "Protolink Studio" in dashboard_html
    assert "Coming soon" in dashboard_html
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
