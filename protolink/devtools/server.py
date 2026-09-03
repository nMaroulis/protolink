"""Local HTTP server for the Protolink dashboard."""

from __future__ import annotations

import ipaddress
import json
import sqlite3
import subprocess
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import parse_qs, unquote, urlsplit

from protolink.__version__ import __version__
from protolink.devtools.agents import chat_with_agent, ping_agent
from protolink.devtools.registry import fetch_registry_agents
from protolink.devtools.runs import build_run_replay_view, list_run_store_records
from protolink.devtools.studio import (
    StudioRuntimeManager,
    StudioValidationError,
    default_studio_blueprint,
    generate_studio_code,
    studio_catalog,
    studio_code_digest,
)
from protolink.devtools.traces import (
    DEFAULT_TRACE_PAGE_LIMIT,
    InvalidTraceTokenError,
    StaleTraceTokenError,
    TraceFileError,
    TraceRecordTooLargeError,
    empty_trace_page,
    list_trace_records,
    load_trace_record,
)
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer

_MAX_DASHBOARD_REQUEST_BYTES = 1024 * 1024
_MAX_REGISTRY_URL_CHARS = 2048
_MAX_RUN_STORE_PATH_CHARS = 4096


@dataclass
class _DashboardSourceState:
    """Thread-safe, process-local sources selected by the dashboard."""

    registry_url: str | None
    store_path: Path | None
    revision: int = 0
    _registry_request: int = 0
    _runs_request: int = 0
    _lock: RLock = field(default_factory=RLock, repr=False)

    def current(self) -> tuple[str | None, Path | None, int]:
        with self._lock:
            return self.registry_url, self.store_path, self.revision

    def begin(self, kind: str) -> int:
        with self._lock:
            if kind == "registry":
                self._registry_request += 1
                return self._registry_request
            self._runs_request += 1
            return self._runs_request

    def commit_registry(self, request: int, url: str | None) -> int | None:
        with self._lock:
            if request != self._registry_request:
                return None
            self.registry_url = url
            self.revision += 1
            return self.revision

    def commit_runs(self, request: int, path: Path | None) -> int | None:
        with self._lock:
            if request != self._runs_request:
                return None
            self.store_path = path
            self.revision += 1
            return self.revision


def build_dashboard_snapshot(
    *,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    blueprint: dict[str, Any] | None = None,
    project_loaded: bool = False,
    limit: int = 20,
    source_revision: int = 0,
) -> dict[str, Any]:
    """Collect dashboard data from registry, run-store, and telemetry sources."""
    telemetry = empty_trace_page()
    telemetry["limit"] = limit
    if trace_path is not None:
        telemetry.update(
            {
                "path": str(Path(trace_path).expanduser()),
                "configured": True,
            }
        )
    snapshot: dict[str, Any] = {
        "version": __version__,
        "source_revision": source_revision,
        "registry": {
            "configured": bool(registry_url),
            "url": registry_url,
            "agents": [],
            "error": None,
        },
        "runs": {
            "configured": bool(store_path),
            "store": str(store_path) if store_path else None,
            "tasks": [],
            "reports": [],
            "error": None,
        },
        "telemetry": telemetry,
        "studio": {
            "blueprint": blueprint if blueprint is not None else default_studio_blueprint(),
            "catalog": studio_catalog(),
            "loaded": project_loaded,
        },
    }

    if registry_url:
        try:
            snapshot["registry"]["agents"] = fetch_registry_agents(registry_url, timeout=2.0)
        except Exception as exc:
            snapshot["registry"]["error"] = _dashboard_error_message(exc)

    if store_path:
        try:
            records = list_run_store_records(
                store_path,
                limit=limit,
                read_only=True,
                compact=True,
            )
            snapshot["runs"].update(records)
        except Exception as exc:
            snapshot["runs"]["error"] = _dashboard_error_message(exc)

    if trace_path is not None:
        try:
            snapshot["telemetry"] = list_trace_records(trace_path, limit=limit)
        except Exception as exc:
            snapshot["telemetry"]["error"] = _dashboard_error_message(exc)

    return snapshot


