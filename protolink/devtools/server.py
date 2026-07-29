"""Local HTTP server for the Protolink dashboard."""

from __future__ import annotations

import ipaddress
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from protolink.devtools.agents import chat_with_agent, ping_agent
from protolink.devtools.registry import fetch_registry_agents
from protolink.devtools.runs import build_run_replay_view, list_run_store_records
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


def build_dashboard_snapshot(
    *,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    limit: int = 20,
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
        "registry": {"url": registry_url, "agents": [], "error": None},
        "runs": {"store": str(store_path) if store_path else None, "tasks": [], "reports": [], "error": None},
        "telemetry": telemetry,
        "studio": {"blueprint": _default_studio_blueprint()},
    }

    if registry_url:
        try:
            snapshot["registry"]["agents"] = fetch_registry_agents(registry_url, timeout=2.0)
        except Exception as exc:
            snapshot["registry"]["error"] = str(exc)

    if store_path:
        try:
            records = list_run_store_records(store_path, limit=limit)
            snapshot["runs"].update(records)
        except Exception as exc:
            snapshot["runs"]["error"] = str(exc)

    if trace_path is not None:
        try:
            snapshot["telemetry"] = list_trace_records(trace_path, limit=limit)
        except Exception as exc:
            snapshot["telemetry"]["error"] = str(exc)

    return snapshot


def serve_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    open_browser: bool = False,
) -> None:
    """Serve the local dashboard until interrupted."""
    renderer = DevtoolsHtmlRenderer()

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
                snapshot = build_dashboard_snapshot(
                    registry_url=registry_url,
                    store_path=store_path,
                    trace_path=trace_path,
                )
                self._send_html(renderer.render_dashboard(snapshot, live=True))
                return
            if path == "/studio":
                snapshot = build_dashboard_snapshot(
                    registry_url=registry_url,
                    store_path=store_path,
                    trace_path=trace_path,
                )
                self._send_html(renderer.render_dashboard(snapshot, start_tab="studio", live=True))
                return
            if path == "/api/snapshot":
                self._send_json(
                    build_dashboard_snapshot(
                        registry_url=registry_url,
                        store_path=store_path,
                        trace_path=trace_path,
                    )
                )
                return
            if path.startswith("/api/runs/") and store_path is not None:
                run_id = unquote(path.removeprefix("/api/runs/"))
                self._send_json(build_run_replay_view(store_path, run_id).to_dict())
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
    print(f"Protolink dashboard running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Protolink dashboard")
    finally:
        server.server_close()


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


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


def _default_studio_blueprint() -> dict[str, Any]:
    """Return a starter canvas blueprint used by the disabled Studio preview."""
    return {
        "nodes": [
            {"id": "agent-1", "kind": "agent", "label": "Planner", "x": 110, "y": 120},
            {"id": "llm-1", "kind": "llm", "label": "LLM", "x": 370, "y": 70},
            {"id": "tool-1", "kind": "tool", "label": "Search Tool", "x": 370, "y": 190},
        ],
        "edges": [
            {"from": "agent-1", "to": "llm-1"},
            {"from": "agent-1", "to": "tool-1"},
        ],
    }
