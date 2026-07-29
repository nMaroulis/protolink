import json
import sqlite3
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from protolink import RunContext, RunReport, SQLiteRunStore, Task
from protolink.devtools.server import (
    _dashboard_error_message,
    _dashboard_host_allowed,
    _dashboard_origin_allowed,
    _dashboard_source_mutation_allowed,
    _normalize_registry_url,
    _validate_run_store_path,
    build_dashboard_snapshot,
    serve_dashboard,
)
from protolink.devtools.traces import (
    InvalidTraceTokenError,
    StaleTraceTokenError,
    TraceJsonlReader,
    list_trace_records,
    load_trace_record,
)


def test_trace_pages_are_recent_first_bounded_and_lazy(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    _write_records(trace_path, [_trace_record(index) for index in range(1, 6)])

    first = list_trace_records(trace_path, limit=2)

    assert [record["task_id"] for record in first["records"]] == ["task_5", "task_4"]
    assert first["next_cursor"]
    assert first["records"][0]["span_count"] == 2
    assert first["records"][0]["event_count"] == 2
    assert first["records"][0]["span_kinds"] == {"task": 1, "llm": 1}
    assert first["records"][0]["llm_metrics"]["total_tokens"] == 105
    assert first["records"][0]["final_state"] == "completed"
    assert "spans" not in first["records"][0]
    assert "payload" not in json.dumps(first)

    second = list_trace_records(trace_path, limit=2, cursor=first["next_cursor"])
    third = list_trace_records(trace_path, limit=2, cursor=second["next_cursor"])

    assert [record["task_id"] for record in second["records"]] == ["task_3", "task_2"]
    assert [record["task_id"] for record in third["records"]] == ["task_1"]
    assert third["next_cursor"] is None

    detail = load_trace_record(trace_path, first["records"][0]["record_id"])

    assert detail["trace"]["task_id"] == "task_5"
    assert detail["trace"]["spans"][1]["input"] == {"prompt": "payload 5"}
    assert detail["summary"] == first["records"][0]
    assert "task_5" not in first["records"][0]["record_id"]


def test_trace_cursor_and_record_id_survive_append(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    _write_records(trace_path, [_trace_record(index) for index in range(1, 4)])
    first = list_trace_records(trace_path, limit=1)
    record_id = first["records"][0]["record_id"]
    cursor = first["next_cursor"]

    _append_record(trace_path, _trace_record(4))

    older = list_trace_records(trace_path, limit=2, cursor=cursor)
    detail = load_trace_record(trace_path, record_id)

    assert [record["task_id"] for record in older["records"]] == ["task_2", "task_1"]
    assert detail["trace"]["task_id"] == "task_3"
    assert list_trace_records(trace_path, limit=1)["records"][0]["task_id"] == "task_4"


def test_trace_reader_uses_byte_offsets_for_unicode_records(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    first = _trace_record(1)
    second = _trace_record(2)
    first["agent_name"] = "πράκτορας-🧭"
    first["spans"][1]["input"] = {"prompt": "naïve café 東京"}
    _write_records(trace_path, [first, second])

    newest = list_trace_records(trace_path, limit=1)
    older = list_trace_records(trace_path, limit=1, cursor=newest["next_cursor"])
    detail = load_trace_record(trace_path, older["records"][0]["record_id"])

    assert older["records"][0]["agent_name"] == "πράκτορας-🧭"
    assert detail["trace"]["spans"][1]["input"]["prompt"] == "naïve café 東京"


def test_trace_reader_skips_partial_tail_and_reports_malformed_lines(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    trace_path.write_bytes(
        json.dumps(_trace_record(1)).encode()
        + b"\n"
        + b"{malformed json}\n"
        + json.dumps(_trace_record(2)).encode()
        + b"\n"
        + b'{"trace_id":"still-being-written"'
    )

    page = list_trace_records(trace_path, limit=10)

    assert [record["task_id"] for record in page["records"]] == ["task_2", "task_1"]
    assert page["partial_tail"] is True
    assert page["malformed_count"] == 1
    assert page["next_cursor"] is None


def test_trace_reader_rejects_non_finite_json_numbers(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    invalid = _trace_record(2)
    invalid["duration_ms"] = float("nan")
    _write_records(trace_path, [_trace_record(1), invalid, _trace_record(3)])

    page = list_trace_records(trace_path, limit=10)

    assert [record["task_id"] for record in page["records"]] == ["task_3", "task_1"]
    assert page["malformed_count"] == 1
    assert "NaN" not in json.dumps(page, allow_nan=False)


def test_trace_reader_rejects_finite_range_overflow_at_any_depth(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    overflow = json.dumps(_trace_record(2))
    overflow = overflow[:-1] + ', "nested": {"overflow": 1e9999}}'
    trace_path.write_text(
        json.dumps(_trace_record(1)) + "\n" + overflow + "\n" + json.dumps(_trace_record(3)) + "\n",
        encoding="utf-8",
    )

    page = list_trace_records(trace_path, limit=10)

    assert [record["task_id"] for record in page["records"]] == ["task_3", "task_1"]
    assert page["malformed_count"] == 1
    json.dumps(page, allow_nan=False)


def test_trace_reader_counts_excessively_nested_json_as_malformed(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    deeply_nested = '{"trace_id":"deep","payload":' + "[" * 10_000 + "0" + "]" * 10_000 + "}\n"
    trace_path.write_text(
        deeply_nested + json.dumps(_trace_record(1)) + "\n",
        encoding="utf-8",
    )

    page = list_trace_records(trace_path, limit=10)

    assert [record["task_id"] for record in page["records"]] == ["task_1"]
    assert page["malformed_count"] == 1


def test_trace_reader_requires_newline_before_exposing_final_record(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    trace_path.write_text(json.dumps(_trace_record(1)), encoding="utf-8")

    partial = list_trace_records(trace_path)
    assert partial["records"] == []
    assert partial["partial_tail"] is True

    with trace_path.open("ab") as file:
        file.write(b"\n")

    complete = list_trace_records(trace_path)
    assert [record["task_id"] for record in complete["records"]] == ["task_1"]
    assert complete["partial_tail"] is False


def test_trace_reader_skips_large_blank_tail_in_bounded_chunks(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    trace_path.write_bytes(json.dumps(_trace_record(1)).encode() + b"\n" + b"\n" * (2 * 1024 * 1024))
    reader = TraceJsonlReader(
        trace_path,
        max_line_bytes=1024 * 1024,
        max_scan_bytes=3 * 1024 * 1024,
    )

    page = reader.page(limit=10)

    assert [record["task_id"] for record in page["records"]] == ["task_1"]
    assert page["scanned_bytes"] <= 3 * 1024 * 1024
    assert page["next_cursor"] is None


def test_trace_reader_rejects_scan_budget_smaller_than_record_limit(tmp_path: Path):
    with pytest.raises(
        ValueError,
        match="max_scan_bytes must be greater than or equal to max_line_bytes",
    ):
        TraceJsonlReader(
            tmp_path / "traces.jsonl",
            max_line_bytes=180,
            max_scan_bytes=64,
        )


def test_trace_reader_preserves_valid_record_straddling_blank_scan_page(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    older = {
        "trace_id": "old",
        "task_id": "reachable",
        "payload": "x" * 380,
        "spans": [],
        "events": [],
    }
    trace_path.write_bytes(json.dumps(older).encode() + b"\n" + b"\n" * 800)
    reader = TraceJsonlReader(
        trace_path,
        max_line_bytes=512,
        max_scan_bytes=1024,
    )

    first = reader.page(limit=10)
    second = reader.page(limit=10, cursor=first["next_cursor"])

    assert first["records"] == []
    assert first["next_cursor"]
    assert first["malformed_count"] == 0
    assert first["oversized_count"] == 0
    assert [record["task_id"] for record in second["records"]] == ["reachable"]


def test_trace_reader_pages_across_a_line_larger_than_scan_budget(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    older = {"trace_id": "old", "task_id": "reachable", "spans": [], "events": []}
    oversized = {"trace_id": "huge", "task_id": "skip-me", "payload": "x" * 3500}
    _write_records(trace_path, [older, oversized])
    reader = TraceJsonlReader(
        trace_path,
        max_line_bytes=1024,
        max_scan_bytes=1024,
    )

    cursor = None
    task_ids: list[str] = []
    oversized_count = 0
    pages = []
    for _ in range(8):
        page = reader.page(limit=10, cursor=cursor)
        pages.append(page)
        task_ids.extend(record["task_id"] for record in page["records"])
        oversized_count += page["oversized_count"]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert task_ids == ["reachable"]
    assert oversized_count == 1
    assert len(pages) > 2
    assert all(page["scanned_bytes"] <= 1024 for page in pages)
    assert cursor is None


def test_trace_reader_skips_oversized_lines_and_bounds_each_scan(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    huge = _trace_record(2)
    huge["spans"][1]["input"] = {"prompt": "x" * 10_000}
    _write_records(trace_path, [_trace_record(1), huge, _trace_record(3), _trace_record(4)])
    reader = TraceJsonlReader(trace_path, max_line_bytes=5000, max_scan_lines=2)

    first = reader.page(limit=10)
    second = reader.page(limit=10, cursor=first["next_cursor"])

    assert [record["task_id"] for record in first["records"]] == ["task_4", "task_3"]
    assert first["scan_exhausted"] is True
    assert first["next_cursor"]
    assert [record["task_id"] for record in second["records"]] == ["task_1"]
    assert second["oversized_count"] == 1


def test_trace_record_tokens_reject_invalid_or_replaced_files(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    replacement_path = tmp_path / "replacement.jsonl"
    _write_records(trace_path, [_trace_record(1)])
    record_id = list_trace_records(trace_path)["records"][0]["record_id"]

    with pytest.raises(InvalidTraceTokenError):
        load_trace_record(trace_path, "not-a-record-token")

    _write_records(replacement_path, [_trace_record(2)])
    replacement_path.replace(trace_path)

    with pytest.raises(StaleTraceTokenError):
        load_trace_record(trace_path, record_id)


def test_trace_record_token_rejects_removed_terminating_newline(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    _write_records(trace_path, [_trace_record(1)])
    record_id = list_trace_records(trace_path)["records"][0]["record_id"]

    trace_path.write_bytes(trace_path.read_bytes()[:-1])

    with pytest.raises(StaleTraceTokenError):
        load_trace_record(trace_path, record_id)


def test_trace_tokens_detect_in_place_truncation_and_regrowth(tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    _write_records(trace_path, [_trace_record(index) for index in range(1, 4)])
    page = list_trace_records(trace_path, limit=1)
    record_id = page["records"][0]["record_id"]
    cursor = page["next_cursor"]

    _write_records(trace_path, [_trace_record(index) for index in range(7, 10)])

    with pytest.raises(StaleTraceTokenError):
        load_trace_record(trace_path, record_id)
    with pytest.raises(StaleTraceTokenError):
        list_trace_records(trace_path, cursor=cursor)


def test_trace_source_and_snapshot_handle_missing_files(tmp_path: Path):
    trace_path = tmp_path / "missing.jsonl"

    page = list_trace_records(trace_path)
    snapshot = build_dashboard_snapshot(trace_path=trace_path)

    assert page["configured"] is True
    assert page["exists"] is False
    assert page["records"] == []
    assert snapshot["telemetry"]["path"] == str(trace_path)
    assert snapshot["telemetry"]["exists"] is False
    assert snapshot["telemetry"]["error"] is None
    assert build_dashboard_snapshot()["telemetry"]["configured"] is False


def test_dashboard_source_validation_is_local_and_run_store_is_read_only(tmp_path: Path):
    store_path = tmp_path / "runs.db"
    SQLiteRunStore(store_path)
    modified_at = store_path.stat().st_mtime_ns

    assert _normalize_registry_url(" http://127.0.0.1:9000/ ") == "http://127.0.0.1:9000"
    assert _validate_run_store_path(str(store_path)) == store_path.resolve()
    assert _dashboard_source_mutation_allowed("127.0.0.1") is True
    assert _dashboard_source_mutation_allowed("::1") is True
    assert _dashboard_source_mutation_allowed("192.168.1.20") is False

    snapshot = build_dashboard_snapshot(store_path=store_path)

    assert snapshot["runs"]["configured"] is True
    assert snapshot["runs"]["error"] is None
    assert store_path.stat().st_mtime_ns == modified_at


def test_dashboard_error_messages_are_bounded():
    message = _dashboard_error_message(ValueError("x" * 2_000))

    assert len(message) == 500
    assert message.endswith("…")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1:9000",
        "http://user:secret@127.0.0.1:9000",
        "http://127.0.0.1:9000?token=secret",
        "http://127.0.0.1:9000/#fragment",
    ],
)
def test_dashboard_registry_source_rejects_unsafe_urls(url: str):
    with pytest.raises(ValueError):
        _normalize_registry_url(url)


def test_dashboard_run_store_validation_rejects_missing_and_non_sqlite_files(tmp_path: Path):
    missing = tmp_path / "missing.db"
    plain = tmp_path / "plain.db"
    plain.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(ValueError, match="not found"):
        _validate_run_store_path(str(missing))
    with pytest.raises(ValueError, match="not a SQLite"):
        _validate_run_store_path(str(plain))
    with pytest.raises(FileNotFoundError):
        SQLiteRunStore(missing, read_only=True)
    assert not missing.exists()


def test_read_only_run_store_rejects_sqlite_without_protolink_tables(tmp_path: Path):
    database = tmp_path / "other.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    modified_at = database.stat().st_mtime_ns

    with pytest.raises(ValueError, match="expected protolink_tasks schema"):
        _validate_run_store_path(str(database))
    snapshot = build_dashboard_snapshot(store_path=database)

    assert "no such table" in snapshot["runs"]["error"]
    assert snapshot["runs"]["tasks"] == []
    assert database.stat().st_mtime_ns == modified_at


def test_dashboard_trace_endpoints_page_detail_and_disable_caching(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "traces.jsonl"
    store_path = tmp_path / "runs.db"
    _write_records(trace_path, [_trace_record(1), _trace_record(2)])
    store = SQLiteRunStore(store_path)
    shared_id = "shared_run_and_task_id"
    task = Task(id=shared_id)
    task_context = RunContext(run_id="task_only_run")
    task_context.attach_to_task(task)
    task.complete("task result")
    store.save_task(task, context=task_context, agent_name="task_agent")
    report_task = Task.create_infer(prompt="report result")
    report_context = RunContext(run_id=shared_id)
    report_context.attach_to_task(report_task)
    report_task.complete("report result")
    store.save_report(
        RunReport.from_events([], context=report_context, final_task=report_task.to_dict()),
        agent_name="report_agent",
    )
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            """
            INSERT INTO protolink_run_reports
            (run_id, report_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("malformed_report", "[]", "{}", "2026-07-29T00:00:00+00:00"),
        )
    monkeypatch.setattr(
        "protolink.devtools.server.fetch_registry_agents",
        lambda url, timeout: [{"name": "connected-agent", "url": f"{url}/agent"}],
    )
    server, thread = _start_dashboard_server(monkeypatch, trace_path)
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with urlopen(f"{base_url}/api/snapshot?refresh=1", timeout=3) as response:
            snapshot = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"
        assert snapshot["telemetry"]["records"][0]["task_id"] == "task_2"

        with urlopen(base_url, timeout=3) as response:
            dashboard_html = response.read().decode()
        assert "window.__PROTOLINK_LIVE__ = true;" in dashboard_html

        with urlopen(f"{base_url}/api/traces?limit=1&unused=value", timeout=3) as response:
            page = json.loads(response.read())
            assert response.headers["Pragma"] == "no-cache"
        assert [record["task_id"] for record in page["records"]] == ["task_2"]

        record_id = page["records"][0]["record_id"]
        with urlopen(f"{base_url}/api/traces/{record_id}", timeout=3) as response:
            detail = json.loads(response.read())
        assert detail["trace"]["task_id"] == "task_2"

        with pytest.raises(HTTPError) as invalid_limit:
            urlopen(f"{base_url}/api/traces?limit=not-an-integer", timeout=3)
        assert invalid_limit.value.code == 400
        assert invalid_limit.value.headers["Cache-Control"] == "no-store"

        hostile_request = Request(f"{base_url}/api/traces", headers={"Host": "attacker.example"})
        with pytest.raises(HTTPError) as hostile_host:
            urlopen(hostile_request, timeout=3)
        assert hostile_host.value.code == 421
        assert hostile_host.value.headers["Cache-Control"] == "no-store"

        plain_post = Request(
            f"{base_url}/api/agents/ping",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with pytest.raises(HTTPError) as unsupported_content_type:
            urlopen(plain_post, timeout=3)
        assert unsupported_content_type.value.code == 415

        cross_origin_post = Request(
            f"{base_url}/api/agents/ping",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as cross_origin:
            urlopen(cross_origin_post, timeout=3)
        assert cross_origin.value.code == 403

        invalid_utf8_post = Request(
            f"{base_url}/api/agents/ping",
            data=b"\xff",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(invalid_utf8_post, timeout=3) as response:
            invalid_utf8_result = json.loads(response.read())
        assert invalid_utf8_result["ok"] is False

        registry_connect = Request(
            f"{base_url}/api/sources/registry",
            data=json.dumps({"url": "http://127.0.0.1:9100"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(registry_connect, timeout=3) as response:
            registry_source = json.loads(response.read())
        assert registry_source["registry"]["configured"] is True
        assert registry_source["registry"]["agents"][0]["name"] == "connected-agent"

        runs_connect = Request(
            f"{base_url}/api/sources/runs",
            data=json.dumps({"path": str(store_path)}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(runs_connect, timeout=3) as response:
            runs_source = json.loads(response.read())
        assert runs_source["runs"]["configured"] is True
        assert runs_source["runs"]["store"] == str(store_path.resolve())

        with urlopen(f"{base_url}/api/runs/{shared_id}?kind=task", timeout=3) as response:
            task_replay = json.loads(response.read())
        assert task_replay["source"] == "task"
        assert task_replay["agent_name"] == "task_agent"

        with urlopen(f"{base_url}/api/runs/{shared_id}?kind=report", timeout=3) as response:
            report_replay = json.loads(response.read())
        assert report_replay["source"] == "report"
        assert report_replay["agent_name"] == "report_agent"

        with pytest.raises(HTTPError) as invalid_replay_kind:
            urlopen(f"{base_url}/api/runs/{shared_id}?kind=unknown", timeout=3)
        assert invalid_replay_kind.value.code == 400

        with pytest.raises(HTTPError) as malformed_replay:
            urlopen(f"{base_url}/api/runs/malformed_report?kind=report", timeout=3)
        malformed_error = json.loads(malformed_replay.value.read())
        assert malformed_replay.value.code == 422
        assert "must be a JSON object" in malformed_error["error"]
        assert len(malformed_error["error"]) <= 500

        with urlopen(f"{base_url}/api/snapshot", timeout=3) as response:
            connected_snapshot = json.loads(response.read())
        assert connected_snapshot["registry"]["url"] == "http://127.0.0.1:9100"
        assert connected_snapshot["runs"]["store"] == str(store_path.resolve())
        assert connected_snapshot["source_revision"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_invalid_registry_request_does_not_supersede_valid_inflight_connection(tmp_path: Path, monkeypatch):
    trace_path = tmp_path / "traces.jsonl"
    _write_records(trace_path, [_trace_record(1)])
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    def slow_registry_fetch(url: str, timeout: float):
        fetch_started.set()
        assert release_fetch.wait(timeout=3)
        return [{"name": "connected-agent", "url": f"{url}/agent"}]

    monkeypatch.setattr("protolink.devtools.server.fetch_registry_agents", slow_registry_fetch)
    server, server_thread = _start_dashboard_server(monkeypatch, trace_path)
    base_url = f"http://127.0.0.1:{server.server_port}"
    result: dict[str, Any] = {}

    def connect_valid_registry() -> None:
        request = Request(
            f"{base_url}/api/sources/registry",
            data=json.dumps({"url": "http://127.0.0.1:9100"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                result["payload"] = json.loads(response.read())
        except Exception as exc:  # pragma: no cover - assertion reports the captured error
            result["error"] = exc

    connect_thread = threading.Thread(target=connect_valid_registry, daemon=True)
    connect_thread.start()
    try:
        assert fetch_started.wait(timeout=3)
        invalid_request = Request(
            f"{base_url}/api/sources/registry",
            data=json.dumps({"url": "ftp://invalid.example"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as invalid_source:
            urlopen(invalid_request, timeout=3)
        assert invalid_source.value.code == 400

        release_fetch.set()
        connect_thread.join(timeout=3)
        assert not connect_thread.is_alive()
        assert "error" not in result
        assert result["payload"]["revision"] == 1
        assert result["payload"]["registry"]["url"] == "http://127.0.0.1:9100"
    finally:
        release_fetch.set()
        connect_thread.join(timeout=3)
        server.shutdown()
        server_thread.join(timeout=3)


@pytest.mark.parametrize(
    ("host_header", "bind_host", "expected"),
    [
        ("localhost:8765", "127.0.0.1", True),
        ("127.0.0.1:8765", "localhost", True),
        ("[::1]:8765", "::1", True),
        ("attacker.example", "127.0.0.1", False),
        ("127.0.0.1.attacker.example", "127.0.0.1", False),
        ("192.168.1.10:8765", "0.0.0.0", True),
        ("dashboard.internal:8765", "0.0.0.0", False),
        ("dashboard.internal:8765", "dashboard.internal", True),
    ],
)
def test_dashboard_host_validation(host_header: str, bind_host: str, expected):
    assert _dashboard_host_allowed(host_header, bind_host=bind_host) is expected


@pytest.mark.parametrize(
    ("origin", "referer", "host_header", "expected"),
    [
        ("http://127.0.0.1:8765", None, "127.0.0.1:8765", True),
        (None, "http://localhost:8765/dashboard", "localhost:8765", True),
        ("https://attacker.example", None, "127.0.0.1:8765", False),
        ("null", None, "127.0.0.1:8765", False),
        (None, None, "127.0.0.1:8765", True),
    ],
)
def test_dashboard_origin_validation(origin, referer, host_header: str, expected):
    assert (
        _dashboard_origin_allowed(
            origin,
            referer,
            host_header=host_header,
        )
        is expected
    )


def _start_dashboard_server(monkeypatch, trace_path: Path):
    import protolink.devtools.server as server_module

    original_server = server_module.ThreadingHTTPServer
    ready = threading.Event()
    created = []

    class CapturingServer(original_server):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        def serve_forever(self, *args, **kwargs):
            ready.set()
            return super().serve_forever(*args, **kwargs)

    monkeypatch.setattr(server_module, "ThreadingHTTPServer", CapturingServer)
    thread = threading.Thread(
        target=serve_dashboard,
        kwargs={"host": "127.0.0.1", "port": 0, "trace_path": trace_path},
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=3)
    return created[0], thread


def _trace_record(index: int) -> dict:
    trace_id = "shared_trace"
    started = f"2026-07-28T10:00:{index:02d}+00:00"
    ended = f"2026-07-28T10:00:{index + 1:02d}+00:00"
    return {
        "trace_id": trace_id,
        "task_id": f"task_{index}",
        "agent_name": f"agent_{index % 2}",
        "started_at": started,
        "ended_at": ended,
        "status": "error" if index == 2 else "ok",
        "duration_ms": index * 100.5,
        "metadata": {
            "final_state": "failed" if index == 2 else "completed",
            "retry_count": index % 2,
            "llm_metrics": {
                "call_count": 1,
                "total_latency_ms": index * 90,
                "total_input_tokens": 100,
                "total_output_tokens": index,
                "total_tokens": 100 + index,
                "unused_payload": {"must": "not leak into summaries"},
            },
        },
        "spans": [
            {
                "id": f"task-span-{index}",
                "trace_id": trace_id,
                "name": "Task",
                "kind": "task",
                "parent_id": None,
                "started_at": started,
                "ended_at": ended,
                "status": "ok",
                "events": [],
            },
            {
                "id": f"llm-span-{index}",
                "trace_id": trace_id,
                "name": "LLM Call",
                "kind": "llm",
                "parent_id": f"task-span-{index}",
                "started_at": started,
                "ended_at": ended,
                "status": "ok",
                "input": {"prompt": f"payload {index}"},
                "events": [],
            },
        ],
        "events": [
            {"type": "llm_call_started", "timestamp": started, "span_id": f"llm-span-{index}", "payload": {}},
            {"type": "llm_call_completed", "timestamp": ended, "span_id": f"llm-span-{index}", "payload": {}},
        ],
    }


def _write_records(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _append_record(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