def serve_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    blueprint: dict[str, Any] | None = None,
    project_loaded: bool = False,
    open_browser: bool = False,
    start_tab: str = "dashboard",
) -> None:
    """Serve the local dashboard until interrupted."""
    renderer = DevtoolsHtmlRenderer()
    studio_runtime = StudioRuntimeManager()
    source_state = _DashboardSourceState(
        registry_url=registry_url or None,
        store_path=Path(store_path).expanduser() if store_path else None,
    )

    def current_snapshot() -> dict[str, Any]:
        active_registry, active_store, revision = source_state.current()
        return build_dashboard_snapshot(
            registry_url=active_registry,
            store_path=active_store,
            trace_path=trace_path,
            blueprint=blueprint,
            project_loaded=project_loaded,
            source_revision=revision,
        )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Serve dashboard HTML and JSON endpoints."""
            if not _dashboard_host_allowed(self.headers.get("Host"), bind_host=host):
                self._send_json({"error": "Unrecognized dashboard Host header"}, status=421)
                return
            request = urlsplit(self.path)
            path = request.path
            query = parse_qs(request.query, keep_blank_values=True)
            if path == "/":
                snapshot = current_snapshot()
                self._send_html(renderer.render_dashboard(snapshot, start_tab=start_tab, live=True))
                return
            if path == "/studio":
                snapshot = current_snapshot()
                self._send_html(renderer.render_dashboard(snapshot, start_tab="studio", live=True))
                return
            if path == "/api/snapshot":
                self._send_json(current_snapshot())
                return
            if path == "/api/studio/catalog":
                self._send_json(studio_catalog())
                return
            if path == "/api/studio/status":
                self._send_json(studio_runtime.status())
                return
            if path.startswith("/api/runs/"):
                _, active_store, _ = source_state.current()
                if active_store is None:
                    self._send_json({"error": "No run store configured"}, status=404)
                    return
                run_id = unquote(path.removeprefix("/api/runs/"))
                raw_kind = _first_query_value(query, "kind")
                kind: Literal["report", "task"] | None
                if raw_kind in {None, ""}:
                    kind = None
                elif raw_kind == "report":
                    kind = "report"
                elif raw_kind == "task":
                    kind = "task"
                else:
                    self._send_json({"error": "Run replay kind must be 'report' or 'task'"}, status=400)
                    return
                try:
                    self._send_json(
                        build_run_replay_view(
                            active_store,
                            run_id,
                            read_only=True,
                            kind=kind,
                        ).to_dict()
                    )
                except (OSError, sqlite3.Error) as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=400)
                except Exception as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=422)
                return
            if path == "/api/traces":
                if trace_path is None:
                    self._send_json({"error": "No telemetry trace file configured"}, status=404)
                    return
                raw_limit = _first_query_value(query, "limit")
                cursor = _first_query_value(query, "cursor")
                try:
                    page_limit = DEFAULT_TRACE_PAGE_LIMIT if raw_limit in {None, ""} else int(raw_limit)
                    if page_limit <= 0:
                        raise ValueError("limit must be a positive integer")
                    self._send_json(list_trace_records(trace_path, limit=page_limit, cursor=cursor or None))
                except (ValueError, TraceFileError) as exc:
                    self._send_trace_error(exc)
                except OSError as exc:
                    self._send_json({"error": str(exc)}, status=500)
                return
            if path.startswith("/api/traces/"):
                if trace_path is None:
                    self._send_json({"error": "No telemetry trace file configured"}, status=404)
                    return
                record_id = unquote(path.removeprefix("/api/traces/"))
                if not record_id:
                    self._send_json({"error": "Missing trace record identifier"}, status=400)
                    return
                try:
                    self._send_json(load_trace_record(trace_path, record_id))
                except (ValueError, TraceFileError) as exc:
                    self._send_trace_error(exc)
                except FileNotFoundError:
                    self._send_json({"error": "Telemetry trace file not found"}, status=404)
                except OSError as exc:
                    self._send_json({"error": str(exc)}, status=500)
                return
            self.send_error(404, "Not found")

        def do_POST(self) -> None:
            """Serve dashboard action endpoints."""
            if not _dashboard_host_allowed(self.headers.get("Host"), bind_host=host):
                self._send_json({"error": "Unrecognized dashboard Host header"}, status=421)
                return
            content_type = (self.headers.get("Content-Type") or "").partition(";")[0].strip().lower()
            if content_type != "application/json":
                self._send_json({"error": "Dashboard POST requests require application/json"}, status=415)
                return
            if not _dashboard_origin_allowed(
                self.headers.get("Origin"),
                self.headers.get("Referer"),
                host_header=self.headers.get("Host"),
            ):
                self._send_json({"error": "Cross-origin dashboard POST rejected"}, status=403)
                return
            try:
                content_length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send_json({"error": "Invalid Content-Length"}, status=400)
                return
            if content_length < 0 or content_length > _MAX_DASHBOARD_REQUEST_BYTES:
                self._send_json({"error": "Dashboard request body is too large"}, status=413)
                return
            path = urlsplit(self.path).path
            if path == "/api/studio/generate":
                payload = self._read_json()
                if "blueprint" not in payload:
                    self._send_json({"error": "Missing Studio blueprint"}, status=400)
                    return
                try:
                    generated = generate_studio_code(payload["blueprint"])
                except StudioValidationError as exc:
                    self._send_json(exc.to_dict(), status=422)
                    return
                except (TypeError, ValueError, OverflowError) as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=422)
                    return
                response = generated.to_dict()
                response.update(
                    {
                        "language": "python",
                        "digest": studio_code_digest(generated.source),
                    }
                )
                self._send_json(response)
                return

            if path == "/api/studio/run":
                if not _dashboard_source_mutation_allowed(self.client_address[0]):
                    self._send_json(
                        {"error": "Studio projects can only be run from this machine"},
                        status=403,
                    )
                    return
                payload = self._read_json()
                if "blueprint" not in payload:
                    self._send_json({"error": "Missing Studio blueprint"}, status=400)
                    return
                try:
                    self._send_json(studio_runtime.start(payload["blueprint"]), status=201)
                except StudioValidationError as exc:
                    self._send_json(exc.to_dict(), status=422)
                except (TypeError, ValueError, OverflowError) as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=422)
                except RuntimeError as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=409)
                except (OSError, subprocess.SubprocessError) as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=500)
                return

            if path == "/api/studio/stop":
                if not _dashboard_source_mutation_allowed(self.client_address[0]):
                    self._send_json(
                        {"error": "Studio projects can only be stopped from this machine"},
                        status=403,
                    )
                    return
                payload = self._read_json()
                run_id = payload.get("run_id")
                if not isinstance(run_id, str) or not run_id:
                    self._send_json({"error": "Missing Studio run id"}, status=400)
                    return
                try:
                    self._send_json(studio_runtime.stop(run_id))
                except RuntimeError as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=409)
                return

            if path == "/api/sources/registry":
                if not _dashboard_source_mutation_allowed(self.client_address[0]):
                    self._send_json(
                        {"error": "Dashboard sources can only be changed from this machine"},
                        status=403,
                    )
                    return
                payload = self._read_json()
                if "url" not in payload:
                    self._send_json({"error": "Missing registry URL"}, status=400)
                    return
                try:
                    active_url = _normalize_registry_url(payload.get("url"))
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                    return
                request_id = source_state.begin("registry")
                if active_url is None:
                    revision = source_state.commit_registry(request_id, None)
                    if revision is None:
                        self._send_json({"error": "A newer registry connection replaced this request"}, status=409)
                        return
                    self._send_json(
                        {
                            "revision": revision,
                            "registry": {
                                "configured": False,
                                "url": None,
                                "agents": [],
                                "error": None,
                            },
                        }
                    )
                    return
                try:
                    agents = fetch_registry_agents(active_url, timeout=2.0)
                    error = None
                except Exception as exc:
                    agents = []
                    error = _dashboard_error_message(exc)
                revision = source_state.commit_registry(request_id, active_url)
                if revision is None:
                    self._send_json({"error": "A newer registry connection replaced this request"}, status=409)
                    return
                self._send_json(
                    {
                        "revision": revision,
                        "registry": {
                            "configured": True,
                            "url": active_url,
                            "agents": agents,
                            "error": error,
                        },
                    }
                )
                return

            if path == "/api/sources/runs":
                if not _dashboard_source_mutation_allowed(self.client_address[0]):
                    self._send_json(
                        {"error": "Dashboard sources can only be changed from this machine"},
                        status=403,
                    )
                    return
                payload = self._read_json()
                if "path" not in payload:
                    self._send_json({"error": "Missing run-store path"}, status=400)
                    return
                raw_path = payload.get("path")
                if raw_path is None or (isinstance(raw_path, str) and not raw_path.strip()):
                    request_id = source_state.begin("runs")
                    revision = source_state.commit_runs(request_id, None)
                    if revision is None:
                        self._send_json({"error": "A newer run-store connection replaced this request"}, status=409)
                        return
                    self._send_json(
                        {
                            "revision": revision,
                            "runs": {
                                "configured": False,
                                "store": None,
                                "tasks": [],
                                "reports": [],
                                "error": None,
                            },
                        }
                    )
                    return
                try:
                    active_store = _validate_run_store_path(raw_path)
                except (OSError, ValueError) as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=422)
                    return
                request_id = source_state.begin("runs")
                try:
                    records = list_run_store_records(
                        active_store,
                        limit=20,
                        read_only=True,
                        compact=True,
                    )
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self._send_json({"error": _dashboard_error_message(exc)}, status=422)
                    return
                revision = source_state.commit_runs(request_id, active_store)
                if revision is None:
                    self._send_json({"error": "A newer run-store connection replaced this request"}, status=409)
                    return
                self._send_json(
                    {
                        "revision": revision,
                        "runs": {
                            "configured": True,
                            "store": str(active_store),
                            "tasks": records["tasks"],
                            "reports": records["reports"],
                            "error": None,
                        },
                    }
                )
                return

            if path == "/api/agents/ping":
                payload = self._read_json()
                try:
                    result = ping_agent(str(payload.get("url") or ""), timeout=float(payload.get("timeout") or 3.0))
                except Exception as exc:
                    result = {
                        "ok": False,
                        "status": None,
                        "latency_ms": None,
                        "url": payload.get("url"),
                        "error": str(exc),
                    }
                self._send_json(result)
                return

            if path == "/api/agents/chat":
                payload = self._read_json()
                try:
                    result = chat_with_agent(
                        str(payload.get("url") or ""),
                        str(payload.get("message") or ""),
                        session_id=str(payload.get("session_id") or "dashboard"),
                        timeout=float(payload.get("timeout") or 30.0),
                    )
                except Exception as exc:
                    result = {"response": None, "error": str(exc), "url": payload.get("url")}
                self._send_json(result)
                return

            self.send_error(404, "Not found")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Keep dashboard request logs quiet by default."""
            return

        def end_headers(self) -> None:
            """Prevent browsers and intermediaries from retaining local data."""
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            super().end_headers()

        def _read_json(self) -> dict[str, Any]:
            """Read a small JSON request body."""
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                return {}
            return payload if isinstance(payload, dict) else {}

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            body = json.dumps(payload, indent=2, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_trace_error(self, exc: Exception) -> None:
            if isinstance(exc, TraceRecordTooLargeError):
                status = 413
            elif isinstance(exc, StaleTraceTokenError):
                status = 409
            elif isinstance(exc, InvalidTraceTokenError):
                status = 400
            else:
                status = 400
            self._send_json({"error": str(exc)}, status=status)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    target_url = f"{url}/studio" if start_tab == "studio" else url
    service_label = "Protolink Studio" if start_tab == "studio" else "Protolink dashboard"
    print(f"{service_label} running at {target_url}")
    if open_browser:
        webbrowser.open(target_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nStopping {service_label}")
    finally:
        studio_runtime.close()
        server.server_close()


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _dashboard_error_message(exc: BaseException, *, max_chars: int = 500) -> str:
    """Return a bounded error message suitable for a local JSON response."""
    try:
        message = str(exc).strip()
    except Exception:
        message = type(exc).__name__
    if not message:
        message = type(exc).__name__
    return message if len(message) <= max_chars else message[: max_chars - 1] + "…"


def _normalize_registry_url(value: Any) -> str | None:
    """Validate a session-only registry source selected in the dashboard."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Registry URL must be a string")
    url = value.strip()
    if not url:
        return None
    if len(url) > _MAX_REGISTRY_URL_CHARS:
        raise ValueError("Registry URL is too long")
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("Registry URL contains invalid whitespace")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Registry URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Registry URL must use http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Registry URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Registry URL must not contain a query or fragment")
    return url.rstrip("/")


def _validate_run_store_path(value: Any) -> Path:
    """Resolve and validate an existing Protolink SQLite run store."""
    if not isinstance(value, str):
        raise ValueError("Run-store path must be a string")
    raw_path = value.strip()
    if not raw_path:
        raise ValueError("Run-store path is required")
    if len(raw_path) > _MAX_RUN_STORE_PATH_CHARS or "\x00" in raw_path:
        raise ValueError("Run-store path is invalid")
    path = Path(raw_path).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"Run store not found: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"Run store is not a file: {resolved}")
    with resolved.open("rb") as file:
        if file.read(16) != b"SQLite format 3\x00":
            raise ValueError("Run store is not a SQLite database")
    required_columns = {
        "protolink_tasks": {
            "task_id",
            "state",
            "run_id",
            "session_id",
            "trace_id",
            "agent_name",
            "task_json",
            "metadata_json",
            "created_at",
            "updated_at",
        },
        "protolink_run_reports": {
            "run_id",
            "session_id",
            "trace_id",
            "agent_name",
            "report_json",
            "metadata_json",
            "created_at",
        },
    }
    try:
        uri = resolved.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as connection:
            for table, expected in required_columns.items():
                actual = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
                if not expected.issubset(actual):
                    raise ValueError(f"Run store is missing the expected {table} schema")
    except sqlite3.Error as exc:
        raise ValueError("Run store could not be inspected as SQLite") from exc
    return resolved


def _dashboard_source_mutation_allowed(client_host: str | None) -> bool:
    """Restrict browser-selected server sources to local dashboard clients."""
    if not client_host:
        return False
    address = _ip_literal(client_host.strip().strip("[]"))
    return bool(address and address.is_loopback)


def _dashboard_host_allowed(host_header: str | None, *, bind_host: str) -> bool:
    """Reject DNS-rebinding Host headers while preserving explicit LAN binds."""
    if not host_header:
        return False
    raw_header = host_header.strip()
    if (
        not raw_header
        or any(character in raw_header for character in "/\\@,#?")
        or any(character.isspace() for character in raw_header)
    ):
        return False
    try:
        parsed = urlsplit(f"//{raw_header}")
        header_host = (parsed.hostname or "").rstrip(".").lower()
        _ = parsed.port  # Validate an optional port without constraining ephemeral ports.
    except ValueError:
        return False
    if not header_host:
        return False

    normalized_bind = bind_host.strip().strip("[]").rstrip(".").lower()
    if normalized_bind in {"", "0.0.0.0", "::"}:
        return header_host == "localhost" or _ip_literal(header_host) is not None

    bind_ip = _ip_literal(normalized_bind)
    header_ip = _ip_literal(header_host)
    if bind_ip is not None:
        if bind_ip.is_loopback:
            return header_host == "localhost" or bool(header_ip and header_ip.is_loopback)
        return header_ip == bind_ip
    if normalized_bind == "localhost":
        return header_host == "localhost" or bool(header_ip and header_ip.is_loopback)
    return header_host == normalized_bind


def _dashboard_origin_allowed(
    origin_header: str | None,
    referer_header: str | None,
    *,
    host_header: str | None,
) -> bool:
    """Allow browser mutations only from the dashboard's own HTTP origin."""
    source = (origin_header or referer_header or "").strip()
    if not source:
        return True
    if not host_header or source == "null":
        return False
    try:
        source_url = urlsplit(source)
        request_url = urlsplit(f"//{host_header.strip()}")
        source_host = (source_url.hostname or "").rstrip(".").lower()
        request_host = (request_url.hostname or "").rstrip(".").lower()
        source_port = source_url.port or (443 if source_url.scheme == "https" else 80)
        request_port = request_url.port or 80
    except ValueError:
        return False
    return (
        source_url.scheme in {"http", "https"}
        and bool(source_host)
        and source_host == request_host
        and source_port == request_port
    )


def _ip_literal(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None
