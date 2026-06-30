"""Local HTTP server for the Protolink dashboard."""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from protolink.devtools.agents import chat_with_agent, ping_agent
from protolink.devtools.registry import fetch_registry_agents
from protolink.devtools.runs import build_run_replay_view, list_run_store_records
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer


def build_dashboard_snapshot(
    *,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Collect dashboard data from registry and run-store sources."""
    snapshot: dict[str, Any] = {
        "registry": {"url": registry_url, "agents": [], "error": None},
        "runs": {"store": str(store_path) if store_path else None, "tasks": [], "reports": [], "error": None},
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

    return snapshot


def serve_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    open_browser: bool = False,
) -> None:
    """Serve the local dashboard until interrupted."""
    renderer = DevtoolsHtmlRenderer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Serve dashboard HTML and JSON endpoints."""
            if self.path == "/" or self.path.startswith("/?"):
                snapshot = build_dashboard_snapshot(registry_url=registry_url, store_path=store_path)
                self._send_html(renderer.render_dashboard(snapshot))
                return
            if self.path == "/studio":
                snapshot = build_dashboard_snapshot(registry_url=registry_url, store_path=store_path)
                self._send_html(renderer.render_dashboard(snapshot, start_tab="studio"))
                return
            if self.path == "/api/snapshot":
                self._send_json(build_dashboard_snapshot(registry_url=registry_url, store_path=store_path))
                return
            if self.path.startswith("/api/runs/") and store_path is not None:
                run_id = unquote(self.path.removeprefix("/api/runs/").split("?", 1)[0])
                self._send_json(build_run_replay_view(store_path, run_id).to_dict())
                return
            self.send_error(404, "Not found")

        def do_POST(self) -> None:
            """Serve dashboard action endpoints."""
            if self.path == "/api/agents/ping":
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

            if self.path == "/api/agents/chat":
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

        def _read_json(self) -> dict[str, Any]:
            """Read a small JSON request body."""
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        def _send_html(self, html: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def _send_json(self, payload: dict[str, Any]) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))

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
