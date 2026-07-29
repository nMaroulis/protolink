# ruff: noqa: E501
"""Text and HTML renderers for Protolink developer tools."""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape
from typing import Any

from protolink.devtools.models import DoctorReport, RunDiffView, RunReplayView


class DevtoolsTextRenderer:
    """Render devtool data as dependency-free terminal text."""

    def render_doctor(self, report: DoctorReport) -> str:
        """Render a doctor report."""
        rows = [(check.status.upper(), check.name, check.detail) for check in report.checks]
        return "Protolink doctor: " + report.status.upper() + "\n" + _table(("STATUS", "CHECK", "DETAIL"), rows)

    def render_registry_agents(self, cards: list[dict[str, Any]]) -> str:
        """Render registered agents as a compact table."""
        rows = []
        for card in cards:
            capabilities = card.get("capabilities") or {}
            enabled = [key for key, value in capabilities.items() if value is True]
            rows.append(
                (
                    str(card.get("name") or "-"),
                    str(card.get("transport") or "-"),
                    str(card.get("url") or "-"),
                    ", ".join(enabled[:5]) or "-",
                )
            )
        if not rows:
            return "No agents found."
        return _table(("NAME", "TRANSPORT", "URL", "CAPABILITIES"), rows)

    def render_run_list(self, records: dict[str, list[dict[str, Any]]]) -> str:
        """Render recent run-store task and report records."""
        task_rows = [
            (
                str(record.get("task_id") or "-"),
                str(record.get("state") or "-"),
                str(record.get("run_id") or "-"),
                str(record.get("session_id") or "-"),
                str(record.get("updated_at") or "-"),
            )
            for record in records.get("tasks", [])
        ]
        report_rows = [
            (
                str(record.get("run_id") or "-"),
                str(record.get("session_id") or "-"),
                str(record.get("agent_name") or "-"),
                str(record.get("created_at") or "-"),
            )
            for record in records.get("reports", [])
        ]
        sections = ["Recent task snapshots", _table(("TASK", "STATE", "RUN", "SESSION", "UPDATED"), task_rows)]
        sections.extend(["", "Recent run reports", _table(("RUN", "SESSION", "AGENT", "CREATED"), report_rows)])
        return "\n".join(sections)

    def render_run_replay(self, view: RunReplayView) -> str:
        """Render a replay timeline."""
        if view.source == "missing":
            return f"Run not found: {view.run_id}"
        header = f"Run replay: {view.run_id} ({view.source})"
        rows = [
            (
                item.timestamp or "-",
                item.event_type,
                item.severity,
                item.agent_name or "-",
                item.summary,
            )
            for item in view.items
        ]
        return header + "\n" + _table(("TIME", "EVENT", "LEVEL", "AGENT", "SUMMARY"), rows)

    def render_run_diff(self, view: RunDiffView) -> str:
        """Render a normalized comparison of two stored run reports."""
        if view.status == "missing":
            label = "Run report not found" if len(view.missing_run_ids) == 1 else "Run reports not found"
            return f"{label}: {', '.join(view.missing_run_ids)}"

        header = f"Normalized run report diff: {view.baseline_run_id} -> {view.candidate_run_id}"
        if view.diff is None:  # pragma: no cover - guarded by status
            return header + "\nResult: MISSING"
        if view.diff.matches:
            return header + "\nResult: MATCH\nNo behavioral differences after normalization."

        count = len(view.diff.differences)
        label = "difference" if count == 1 else "differences"
        return header + f"\nResult: CHANGED ({count} {label})\n" + view.diff.format(max_differences=50)


class DevtoolsHtmlRenderer:
    """Render the local Protolink dashboard as self-contained HTML."""

    def render_dashboard(
        self,
        snapshot: dict[str, Any],
        *,
        start_tab: str = "dashboard",
        live: bool = False,
    ) -> str:
        """Render the dashboard shell with an embedded initial snapshot."""
        snapshot_json = _safe_json(snapshot)
        return _dashboard_html(snapshot_json, start_tab=start_tab, live=live)


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render a simple aligned table."""
    if not rows:
        return "(none)"
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    header_line = "  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))
    sep = "  ".join("-" * width for width in widths)
    body = ["  ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)) for row in rows]
    return "\n".join([header_line, sep, *body])


def _safe_json(data: dict[str, Any]) -> str:
    """Serialize JSON safely for embedding in a script tag."""
    return json.dumps(data).replace("</", "<\\/")


def _default_blueprint() -> dict[str, Any]:
    """Return the default blueprint used by the disabled Studio preview."""
    return {
        "nodes": [
            {"id": "agent-1", "kind": "agent", "label": "Planner", "x": 110, "y": 120},
            {"id": "llm-1", "kind": "llm", "label": "LLM", "x": 370, "y": 70},
            {"id": "tool-1", "kind": "tool", "label": "Search Tool", "x": 370, "y": 190},
        ],
        "edges": [{"from": "agent-1", "to": "llm-1"}, {"from": "agent-1", "to": "tool-1"}],
    }


def _dashboard_html(
    snapshot_json: str,
    *,
    start_tab: str = "dashboard",
    title: str = "Protolink Dashboard",
    live: bool = False,
) -> str:
    """Return the dashboard HTML document."""
    safe_title = escape(title)
    safe_start_tab = (
        start_tab if start_tab in {"dashboard", "runs", "telemetry", "registry", "chat", "studio"} else "dashboard"
    )
    return (
        _DASHBOARD_TEMPLATE.replace("__PROTOLINK_TITLE__", safe_title)
        .replace("__PROTOLINK_SNAPSHOT_JSON__", snapshot_json)
        .replace("__PROTOLINK_START_TAB_VALUE__", safe_start_tab)
        .replace("__PROTOLINK_LIVE_VALUE__", "true" if live else "false")
    )


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__PROTOLINK_TITLE__</title>
<style>
:root {
  --bg: #f5f7fb;
  --ink: #18212f;
  --muted: #697386;
  --line: #d7deea;
  --panel: #ffffff;
  --panel-2: #f8fafc;
  --nav: #111827;
  --teal: #0f9f92;
  --teal-soft: #dff6f2;
  --coral: #d65b48;
  --coral-soft: #fde9e4;
  --amber: #bd7d11;
  --amber-soft: #fff3cf;
  --indigo: #5665d8;
  --indigo-soft: #e8ebff;
  --green: #248a57;
  --green-soft: #ddf7ea;
  --shadow: 0 16px 42px rgba(24, 33, 47, .10);
  --shadow-soft: 0 8px 22px rgba(24, 33, 47, .08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    linear-gradient(180deg, #eaf0f7 0%, #f7fafc 34%, var(--bg) 100%),
    linear-gradient(90deg, rgba(15,159,146,.06) 0, rgba(86,101,216,.04) 48%, rgba(214,91,72,.05) 100%);
  color: var(--ink);
  font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
button, input, select, textarea { font: inherit; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible { outline: 3px solid rgba(15,159,146,.22); outline-offset: 2px; }
.shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; min-width: 0; }
.side { background: var(--nav); color: #f8fafc; padding: 22px 18px; display: flex; flex-direction: column; gap: 20px; border-right: 1px solid rgba(255,255,255,.08); min-width: 0; }
.brand-card { width: 100%; display: flex; align-items: center; gap: 11px; text-align: left; border: 0; border-radius: 0; padding: 3px 0; color: #f8fafc; background: transparent; cursor: pointer; transition: transform .18s ease, color .18s ease; }
.brand-card:hover { transform: translateX(2px); color: #fff; }
.brand-logo { width: 38px; height: 38px; display: grid; place-items: center; background: transparent; border: 0; box-shadow: none; flex: 0 0 auto; }
.brand-logo img { width: 32px; height: 32px; object-fit: contain; border-radius: 6px; transition: transform .18s ease, filter .18s ease; filter: drop-shadow(0 8px 12px rgba(0,0,0,.22)); }
.brand-card:hover .brand-logo img { transform: rotate(-4deg) scale(1.08); filter: drop-shadow(0 10px 16px rgba(15,159,146,.28)); }
.brand { font-size: 20px; font-weight: 780; letter-spacing: 0; }
.sub { display: block; color: #bac5d4; font-size: 12px; margin-top: 2px; }
.side-meta { display: grid; gap: 8px; padding: 12px; border: 1px solid rgba(255,255,255,.10); border-radius: 8px; background: rgba(255,255,255,.05); }
.side-meta span { color: #c7d2e0; font-size: 12px; overflow-wrap: anywhere; }
.nav { display: grid; gap: 7px; }
.nav button { text-align: left; border: 0; border-radius: 8px; padding: 10px 12px; color: #dbe4ef; background: transparent; cursor: pointer; display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 40px; }
.nav button:hover { background: rgba(255,255,255,.08); }
.nav button.active { color: #fff; background: rgba(15,159,146,.26); box-shadow: inset 3px 0 0 var(--teal); }
.soon-mini { font-size: 10px; color: #fff; background: rgba(189,125,17,.95); border-radius: 999px; padding: 2px 6px; }
.side-foot { margin-top: auto; color: #bac5d4; font-size: 12px; line-height: 1.5; display: grid; gap: 8px; }
.side-version { color: #8795a8; font: 10px/1.3 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; letter-spacing: .03em; }
.main { padding: 24px; overflow: auto; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 18px; }
.kicker { margin: 0 0 4px; color: var(--teal); font-size: 12px; font-weight: 760; text-transform: uppercase; letter-spacing: .06em; }
h1 { margin: 0; font-size: 26px; letter-spacing: 0; }
.lede { margin: 6px 0 0; max-width: 740px; color: var(--muted); }
.actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.btn, .mini-btn { border: 1px solid var(--line); background: var(--panel); border-radius: 8px; cursor: pointer; color: var(--ink); text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 34px; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease, background .16s ease; }
.btn { padding: 8px 11px; box-shadow: var(--shadow-soft); }
.mini-btn { min-height: 28px; padding: 4px 8px; font-size: 12px; box-shadow: none; }
.btn:hover, .mini-btn:hover { border-color: rgba(15,159,146,.42); box-shadow: 0 0 0 3px rgba(15,159,146,.10); transform: translateY(-1px); }
.btn.primary, .mini-btn.primary { background: linear-gradient(135deg, var(--teal), #167fbc); border-color: rgba(15,159,146,.88); color: #fff; }
.btn:disabled, .mini-btn:disabled { opacity: .48; cursor: not-allowed; box-shadow: none; }
.btn:disabled:hover, .mini-btn:disabled:hover { transform: none; border-color: var(--line); }
.icon { width: 16px; height: 16px; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; fill: none; flex: 0 0 auto; }
.mini-btn .icon { width: 14px; height: 14px; }
.nav .icon { width: 15px; height: 15px; color: #b9c7da; }
.nav-label { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.icon-muted { color: var(--muted); }
.alerts { display: grid; gap: 8px; margin-bottom: 14px; }
.alert { border: 1px solid var(--amber); background: var(--amber-soft); color: #6d4608; border-radius: 8px; padding: 10px 12px; }
.grid { display: grid; grid-template-columns: repeat(5, minmax(145px, 1fr)); gap: 12px; margin-bottom: 16px; }
.metric { width: 100%; text-align: left; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; box-shadow: var(--shadow-soft); min-height: 104px; position: relative; overflow: hidden; cursor: pointer; color: var(--ink); transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease; }
.metric::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--teal); }
.metric[data-accent="indigo"]::before { background: var(--indigo); }
.metric[data-accent="amber"]::before { background: var(--amber); }
.metric[data-accent="coral"]::before { background: var(--coral); }
.metric:hover { transform: translateY(-2px); border-color: rgba(15,159,146,.38); box-shadow: 0 16px 34px rgba(24,33,47,.12); }
.metric-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.metric-icon { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; color: var(--teal); background: var(--teal-soft); border: 1px solid rgba(15,159,146,.14); }
.metric[data-accent="indigo"] .metric-icon { color: var(--indigo); background: var(--indigo-soft); border-color: rgba(86,101,216,.14); }
.metric[data-accent="amber"] .metric-icon { color: var(--amber); background: var(--amber-soft); border-color: rgba(189,125,17,.18); }
.metric[data-accent="coral"] .metric-icon { color: var(--coral); background: var(--coral-soft); border-color: rgba(214,91,72,.18); }
.metric .label { color: var(--muted); font-size: 12px; }
.metric .value { font-size: 30px; font-weight: 800; margin-top: 4px; letter-spacing: 0; overflow-wrap: anywhere; }
.metric .hint { color: var(--muted); font-size: 12px; margin-top: 4px; overflow-wrap: anywhere; }
.store-state { display: inline-flex; align-items: center; gap: 8px; font-size: 24px; font-weight: 820; letter-spacing: 0; }
.store-state.on { color: var(--green); }
.store-state.off { color: var(--coral); }
.dashboard-stack { display: grid; gap: 14px; }
.bands { display: grid; grid-template-columns: minmax(360px, 1fr) minmax(360px, 1fr); gap: 14px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); overflow: hidden; }
.panel + .panel { margin-top: 14px; }
.panel h2 { margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line); font-size: 15px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.panel-body { padding: 14px 16px; }
.panel-note { padding: 10px 16px; color: var(--muted); font-size: 13px; border-bottom: 1px solid #edf1f6; background: linear-gradient(90deg, #fbfcfe, #f5fbfa); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; border-bottom: 1px solid #edf1f6; text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; background: #fbfcfe; }
td { font-size: 13px; overflow-wrap: anywhere; }
.pill { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 2px 8px; font-size: 12px; border: 1px solid var(--line); background: var(--panel-2); font-weight: 650; white-space: nowrap; }
.pill.ok { color: var(--green); background: var(--green-soft); border-color: rgba(36,138,87,.18); }
.pill.warn { color: var(--amber); background: var(--amber-soft); border-color: rgba(189,125,17,.22); }
.pill.error { color: var(--coral); background: var(--coral-soft); border-color: rgba(214,91,72,.20); }
.pill.idle { color: var(--muted); }
.pill.capability-badge { color: var(--indigo); background: var(--indigo-soft); border-color: rgba(86,101,216,.22); }
.badge-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; min-width: 160px; }
.transport-badge { display: inline-flex; align-items: center; gap: 7px; border-radius: 999px; padding: 3px 9px; font-size: 12px; font-weight: 760; border: 1px solid #d8dee8; background: #eef2f7; color: #586272; white-space: nowrap; text-transform: uppercase; letter-spacing: .02em; }
.transport-badge.unknown { color: #697386; background: #f5f7fa; }
.status-dot { width: 8px; height: 8px; border-radius: 999px; display: inline-block; flex: 0 0 auto; background: #9aa5b5; box-shadow: 0 0 0 3px rgba(154,165,181,.16); }
.status-dot.online { background: var(--green); box-shadow: 0 0 0 3px rgba(36,138,87,.15), 0 0 12px rgba(36,138,87,.28); }
.status-dot.offline { background: var(--coral); box-shadow: 0 0 0 3px rgba(214,91,72,.15); }
.status-dot.pending { background: var(--amber); box-shadow: 0 0 0 3px rgba(189,125,17,.15); animation: pulseDot 1.15s ease-in-out infinite; }
.status-dot.runtime { background: var(--indigo); box-shadow: 0 0 0 3px rgba(86,101,216,.14); }
.status-dot.unknown { background: #98a2b3; box-shadow: 0 0 0 3px rgba(105,115,134,.14); }
@keyframes pulseDot { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(.72); opacity: .62; } }
.health-cell { display: inline-flex; align-items: center; gap: 8px; min-width: max-content; }
.agent-cell { display: flex; align-items: center; gap: 10px; min-width: 180px; }
.agent-avatar { width: 34px; height: 34px; border-radius: 8px; background: linear-gradient(135deg, var(--teal-soft), var(--indigo-soft)); border: 1px solid rgba(15,159,146,.18); color: var(--ink); font-weight: 820; display: inline-flex; align-items: center; justify-content: center; box-shadow: 0 7px 16px rgba(24,33,47,.08); flex: 0 0 auto; }
.agent-avatar.small { width: 28px; height: 28px; font-size: 12px; border-radius: 8px; }
.agent-main { display: grid; gap: 2px; min-width: 0; }
.agent-name { font-weight: 760; overflow-wrap: anywhere; }
.agent-meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; display: flex; align-items: center; gap: 6px; }
.online-summary { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.detail-item { border: 1px solid var(--line); background: var(--panel-2); border-radius: 8px; padding: 10px 12px; }
.detail-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 2px; }
.detail-value { font-weight: 700; overflow-wrap: anywhere; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.agent-detail-shell { display: grid; gap: 14px; }
.agent-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 14px; border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: linear-gradient(135deg, #ffffff 0%, #f7fbff 62%, #f2fbf9 100%); box-shadow: var(--shadow-soft); }
.agent-hero-main { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.agent-hero h3 { margin: 0; font-size: 18px; line-height: 1.2; overflow-wrap: anywhere; }
.agent-hero p { margin: 5px 0 0; color: var(--muted); max-width: 760px; }
.agent-hero-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.agent-stat-grid { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 10px; }
.agent-stat { border: 1px solid var(--line); background: var(--panel-2); border-radius: 8px; padding: 10px 12px; min-height: 72px; }
.agent-stat .detail-value { font-size: 15px; }
.schema-grid { display: grid; grid-template-columns: repeat(2, minmax(260px, 1fr)); gap: 10px; }
.schema-card { border: 1px solid var(--line); background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 6px 18px rgba(24,33,47,.05); }
.schema-head { padding: 10px 12px; border-bottom: 1px solid #edf1f6; display: flex; align-items: center; justify-content: space-between; gap: 10px; background: #fbfcfe; }
.schema-title { display: grid; gap: 2px; min-width: 0; }
.schema-title strong { overflow-wrap: anywhere; }
.schema-title span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.schema-body { padding: 10px 12px; display: grid; gap: 10px; }
.schema-pre { margin: 0; white-space: pre-wrap; overflow: auto; max-height: 210px; border: 1px solid #e3e9f2; border-radius: 8px; background: #111827; color: #e5e7eb; padding: 10px; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.empty-muted { color: var(--muted); font-size: 13px; border: 1px dashed #cfd8e5; border-radius: 8px; padding: 10px; background: #fbfcfe; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 2px 0 8px; }
.section-title h3 { margin: 0; font-size: 14px; }
.view { display: none; }
.view.active { display: block; }
.chat-layout { display: grid; grid-template-columns: minmax(300px, 380px) minmax(0, 1fr); gap: 16px; align-items: stretch; }
.chat-sidebar { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); padding: 14px; display: grid; gap: 12px; align-content: start; }
.chat-agent-card { border: 1px solid var(--line); background: linear-gradient(180deg, #fff, #f8fbff); border-radius: 8px; padding: 13px; display: grid; gap: 10px; }
.chat-agent-card .detail-item { background: #fff; }
.chat-box { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); display: grid; grid-template-rows: auto auto 1fr auto; min-height: 680px; overflow: hidden; position: relative; }
.chat-head { padding: 15px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; background: linear-gradient(180deg, #fff, #f9fbff); }
.chat-title-wrap { display: flex; align-items: center; gap: 10px; min-width: 0; }
.chat-title-main { display: grid; gap: 2px; min-width: 0; }
.chat-title-main strong { overflow-wrap: anywhere; }
.chat-title-main span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.chat-head-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.debug-panel { display: none; border-bottom: 1px solid var(--line); background: linear-gradient(135deg, rgba(232,235,255,.65), rgba(223,246,242,.58)); padding: 12px 16px; }
.debug-panel.visible { display: block; }
.debug-grid { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; }
.debug-item { border: 1px solid rgba(86,101,216,.16); background: rgba(255,255,255,.78); border-radius: 8px; padding: 9px 10px; box-shadow: 0 7px 16px rgba(24,33,47,.05); }
.debug-label { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 2px; }
.debug-value { font-weight: 760; overflow-wrap: anywhere; }
.debug-value.warn { color: var(--amber); }
.debug-value.error { color: var(--coral); }
.messages { padding: 22px; overflow: auto; background: radial-gradient(circle at top left, rgba(15,159,146,.08), transparent 34%), radial-gradient(circle at bottom right, rgba(86,101,216,.07), transparent 28%), linear-gradient(180deg, #fbfcfe 0%, #f3f7fb 100%); display: flex; flex-direction: column; gap: 14px; scroll-behavior: smooth; }
.messages::-webkit-scrollbar { width: 8px; }
.messages::-webkit-scrollbar-thumb { background: #cdd7e6; border-radius: 999px; border: 2px solid #f5f8fb; }
.msg { display: flex; align-items: flex-end; gap: 10px; max-width: min(720px, 84%); animation: msgIn .22s ease-out; }
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
.msg.user { align-self: flex-end; flex-direction: row-reverse; }
.msg.agent, .msg.system { align-self: flex-start; }
.msg-avatar { width: 30px; height: 30px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; font-weight: 780; font-size: 12px; flex: 0 0 auto; border: 1px solid var(--line); background: #fff; box-shadow: 0 4px 14px rgba(24,33,47,.06); }
.msg.user .msg-avatar { background: linear-gradient(135deg, var(--teal), #167fbc); color: #fff; border-color: rgba(15,159,146,.5); }
.msg.agent .msg-avatar { color: var(--indigo); background: var(--indigo-soft); border-color: rgba(86,101,216,.18); }
.msg.system .msg-avatar { color: var(--amber); background: var(--amber-soft); border-color: rgba(189,125,17,.22); }
.msg-body { display: grid; gap: 4px; min-width: 0; max-width: 100%; }
.bubble { border: 1px solid var(--line); border-radius: 8px 8px 8px 3px; padding: 12px 14px; background: rgba(255,255,255,.96); white-space: pre-wrap; box-shadow: 0 5px 18px rgba(24,33,47,.06); line-height: 1.55; overflow-wrap: anywhere; }
.msg.user .bubble { background: linear-gradient(135deg, var(--teal), #167fbc); color: #fff; border-color: rgba(15,159,146,.72); border-radius: 8px 8px 3px 8px; }
.msg.system .bubble { background: var(--amber-soft); border-color: rgba(189,125,17,.26); color: #6d4608; }
.msg.pending .bubble { color: var(--muted); }
.msg-meta { color: var(--muted); font-size: 11px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 0 2px; }
.typing-dots { display: inline-flex; gap: 4px; align-items: center; }
.typing-dots span { width: 5px; height: 5px; border-radius: 999px; background: currentColor; opacity: .42; animation: dotPulse 1.1s ease-in-out infinite; }
.typing-dots span:nth-child(2) { animation-delay: .14s; }
.typing-dots span:nth-child(3) { animation-delay: .28s; }
@keyframes dotPulse { 0%, 100% { transform: translateY(0); opacity: .35; } 50% { transform: translateY(-3px); opacity: .9; } }
.chat-compose { border-top: 1px solid var(--line); padding: 14px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: end; background: rgba(255,255,255,.82); }
.chat-input-wrap { border: 1px solid var(--line); border-radius: 8px; background: #fff; display: grid; gap: 6px; padding: 9px 10px 7px; box-shadow: inset 0 1px 0 rgba(255,255,255,.75); transition: border-color .16s ease, box-shadow .16s ease; }
.chat-input-wrap:focus-within { border-color: rgba(15,159,146,.46); box-shadow: 0 0 0 3px rgba(15,159,146,.11); }
.chat-compose textarea { width: 100%; min-height: 46px; max-height: 150px; resize: none; border: 0; outline: 0; padding: 0; background: transparent; line-height: 1.45; }
.compose-meta { color: var(--muted); font-size: 11px; display: flex; justify-content: space-between; gap: 10px; }
.compose-meta span { overflow-wrap: anywhere; }
.field { display: grid; gap: 5px; }
.field label { color: var(--muted); font-size: 12px; }
.field input, .field select { border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: #fff; min-width: 0; }
.source-connect {
  margin-bottom: 14px; border: 1px solid var(--line); border-radius: 10px; padding: 13px 14px;
  background: linear-gradient(110deg, rgba(255,255,255,.96), rgba(223,246,242,.58), rgba(232,235,255,.52));
  box-shadow: var(--shadow-soft); display: grid; grid-template-columns: minmax(230px, .8fr) minmax(320px, 1.2fr); gap: 14px; align-items: center;
}
.source-connect-copy { display: flex; align-items: center; gap: 10px; min-width: 0; }
.source-connect-mark { width: 38px; height: 38px; border-radius: 9px; display: grid; place-items: center; flex: 0 0 auto; color: var(--teal); background: #fff; border: 1px solid rgba(15,159,146,.20); }
.source-connect-text { display: grid; gap: 2px; min-width: 0; }
.source-connect-text strong, .source-connect-text span { overflow-wrap: anywhere; }
.source-connect-text span { color: var(--muted); font-size: 12px; }
.source-connect-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.source-connect-form input { width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; background: rgba(255,255,255,.96); }
.source-feedback { grid-column: 1 / -1; min-height: 15px; color: var(--muted); font-size: 11px; }
.source-feedback.error { color: var(--coral); }
.source-feedback.ok { color: var(--green); }
.runs-overview { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 10px; margin-bottom: 14px; }
.run-overview-card { position: relative; overflow: hidden; border: 1px solid var(--line); border-radius: 9px; padding: 12px 13px; background: rgba(255,255,255,.94); box-shadow: var(--shadow-soft); }
.run-overview-card::after { content: ""; position: absolute; inset: auto -22px -30px auto; width: 74px; height: 74px; border-radius: 999px; background: rgba(86,101,216,.08); }
.run-overview-card:nth-child(2)::after { background: rgba(15,159,146,.09); }
.run-overview-card:nth-child(3)::after { background: rgba(189,125,17,.10); }
.run-overview-card:nth-child(4)::after { background: rgba(214,91,72,.09); }
.run-overview-card span { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .045em; }
.run-overview-card strong { display: block; margin-top: 3px; font-size: 23px; line-height: 1.1; }
.runs-layout { display: grid; grid-template-columns: minmax(300px, 370px) minmax(0, 1fr); gap: 14px; align-items: start; }
.run-browser { min-height: 610px; display: grid; grid-template-rows: auto minmax(0, 1fr); }
.run-browser-head { padding: 12px; border-bottom: 1px solid var(--line); display: grid; grid-template-columns: minmax(0, 1fr) 105px; gap: 8px; background: linear-gradient(180deg, #fff, #f8fbfe); }
.run-browser-head input, .run-browser-head select { width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 8px 9px; }
.run-record-list { overflow: auto; max-height: 690px; padding: 7px; display: grid; align-content: start; gap: 6px; }
.run-record {
  appearance: none; width: 100%; border: 1px solid transparent; border-left: 3px solid transparent; border-radius: 8px; padding: 10px;
  background: transparent; color: var(--ink); text-align: left; cursor: pointer; display: grid; gap: 7px; transition: background .14s ease, border-color .14s ease;
}
.run-record:hover { background: #f7fafc; border-color: #e4eaf2; }
.run-record.active { background: linear-gradient(90deg, rgba(232,235,255,.68), rgba(223,246,242,.38)); border-color: rgba(86,101,216,.18); border-left-color: var(--indigo); }
.run-record-top, .run-record-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
.run-record-id { font: 12px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 720; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-record-meta { color: var(--muted); font-size: 11px; }
.run-record-agent { display: flex; align-items: center; gap: 7px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-record-agent .agent-avatar { width: 25px; height: 25px; border-radius: 7px; font-size: 9px; box-shadow: none; }
.run-replay-shell { min-height: 610px; }
.run-replay-empty { min-height: 430px; display: grid; place-items: center; padding: 40px 24px; text-align: center; background: radial-gradient(circle at 20% 20%, rgba(86,101,216,.08), transparent 30%), radial-gradient(circle at 85% 80%, rgba(15,159,146,.08), transparent 30%); }
.run-replay-empty > div { max-width: 440px; }
.run-replay-empty h3 { margin: 8px 0 5px; font-size: 20px; }
.run-replay-empty p { margin: 0; color: var(--muted); }
.run-replay-hero { padding: 15px 16px; border-bottom: 1px solid var(--line); background: linear-gradient(120deg, #fff, #f3f5ff 55%, #f0fbf8); display: grid; gap: 12px; }
.run-replay-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.run-replay-title h3 { margin: 0; font-size: 18px; overflow-wrap: anywhere; }
.run-replay-title p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.run-replay-facts { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 8px; }
.run-replay-fact { border: 1px solid rgba(86,101,216,.13); border-radius: 8px; padding: 8px 10px; background: rgba(255,255,255,.78); min-width: 0; }
.run-replay-fact strong { display: block; margin-top: 2px; overflow-wrap: anywhere; }
.run-timeline { padding: 14px 16px 18px; display: grid; gap: 0; }
.run-event { position: relative; display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 10px; padding-bottom: 14px; }
.run-event:last-child { padding-bottom: 0; }
.run-event-rail { position: relative; display: flex; justify-content: center; }
.run-event-rail::after { content: ""; position: absolute; top: 22px; bottom: -14px; width: 1px; background: #dbe2ec; }
.run-event:last-child .run-event-rail::after { display: none; }
.run-event-dot { width: 20px; height: 20px; border-radius: 999px; display: grid; place-items: center; background: var(--indigo-soft); border: 1px solid rgba(86,101,216,.24); color: var(--indigo); font-size: 9px; font-weight: 800; z-index: 1; }
.run-event.error .run-event-dot { color: var(--coral); background: var(--coral-soft); border-color: rgba(214,91,72,.24); }
.run-event.warn .run-event-dot { color: var(--amber); background: var(--amber-soft); border-color: rgba(189,125,17,.24); }
.run-event-card { border: 1px solid #e3e9f2; border-radius: 8px; padding: 10px 11px; background: #fff; min-width: 0; }
.run-event-card strong { display: block; overflow-wrap: anywhere; }
.run-event-card p { margin: 3px 0 0; color: var(--muted); overflow-wrap: anywhere; }
.run-event-meta { margin-top: 7px; color: var(--muted); font-size: 11px; display: flex; flex-wrap: wrap; gap: 8px; }
.telemetry-drop {
  margin-bottom: 14px; border: 1px dashed #b9c6d8; border-radius: 10px; padding: 12px 14px;
  background: linear-gradient(110deg, rgba(223,246,242,.74), rgba(232,235,255,.64), rgba(255,255,255,.92));
  display: flex; align-items: center; justify-content: space-between; gap: 14px; transition: border-color .16s ease, transform .16s ease, box-shadow .16s ease;
}
.telemetry-drop.dragging { border-color: var(--teal); transform: translateY(-1px); box-shadow: 0 0 0 4px rgba(15,159,146,.10); }
.telemetry-source { display: flex; align-items: center; gap: 10px; min-width: 0; }
.telemetry-source-mark { width: 38px; height: 38px; border-radius: 9px; display: grid; place-items: center; flex: 0 0 auto; color: var(--teal); background: #fff; border: 1px solid rgba(15,159,146,.20); box-shadow: var(--shadow-soft); }
.telemetry-source-copy { display: grid; gap: 2px; min-width: 0; }
.telemetry-source-copy strong, .telemetry-source-copy span { overflow-wrap: anywhere; }
.telemetry-source-copy span { color: var(--muted); font-size: 12px; }
.telemetry-source-meta { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.telemetry-grid { display: grid; grid-template-columns: minmax(290px, 360px) minmax(0, 1fr); gap: 14px; align-items: start; }
.trace-browser { min-height: 720px; display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; }
.trace-browser-head { padding: 13px 14px; border-bottom: 1px solid var(--line); display: grid; gap: 10px; background: linear-gradient(180deg, #fff, #f8fbfe); }
.trace-browser-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.trace-browser-title h2 { border: 0; padding: 0; }
.trace-filters { display: grid; grid-template-columns: minmax(0, 1fr) 112px; gap: 7px; }
.trace-filters input, .trace-filters select {
  width: 100%; min-width: 0; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 8px 9px;
}
.trace-window-note { padding: 8px 13px; color: var(--muted); font-size: 11px; border-bottom: 1px solid #edf1f6; background: #fbfcfe; }
.trace-list { overflow: auto; max-height: 610px; scrollbar-color: #cbd5e1 transparent; }
.trace-group + .trace-group { border-top: 4px solid #eef2f7; }
.trace-group-head { padding: 8px 13px; display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--muted); background: linear-gradient(90deg, #f7fafc, #fbfcff); border-bottom: 1px solid #e8edf4; font-size: 10px; text-transform: uppercase; letter-spacing: .045em; }
.trace-group-head code { color: var(--indigo); font: 10px/1.3 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; text-transform: none; letter-spacing: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-record {
  width: 100%; border: 0; border-bottom: 1px solid #edf1f6; padding: 12px 13px; background: #fff; color: var(--ink);
  text-align: left; cursor: pointer; display: grid; gap: 7px; transition: background .14s ease, box-shadow .14s ease;
}
.trace-record:hover { background: #f8fbfe; }
.trace-record.active { background: linear-gradient(90deg, var(--teal-soft), #f6f8ff 76%); box-shadow: inset 3px 0 0 var(--teal); }
.trace-record-top, .trace-record-bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.trace-agent { font-weight: 780; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-record-id { color: var(--muted); font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-record-bottom { color: var(--muted); font-size: 11px; }
.trace-browser-foot { padding: 10px 12px; border-top: 1px solid var(--line); background: #fbfcfe; }
.trace-browser-foot .btn { width: 100%; }
.trace-workbench { display: grid; gap: 14px; min-width: 0; }
.trace-empty {
  min-height: 420px; padding: 48px 24px; border: 1px dashed #c7d2e0; border-radius: 10px; background:
  radial-gradient(circle at 15% 10%, rgba(15,159,146,.10), transparent 28%),
  radial-gradient(circle at 90% 90%, rgba(86,101,216,.09), transparent 32%), #fff;
  display: grid; place-items: center; text-align: center;
}
.trace-empty-inner { max-width: 480px; }
.trace-empty-icon { width: 52px; height: 52px; margin: 0 auto 14px; border-radius: 14px; display: grid; place-items: center; color: var(--indigo); background: var(--indigo-soft); border: 1px solid rgba(86,101,216,.18); }
.trace-empty h2 { margin: 0 0 7px; font-size: 21px; }
.trace-empty p { margin: 0; color: var(--muted); }
.trace-hero { overflow: visible; }
.trace-hero-head { padding: 15px 16px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 14px; align-items: start; background: linear-gradient(120deg, #fff 10%, #f2fbf9 54%, #f3f5ff); }
.trace-hero-title { display: flex; align-items: flex-start; gap: 11px; min-width: 0; }
.trace-kind-mark { width: 38px; height: 38px; border-radius: 9px; display: grid; place-items: center; color: var(--teal); background: var(--teal-soft); border: 1px solid rgba(15,159,146,.18); flex: 0 0 auto; }
.trace-hero-title h2 { margin: 0; padding: 0; border: 0; font-size: 18px; display: block; overflow-wrap: anywhere; }
.trace-hero-title p { margin: 3px 0 0; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.trace-hero-badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.trace-stats { display: grid; grid-template-columns: repeat(5, minmax(112px, 1fr)); gap: 0; border-top: 1px solid var(--line); }
.trace-stat { padding: 11px 13px; border-right: 1px solid #edf1f6; background: rgba(255,255,255,.82); }
.trace-stat:last-child { border-right: 0; }
.trace-stat strong { display: block; margin-top: 2px; font-size: 15px; overflow-wrap: anywhere; }
.trace-waterfall { padding: 12px 14px 15px; overflow-x: auto; }
.waterfall-inner { --span-label-column: 210px; min-width: 720px; }
.waterfall-scale, .span-row { display: grid; grid-template-columns: var(--span-label-column) minmax(460px, 1fr); gap: 12px; }
.waterfall-scale { align-items: end; padding: 0 8px 7px; border: 1px solid transparent; color: var(--muted); font-size: 10px; }
.waterfall-scale-ticks { grid-column: 2; display: flex; justify-content: space-between; min-width: 0; font-variant-numeric: tabular-nums; }
.span-row {
  appearance: none; position: relative; width: 100%; align-items: center; padding: 6px 8px; border: 1px solid transparent;
  border-radius: 7px; background: transparent; color: inherit; text-align: left; cursor: pointer;
  transition: background .13s ease, border-color .13s ease;
}
.span-row::before { content: ""; position: absolute; left: 2px; top: 7px; bottom: 7px; width: 3px; border-radius: 999px; background: var(--teal); opacity: 0; }
.span-row:hover { background: #f6f9fc; border-color: #e6ebf2; }
.span-row.active { background: linear-gradient(90deg, rgba(223,246,242,.72), rgba(232,235,255,.34)); border-color: rgba(15,159,146,.18); }
.span-row.active::before { opacity: 1; }
.span-row.active .span-name { color: #116d65; }
.span-label { min-width: 0; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 7px; padding-left: calc(var(--depth, 0) * 10px); }
.span-kind-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--teal); }
.span-kind-dot.llm { background: var(--indigo); }
.span-kind-dot.tool { background: var(--amber); }
.span-kind-dot.agent-call { background: var(--coral); }
.span-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; font-size: 12px; }
.span-duration { color: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.span-track { position: relative; height: 21px; border-radius: 6px; background:
  linear-gradient(90deg, rgba(215,222,234,.48) 1px, transparent 1px); background-size: 25% 100%; overflow: hidden; }
.span-bar { position: absolute; min-width: 4px; height: 11px; top: 5px; border-radius: 999px; background: linear-gradient(90deg, var(--teal), #2cc6b9); }
.span-bar.llm { background: linear-gradient(90deg, var(--indigo), #8c96ef); }
.span-bar.tool { background: linear-gradient(90deg, var(--amber), #e9af42); }
.span-bar.agent-call { background: linear-gradient(90deg, var(--coral), #ef8e7d); }
.span-bar.error { background: repeating-linear-gradient(135deg, var(--coral), var(--coral) 5px, #f69b8d 5px, #f69b8d 9px); }
.span-bar.open { border: 1px dashed rgba(189,125,17,.9); background: rgba(255,243,207,.92); }
.trace-limit-note { margin-top: 9px; color: var(--muted); font-size: 11px; }
.replay-controls { padding: 11px 13px; border-bottom: 1px solid var(--line); display: grid; grid-template-columns: auto auto auto minmax(120px, 1fr) auto auto; align-items: center; gap: 8px; background: linear-gradient(90deg, #fbfcfe, #f3faf9); }
.replay-controls input[type="range"] { width: 100%; accent-color: var(--teal); }
.replay-controls select { border: 1px solid var(--line); border-radius: 7px; padding: 5px 7px; background: #fff; }
.event-stage { padding: 15px 16px; display: grid; grid-template-columns: minmax(0, 1fr) 230px; gap: 14px; min-height: 180px; }
.event-focus { border-left: 3px solid var(--indigo); padding: 4px 0 4px 14px; min-width: 0; }
.event-focus.error { border-left-color: var(--coral); }
.event-focus-kicker { color: var(--teal); font-size: 10px; font-weight: 780; letter-spacing: .06em; text-transform: uppercase; }
.event-focus h3 { margin: 5px 0 7px; font-size: 18px; overflow-wrap: anywhere; }
.event-focus p { margin: 0; color: var(--muted); }
.event-payload-preview { margin: 11px 0 0; max-height: 130px; overflow: auto; white-space: pre-wrap; border-radius: 8px; background: #111827; color: #dbe7f5; padding: 10px; font: 11px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.event-rail { display: grid; align-content: center; gap: 6px; max-height: 160px; overflow: auto; padding-right: 4px; }
.event-rail button { border: 0; background: transparent; color: var(--muted); text-align: left; cursor: pointer; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 7px; align-items: center; padding: 4px 6px; border-radius: 6px; font-size: 11px; }
.event-rail button:hover, .event-rail button.active { background: var(--indigo-soft); color: var(--ink); }
.event-dot { width: 7px; height: 7px; border-radius: 999px; background: #aab5c4; }
.event-rail button.active .event-dot { background: var(--indigo); box-shadow: 0 0 0 3px rgba(86,101,216,.12); }
.inspector-tabs { padding: 10px 12px 0; display: flex; gap: 6px; flex-wrap: wrap; }
.inspector-tab { border: 1px solid var(--line); border-radius: 999px; background: #fff; color: var(--muted); padding: 4px 9px; cursor: pointer; font-size: 11px; }
.inspector-tab.active { color: var(--indigo); background: var(--indigo-soft); border-color: rgba(86,101,216,.22); font-weight: 740; }
.inspector-body { padding: 12px; }
.inspector-json { margin: 0; max-height: 360px; overflow: auto; white-space: pre-wrap; border: 1px solid #253247; border-radius: 8px; background: #111827; color: #dbe7f5; padding: 12px; font: 11px/1.48 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
}
.studio-layout { display: grid; grid-template-columns: 220px 1fr 280px; gap: 12px; min-height: 660px; }
.palette, .props { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; box-shadow: var(--shadow); opacity: .68; }
.palette h2, .props h2 { font-size: 14px; margin: 0 0 10px; }
.palette .btn { width: 100%; margin-bottom: 8px; text-align: left; justify-content: flex-start; }
.canvas-wrap { position: relative; background: #edf1f5; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; box-shadow: var(--shadow); }
.canvas { position: relative; min-height: 660px; background-image: linear-gradient(#dce4ee 1px, transparent 1px), linear-gradient(90deg, #dce4ee 1px, transparent 1px); background-size: 32px 32px; }
.edge-layer { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.node { position: absolute; width: 165px; min-height: 72px; border-radius: 8px; border: 1px solid var(--line); background: #fff; box-shadow: 0 10px 24px rgba(23,32,42,.13); user-select: none; z-index: 1;}
.node .kind { padding: 7px 9px 0; font-size: 11px; color: var(--muted); text-transform: uppercase; }
.node .label { padding: 2px 9px 10px; font-weight: 740; }
.node.agent { border-top: 4px solid var(--teal); }
.node.llm { border-top: 4px solid var(--indigo); }
.node.tool { border-top: 4px solid var(--coral); }
.node.registry { border-top: 4px solid var(--amber); }
.studio-muted { pointer-events: none; filter: saturate(.78); opacity: .66; }
.studio-lock { position: absolute; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(245,247,251,.42); backdrop-filter: blur(1.2px); z-index: 1000;}
.studio-lock-inner { max-width: 460px; text-align: center; border: 1px solid rgba(15,159,146,.28); background: rgba(255,255,255,.96); border-radius: 8px; padding: 24px; box-shadow: 0 28px 80px rgba(24,33,47,.26), 0 0 0 1px rgba(255,255,255,.82), 0 0 0 9999px rgba(255,255,255,.18); z-index: 1001;}
.studio-lock-inner .eyebrow { display: inline-flex; margin-bottom: 10px; color: var(--teal); background: var(--teal-soft); border: 1px solid rgba(15,159,146,.18); border-radius: 999px; padding: 3px 10px; font-size: 11px; font-weight: 760; text-transform: uppercase; letter-spacing: .06em; }
.studio-lock-inner h2 { margin: 0 0 7px; font-size: 24px; }
.studio-lock-inner p { margin: 0; color: var(--muted); }
.code { white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; background: #111827; color: #e5e7eb; border-radius: 8px; padding: 12px; max-height: 260px; overflow: auto; }
@media (max-width: 1180px) {
  .shell { grid-template-columns: 1fr; }
  .side { position: sticky; top: 0; z-index: 5; padding: 12px 16px; gap: 10px; box-shadow: 0 10px 28px rgba(17,24,39,.18); }
  .side-meta, .side-foot > span:not(.side-version) { display: none; }
  .side-foot { display: block; position: absolute; top: 18px; right: 16px; margin: 0; }
  .side-version { color: #bac5d4; }
  .brand-card { width: auto; align-self: flex-start; }
  .brand-logo { width: 32px; height: 32px; }
  .brand-logo img { width: 28px; height: 28px; }
  .brand { font-size: 17px; }
  .sub { font-size: 10px; }
  .nav { display: flex; gap: 6px; overflow-x: auto; padding: 2px 1px 4px; scrollbar-width: thin; width: 100%; max-width: 100%; min-width: 0; }
  .nav::-webkit-scrollbar { height: 4px; }
  .nav::-webkit-scrollbar-track { background: rgba(255,255,255,.04); }
  .nav::-webkit-scrollbar-thumb { background: rgba(186,197,212,.42); border-radius: 999px; }
  .nav button { flex: 0 0 auto; min-height: 34px; padding: 7px 10px; white-space: nowrap; }
  .grid, .bands, .studio-layout, .chat-layout, .telemetry-grid, .runs-layout, .source-connect { grid-template-columns: 1fr; }
  .agent-hero { grid-template-columns: 1fr; }
  .agent-hero-actions { justify-content: flex-start; }
  .agent-stat-grid, .schema-grid { grid-template-columns: 1fr; }
  .debug-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .trace-browser { min-height: 0; }
  .trace-list { max-height: 430px; }
  .run-browser { min-height: 0; }
  .run-record-list { max-height: 430px; }
  .event-stage { grid-template-columns: 1fr; }
  .event-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .main { padding: 16px; }
  .top { flex-direction: column; }
  .telemetry-drop, .trace-hero-head { grid-template-columns: 1fr; display: grid; }
  .telemetry-source-meta, .trace-hero-badges { justify-content: flex-start; }
  .trace-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .runs-overview, .run-replay-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .trace-stat { border-bottom: 1px solid #edf1f6; }
  .replay-controls { grid-template-columns: repeat(3, auto); }
  .replay-controls input[type="range"] { grid-column: 1 / -1; }
  .event-rail { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <button class="brand-card" onclick="showView('dashboard')" aria-label="Open Protolink dashboard">
      <span class="brand-logo"><img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/logo_sm.png" alt="" /></span>
      <span><span class="brand">Protolink</span><span class="sub">runtime dashboard</span></span>
    </button>
    <div class="side-meta">
      <span>Local inspection</span>
      <span id="side-store">Store: -</span>
      <span id="side-traces">Telemetry: -</span>
    </div>
    <nav class="nav">
      <button id="nav-dashboard" onclick="showView('dashboard')"><span class="nav-label" data-icon="dashboard">Dashboard</span></button>
      <button id="nav-registry" onclick="showView('registry')"><span class="nav-label" data-icon="registry">Registry</span></button>
      <button id="nav-runs" onclick="showView('runs')"><span class="nav-label" data-icon="timeline">Runs</span></button>
      <button id="nav-telemetry" onclick="showView('telemetry')"><span class="nav-label" data-icon="activity">Telemetry</span></button>
      <button id="nav-chat" onclick="showView('chat')"><span class="nav-label" data-icon="chat">Chat</span></button>
      <button id="nav-studio" onclick="showView('studio')"><span class="nav-label" data-icon="studio">Studio</span> <span class="soon-mini">Soon</span></button>
    </nav>
    <div class="side-foot">
      <span>Local devtools over registry cards, run reports, telemetry traces, agent status, and chat.</span>
      <span class="side-version" id="side-version">Protolink</span>
    </div>
  </aside>
  <main class="main">
    <section id="view-dashboard" class="view">
      <div class="top">
        <div>
          <p class="kicker">Local runtime view</p>
          <h1>Dashboard</h1>
          <p class="lede">Inspect persisted task snapshots, run reports, local telemetry, registry cards, agent health, and chat-ready HTTP agents from one local surface.</p>
        </div>
        <div class="actions"><button class="btn primary" data-icon="refresh" onclick="refresh()">Refresh</button><button class="btn" data-icon="ping" onclick="pingAll()">Ping all</button></div>
      </div>
      <div class="alerts" id="alerts"></div>
      <div class="grid" id="metrics"></div>
      <div class="dashboard-stack"><div class="panel"><h2>Registry <span class="online-summary" id="dashboard-registry-summary"></span></h2><div class="panel-note">For full agent details, schemas, transports, and security metadata, open the Registry tab.</div><div id="health-table"></div></div></div>
    </section>
    <section id="view-runs" class="view">
      <div class="top"><div><p class="kicker">Execution archive</p><h1>Runs</h1><p class="lede">Search recent task snapshots and reports, then replay their event history from a read-only SQLite source.</p></div><div class="actions"><button class="btn" data-icon="refresh" onclick="refresh()">Refresh</button></div></div>
      <div class="source-connect" id="runs-source-card">
        <div class="source-connect-copy">
          <span class="source-connect-mark" data-icon="timeline"></span>
          <div class="source-connect-text"><strong id="runs-source-name">No run store connected</strong><span id="runs-source-detail">Connect an existing Protolink SQLite database.</span></div>
        </div>
        <form class="source-connect-form" onsubmit="connectRunStore(event)">
          <input id="runs-source-input" type="text" autocomplete="off" spellcheck="false" placeholder="/path/to/runs.db" aria-label="SQLite run-store path" />
          <button class="btn primary" id="runs-source-button" data-icon="plug" type="submit">Connect store</button>
          <span class="source-feedback" id="runs-source-feedback" role="status" aria-live="polite"></span>
        </form>
      </div>
      <div class="runs-overview" id="runs-overview"></div>
      <div class="runs-layout">
        <aside class="panel run-browser">
          <div class="run-browser-head">
            <input id="run-search" type="search" placeholder="Run, session, agent…" oninput="renderRuns()" aria-label="Filter runs" />
            <select id="run-kind-filter" onchange="renderRuns()" aria-label="Filter run record type"><option value="">All records</option><option value="report">Reports</option><option value="task">Tasks</option></select>
          </div>
          <div class="run-record-list" id="runs-list"></div>
        </aside>
        <section class="panel run-replay-shell">
          <h2>Replay <span class="online-summary" id="run-replay-summary" role="status" aria-live="polite">Select a record</span></h2>
          <div id="replay-panel" class="run-replay-empty" aria-busy="false"><div><span class="trace-empty-icon" data-icon="timeline"></span><h3>Choose a run</h3><p>Select a report or task snapshot to inspect its correlation details and event timeline.</p></div></div>
        </section>
      </div>
    </section>
    <section id="view-telemetry" class="view">
      <div class="top">
        <div>
          <p class="kicker">LocalTraceTelemetry</p>
          <h1>Telemetry</h1>
          <p class="lede">Explore Protolink <code>traces.jsonl</code> as grouped task records, span waterfalls, and a playable event timeline. Only a bounded recent window is loaded at once.</p>
        </div>
        <div class="actions">
          <button class="btn" data-icon="refresh" onclick="reloadTelemetry()">Latest</button>
          <button class="btn primary" data-icon="upload" onclick="openTelemetryFile()">Open JSONL</button>
          <input id="telemetry-file" type="file" accept=".jsonl,application/json,text/plain" hidden onchange="handleTelemetryFile(this.files && this.files[0])" />
        </div>
      </div>
      <div class="telemetry-drop" id="telemetry-drop"
        ondragenter="telemetryDrag(event, true)" ondragover="telemetryDrag(event, true)"
        ondragleave="telemetryDrag(event, false)" ondrop="dropTelemetryFile(event)">
        <div class="telemetry-source">
          <span class="telemetry-source-mark" id="telemetry-source-icon"></span>
          <div class="telemetry-source-copy"><strong id="telemetry-source-name">No telemetry source</strong><span id="telemetry-source-detail">Pass --traces to the CLI or drop a traces.jsonl file here.</span></div>
        </div>
        <div class="telemetry-source-meta" id="telemetry-source-meta"></div>
      </div>
      <div class="alerts" id="telemetry-alerts"></div>
      <div class="grid" id="telemetry-metrics"></div>
      <div class="telemetry-grid">
        <aside class="panel trace-browser">
          <div class="trace-browser-head">
            <div class="trace-browser-title"><h2>Task records</h2><span class="pill idle" id="trace-filter-count">0</span></div>
            <div class="trace-filters">
              <input id="trace-search" type="search" placeholder="Agent, trace, task, model…" oninput="renderTelemetryList()" aria-label="Filter telemetry records" />
              <select id="trace-status-filter" onchange="renderTelemetryList()" aria-label="Filter telemetry by status">
                <option value="">All status</option>
                <option value="ok">OK</option>
                <option value="error">Error</option>
                <option value="running">Running</option>
              </select>
            </div>
          </div>
          <div class="trace-window-note" id="trace-window-note">Recent-first bounded window</div>
          <div class="trace-list" id="trace-list"></div>
          <div class="trace-browser-foot"><button class="btn" id="trace-load-more" data-icon="download" onclick="loadOlderTelemetry()">Load older records</button></div>
        </aside>
        <div class="trace-workbench" id="trace-workbench">
          <div class="trace-empty"><div class="trace-empty-inner"><span class="trace-empty-icon" data-icon="activity"></span><h2>Open a telemetry trace</h2><p>Select a task record, pass <code>--traces traces.jsonl</code>, or drop a file above. Uploaded files stay in this browser tab.</p></div></div>
        </div>
      </div>
    </section>
    <section id="view-registry" class="view">
      <div class="top"><div><p class="kicker">Discovery</p><h1>Registry</h1><p class="lede">Agent cards currently visible to the dashboard snapshot, with status probes and chat entry points for HTTP agents.</p></div><div class="actions"><button class="btn" data-icon="refresh" onclick="refresh()">Refresh</button><button class="btn" data-icon="ping" onclick="pingAll()">Ping all</button></div></div>
      <div class="source-connect" id="registry-source-card">
        <div class="source-connect-copy">
          <span class="source-connect-mark" data-icon="registry"></span>
          <div class="source-connect-text"><strong id="registry-source-name">No registry connected</strong><span id="registry-source-detail">Connect a local HTTP registry to discover agents.</span></div>
        </div>
        <form class="source-connect-form" onsubmit="connectRegistry(event)">
          <input id="registry-source-input" type="url" autocomplete="url" spellcheck="false" placeholder="http://127.0.0.1:9000" aria-label="Registry URL" />
          <button class="btn primary" id="registry-source-button" data-icon="plug" type="submit">Connect registry</button>
          <span class="source-feedback" id="registry-source-feedback" role="status" aria-live="polite"></span>
        </form>
      </div>
      <div class="panel"><h2>Agents</h2><div id="registry-table"></div></div>
      <div class="panel"><h2>Selected agent</h2><div class="panel-body" id="agent-detail"></div></div>
    </section>
    <section id="view-chat" class="view">
      <div class="top"><div><p class="kicker">Agent chat</p><h1>Chat</h1><p class="lede">Talk to any HTTP agent that advertises LLM chat support. Static dashboard files show the panel, while live chat requires the served dashboard.</p></div><div class="actions"><button class="btn" data-icon="refresh" onclick="refresh()">Refresh</button></div></div>
      <div class="chat-layout">
        <aside class="chat-sidebar">
          <div class="field"><label>Agent</label><select id="chat-agent-select" onchange="selectChatAgent(this.value)"></select></div>
          <div class="field"><label>Session</label><input id="chat-session" oninput="chatRequestGeneration += 1; chatPending = false; chatSessionId = this.value || chatSessionId; renderChat()" /></div>
          <div id="chat-agent-detail"></div>
        </aside>
        <div class="chat-box">
          <div class="chat-head">
            <div class="chat-title-wrap">
              <span class="agent-avatar small" id="chat-avatar">A</span>
              <div class="chat-title-main"><strong id="chat-title">Chat</strong><span id="chat-subtitle">Select an agent</span></div>
            </div>
            <div class="chat-head-actions">
              <span class="pill idle" id="chat-status">idle</span>
              <button class="mini-btn" data-icon="reset" id="chat-reset" onclick="resetChat()">Reset</button>
              <button class="mini-btn" data-icon="activity" id="chat-debug-toggle" onclick="toggleChatDebug()">Debug</button>
            </div>
          </div>
          <div class="debug-panel" id="chat-debug-panel">
            <div class="debug-grid">
              <div class="debug-item"><div class="debug-label">Last latency</div><div class="debug-value" id="debug-latency">-</div></div>
              <div class="debug-item"><div class="debug-label">Average latency</div><div class="debug-value" id="debug-avg-latency">-</div></div>
              <div class="debug-item"><div class="debug-label">Messages sent</div><div class="debug-value" id="debug-count">0</div></div>
              <div class="debug-item"><div class="debug-label">Session</div><div class="debug-value" id="debug-session">-</div></div>
              <div class="debug-item"><div class="debug-label">Last error</div><div class="debug-value" id="debug-error">none</div></div>
            </div>
          </div>
          <div class="messages" id="chat-messages"></div>
          <div class="chat-compose">
            <div class="chat-input-wrap">
              <textarea id="chat-input" placeholder="Type a message to the selected agent" oninput="handleChatInput()" onkeydown="handleChatKeydown(event)"></textarea>
              <div class="compose-meta"><span>Proxy /chat</span><span id="chat-compose-state">idle</span></div>
            </div>
            <button class="btn primary" data-icon="send" id="chat-send" onclick="sendChat()">Send</button>
          </div>
        </div>
      </div>
    </section>
    <section id="view-studio" class="view">
      <div class="top"><div><p class="kicker">Canvas preview</p><h1>Protolink Studio</h1><p class="lede">The visual agent builder is disabled while the blueprint format settles.</p></div><div class="actions"><button class="btn" data-icon="plug" disabled>Connect</button><button class="btn primary" data-icon="download" disabled>Export JSON</button></div></div>
      <div class="studio-layout">
        <aside class="palette">
          <h2>Palette</h2>
          <button class="btn" data-icon="agent" disabled>Add Agent</button>
          <button class="btn" data-icon="spark" disabled>Add LLM</button>
          <button class="btn" data-icon="tool" disabled>Add Tool</button>
          <button class="btn" data-icon="registry" disabled>Add Registry</button>
        </aside>
        <div class="canvas-wrap">
          <div class="canvas" id="studio-canvas">
            <svg class="edge-layer studio-muted" id="edge-layer"></svg>
            <div class="studio-lock"><div class="studio-lock-inner"><span class="eyebrow">Preview locked</span><h2>Protolink Studio is coming soon</h2><p>Studio will return as a proper canvas builder for agents, LLMs, tools, registries, telemetry, and flow blueprints. For now, this page is a disabled preview inside the dashboard.</p></div></div>
          </div>
        </div>
        <aside class="props">
          <h2>Selection</h2>
          <div class="field"><label>Label</label><input id="node-label" disabled /></div>
          <div class="field"><label>Kind</label><select id="node-kind" disabled><option>agent</option><option>llm</option><option>tool</option><option>registry</option></select></div>
          <button class="btn" data-icon="details" disabled>Delete</button>
          <h2 style="margin-top:16px;">Blueprint</h2>
          <div class="code" id="blueprint-json"></div>
        </aside>
      </div>
    </section>
  </main>
</div>
<script>
window.__PROTOLINK_SNAPSHOT__ = __PROTOLINK_SNAPSHOT_JSON__;
window.__PROTOLINK_LIVE__ = __PROTOLINK_LIVE_VALUE__;
let snapshot = window.__PROTOLINK_SNAPSHOT__;
let blueprint = JSON.parse(JSON.stringify(snapshot.studio?.blueprint || {nodes: [], edges: []}));
let selectedAgentIndex = 0;
let chatMessages = [];
let health = {};
let chatSessionId = newChatSessionId();
let chatPending = false;
let chatDebugOpen = false;
let chatDebugStats = {sent: 0, latencies: [], lastLatency: null, lastError: null};
let selectedRunKey = null;
let runReplayGeneration = 0;
let chatRequestGeneration = 0;
let sourceConnectGeneration = {registry: 0, runs: 0};
let sourceConnectionBusy = {registry: false, runs: false};
let sourceConnectionFeedback = {registry: null, runs: null};
let sourceInputDraft = {registry: null, runs: null};
const TELEMETRY_PAGE_SIZE = 50;
const TELEMETRY_SUMMARY_CAP = 500;
const TELEMETRY_SPAN_RENDER_CAP = 240;
const TELEMETRY_EVENT_RENDER_CAP = 320;
const TELEMETRY_JSON_PREVIEW_CHARS = 90000;
const TELEMETRY_DETAIL_MAX_BYTES = 16 * 1024 * 1024;
let telemetryState = createTelemetryState(snapshot.telemetry);

const ICON_PATHS = {
  activity: '<path d="M22 12h-4l-3 8-6-16-3 8H2"/>',
  agent: '<path d="M12 8V4"/><rect x="6" y="8" width="12" height="10" rx="3"/><path d="M9 13h.01M15 13h.01"/><path d="M10 18v2h4v-2"/>',
  chat: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>',
  dashboard: '<rect x="3" y="3" width="7" height="8" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="15" width="7" height="6" rx="1"/>',
  details: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  ping: '<path d="M12 18.5h.01"/><path d="M8.5 15a5 5 0 0 1 7 0"/><path d="M5 11.5a10 10 0 0 1 14 0"/><path d="M2 8a14 14 0 0 1 20 0"/>',
  play: '<path d="m8 5 11 7-11 7z"/>',
  plug: '<path d="M9 7V2M15 7V2"/><path d="M7 7h10v5a5 5 0 0 1-10 0z"/><path d="M12 17v5"/>',
  refresh: '<path d="M21 12a9 9 0 0 1-15.4 6.4"/><path d="M3 12A9 9 0 0 1 18.4 5.6"/><path d="M21 4v5h-5"/><path d="M3 20v-5h5"/>',
  registry: '<path d="M4 6h16v12H4z"/><path d="M8 6v12M16 6v12"/><path d="M4 10h16M4 14h16"/>',
  reset: '<path d="M3 12a9 9 0 0 1 9-9 9.7 9.7 0 0 1 6.4 2.4"/><path d="M18 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.7 9.7 0 0 1-6.4-2.4"/><path d="M6 21v-5h5"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  spark: '<path d="m12 2 1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  status: '<circle cx="12" cy="12" r="9"/><path d="m9 12 2 2 4-5"/>',
  studio: '<path d="M4 4h6v6H4z"/><path d="M14 4h6v6h-6z"/><path d="M9 14h6v6H9z"/><path d="M10 7h4M12 10v4"/>',
  timeline: '<path d="M4 5v14"/><circle cx="4" cy="6" r="2"/><circle cx="4" cy="18" r="2"/><path d="M8 6h12M8 18h12M8 12h8"/>',
  tool: '<path d="m14.7 6.3 3-3a3 3 0 0 1-4 4l-7.4 7.4a2 2 0 1 0 3 3l7.4-7.4a3 3 0 0 1 4-4l-3 3"/>',
  upload: '<path d="M12 21V8"/><path d="m7 13 5-5 5 5"/><path d="M5 3h14"/>'
};

function icon(name) {
  const body = ICON_PATHS[name] || ICON_PATHS.spark;
  return `<svg class="icon icon-${htmlAttr(name)}" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
}

function hydrateIcons(root = document) {
  for (const el of root.querySelectorAll('[data-icon]:not([data-icon-ready])')) {
    el.insertAdjacentHTML('afterbegin', icon(el.dataset.icon));
    el.setAttribute('data-icon-ready', 'true');
  }
}

function newChatSessionId() {
  return "dashboard_" + Math.random().toString(36).slice(2, 10);
}

function showView(name) {
  if (name !== 'telemetry') stopTelemetryPlayback();
  for (const el of document.querySelectorAll('.view')) el.classList.remove('active');
  for (const el of document.querySelectorAll('.nav button')) el.classList.remove('active');
  document.getElementById('view-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'telemetry') renderTelemetry();
  if (name === 'chat') renderChat();
  if (name === 'studio') renderStudio();
  hydrateIcons();
}

async function refresh() {
  if (window.__PROTOLINK_LIVE__) {
    const refreshGeneration = ++telemetryState.refreshGeneration;
    const sourceGeneration = telemetryState.sourceGeneration;
    try {
      const res = await fetch('/api/snapshot', {cache: 'no-store'});
      const refreshedSnapshot = res.ok ? await res.json() : null;
      const refreshedRevision = Number(refreshedSnapshot?.source_revision || 0);
      const currentRevision = Number(snapshot.source_revision || 0);
      if (
        refreshedSnapshot
        && refreshGeneration === telemetryState.refreshGeneration
        && refreshedRevision >= currentRevision
      ) {
        const previousRegistryUrl = snapshot.registry?.url || null;
        const previousStore = snapshot.runs?.store || null;
        chatRequestGeneration += 1;
        chatPending = false;
        snapshot = refreshedSnapshot;
        if (previousRegistryUrl !== (snapshot.registry?.url || null)) {
          sourceInputDraft.registry = null;
          sourceConnectionFeedback.registry = null;
          health = {};
          selectedAgentIndex = 0;
          chatMessages = [];
          chatPending = false;
        }
        if (previousStore !== (snapshot.runs?.store || null)) {
          sourceInputDraft.runs = null;
          sourceConnectionFeedback.runs = null;
        }
        selectedRunKey = null;
        runReplayGeneration += 1;
        resetRunReplayPanel();
        if (
          telemetryState.mode !== 'upload'
          && sourceGeneration === telemetryState.sourceGeneration
        ) {
          syncTelemetryFromSnapshot(snapshot.telemetry);
        }
      }
    } catch (_) {}
  }
  blueprint = blueprint.nodes?.length ? blueprint : JSON.parse(JSON.stringify(snapshot.studio?.blueprint || {nodes: [], edges: []}));
  render();
}

function render() {
  const agents = snapshot.registry?.agents || [];
  const tasks = snapshot.runs?.tasks || [];
  const reports = snapshot.runs?.reports || [];
  const telemetryRecords = telemetryState.records || [];
  const telemetryGroups = new Set(telemetryRecords.map(record => record.trace_id).filter(Boolean)).size;
  const onlineCount = agents.filter(agent => healthStatus(agent).state === 'online').length;
  const alerts = [];
  if (snapshot.registry?.error) alerts.push('Registry: ' + snapshot.registry.error);
  if (snapshot.runs?.error) alerts.push('Run store: ' + snapshot.runs.error);
  if (telemetryState.error) alerts.push('Telemetry: ' + telemetryState.error);
  document.getElementById('alerts').innerHTML = alerts.map(message => `<div class="alert">${esc(message)}</div>`).join('');
  document.getElementById('side-version').textContent = 'Protolink v' + boundedDisplayText(snapshot.version, 'unknown', 48);
  document.getElementById('side-store').textContent = 'Store: ' + (snapshot.runs?.store || 'not configured');
  document.getElementById('side-traces').textContent = 'Telemetry: ' + telemetrySourceShortLabel();
  document.getElementById('metrics').innerHTML = [
    metric('Agents', agents.length, onlineCount ? `${onlineCount} online` : snapshot.registry?.url || 'snapshot', 'teal', 'registry', 'registry'),
    metric('Tasks', tasks.length, 'open in Runs', 'indigo', 'runs', 'timeline'),
    metric('Reports', reports.length, 'stored run reports', 'amber', 'runs', 'play'),
    metric('Telemetry', telemetryRecords.length, telemetryGroups ? `${telemetryGroups} trace group${telemetryGroups === 1 ? '' : 's'} loaded` : 'open traces.jsonl', 'indigo', 'telemetry', 'activity'),
    metric('Store', raw(storeStateHtml(Boolean(snapshot.runs?.store), snapshot.runs?.error)), snapshot.runs?.error || 'local run store', snapshot.runs?.error ? 'coral' : 'teal', 'runs', 'status')
  ].join('');
  const registrySummary = document.getElementById('dashboard-registry-summary');
  if (registrySummary) registrySummary.innerHTML = `${statusDotHtml(onlineCount ? 'online' : agents.length ? 'unknown' : 'runtime')} ${esc(agents.length ? `${agents.length} visible` : 'no agents')}`;
  document.getElementById('health-table').innerHTML = table(['Agent', 'URL', 'Health', 'Actions'], agents.slice(0, 8).map((a, index) => agentHealthRow(a, index)));
  document.getElementById('registry-table').innerHTML = table(['Agent', 'Transport', 'URL', 'Capabilities', 'Health', 'Actions'], agents.map((a, index) => registryRow(a, index)));
  renderSourceControls();
  renderRuns();
  renderAgentDetail();
  renderTelemetry();
  renderChat();
  renderStudio();
  hydrateIcons();
}

function renderSourceControls() {
  const registry = snapshot.registry || {};
  const runs = snapshot.runs || {};
  updateSourceControl({
    kind: 'registry',
    configured: registry.configured ?? Boolean(registry.url),
    value: registry.url || '',
    connectedName: registry.url || 'Registry connected',
    emptyName: 'No registry connected',
    connectedDetail: registry.error
      ? 'Connected, but the registry is currently unavailable.'
      : `${(registry.agents || []).length} agent card${(registry.agents || []).length === 1 ? '' : 's'} discovered`,
    emptyDetail: 'Connect a local HTTP registry to discover agents.',
  });
  updateSourceControl({
    kind: 'runs',
    configured: runs.configured ?? Boolean(runs.store),
    value: runs.store || '',
    connectedName: runs.store || 'Run store connected',
    emptyName: 'No run store connected',
    connectedDetail: runs.error
      ? 'The configured store could not be read.'
      : `${(runs.reports || []).length} reports · ${(runs.tasks || []).length} task snapshots loaded`,
    emptyDetail: 'Connect an existing Protolink SQLite database.',
  });
}

function updateSourceControl(config) {
  const input = document.getElementById(`${config.kind}-source-input`);
  const button = document.getElementById(`${config.kind}-source-button`);
  const name = document.getElementById(`${config.kind}-source-name`);
  const detail = document.getElementById(`${config.kind}-source-detail`);
  const feedback = document.getElementById(`${config.kind}-source-feedback`);
  if (!input || !button || !name || !detail || !feedback) return;
  if (document.activeElement !== input) input.value = sourceInputDraft[config.kind] ?? config.value;
  name.textContent = config.configured ? config.connectedName : config.emptyName;
  detail.textContent = config.configured ? config.connectedDetail : config.emptyDetail;
  const busy = Boolean(sourceConnectionBusy[config.kind]);
  input.disabled = !window.__PROTOLINK_LIVE__ || busy;
  button.disabled = !window.__PROTOLINK_LIVE__ || busy;
  const state = sourceConnectionFeedback[config.kind];
  feedback.className = `source-feedback ${state?.kind || ''}`;
  feedback.textContent = !window.__PROTOLINK_LIVE__
    ? 'Serve the dashboard locally to connect or change this source.'
    : state?.message || (config.configured ? 'Connection is session-only and resets when the dashboard stops.' : '');
}

async function connectRegistry(event) {
  event.preventDefault();
  const input = document.getElementById('registry-source-input');
  sourceInputDraft.registry = input?.value || '';
  await connectDashboardSource('registry', {url: sourceInputDraft.registry});
}

async function connectRunStore(event) {
  event.preventDefault();
  const input = document.getElementById('runs-source-input');
  sourceInputDraft.runs = input?.value || '';
  await connectDashboardSource('runs', {path: sourceInputDraft.runs});
}

async function connectDashboardSource(kind, body) {
  if (!window.__PROTOLINK_LIVE__) {
    sourceConnectionFeedback[kind] = {kind: 'error', message: 'Serve the dashboard locally to connect a source.'};
    renderSourceControls();
    return;
  }
  const generation = ++sourceConnectGeneration[kind];
  sourceConnectionBusy[kind] = true;
  sourceConnectionFeedback[kind] = {kind: '', message: kind === 'registry' ? 'Connecting registry…' : 'Opening store read-only…'};
  renderSourceControls();
  try {
    const endpoint = kind === 'registry' ? '/api/sources/registry' : '/api/sources/runs';
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (generation !== sourceConnectGeneration[kind]) return;
    if (!response.ok || payload.error) throw new Error(payload.error || `Source request failed (${response.status})`);
    const revision = Number(payload.revision || 0);
    snapshot.source_revision = Math.max(revision, Number(snapshot.source_revision || 0));
    if (kind === 'registry') {
      chatRequestGeneration += 1;
      snapshot.registry = payload.registry;
      sourceInputDraft.registry = null;
      health = {};
      selectedAgentIndex = 0;
      chatMessages = [];
      chatPending = false;
      sourceConnectionFeedback.registry = payload.registry?.error
        ? {kind: 'error', message: `Source saved, but connection failed: ${payload.registry.error}`}
        : {kind: 'ok', message: payload.registry?.configured ? 'Registry connected.' : 'Registry disconnected.'};
    } else {
      snapshot.runs = payload.runs;
      sourceInputDraft.runs = null;
      selectedRunKey = null;
      runReplayGeneration += 1;
      resetRunReplayPanel();
      sourceConnectionFeedback.runs = {kind: 'ok', message: payload.runs?.configured ? 'Run store connected read-only.' : 'Run store disconnected.'};
    }
  } catch (error) {
    if (generation !== sourceConnectGeneration[kind]) return;
    sourceConnectionFeedback[kind] = {kind: 'error', message: error?.message || String(error)};
  } finally {
    if (generation !== sourceConnectGeneration[kind]) return;
    sourceConnectionBusy[kind] = false;
    render();
  }
}

function runIndexRecords() {
  const reports = Array.isArray(snapshot.runs?.reports) ? snapshot.runs.reports : [];
  const tasks = Array.isArray(snapshot.runs?.tasks) ? snapshot.runs.tasks : [];
  const records = [
    ...reports.map((record, sourceIndex) => ({
      kind: 'report',
      key: `report:${boundedSummaryText(record.run_id, 512)}`,
      id: record.run_id,
      correlationId: record.run_id,
      sessionId: record.session_id,
      traceId: record.trace_id,
      agentName: record.agent_name,
      timestamp: record.created_at,
      state: record.state,
      eventCount: record.event_count,
      sourceIndex,
    })),
    ...tasks.map((record, sourceIndex) => ({
      kind: 'task',
      key: `task:${boundedSummaryText(record.task_id, 512)}`,
      id: record.task_id,
      correlationId: record.run_id || record.task_id,
      sessionId: record.session_id,
      traceId: record.trace_id,
      agentName: record.agent_name,
      timestamp: record.updated_at || record.created_at,
      state: record.state,
      eventCount: null,
      sourceIndex,
    })),
  ];
  records.sort((left, right) => {
    const leftTime = timestampMs(left.timestamp);
    const rightTime = timestampMs(right.timestamp);
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return rightTime - leftTime;
    if (Number.isFinite(leftTime) !== Number.isFinite(rightTime)) return Number.isFinite(leftTime) ? -1 : 1;
    if (left.kind !== right.kind) return left.kind === 'report' ? -1 : 1;
    return left.sourceIndex - right.sourceIndex;
  });
  return records;
}

function runLifecycle(value) {
  const state = boundedSummaryText(value || 'unknown', 64).toLowerCase();
  if (['failed', 'error', 'rejected'].includes(state)) return {label: state, cls: 'error'};
  if (['running', 'pending', 'submitted', 'working'].includes(state)) return {label: state, cls: 'warn'};
  if (['completed', 'ok', 'success'].includes(state)) return {label: state, cls: 'ok'};
  return {label: state, cls: 'idle'};
}

function renderRuns() {
  const overview = document.getElementById('runs-overview');
  const list = document.getElementById('runs-list');
  if (!overview || !list) return;
  const allRecords = runIndexRecords();
  if (selectedRunKey && !allRecords.some(record => record.key === selectedRunKey)) {
    selectedRunKey = null;
    runReplayGeneration += 1;
    resetRunReplayPanel();
  }
  const reportCount = allRecords.filter(record => record.kind === 'report').length;
  const taskCount = allRecords.length - reportCount;
  const sessions = new Set(allRecords.map(record => record.sessionId).filter(Boolean)).size;
  const attention = allRecords.filter(record => ['error', 'warn'].includes(runLifecycle(record.state).cls)).length;
  overview.innerHTML = [
    runOverviewCard('Reports', reportCount, 'bounded recent index'),
    runOverviewCard('Tasks', taskCount, 'persisted snapshots'),
    runOverviewCard('Sessions', sessions, 'loaded correlations'),
    runOverviewCard('Attention', attention, 'running or failed'),
  ].join('');
  const search = boundedSummaryText(document.getElementById('run-search')?.value || '', 256).trim().toLowerCase();
  const kind = document.getElementById('run-kind-filter')?.value || '';
  const records = allRecords.filter(record => {
    if (kind && record.kind !== kind) return false;
    if (!search) return true;
    return [
      record.id,
      record.correlationId,
      record.sessionId,
      record.traceId,
      record.agentName,
      record.state,
    ].some(value => boundedSummaryText(value, 512).toLowerCase().includes(search));
  });
  if (!records.length) {
    const configured = snapshot.runs?.configured ?? Boolean(snapshot.runs?.store);
    const message = snapshot.runs?.error
      ? `Run store unavailable: ${snapshot.runs.error}`
      : configured
        ? (allRecords.length ? 'No run records match this filter.' : 'This store has no recent Protolink run records.')
        : 'Connect a run store above to browse reports and task snapshots.';
    list.innerHTML = `<div class="empty-muted">${esc(message)}</div>`;
  } else {
    list.innerHTML = records.map(renderRunRecord).join('');
  }
  hydrateIcons(list);
}

function runOverviewCard(label, value, hint) {
  return `<div class="run-overview-card"><span>${esc(label)}</span><strong>${esc(formatCompactNumber(value))}</strong><div class="agent-meta">${esc(hint)}</div></div>`;
}

function renderRunRecord(record) {
  const lifecycle = runLifecycle(record.state);
  const active = record.key === selectedRunKey;
  const detail = record.kind === 'report' && record.eventCount != null && Number.isFinite(Number(record.eventCount))
    ? `${formatCompactNumber(record.eventCount)} events`
    : `session ${shortId(record.sessionId || '-', 18)}`;
  return `
    <button type="button" class="run-record ${active ? 'active' : ''}" aria-pressed="${active ? 'true' : 'false'}" onclick="replayRun(${jsStringAttr(record.id)}, ${jsStringAttr(record.key)})">
      <span class="run-record-top"><span class="pill ${record.kind === 'report' ? 'capability-badge' : 'idle'}">${esc(record.kind)}</span><span class="pill ${lifecycle.cls}">${esc(lifecycle.label)}</span></span>
      <span class="run-record-id" title="${htmlAttr(record.id || '-')}">${esc(shortId(record.id || '-', 44))}</span>
      <span class="run-record-meta"><span class="run-record-agent"><span class="agent-avatar">${esc(initials(record.agentName || record.kind))}</span>${esc(boundedDisplayText(record.agentName, 'unassigned', 80))}</span><span>${esc(relativeTime(record.timestamp) || detail)}</span></span>
      <span class="run-record-meta"><span>${esc(detail)}</span><span>trace ${esc(shortId(record.traceId || '-', 14))}</span></span>
    </button>
  `;
}

function resetRunReplayPanel() {
  const panel = document.getElementById('replay-panel');
  const summary = document.getElementById('run-replay-summary');
  if (summary) summary.textContent = 'Select a record';
  if (panel) {
    panel.setAttribute('aria-busy', 'false');
    panel.className = 'run-replay-empty';
    panel.innerHTML = '<div><span class="trace-empty-icon" data-icon="timeline"></span><h3>Choose a run</h3><p>Select a report or task snapshot to inspect its correlation details and event timeline.</p></div>';
    hydrateIcons(panel);
  }
}

function createTelemetryState(source) {
  const meta = source && typeof source === 'object' ? source : {};
  return {
    mode: meta.configured ? (window.__PROTOLINK_LIVE__ ? 'server' : 'snapshot') : 'none',
    source: meta,
    uploadFile: null,
    records: Array.isArray(meta.records) ? meta.records : [],
    nextCursor: meta.next_cursor ?? null,
    selectedRecordId: null,
    selectedTrace: null,
    selectedSpanKey: null,
    loadingDetail: false,
    loadingPage: false,
    error: meta.error || null,
    eventIndex: 0,
    eventTimer: null,
    eventSpeed: 950,
    inspectorTab: 'summary',
    sourceGeneration: 0,
    detailGeneration: 0,
    refreshGeneration: 0,
    windowShifted: false,
  };
}

function syncTelemetryFromSnapshot(source) {
  const meta = source && typeof source === 'object' ? source : {};
  stopTelemetryPlayback();
  telemetryState.sourceGeneration += 1;
  telemetryState.detailGeneration += 1;
  telemetryState.mode = meta.configured ? (window.__PROTOLINK_LIVE__ ? 'server' : 'snapshot') : 'none';
  telemetryState.source = meta;
  telemetryState.uploadFile = null;
  telemetryState.records = Array.isArray(meta.records) ? meta.records : [];
  telemetryState.nextCursor = meta.next_cursor ?? null;
  telemetryState.error = meta.error || null;
  telemetryState.loadingDetail = false;
  telemetryState.loadingPage = false;
  telemetryState.windowShifted = false;
  if (!telemetryState.records.some(record => record.record_id === telemetryState.selectedRecordId)) {
    telemetryState.selectedRecordId = null;
    telemetryState.selectedTrace = null;
    telemetryState.selectedSpanKey = null;
  }
}

function telemetrySourceShortLabel() {
  if (telemetryState.mode === 'upload' && telemetryState.uploadFile) return telemetryState.uploadFile.name;
  const path = telemetryState.source?.path;
  if (path) return String(path).split(/[\\\\/]/).pop() || String(path);
  return 'not loaded';
}

function telemetryLifecycle(record) {
  const value = boundedSummaryText(record?.final_state || record?.status || 'unknown', 64).toLowerCase();
  if (['failed', 'error'].includes(value)) return {value, cls: 'error'};
  if (['canceled', 'cancelled'].includes(value)) return {value, cls: 'warn'};
  if (['ok', 'completed', 'success'].includes(value)) return {value, cls: 'ok'};
  return {value, cls: 'idle'};
}

function renderTelemetry() {
  const sourceIcon = document.getElementById('telemetry-source-icon');
  const sourceName = document.getElementById('telemetry-source-name');
  const sourceDetail = document.getElementById('telemetry-source-detail');
  const sourceMeta = document.getElementById('telemetry-source-meta');
  const telemetryAlerts = document.getElementById('telemetry-alerts');
  if (!sourceIcon || !sourceName || !sourceDetail || !sourceMeta || !telemetryAlerts) return;

  const meta = telemetryState.source || {};
  const file = telemetryState.uploadFile;
  sourceIcon.innerHTML = icon(telemetryState.mode === 'upload' ? 'upload' : 'activity');
  if (telemetryState.mode === 'upload' && file) {
    sourceName.textContent = file.name;
    sourceDetail.textContent = 'Browser file · payloads stay in this tab';
  } else if (telemetryState.mode === 'snapshot') {
    sourceName.textContent = meta.path || 'Telemetry snapshot';
    sourceDetail.textContent = 'Static summary snapshot · open the matching JSONL file for details';
  } else if (meta.configured) {
    sourceName.textContent = meta.path || 'Configured telemetry file';
    sourceDetail.textContent = meta.exists
      ? 'CLI source · detail records are read lazily from disk'
      : 'Waiting for the configured JSONL file to appear';
  } else {
    sourceName.textContent = 'No telemetry source';
    sourceDetail.textContent = 'Pass --traces to the CLI or drop a traces.jsonl file here.';
  }

  const size = file ? file.size : meta.size_bytes;
  const modified = file ? file.lastModified : meta.modified_at;
  const malformed = Number(meta.malformed_count || 0);
  const oversized = Number(meta.oversized_count || 0);
  sourceMeta.innerHTML = [
    size != null ? `<span class="pill idle">${esc(formatBytes(size))}</span>` : '',
    modified ? `<span class="pill idle">${esc(relativeTime(modified))}</span>` : '',
    malformed ? `<span class="pill warn">${esc(malformed)} malformed skipped</span>` : '',
    oversized ? `<span class="pill warn">${esc(oversized)} oversized skipped</span>` : '',
    meta.partial_tail ? '<span class="pill warn">partial tail ignored</span>' : '',
    meta.scan_exhausted ? '<span class="pill warn">scan budget reached</span>' : '',
    telemetryState.mode === 'upload'
      ? '<span class="pill ok">local only</span>'
      : telemetryState.mode === 'snapshot'
        ? '<span class="pill idle">summaries only</span>'
        : meta.exists
          ? '<span class="pill ok">connected</span>'
          : '',
  ].join('');
  telemetryAlerts.innerHTML = telemetryState.error
    ? `<div class="alert">${esc(telemetryState.error)} <button type="button" class="mini-btn" style="margin-left:8px" onclick="${telemetryState.mode === 'snapshot' ? 'openTelemetryFile()' : 'reloadTelemetry()'}">${telemetryState.mode === 'snapshot' ? 'Open JSONL' : 'Load latest'}</button></div>`
    : '';

  renderTelemetryMetrics();
  renderTelemetryList();
  renderTelemetryWorkbench();
  hydrateIcons(document.getElementById('view-telemetry'));

  if (
    telemetryState.records.length
    && !telemetryState.selectedRecordId
    && !telemetryState.loadingDetail
    && !telemetryState.loadingPage
    && ['server', 'upload'].includes(telemetryState.mode)
  ) {
    const recordId = telemetryState.records[0].record_id;
    queueMicrotask(() => selectTelemetryRecord(recordId));
  }
}

function renderTelemetryMetrics() {
  const target = document.getElementById('telemetry-metrics');
  if (!target) return;
  const records = telemetryState.records || [];
  const groups = new Set(records.map(record => record.trace_id).filter(Boolean)).size;
  const errors = records.filter(record => telemetryLifecycle(record).cls === 'error').length;
  const spans = records.reduce((sum, record) => sum + Number(record.span_count || 0), 0);
  const events = records.reduce((sum, record) => sum + Number(record.event_count || 0), 0);
  const tokens = records.reduce((sum, record) => sum + Number(record.llm_metrics?.total_tokens || 0), 0);
  target.innerHTML = [
    metric('Trace groups', groups, 'shared correlation IDs', 'teal', null, 'activity'),
    metric('Task records', records.length, records.length >= TELEMETRY_SUMMARY_CAP ? 'window cap reached' : 'loaded summary window', 'indigo', null, 'timeline'),
    metric('Errors', errors, errors ? 'inspect failed records' : 'none in loaded window', errors ? 'coral' : 'teal', null, 'status'),
    metric('Spans', formatCompactNumber(spans), 'task · LLM · tool · agent', 'amber', null, 'timeline'),
    metric('Events', formatCompactNumber(events), tokens ? `${formatCompactNumber(tokens)} tokens` : 'canonical trace events', 'indigo', null, 'activity'),
  ].join('');
}

function filteredTelemetryRecords() {
  const search = String(document.getElementById('trace-search')?.value || '').trim().toLowerCase();
  const status = String(document.getElementById('trace-status-filter')?.value || '').toLowerCase();
  return (telemetryState.records || []).filter(record => {
    const lifecycle = telemetryLifecycle(record);
    const statusMatches = !status
      || (status === 'ok' && lifecycle.cls === 'ok')
      || (status === 'error' && lifecycle.cls === 'error')
      || lifecycle.value === status;
    if (!statusMatches) return false;
    if (!search) return true;
    const haystack = [
      record.agent_name,
      record.trace_id,
      record.task_id,
      record.status,
      record.final_state,
      ...summaryModels(record),
      ...summarySpanKinds(record),
    ].join(' ').toLowerCase();
    return haystack.includes(search);
  });
}

function renderTelemetryList() {
  const target = document.getElementById('trace-list');
  const count = document.getElementById('trace-filter-count');
  const note = document.getElementById('trace-window-note');
  const more = document.getElementById('trace-load-more');
  if (!target || !count || !note || !more) return;
  const records = filteredTelemetryRecords();
  count.textContent = `${records.length} / ${telemetryState.records.length}`;
  const sourceLabel = telemetryState.mode === 'upload'
    ? 'browser file'
    : telemetryState.mode === 'server'
      ? 'CLI source'
      : telemetryState.mode === 'snapshot'
        ? 'static summaries'
        : 'no source';
  note.textContent = telemetryState.windowShifted
    ? `Older rolling window · ${sourceLabel} · Latest returns to the newest records`
    : `Newest first · ${sourceLabel} · summaries only until selected`;
  if (!records.length) {
    const message = telemetryState.records.length ? 'No records match these filters.' : telemetryState.error || 'No telemetry records loaded.';
    target.innerHTML = `<div style="padding:20px;color:var(--muted);">${esc(message)}</div>`;
  } else {
    target.innerHTML = groupTelemetryRecords(records).map(group => `
      <section class="trace-group">
        <div class="trace-group-head"><code title="${esc(group.traceId || 'No trace ID')}">${esc(shortId(group.traceId || 'No trace ID', 31))}</code><span>${group.records.length} task${group.records.length === 1 ? '' : 's'}</span></div>
        ${group.records.map(renderTelemetryRecordButton).join('')}
      </section>
    `).join('');
  }
  const atCap = telemetryState.records.length >= TELEMETRY_SUMMARY_CAP;
  more.disabled = telemetryState.loadingPage || telemetryState.nextCursor == null || telemetryState.mode === 'snapshot';
  more.innerHTML = telemetryState.loadingPage
    ? `${icon('activity')} Loading…`
      : telemetryState.mode === 'snapshot'
        ? `${icon('upload')} Open JSONL for history`
        : telemetryState.nextCursor == null
        ? `${icon('status')} Oldest loaded`
        : `${icon('download')} Load ${TELEMETRY_PAGE_SIZE} older${atCap ? ' · roll window' : ''}`;
  more.setAttribute('data-icon-ready', 'true');
}

function groupTelemetryRecords(records) {
  const groups = new Map();
  for (const record of records) {
    const key = record.trace_id ? `trace:${record.trace_id}` : `record:${record.record_id}`;
    if (!groups.has(key)) groups.set(key, {traceId: record.trace_id || null, records: []});
    groups.get(key).records.push(record);
  }
  return [...groups.values()];
}

function renderTelemetryRecordButton(record) {
  const lifecycle = telemetryLifecycle(record);
  const metrics = record.llm_metrics || {};
  const models = summaryModels(record);
  const model = models.length ? models[0] : '';
  return `
    <button type="button" class="trace-record ${record.record_id === telemetryState.selectedRecordId ? 'active' : ''}" ${record.record_id === telemetryState.selectedRecordId ? 'aria-current="true"' : ''} onclick="selectTelemetryRecord(${jsStringAttr(record.record_id)})">
      <div class="trace-record-top"><span class="trace-agent">${esc(boundedDisplayText(record.agent_name, 'unknown agent', 160))}</span><span class="pill ${lifecycle.cls}">${esc(boundedDisplayText(lifecycle.value, 'unknown', 48))}</span></div>
      <div class="trace-record-id" title="${esc(record.task_id || '')}">${esc(shortId(record.task_id || record.record_id, 26))}</div>
      <div class="trace-record-bottom"><span>${esc(timestampLabel(record.started_at))}</span><span>${esc(formatMilliseconds(record.duration_ms))}</span></div>
      <div class="trace-record-bottom"><span>${esc(record.span_count || 0)} spans · ${esc(record.event_count || 0)} events</span><span>${esc(model || (metrics.total_tokens ? `${formatCompactNumber(metrics.total_tokens)} tok` : ''))}</span></div>
    </button>
  `;
}

function renderTelemetryWorkbench() {
  const target = document.getElementById('trace-workbench');
  if (!target) return;
  if (telemetryState.loadingDetail) {
    target.innerHTML = '<div class="trace-empty"><div class="trace-empty-inner"><span class="trace-empty-icon" data-icon="activity"></span><h2>Reading one trace</h2><p>The summary window stays light while this JSONL record is decoded.</p></div></div>';
    hydrateIcons(target);
    return;
  }
  const trace = telemetryState.selectedTrace;
  if (!trace) {
    const error = telemetryState.error;
    const snapshotSelected = telemetryState.mode === 'snapshot' && telemetryState.selectedRecordId;
    const message = error
      || (snapshotSelected
        ? 'This static file contains bounded summaries only. Open the matching JSONL file above to inspect this record.'
        : 'Select a task record, pass --traces traces.jsonl, or drop a file above. Uploaded files stay in this browser tab.');
    target.innerHTML = `<div class="trace-empty"><div class="trace-empty-inner"><span class="trace-empty-icon" data-icon="${error ? 'status' : 'activity'}"></span><h2>${error ? 'Trace unavailable' : snapshotSelected ? 'Summary selected' : 'Open a telemetry trace'}</h2><p>${esc(message)}</p></div></div>`;
    hydrateIcons(target);
    return;
  }

  const summary = telemetryState.records.find(record => record.record_id === telemetryState.selectedRecordId) || summarizeUploadTrace(trace, 0, 0, telemetryState.selectedRecordId || 'selected');
  const lifecycle = telemetryLifecycle({...trace, final_state: trace.metadata?.final_state});
  const spans = Array.isArray(trace.spans) ? trace.spans : [];
  const events = telemetryTimelineEvents(trace);
  const llmMetrics = trace.metadata?.llm_metrics || summary.llm_metrics || {};
  const retries = Number(trace.metadata?.retry_count || 0);
  target.innerHTML = `
    <section class="panel trace-hero">
      <div class="trace-hero-head">
        <div class="trace-hero-title">
          <span class="trace-kind-mark">${icon('activity')}</span>
          <div><h2>${esc(boundedDisplayText(trace.agent_name || summary.agent_name, 'Telemetry record', 160))}</h2><p>task ${esc(shortId(trace.task_id || '-', 72))} · trace ${esc(shortId(trace.trace_id || '-', 72))}</p></div>
        </div>
        <div class="trace-hero-badges">
          <span class="pill ${lifecycle.cls}">${statusDotHtml(lifecycle.cls === 'ok' ? 'online' : lifecycle.cls === 'error' ? 'offline' : 'unknown')}${esc(boundedDisplayText(lifecycle.value, 'unknown', 48))}</span>
          ${summaryModels(summary).map(model => `<span class="pill capability-badge">${esc(model)}</span>`).join('')}
        </div>
      </div>
      <div class="trace-stats">
        ${traceStat('Duration', formatMilliseconds(trace.duration_ms ?? summary.duration_ms))}
        ${traceStat('Spans', spans.length)}
        ${traceStat('Events', Array.isArray(trace.events) ? trace.events.length : 0)}
        ${traceStat('Retries', retries)}
        ${traceStat('Tokens', llmMetrics.total_tokens ? formatCompactNumber(llmMetrics.total_tokens) : '—')}
      </div>
    </section>
    <section class="panel">
      <h2>Span waterfall <span class="online-summary">${esc(spans.length)} operations · parent-linked within this task</span></h2>
      ${renderSpanWaterfall(trace)}
    </section>
    <section class="panel">
      <h2>Event replay <span class="online-summary">${esc(events.length)} visible · trace events counted once</span></h2>
      ${renderTelemetryReplay(trace, events)}
    </section>
    <section class="panel">
      <h2>Inspector <span class="online-summary">payloads are collapsed by default</span></h2>
      ${renderTelemetryInspector(trace, events)}
    </section>
  `;
  hydrateIcons(target);
  const activeRail = target.querySelector('.event-rail button.active');
  if (activeRail) activeRail.scrollIntoView({block: 'nearest'});
}

function traceStat(label, value) {
  return `<div class="trace-stat"><span class="detail-label">${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

function collectRenderableSpans(trace) {
  const rawSpans = Array.isArray(trace.spans) ? trace.spans : [];
  const entries = [];
  const spanScanLimit = Math.min(rawSpans.length, TELEMETRY_SPAN_RENDER_CAP * 20);
  for (let index = 0; index < spanScanLimit && entries.length < TELEMETRY_SPAN_RENDER_CAP; index += 1) {
    const span = rawSpans[index];
    if (span && typeof span === 'object' && !Array.isArray(span)) {
      entries.push({span, sourceIndex: index, key: `span:${index}`});
    }
  }
  return entries;
}

function renderSpanWaterfall(trace) {
  const rawSpans = Array.isArray(trace.spans) ? trace.spans : [];
  const entries = collectRenderableSpans(trace);
  if (!entries.length) return '<div class="panel-body"><div class="empty-muted">No spans were recorded for this task.</div></div>';
  entries.sort((left, right) => {
    const leftStart = timestampMs(left.span.started_at);
    const rightStart = timestampMs(right.span.started_at);
    if (Number.isFinite(leftStart) && Number.isFinite(rightStart) && leftStart !== rightStart) return leftStart - rightStart;
    if (Number.isFinite(leftStart) !== Number.isFinite(rightStart)) return Number.isFinite(leftStart) ? -1 : 1;
    return left.sourceIndex - right.sourceIndex;
  });
  const spanStarts = entries.map(entry => timestampMs(entry.span.started_at)).filter(Number.isFinite);
  const spanEnds = entries.map(entry => {
    const startedAt = timestampMs(entry.span.started_at);
    const endedAt = timestampMs(entry.span.ended_at);
    const duration = entry.span.duration_ms == null || entry.span.duration_ms === ''
      ? Number.NaN
      : Number(entry.span.duration_ms);
    if (Number.isFinite(endedAt)) return endedAt;
    if (Number.isFinite(startedAt) && Number.isFinite(duration) && duration >= 0) return startedAt + duration;
    return Number.NaN;
  }).filter(Number.isFinite);
  const recordStart = timestampMs(trace.started_at);
  const recordEnd = timestampMs(trace.ended_at);
  const recordDuration = trace.duration_ms == null || trace.duration_ms === '' ? Number.NaN : Number(trace.duration_ms);
  const startCandidates = [...spanStarts];
  if (Number.isFinite(recordStart)) startCandidates.push(recordStart);
  const traceStart = startCandidates.length ? Math.min(...startCandidates) : 0;
  const endCandidates = [...spanEnds, ...spanStarts];
  if (Number.isFinite(recordEnd)) endCandidates.push(recordEnd);
  if (Number.isFinite(recordStart) && Number.isFinite(recordDuration) && recordDuration >= 0) {
    endCandidates.push(recordStart + recordDuration);
  }
  const traceEnd = Math.max(traceStart + 1, ...(endCandidates.length ? endCandidates : [traceStart + 1]));
  const total = Math.max(1, traceEnd - traceStart);
  const idCounts = new Map();
  for (const entry of entries) {
    const id = entry.span.id == null ? '' : boundedSummaryText(entry.span.id, 4096);
    if (id) idCounts.set(id, (idCounts.get(id) || 0) + 1);
  }
  const spanMap = new Map();
  for (const entry of entries) {
    const id = entry.span.id == null ? '' : boundedSummaryText(entry.span.id, 4096);
    if (id && idCounts.get(id) === 1) spanMap.set(id, entry);
  }
  const depthMemo = new Map();
  function spanDepth(entry) {
    if (depthMemo.has(entry.key)) return depthMemo.get(entry.key);
    const seen = new Set([entry.key]);
    let current = entry;
    let depth = 0;
    while (depth < 8) {
      const parentId = current.span.parent_id == null ? '' : boundedSummaryText(current.span.parent_id, 4096);
      const parent = parentId ? spanMap.get(parentId) : null;
      if (!parent || seen.has(parent.key)) break;
      seen.add(parent.key);
      current = parent;
      depth += 1;
    }
    depthMemo.set(entry.key, depth);
    return depth;
  }
  const hasSelection = entries.some(entry => entry.key === telemetryState.selectedSpanKey);
  const rows = entries.map((entry, rowIndex) => {
    const span = entry.span;
    const spanName = boundedDisplayText(span.name || span.kind, 'span', 180);
    const rawStart = timestampMs(span.started_at);
    const rawEnd = timestampMs(span.ended_at);
    const rawDuration = span.duration_ms == null || span.duration_ms === '' ? Number.NaN : Number(span.duration_ms);
    const start = Number.isFinite(rawStart) ? rawStart : traceStart;
    const durationEnd = Number.isFinite(rawDuration) && rawDuration >= 0 ? start + rawDuration : Number.NaN;
    const resolvedEnd = Number.isFinite(rawEnd) ? rawEnd : durationEnd;
    const end = Number.isFinite(resolvedEnd) ? resolvedEnd : traceEnd;
    const left = Math.max(0, Math.min(99, ((start - traceStart) / total) * 100));
    const width = Math.max(0.8, Math.min(100 - left, ((Math.max(end, start) - start) / total) * 100));
    const kind = traceKindClass(span.kind);
    const incomplete = !Number.isFinite(resolvedEnd);
    const error = boundedSummaryText(span.status, 64).toLowerCase() === 'error' || Boolean(span.error);
    const active = entry.key === telemetryState.selectedSpanKey;
    const durationLabel = incomplete ? 'open' : formatMilliseconds(Number.isFinite(rawDuration) && rawDuration >= 0 ? rawDuration : Math.max(0, end - start));
    const stateLabel = error ? 'error' : incomplete ? 'open' : boundedDisplayText(span.status, 'complete', 48);
    const startOffsetLabel = formatMilliseconds(Math.max(0, start - traceStart));
    return `
      <button type="button" role="option" class="span-row ${active ? 'active' : ''}" data-span-key="${htmlAttr(entry.key)}" aria-selected="${active ? 'true' : 'false'}" tabindex="${active || (!hasSelection && rowIndex === 0) ? '0' : '-1'}" aria-label="${htmlAttr(`${spanName}, ${boundedDisplayText(span.kind, 'span', 48)}, starts ${startOffsetLabel} from trace start, ${durationLabel}, ${stateLabel}`)}" onclick="selectTelemetrySpan(${jsStringAttr(entry.key)})">
        <span class="span-label" style="--depth:${spanDepth(entry)}">
          <span class="span-kind-dot ${kind}"></span><span class="span-name" title="${htmlAttr(spanName)}">${esc(spanName)}</span>
          <span class="span-duration">${esc(durationLabel)}</span>
        </span>
        <span class="span-track"><span class="span-bar ${kind} ${error ? 'error' : incomplete ? 'open' : ''}" style="left:${left.toFixed(3)}%;width:${width.toFixed(3)}%"></span></span>
      </button>
    `;
  }).join('');
  const capNote = rawSpans.length > entries.length
    ? `<div class="trace-limit-note">Showing ${entries.length} of ${rawSpans.length} span entries to keep rendering responsive; invalid entries are ignored.</div>`
    : '';
  return `<div class="trace-waterfall"><div class="waterfall-inner" id="telemetry-span-waterfall" role="listbox" aria-label="Trace spans" onkeydown="handleTelemetrySpanKeydown(event)"><div class="waterfall-scale"><span class="waterfall-scale-ticks"><span>0 ms</span><span>${esc(formatMilliseconds(total / 2))}</span><span>${esc(formatMilliseconds(total))}</span></span></div>${rows}${capNote}</div></div>`;
}

function telemetryTimelineEvents(trace) {
  const source = Array.isArray(trace.events) ? trace.events : [];
  if (source.length <= TELEMETRY_EVENT_RENDER_CAP) {
    const all = source
      .map((event, sourceIndex) => ({event, sourceIndex}))
      .filter(item => item.event && typeof item.event === 'object' && !Array.isArray(item.event));
    all.sort((a, b) => timestampMs(a.event.timestamp) - timestampMs(b.event.timestamp));
    return all;
  }
  const sampled = [];
  const scanStart = Math.max(0, source.length - TELEMETRY_EVENT_RENDER_CAP * 8);
  for (let sourceIndex = source.length - 1; sourceIndex >= scanStart && sampled.length < TELEMETRY_EVENT_RENDER_CAP; sourceIndex -= 1) {
    const event = source[sourceIndex];
    if (event && typeof event === 'object' && !Array.isArray(event)) sampled.push({event, sourceIndex});
  }
  sampled.reverse();
  sampled.sort((a, b) => timestampMs(a.event.timestamp) - timestampMs(b.event.timestamp));
  return sampled;
}

function renderTelemetryReplay(trace, events) {
  if (!events.length) return '<div class="panel-body"><div class="empty-muted">This task has spans but no inference-loop events. Explicit task-level tools can legitimately appear only in the waterfall.</div></div>';
  telemetryState.eventIndex = Math.max(0, Math.min(telemetryState.eventIndex, events.length - 1));
  const active = events[telemetryState.eventIndex];
  const truncated = (trace.events || []).length > events.length;
  return `
    <div class="replay-controls">
      <button class="mini-btn" type="button" onclick="stepTelemetryEvent(-1)" aria-label="Previous event">←</button>
      <button class="mini-btn primary" id="telemetry-play" type="button" onclick="toggleTelemetryPlayback()" aria-label="${telemetryState.eventTimer ? 'Pause' : 'Play'} event replay">${telemetryState.eventTimer ? 'Pause' : 'Play'}</button>
      <button class="mini-btn" type="button" onclick="stepTelemetryEvent(1)" aria-label="Next event">→</button>
      <input id="telemetry-event-range" type="range" min="0" max="${events.length - 1}" value="${telemetryState.eventIndex}" oninput="setTelemetryEventIndex(this.value)" aria-label="Telemetry event" />
      <span class="pill idle" id="telemetry-event-count">${telemetryEventCountLabel(trace, events)}</span>
      <select id="telemetry-speed" onchange="setTelemetrySpeed(this.value)" aria-label="Replay speed">
        <option value="1600" ${telemetryState.eventSpeed === 1600 ? 'selected' : ''}>0.5x</option>
        <option value="950" ${telemetryState.eventSpeed === 950 ? 'selected' : ''}>1x</option>
        <option value="420" ${telemetryState.eventSpeed === 420 ? 'selected' : ''}>2x</option>
      </select>
    </div>
    <div class="event-stage">
      <article class="${telemetryEventFocusClass(active.event)}" id="telemetry-event-focus" aria-live="polite">
        ${telemetryEventFocusHtml(trace, events)}
      </article>
      <nav class="event-rail" id="telemetry-event-rail" aria-label="Recorded telemetry events">
        ${telemetryEventRailHtml(events)}
      </nav>
    </div>
  `;
}

function telemetryEventCountLabel(trace, events) {
  const total = Array.isArray(trace.events) ? trace.events.length : events.length;
  return `${telemetryState.eventIndex + 1} / ${events.length}${total > events.length ? ` · latest ${events.length} of ${total}` : ''}`;
}

function telemetryEventFocusClass(event) {
  return `event-focus ${boundedSummaryText(event?.type, 128).includes('error') ? 'error' : ''}`.trim();
}

function telemetryEventFocusHtml(trace, events) {
  const active = events[telemetryState.eventIndex] || events[0] || {event: {}, sourceIndex: 0};
  const event = active.event || {};
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const preview = jsonPreview(payload, 4200);
  const elapsed = timestampMs(event.timestamp) - timestampMs(trace.started_at);
  const timeFromStart = Number.isFinite(elapsed) ? Math.max(0, elapsed) : Number.NaN;
  const omitted = Math.max(0, (Array.isArray(trace.events) ? trace.events.length : events.length) - events.length);
  return `
    <div class="event-focus-kicker">+${esc(formatMilliseconds(timeFromStart))} · event ${active.sourceIndex + 1}</div>
    <h3>${esc(boundedDisplayText(event.type, 'event', 180))}</h3>
    <p>${esc(eventSummary(event))}</p>
    ${omitted ? `<div class="trace-limit-note">Replay is a contiguous recent-event window; ${formatCompactNumber(omitted)} earlier event entries are omitted for responsiveness.</div>` : ''}
    <pre class="event-payload-preview">${esc(preview.text || '{}')}</pre>
  `;
}

function telemetryEventRailHtml(events) {
  return events.map((item, index) => `<button type="button" class="${index === telemetryState.eventIndex ? 'active' : ''}" ${index === telemetryState.eventIndex ? 'aria-current="step"' : ''} onclick="setTelemetryEventIndex(${index})"><span class="event-dot"></span><span>${esc(shortId(item.event?.type || 'event', 28))}</span></button>`).join('');
}

function renderTelemetryInspector(trace, events) {
  const tabs = [
    ['summary', 'Summary'],
    ['payload', 'Event payload'],
    ['span', 'Selected span'],
    ['json', 'Trace JSON'],
  ];
  const body = telemetryInspectorBody(trace, events);
  return `<div class="inspector-tabs" id="telemetry-inspector-tabs" role="tablist" aria-label="Trace inspector" onkeydown="handleTelemetryInspectorKeydown(event)">${tabs.map(([key, label]) => `<button type="button" role="tab" aria-controls="telemetry-inspector-panel" aria-selected="${telemetryState.inspectorTab === key ? 'true' : 'false'}" tabindex="${telemetryState.inspectorTab === key ? '0' : '-1'}" data-inspector-tab="${key}" class="inspector-tab ${telemetryState.inspectorTab === key ? 'active' : ''}" onclick="setTelemetryInspectorTab('${key}')">${esc(label)}</button>`).join('')}</div><div class="inspector-body" id="telemetry-inspector-panel" role="tabpanel">${body}</div>`;
}

function telemetryInspectorBody(trace, events) {
  const event = events[telemetryState.eventIndex]?.event || null;
  const selectedSpan = collectRenderableSpans(trace).find(entry => entry.key === telemetryState.selectedSpanKey);
  const span = selectedSpan?.span || null;
  let body = '';
  if (telemetryState.inspectorTab === 'payload') {
    body = inspectorJson(event?.payload ?? {}, 'No event payload is available.');
  } else if (telemetryState.inspectorTab === 'span') {
    body = span ? inspectorJson(span) : '<div class="empty-muted">Select a span in the waterfall.</div>';
  } else if (telemetryState.inspectorTab === 'json') {
    body = inspectorJson(trace);
  } else {
    const cost = trace.metadata?.llm_metrics?.total_cost;
    const currency = trace.metadata?.llm_metrics?.currency;
    body = `
      <div class="detail-grid">
        <div class="detail-item"><div class="detail-label">Started</div><div class="detail-value">${esc(timestampLabel(trace.started_at))}</div></div>
        <div class="detail-item"><div class="detail-label">Ended</div><div class="detail-value">${esc(timestampLabel(trace.ended_at))}</div></div>
        <div class="detail-item"><div class="detail-label">Agent</div><div class="detail-value">${esc(boundedDisplayText(trace.agent_name))}</div></div>
        <div class="detail-item"><div class="detail-label">Final state</div><div class="detail-value">${esc(boundedDisplayText(trace.metadata?.final_state || trace.status))}</div></div>
        <div class="detail-item"><div class="detail-label">Selected event</div><div class="detail-value">${esc(boundedDisplayText(event?.type, 'none'))}</div></div>
        <div class="detail-item"><div class="detail-label">Selected span</div><div class="detail-value">${esc(boundedDisplayText(span?.name, 'none'))}</div></div>
        <div class="detail-item"><div class="detail-label">Estimated cost</div><div class="detail-value">${cost == null ? '—' : `${esc(boundedDisplayText(cost, '', 80))} ${esc(boundedDisplayText(currency, '', 24))}`}</div></div>
        <div class="detail-item"><div class="detail-label">Correlation</div><div class="detail-value">${esc((telemetryState.records || []).filter(record => record.trace_id && record.trace_id === trace.trace_id).length)} loaded task record(s)</div></div>
      </div>
    `;
  }
  return body;
}

function inspectorJson(value, emptyMessage = 'No data is available.') {
  if (value == null) return `<div class="empty-muted">${esc(emptyMessage)}</div>`;
  const preview = jsonPreview(value, TELEMETRY_JSON_PREVIEW_CHARS);
  return `<pre class="inspector-json">${esc(preview.text)}</pre>${preview.truncated ? `<div class="trace-limit-note">Preview is structurally bounded (up to ${formatCompactNumber(TELEMETRY_JSON_PREVIEW_CHARS)} characters) for responsiveness. The source file is unchanged.</div>` : ''}`;
}

function jsonPreview(value, limit) {
  const state = {nodes: 0, maxNodes: 260, maxString: Math.max(160, Math.min(2400, Math.floor(limit / 4))), truncated: false, seen: new WeakSet()};
  const bounded = boundedPreviewValue(value, state, 0);
  let text;
  try { text = JSON.stringify(bounded, null, 2); }
  catch (_) {
    state.truncated = true;
    text = String(bounded);
  }
  if (text.length > limit) {
    state.truncated = true;
    text = text.slice(0, limit) + '\\n… preview truncated …';
  }
  return {text, truncated: state.truncated};
}

function boundedPreviewValue(value, state, depth) {
  if (value == null || typeof value === 'number' || typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    if (value.length <= state.maxString) return value;
    state.truncated = true;
    return value.slice(0, state.maxString) + '…';
  }
  if (typeof value !== 'object') return String(value);
  if (state.seen.has(value)) {
    state.truncated = true;
    return '[Circular]';
  }
  if (depth >= 6 || state.nodes >= state.maxNodes) {
    state.truncated = true;
    return Array.isArray(value) ? `[${value.length} items]` : '[Object]';
  }
  state.seen.add(value);
  state.nodes += 1;
  if (Array.isArray(value)) {
    const visible = value.slice(0, Math.min(value.length, 60)).map(item => boundedPreviewValue(item, state, depth + 1));
    if (value.length > visible.length) {
      state.truncated = true;
      visible.push(`… ${value.length - visible.length} more items`);
    }
    return visible;
  }
  const output = {};
  let visibleFields = 0;
  for (const key in value) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
    if (visibleFields >= 60 || state.nodes >= state.maxNodes) {
      state.truncated = true;
      output['…'] = 'additional fields omitted';
      break;
    }
    const safeKey = boundedSummaryText(key, 180);
    if (safeKey !== key) state.truncated = true;
    output[safeKey] = boundedPreviewValue(value[key], state, depth + 1);
    visibleFields += 1;
  }
  return output;
}

function eventSummary(event) {
  const payload = event?.payload && typeof event.payload === 'object' ? event.payload : {};
  const parts = [
    payload.model ? `model ${boundedDisplayText(payload.model, '', 120)}` : '',
    payload.tool ? `tool ${boundedDisplayText(payload.tool, '', 120)}` : '',
    payload.agent ? `agent ${boundedDisplayText(payload.agent, '', 120)}` : '',
    payload.step != null ? `step ${boundedDisplayText(payload.step, '', 48)}` : '',
    payload.latency_ms != null ? formatMilliseconds(payload.latency_ms) : '',
    boundedDisplayText(payload.message || payload.decision?.reason, '', 420),
  ].filter(Boolean);
  return boundedDisplayText(parts.join(' · '), 'Provider-neutral inference-loop event', 720);
}

function updateTelemetryReplayDom() {
  const trace = telemetryState.selectedTrace;
  if (!trace) return;
  const events = telemetryTimelineEvents(trace);
  if (!events.length) return;
  telemetryState.eventIndex = Math.max(0, Math.min(telemetryState.eventIndex, events.length - 1));
  const range = document.getElementById('telemetry-event-range');
  if (range) {
    range.max = String(events.length - 1);
    range.value = String(telemetryState.eventIndex);
  }
  const count = document.getElementById('telemetry-event-count');
  if (count) count.textContent = telemetryEventCountLabel(trace, events);
  const play = document.getElementById('telemetry-play');
  if (play) {
    play.textContent = telemetryState.eventTimer ? 'Pause' : 'Play';
    play.setAttribute('aria-label', `${telemetryState.eventTimer ? 'Pause' : 'Play'} event replay`);
  }
  const focus = document.getElementById('telemetry-event-focus');
  if (focus) {
    focus.className = telemetryEventFocusClass(events[telemetryState.eventIndex]?.event);
    focus.innerHTML = telemetryEventFocusHtml(trace, events);
  }
  const rail = document.getElementById('telemetry-event-rail');
  if (rail) {
    const buttons = [...rail.querySelectorAll('button')];
    for (const [index, button] of buttons.entries()) {
      const active = index === telemetryState.eventIndex;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    }
    buttons[telemetryState.eventIndex]?.scrollIntoView({block: 'nearest'});
  }
  if (telemetryState.inspectorTab === 'summary' || telemetryState.inspectorTab === 'payload') {
    updateTelemetryInspectorDom();
  }
}

function updateTelemetryInspectorDom() {
  const trace = telemetryState.selectedTrace;
  if (!trace) return;
  const events = telemetryTimelineEvents(trace);
  const tabs = document.getElementById('telemetry-inspector-tabs');
  if (tabs) {
    for (const button of tabs.querySelectorAll('[data-inspector-tab]')) {
      const active = button.dataset.inspectorTab === telemetryState.inspectorTab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    }
  }
  const panel = document.getElementById('telemetry-inspector-panel');
  if (panel) panel.innerHTML = telemetryInspectorBody(trace, events);
}

async function selectTelemetryRecord(recordId) {
  if (!recordId) return;
  stopTelemetryPlayback();
  const sourceGeneration = telemetryState.sourceGeneration;
  const detailGeneration = ++telemetryState.detailGeneration;
  telemetryState.selectedRecordId = recordId;
  telemetryState.selectedTrace = null;
  telemetryState.selectedSpanKey = null;
  telemetryState.error = null;
  telemetryState.eventIndex = 0;
  telemetryState.inspectorTab = 'summary';
  if (telemetryState.mode === 'snapshot') {
    telemetryState.loadingDetail = false;
    renderTelemetryList();
    renderTelemetryWorkbench();
    return;
  }
  telemetryState.loadingDetail = true;
  renderTelemetryList();
  renderTelemetryWorkbench();
  try {
    let trace;
    if (telemetryState.mode === 'upload') {
      const summary = telemetryState.records.find(record => record.record_id === recordId);
      if (!summary || !telemetryState.uploadFile) throw new Error('Uploaded trace record is no longer available.');
      if (Number(summary.length) > TELEMETRY_DETAIL_MAX_BYTES) {
        throw new Error(`This trace record exceeds the ${formatBytes(TELEMETRY_DETAIL_MAX_BYTES)} browser detail limit.`);
      }
      const raw = await telemetryState.uploadFile.slice(summary.offset, summary.offset + summary.length).text();
      trace = JSON.parse(raw);
    } else if (telemetryState.mode === 'server') {
      const response = await fetch('/api/traces/' + encodeURIComponent(recordId), {cache: 'no-store'});
      const payload = await response.json();
      if (!response.ok || payload.error) throw new Error(payload.error || `Trace request failed (${response.status})`);
      trace = payload.trace;
    } else {
      throw new Error('Load a telemetry JSONL file first.');
    }
    if (
      sourceGeneration !== telemetryState.sourceGeneration
      || detailGeneration !== telemetryState.detailGeneration
      || telemetryState.selectedRecordId !== recordId
    ) return;
    if (!trace || typeof trace !== 'object' || Array.isArray(trace)) throw new Error('The selected JSONL record is not a trace object.');
    telemetryState.selectedTrace = trace;
    telemetryState.selectedSpanKey = null;
  } catch (error) {
    if (
      sourceGeneration !== telemetryState.sourceGeneration
      || detailGeneration !== telemetryState.detailGeneration
    ) return;
    telemetryState.error = error?.message || String(error);
  } finally {
    if (
      sourceGeneration !== telemetryState.sourceGeneration
      || detailGeneration !== telemetryState.detailGeneration
    ) return;
    telemetryState.loadingDetail = false;
    renderTelemetry();
  }
}

function selectTelemetrySpan(spanKey) {
  telemetryState.selectedSpanKey = boundedSummaryText(spanKey, 64);
  telemetryState.inspectorTab = 'span';
  const waterfall = document.getElementById('telemetry-span-waterfall');
  for (const button of waterfall?.querySelectorAll('.span-row[data-span-key]') || []) {
    const active = button.dataset.spanKey === telemetryState.selectedSpanKey;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
  }
  updateTelemetryInspectorDom();
}

function handleTelemetrySpanKeydown(event) {
  if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
  const buttons = [...event.currentTarget.querySelectorAll('.span-row[data-span-key]')];
  if (!buttons.length) return;
  const current = Math.max(0, buttons.indexOf(document.activeElement));
  const next = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? buttons.length - 1
      : Math.max(0, Math.min(buttons.length - 1, current + (event.key === 'ArrowDown' ? 1 : -1)));
  event.preventDefault();
  const button = buttons[next];
  selectTelemetrySpan(button.dataset.spanKey);
  button.focus();
}

function setTelemetryInspectorTab(tab) {
  telemetryState.inspectorTab = tab;
  updateTelemetryInspectorDom();
}

function handleTelemetryInspectorKeydown(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const tabs = [...event.currentTarget.querySelectorAll('[data-inspector-tab]')];
  if (!tabs.length) return;
  const current = Math.max(0, tabs.indexOf(document.activeElement));
  const next = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? tabs.length - 1
      : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault();
  const button = tabs[next];
  setTelemetryInspectorTab(button.dataset.inspectorTab);
  button.focus();
}

function setTelemetryEventIndex(index) {
  stopTelemetryPlayback();
  const events = telemetryTimelineEvents(telemetryState.selectedTrace || {});
  telemetryState.eventIndex = Math.max(0, Math.min(Number(index) || 0, Math.max(0, events.length - 1)));
  updateTelemetryReplayDom();
}

function stepTelemetryEvent(delta) {
  const events = telemetryTimelineEvents(telemetryState.selectedTrace || {});
  if (!events.length) return;
  stopTelemetryPlayback();
  telemetryState.eventIndex = Math.max(0, Math.min(events.length - 1, telemetryState.eventIndex + Number(delta || 0)));
  updateTelemetryReplayDom();
}

function toggleTelemetryPlayback() {
  if (telemetryState.eventTimer) {
    stopTelemetryPlayback();
    updateTelemetryReplayDom();
    return;
  }
  const events = telemetryTimelineEvents(telemetryState.selectedTrace || {});
  if (!events.length) return;
  if (telemetryState.eventIndex >= events.length - 1) telemetryState.eventIndex = 0;
  telemetryState.eventTimer = window.setInterval(() => {
    if (telemetryState.eventIndex >= events.length - 1) {
      stopTelemetryPlayback();
    } else {
      telemetryState.eventIndex += 1;
    }
    updateTelemetryReplayDom();
  }, telemetryState.eventSpeed);
  updateTelemetryReplayDom();
}

function stopTelemetryPlayback() {
  if (telemetryState?.eventTimer) window.clearInterval(telemetryState.eventTimer);
  if (telemetryState) telemetryState.eventTimer = null;
}

function setTelemetrySpeed(value) {
  const wasPlaying = Boolean(telemetryState.eventTimer);
  stopTelemetryPlayback();
  telemetryState.eventSpeed = Number(value) || 950;
  if (wasPlaying) toggleTelemetryPlayback();
  else updateTelemetryReplayDom();
}

async function reloadTelemetry() {
  stopTelemetryPlayback();
  const sourceGeneration = ++telemetryState.sourceGeneration;
  telemetryState.detailGeneration += 1;
  if (telemetryState.mode === 'snapshot') {
    telemetryState.error = 'Static telemetry summaries cannot refresh or load detail. Open the matching JSONL file in this tab.';
    renderTelemetry();
    return;
  }
  telemetryState.error = null;
  telemetryState.selectedRecordId = null;
  telemetryState.selectedTrace = null;
  telemetryState.selectedSpanKey = null;
  telemetryState.loadingDetail = false;
  telemetryState.windowShifted = false;
  if (telemetryState.mode === 'upload' && telemetryState.uploadFile) {
    telemetryState.loadingPage = true;
    renderTelemetry();
    try {
      const page = await readUploadTracePage(telemetryState.uploadFile, telemetryState.uploadFile.size, TELEMETRY_PAGE_SIZE);
      if (sourceGeneration !== telemetryState.sourceGeneration) return;
      applyTelemetryPage(page, true);
    } catch (error) {
      if (sourceGeneration !== telemetryState.sourceGeneration) return;
      telemetryState.error = error?.message || String(error);
    } finally {
      if (sourceGeneration !== telemetryState.sourceGeneration) return;
      telemetryState.loadingPage = false;
      renderTelemetry();
    }
    return;
  }
  if (telemetryState.mode === 'server') {
    await fetchTelemetryPage(null, true, sourceGeneration);
    return;
  }
  await refresh();
}

async function loadOlderTelemetry() {
  if (telemetryState.loadingPage || telemetryState.nextCursor == null) return;
  if (telemetryState.mode === 'upload' && telemetryState.uploadFile) {
    const sourceGeneration = telemetryState.sourceGeneration;
    const sourceFile = telemetryState.uploadFile;
    telemetryState.loadingPage = true;
    renderTelemetryList();
    try {
      const page = await readUploadTracePage(sourceFile, telemetryState.nextCursor, TELEMETRY_PAGE_SIZE);
      if (sourceGeneration !== telemetryState.sourceGeneration || telemetryState.uploadFile !== sourceFile) return;
      applyTelemetryPage(page, false);
    } catch (error) {
      if (sourceGeneration !== telemetryState.sourceGeneration) return;
      telemetryState.error = error?.message || String(error);
    } finally {
      if (sourceGeneration !== telemetryState.sourceGeneration) return;
      telemetryState.loadingPage = false;
      renderTelemetry();
    }
    return;
  }
  if (telemetryState.mode === 'server') {
    await fetchTelemetryPage(telemetryState.nextCursor, false, telemetryState.sourceGeneration);
  }
}

async function fetchTelemetryPage(cursor, replace, sourceGeneration = telemetryState.sourceGeneration) {
  telemetryState.loadingPage = true;
  telemetryState.error = null;
  renderTelemetry();
  try {
    const params = new URLSearchParams({limit: String(TELEMETRY_PAGE_SIZE)});
    if (cursor != null) params.set('cursor', String(cursor));
    const response = await fetch('/api/traces?' + params.toString(), {cache: 'no-store'});
    const page = await response.json();
    if (!response.ok || page.error) throw new Error(page.error || `Trace page request failed (${response.status})`);
    if (sourceGeneration !== telemetryState.sourceGeneration) return;
    telemetryState.mode = 'server';
    applyTelemetryPage(page, replace);
  } catch (error) {
    if (sourceGeneration !== telemetryState.sourceGeneration) return;
    telemetryState.error = error?.message || String(error);
  } finally {
    if (sourceGeneration !== telemetryState.sourceGeneration) return;
    telemetryState.loadingPage = false;
    renderTelemetry();
  }
}

function applyTelemetryPage(page, replace) {
  const previousSource = telemetryState.source || {};
  const incoming = Array.isArray(page.records) ? page.records : [];
  const combined = replace ? incoming : [...telemetryState.records, ...incoming];
  const seen = new Set();
  const deduplicated = combined.filter(record => {
    if (!record?.record_id || seen.has(record.record_id)) return false;
    seen.add(record.record_id);
    return true;
  });
  const overflow = Math.max(0, deduplicated.length - TELEMETRY_SUMMARY_CAP);
  telemetryState.records = replace
    ? deduplicated.slice(0, TELEMETRY_SUMMARY_CAP)
    : deduplicated.slice(overflow);
  telemetryState.windowShifted = replace ? false : telemetryState.windowShifted || overflow > 0;
  if (
    telemetryState.selectedRecordId
    && !telemetryState.records.some(record => record.record_id === telemetryState.selectedRecordId)
  ) {
    telemetryState.detailGeneration += 1;
    telemetryState.selectedRecordId = null;
    telemetryState.selectedTrace = null;
    telemetryState.selectedSpanKey = null;
    telemetryState.loadingDetail = false;
  }
  telemetryState.nextCursor = page.next_cursor ?? null;
  telemetryState.source = {
    ...previousSource,
    path: page.path ?? previousSource.path,
    configured: page.configured == null ? true : Boolean(page.configured),
    is_file: page.is_file == null ? previousSource.is_file : Boolean(page.is_file),
    size_bytes: page.size_bytes ?? previousSource.size_bytes,
    modified_at: page.modified_at ?? previousSource.modified_at,
    malformed_count: replace
      ? Number(page.malformed_count || 0)
      : Number(previousSource.malformed_count || 0) + Number(page.malformed_count || 0),
    oversized_count: replace
      ? Number(page.oversized_count || 0)
      : Number(previousSource.oversized_count || 0) + Number(page.oversized_count || 0),
    partial_tail: replace ? Boolean(page.partial_tail) : Boolean(previousSource.partial_tail || page.partial_tail),
    scan_exhausted: replace ? Boolean(page.scan_exhausted) : Boolean(previousSource.scan_exhausted || page.scan_exhausted),
    exists: page.exists == null ? true : Boolean(page.exists),
  };
}

function openTelemetryFile() {
  document.getElementById('telemetry-file')?.click();
}

function telemetryDrag(event, active) {
  event.preventDefault();
  if (event.type === 'dragleave' && event.currentTarget.contains(event.relatedTarget)) return;
  document.getElementById('telemetry-drop')?.classList.toggle('dragging', active);
}

function dropTelemetryFile(event) {
  event.preventDefault();
  document.getElementById('telemetry-drop')?.classList.remove('dragging');
  const file = event.dataTransfer?.files?.[0];
  if (file) handleTelemetryFile(file);
}

async function handleTelemetryFile(file) {
  if (!file) return;
  stopTelemetryPlayback();
  const sourceGeneration = ++telemetryState.sourceGeneration;
  telemetryState.detailGeneration += 1;
  telemetryState.mode = 'upload';
  telemetryState.uploadFile = file;
  telemetryState.source = {
    configured: true,
    exists: true,
    path: file.name,
    size_bytes: file.size,
    modified_at: file.lastModified,
    malformed_count: 0,
    partial_tail: false,
  };
  telemetryState.records = [];
  telemetryState.nextCursor = null;
  telemetryState.selectedRecordId = null;
  telemetryState.selectedTrace = null;
  telemetryState.selectedSpanKey = null;
  telemetryState.loadingDetail = false;
  telemetryState.error = null;
  telemetryState.loadingPage = true;
  telemetryState.windowShifted = false;
  renderTelemetry();
  try {
    const page = await readUploadTracePage(file, file.size, TELEMETRY_PAGE_SIZE);
    if (sourceGeneration !== telemetryState.sourceGeneration || telemetryState.uploadFile !== file) return;
    applyTelemetryPage(page, true);
    if (!page.records.length && page.oversized_count) {
      throw new Error(`No readable trace records were found within the ${formatBytes(TELEMETRY_DETAIL_MAX_BYTES)} per-record safety limit.`);
    }
    if (!page.records.length && !page.partial_tail && page.next_cursor == null) {
      throw new Error('No valid Protolink trace records were found in this file.');
    }
  } catch (error) {
    if (sourceGeneration !== telemetryState.sourceGeneration) return;
    telemetryState.error = error?.message || String(error);
  } finally {
    if (sourceGeneration !== telemetryState.sourceGeneration) return;
    telemetryState.loadingPage = false;
    const input = document.getElementById('telemetry-file');
    if (input) input.value = '';
    renderTelemetry();
  }
}

async function readUploadTracePage(file, before, limit) {
  if (before && typeof before === 'object' && before.kind === 'skip-line') {
    return continueUploadSkippedLine(file, before);
  }
  const requestedEnd = before == null ? file.size : Number(before);
  const end = Math.max(0, Math.min(Number.isFinite(requestedEnd) ? requestedEnd : file.size, file.size));
  const chunkSize = 256 * 1024;
  const scanCap = 32 * 1024 * 1024;
  let base = end;
  let scannedBytes = 0;
  let newlineCount = 0;
  let targetLines = limit + 1;
  const chunks = [];
  let result = {records: [], next_cursor: null, malformed_count: 0, oversized_count: 0, partial_tail: false};
  while (base > 0 && scannedBytes < scanCap) {
    const readSize = Math.min(chunkSize, base, scanCap - scannedBytes);
    const start = base - readSize;
    const chunk = new Uint8Array(await file.slice(start, base).arrayBuffer());
    chunks.unshift(chunk);
    scannedBytes += chunk.length;
    newlineCount += countByte(chunk, 10);
    base = start;
    if (newlineCount >= targetLines || base === 0 || scannedBytes >= scanCap) {
      result = scanUploadTraceBytes(joinByteChunks(chunks, scannedBytes), base, end, file.size, limit);
      if (result.records.length >= limit || result.line_scan_exhausted || base === 0) break;
      targetLines = Math.max(
        newlineCount + Math.max(8, limit - result.records.length),
        Math.ceil(newlineCount * 2),
        targetLines * 2,
      );
    }
  }
  if (!result.records.length && scannedBytes >= scanCap && base > 0 && result.next_cursor == null) {
    throw new Error('No complete trace record was found in the 32 MB scan window. The next JSONL line may be unusually large.');
  }
  return {
    ...result,
    size_bytes: file.size,
    modified_at: file.lastModified,
  };
}

async function continueUploadSkippedLine(file, cursor) {
  const chunkSize = 256 * 1024;
  const scanCap = 32 * 1024 * 1024;
  const initialBefore = Math.max(0, Math.min(Number(cursor.before) || 0, file.size));
  let position = initialBefore;
  let scannedBytes = 0;
  let skippedLineBytes = Math.max(0, Number(cursor.skipped_line_bytes) || 0);
  while (position > 0 && scannedBytes < scanCap) {
    const readSize = Math.min(chunkSize, position, scanCap - scannedBytes);
    const start = position - readSize;
    const chunk = new Uint8Array(await file.slice(start, position).arrayBuffer());
    scannedBytes += chunk.length;
    const newline = chunk.lastIndexOf(10);
    if (newline >= 0) {
      const boundary = start + newline + 1;
      skippedLineBytes += initialBefore - boundary;
      const partialTail = Boolean(cursor.partial_tail);
      return {
        records: [],
        next_cursor: boundary > 0 ? boundary : null,
        malformed_count: !partialTail && skippedLineBytes <= TELEMETRY_DETAIL_MAX_BYTES ? 1 : 0,
        oversized_count: !partialTail && skippedLineBytes > TELEMETRY_DETAIL_MAX_BYTES ? 1 : 0,
        partial_tail: partialTail,
        scan_exhausted: false,
        size_bytes: file.size,
        modified_at: file.lastModified,
      };
    }
    position = start;
  }
  skippedLineBytes += initialBefore - position;
  const partialTail = Boolean(cursor.partial_tail);
  if (position === 0) {
    return {
      records: [],
      next_cursor: null,
      malformed_count: !partialTail && skippedLineBytes <= TELEMETRY_DETAIL_MAX_BYTES ? 1 : 0,
      oversized_count: !partialTail && skippedLineBytes > TELEMETRY_DETAIL_MAX_BYTES ? 1 : 0,
      partial_tail: partialTail,
      scan_exhausted: false,
      size_bytes: file.size,
      modified_at: file.lastModified,
    };
  }
  return {
    records: [],
    next_cursor: {
      kind: 'skip-line',
      before: position,
      skipped_line_bytes: skippedLineBytes,
      partial_tail: partialTail,
    },
    malformed_count: 0,
    oversized_count: 0,
    partial_tail: partialTail,
    scan_exhausted: true,
    size_bytes: file.size,
    modified_at: file.lastModified,
  };
}

function countByte(data, byte) {
  let count = 0;
  for (const value of data) if (value === byte) count += 1;
  return count;
}

function joinByteChunks(chunks, size) {
  const joined = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.length;
  }
  return joined;
}

function scanUploadTraceBytes(data, base, end, fileSize, limit) {
  const maxScannedLines = 5000;
  const decoder = new TextDecoder('utf-8', {fatal: true});
  let localEnd = data.length;
  let partialTail = false;
  let malformed = 0;
  let oversized = 0;
  let scannedLines = 0;
  let blockedPrefix = false;
  let blockedPartialTail = false;
  let blankPrefix = false;
  let safePrefixBoundary = null;
  let oldestHandledOffset = null;
  let knownLineEnd = false;
  if (end === fileSize && localEnd && data[localEnd - 1] !== 10) {
    partialTail = true;
    const newline = previousByte(data, 10, localEnd - 1);
    if (newline < 0 && base > 0) {
      blockedPrefix = true;
      blockedPartialTail = true;
    }
    localEnd = newline >= 0 ? newline + 1 : 0;
  }
  const records = [];
  let oldestOffset = null;
  while (localEnd > 0 && records.length < limit && scannedLines < maxScannedLines) {
    const beforeTrim = localEnd;
    while (localEnd > 0 && (data[localEnd - 1] === 10 || data[localEnd - 1] === 13)) localEnd -= 1;
    if (localEnd < beforeTrim) knownLineEnd = true;
    if (localEnd <= 0) {
      if (base > 0 && !blockedPrefix) blankPrefix = true;
      break;
    }
    const newline = previousByte(data, 10, localEnd - 1);
    const lineStart = newline + 1;
    if (lineStart === 0 && base > 0) {
      if (knownLineEnd) safePrefixBoundary = base + localEnd;
      else blockedPrefix = true;
      break;
    }
    let raw = data.subarray(lineStart, localEnd);
    if (raw.length && raw[raw.length - 1] === 13) raw = raw.subarray(0, raw.length - 1);
    const offset = base + lineStart;
    scannedLines += 1;
    oldestHandledOffset = offset;
    if (raw.length > TELEMETRY_DETAIL_MAX_BYTES) {
      oversized += 1;
      localEnd = newline;
      continue;
    }
    try {
      const trace = JSON.parse(decoder.decode(raw));
      if (!trace || typeof trace !== 'object' || Array.isArray(trace)) throw new Error('not an object');
      const summary = summarizeUploadTrace(trace, offset, raw.length);
      records.push(summary);
      oldestOffset = offset;
    } catch (_) {
      malformed += 1;
    }
    localEnd = newline;
    knownLineEnd = true;
  }
  const lineScanExhausted = scannedLines >= maxScannedLines && (localEnd > 0 || base > 0);
  return {
    records,
    next_cursor: safePrefixBoundary != null
      ? safePrefixBoundary
      : blockedPrefix
        ? {
            kind: 'skip-line',
            before: base,
            skipped_line_bytes: end - base,
            partial_tail: blockedPartialTail,
          }
        : blankPrefix
          ? base
          : lineScanExhausted && oldestHandledOffset != null
            ? oldestHandledOffset
          : oldestOffset != null && oldestOffset > 0
            ? oldestOffset
            : null,
    malformed_count: malformed,
    oversized_count: oversized,
    partial_tail: partialTail,
    scan_exhausted: blockedPrefix || blankPrefix || safePrefixBoundary != null || lineScanExhausted,
    line_scan_exhausted: lineScanExhausted,
  };
}

function previousByte(data, byte, beforeIndex) {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    if (data[index] === byte) return index;
  }
  return -1;
}

function summarizeUploadTrace(trace, offset, length, forcedId) {
  const spans = Array.isArray(trace.spans) ? trace.spans : [];
  const events = Array.isArray(trace.events) ? trace.events : [];
  const summarySpans = spans.slice(0, 2000);
  const models = [...new Set(summarySpans.map(span => span?.metadata?.model).filter(Boolean).map(value => boundedSummaryText(value, 256)))].slice(0, 5);
  const spanKinds = [...new Set(summarySpans.map(span => span?.kind).filter(Boolean).map(value => boundedSummaryText(value, 128)))].slice(0, 8);
  const rawMetrics = trace.metadata?.llm_metrics && typeof trace.metadata.llm_metrics === 'object'
    ? trace.metadata.llm_metrics
    : {};
  const metricKeys = [
    'call_count', 'total_latency_ms', 'total_input_tokens', 'total_output_tokens', 'total_tokens',
    'estimated_token_calls', 'total_cost', 'currency', 'max_context_used_percent',
    'max_context_used_tokens', 'context_window_tokens',
  ];
  const llmMetrics = {};
  for (const key of metricKeys) {
    const value = rawMetrics[key];
    if (typeof value === 'number' && Number.isFinite(value)) llmMetrics[key] = value;
    else if (typeof value === 'string') llmMetrics[key] = boundedSummaryText(value, 128);
  }
  return {
    record_id: forcedId || `upload-${offset}-${length}`,
    offset,
    length,
    trace_id: optionalSummaryText(trace.trace_id),
    task_id: optionalSummaryText(trace.task_id),
    agent_name: optionalSummaryText(trace.agent_name),
    started_at: optionalSummaryText(trace.started_at),
    ended_at: optionalSummaryText(trace.ended_at),
    duration_ms: Number.isFinite(Number(trace.duration_ms)) ? Number(trace.duration_ms) : null,
    status: optionalSummaryText(trace.status),
    final_state: optionalSummaryText(trace.metadata?.final_state),
    span_count: spans.length,
    event_count: events.length,
    span_kinds: spanKinds,
    models,
    llm_metrics: llmMetrics,
  };
}

function boundedSummaryText(value, limit = 512) {
  const text = String(value ?? '');
  return text.length <= limit ? text : text.slice(0, limit - 1) + '…';
}

function boundedDisplayText(value, fallback = '-', limit = 160) {
  if (value == null || value === '') return fallback;
  return boundedSummaryText(value, Math.max(8, limit));
}

function optionalSummaryText(value) {
  return value == null || value === '' ? null : boundedSummaryText(value);
}

function summaryModels(record) {
  return Array.isArray(record?.models) ? record.models.map(String) : [];
}

function summarySpanKinds(record) {
  if (Array.isArray(record?.span_kinds)) return record.span_kinds.map(String);
  if (record?.span_kinds && typeof record.span_kinds === 'object') return Object.keys(record.span_kinds);
  return [];
}

function traceKindClass(kind) {
  const value = boundedSummaryText(kind, 64).toLowerCase().replace(/_/g, '-');
  return ['llm', 'tool', 'agent-call'].includes(value) ? value : 'task';
}

function timestampMs(value) {
  if (value == null || value === '') return Number.NaN;
  const text = typeof value === 'string' ? boundedSummaryText(value) : String(value);
  const numeric = Number(text);
  if (Number.isFinite(numeric) && text.trim() !== '') return numeric < 1e12 ? numeric * 1000 : numeric;
  return new Date(text).getTime();
}

function formatMilliseconds(value) {
  const ms = numericValue(value);
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatBytes(value) {
  const bytes = numericValue(value);
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let amount = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  return `${amount.toFixed(amount < 10 ? 1 : 0)} ${unit}`;
}

function formatCompactNumber(value) {
  const number = numericValue(value);
  if (!Number.isFinite(number)) return '0';
  return Intl.NumberFormat(undefined, {notation: Math.abs(number) >= 1000 ? 'compact' : 'standard', maximumFractionDigits: 1}).format(number);
}

function numericValue(value) {
  if (typeof value === 'string' && value.length > 128) return Number.NaN;
  return Number(value);
}

function shortId(value, limit = 20) {
  const text = String(value || '-');
  if (text.length <= limit) return text;
  const head = Math.ceil((limit - 1) * .58);
  return text.slice(0, head) + '…' + text.slice(-(limit - head - 1));
}

function relativeTime(value) {
  const ms = timestampMs(value);
  if (!Number.isFinite(ms)) return String(value || '');
  const delta = Date.now() - ms;
  if (Math.abs(delta) < 60000) return 'updated just now';
  if (delta >= 0 && delta < 3600000) return `updated ${Math.floor(delta / 60000)}m ago`;
  return new Date(ms).toLocaleString();
}

function metric(label, value, hint, accent, view, iconName) {
  const action = view ? ` onclick="showView(${jsStringAttr(view)})"` : '';
  return `<button type="button" class="metric" data-accent="${esc(accent || 'teal')}"${action}><div class="metric-top"><div class="label">${esc(label)}</div><span class="metric-icon">${icon(iconName || 'dashboard')}</span></div><div class="value">${cellHtml(value)}</div><div class="hint">${esc(hint || '')}</div></button>`;
}
function storeStateHtml(isOn, error) {
  const state = isOn && !error ? 'on' : 'off';
  const dot = isOn && !error ? 'online' : 'offline';
  return `<span class="store-state ${state}">${statusDotHtml(dot)}${esc(state)}</span>`;
}
function agentKey(agent) { return agent?.url || agent?.name || 'agent'; }
function isHttpAgent(agent) { return /^https?:\\/\\//.test(String(agent.url || '')); }
function hasChat(agent) { return Boolean(agent.capabilities?.has_llm); }
function endpoint(agent, path) { return String(agent.url || '').replace(/\\/+$/, '') + path; }
function pick(source, ...keys) {
  for (const key of keys) {
    if (source && source[key] !== undefined && source[key] !== null && source[key] !== '') return source[key];
  }
  return null;
}
function protocolVersion(agent) { return pick(agent, 'protocol_version', 'protocolVersion') || '-'; }
function listField(agent, snake, camel, fallback = []) {
  const value = pick(agent, snake, camel);
  if (Array.isArray(value)) return value;
  if (typeof value === 'string' && value) return [value];
  return fallback;
}
function initials(value) {
  const text = String(value || 'agent').replace(/[_-]+/g, ' ').trim();
  const parts = text.split(/\\s+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : text.slice(0, 2)).toUpperCase();
}
function formatDuration(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return '-';
  const whole = Math.round(total);
  const days = Math.floor(whole / 86400);
  const hours = Math.floor((whole % 86400) / 3600);
  const mins = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${mins}m`;
  if (mins) return `${mins}m ${secs}s`;
  return `${secs}s`;
}
function timestampLabel(value) {
  if (value == null || value === '') return '-';
  const text = typeof value === 'string' ? boundedSummaryText(value) : String(value);
  const parsed = timestampMs(value);
  const date = Number.isFinite(parsed) ? new Date(parsed) : new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString();
}
function agentUptime(agent) {
  const item = health[agentKey(agent)] || {};
  const metadata = agent.metadata || {};
  const uptime = pick(item, 'uptime_seconds', 'uptimeSeconds') ?? pick(agent, 'uptime_seconds', 'uptimeSeconds') ?? pick(metadata, 'uptime_seconds', 'uptimeSeconds');
  if (uptime !== null) return {value: formatDuration(uptime), hint: 'from status probe'};
  const start = pick(item, 'start_time', 'startTime') ?? pick(agent, 'start_time', 'startTime') ?? pick(metadata, 'start_time', 'startTime');
  if (start !== null) return {value: formatDuration(Date.now() / 1000 - Number(start)), hint: timestampLabel(start)};
  return {value: 'not reported', hint: isHttpAgent(agent) ? 'ping agent to refresh' : 'runtime snapshot'};
}
function pillList(items, empty = 'none') {
  const values = (items || []).map(item => String(item)).filter(Boolean);
  if (!values.length) return `<span class="pill idle">${esc(empty)}</span>`;
  return values.map(item => `<span class="pill">${esc(item)}</span>`).join('');
}
function capabilityPills(caps) {
  const entries = Object.entries(caps || {}).filter(([, value]) => value === true || (typeof value === 'number' && value > 0) || (typeof value === 'string' && value));
  if (!entries.length) return '<span class="pill idle">none</span>';
  return entries.map(([key, value]) => {
    const label = value === true ? key : `${key}: ${value}`;
    return `<span class="pill capability-badge">${esc(label)}</span>`;
  }).join('');
}
function capabilityBadges(caps) { return raw(`<div class="badge-row">${capabilityPills(caps)}</div>`); }
function transportKind(value) {
  const clean = String(value || '').toLowerCase().trim();
  if (!clean || clean === '-') return 'unknown';
  if (clean.startsWith('https')) return 'https';
  if (clean.startsWith('http')) return 'http';
  if (clean.includes('runtime')) return 'runtime';
  if (clean.includes('websocket')) return 'websocket';
  if (clean === 'ws') return 'ws';
  if (clean.includes('sse-json-rpc')) return 'sse-json-rpc';
  if (clean.includes('sse')) return 'sse';
  return clean.replace(/[^a-z0-9]+/g, '-') || 'unknown';
}
function transportBadge(value) {
  const label = String(value || '-');
  return raw(`<span class="transport-badge ${htmlAttr(transportKind(label))}">${esc(label)}</span>`);
}
function skillName(skill) { return typeof skill === 'string' ? skill : skill.id || skill.name || 'skill'; }
function skillDescription(skill) { return typeof skill === 'string' ? '' : skill.description || ''; }
function skillInputSchema(skill) { return typeof skill === 'string' ? {} : pick(skill, 'input_schema', 'inputSchema') || {}; }
function skillOutputSchema(skill) { return typeof skill === 'string' ? {} : pick(skill, 'output_schema', 'outputSchema') || {}; }
function hasSchema(schema) { return schema && typeof schema === 'object' && Object.keys(schema).length > 0; }
function schemaSummary(schema) {
  if (!hasSchema(schema)) return 'not advertised';
  const properties = schema.properties && typeof schema.properties === 'object' ? Object.keys(schema.properties) : [];
  const type = schema.type || 'schema';
  if (properties.length) return `${type} · ${properties.length} field${properties.length === 1 ? '' : 's'}`;
  return type;
}
function schemaBlock(schema, emptyText) {
  if (!hasSchema(schema)) return `<div class="empty-muted">${esc(emptyText)}</div>`;
  return `<pre class="schema-pre">${esc(JSON.stringify(schema, null, 2))}</pre>`;
}
function renderSkillSchemas(skills) {
  const normalized = skills || [];
  if (!normalized.length) return '<div class="empty-muted">No skills or schemas are advertised by this agent card.</div>';
  return `<div class="schema-grid">${normalized.map(skill => {
    const input = skillInputSchema(skill);
    const output = skillOutputSchema(skill);
    return `
      <div class="schema-card">
        <div class="schema-head">
          <div class="schema-title"><strong>${esc(skillName(skill))}</strong><span>${esc(skillDescription(skill) || 'No description')}</span></div>
          <span class="pill idle">${esc(schemaSummary(input))}</span>
        </div>
        <div class="schema-body">
          <div><div class="detail-label">Input schema</div>${schemaBlock(input, 'No input schema advertised.')}</div>
          <div><div class="detail-label">Output schema</div>${schemaBlock(output, 'No output schema advertised.')}</div>
        </div>
      </div>
    `;
  }).join('')}</div>`;
}
function healthStatus(agent) {
  const item = health[agentKey(agent)];
  if (item?.pending) return {state: 'pending', label: 'pinging', detail: 'status probe in flight'};
  if (!isHttpAgent(agent)) return {state: 'runtime', label: 'runtime', detail: 'in-process transport'};
  if (!item) return {state: 'unknown', label: 'unknown', detail: 'not pinged yet'};
  if (item.ok) return {state: 'online', label: `${item.latency_ms ?? '-'} ms`, detail: 'online'};
  return {state: 'offline', label: 'offline', detail: item.error || 'offline'};
}
function statusDotHtml(state) { return `<span class="status-dot ${htmlAttr(state || 'unknown')}"></span>`; }
function agentHealth(agent) {
  const status = healthStatus(agent);
  const cls = status.state === 'online' ? 'ok' : status.state === 'offline' ? 'error' : status.state === 'pending' ? 'warn' : 'idle';
  const label = status.state === 'offline' ? status.detail : status.label;
  return raw(`<span class="health-cell">${statusDotHtml(status.state)}<span class="pill ${cls}">${esc(label)}</span></span>`);
}
function agentCell(agent) {
  const status = healthStatus(agent);
  return raw(`
    <div class="agent-cell">
      <span class="agent-avatar">${esc(initials(agent.name || agent.url))}</span>
      <div class="agent-main">
        <div class="agent-name">${esc(agent.name || '-')}</div>
        <div class="agent-meta">${statusDotHtml(status.state)} ${esc(status.detail || status.label)}</div>
      </div>
    </div>
  `);
}
function agentActionButtons(agent, index, includeDetails) {
  const pingDisabled = isHttpAgent(agent) ? '' : ' disabled';
  const chatDisabled = isHttpAgent(agent) && hasChat(agent) ? '' : ' disabled';
  const status = isHttpAgent(agent) ? `<a class="mini-btn" data-icon="status" href="${esc(endpoint(agent, '/status'))}" target="_blank" rel="noreferrer">Status</a>` : '<button class="mini-btn" data-icon="status" disabled>Status</button>';
  const details = includeDetails ? `<button class="mini-btn" data-icon="details" onclick="selectAgent(${index})">Details</button>` : '';
  return raw(`<div class="actions">${details}<button class="mini-btn" data-icon="ping" onclick="pingAgent(${index})"${pingDisabled}>Ping</button><button class="mini-btn" data-icon="chat" onclick="openChat(${index})"${chatDisabled}>Chat</button>${status}</div>`);
}
function agentActions(agent, index) { return agentActionButtons(agent, index, true); }
function dashboardAgentActions(agent, index) { return agentActionButtons(agent, index, false); }
function agentHealthRow(agent, index) { return [agentCell(agent), agent.url || '-', agentHealth(agent), dashboardAgentActions(agent, index)]; }
function registryRow(agent, index) {
  return [agentCell(agent), transportBadge(agent.transport), agent.url || '-', capabilityBadges(agent.capabilities || {}), agentHealth(agent), agentActions(agent, index)];
}
function pill(value) { const cls = value === 'completed' ? 'ok' : value === 'failed' ? 'error' : value === 'canceled' ? 'warn' : ''; return raw(`<span class="pill ${cls}">${esc(value || '-')}</span>`); }
function table(headers, rows) {
  if (!rows.length) return '<div style="padding:14px;color:var(--muted);">(none)</div>';
  return `<table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cellHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
function raw(html) { return {__html: html}; }
function cellHtml(cell) { return cell && typeof cell === 'object' && '__html' in cell ? cell.__html : esc(cell); }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function htmlAttr(value) { return esc(value); }
function jsStringAttr(value) { return esc(JSON.stringify(String(value ?? ''))); }

function selectAgent(index) {
  const agents = snapshot.registry?.agents || [];
  selectedAgentIndex = Math.max(0, Math.min(Number(index) || 0, Math.max(agents.length - 1, 0)));
  renderAgentDetail();
}

function renderAgentDetail() {
  const agents = snapshot.registry?.agents || [];
  const agent = agents[selectedAgentIndex];
  const target = document.getElementById('agent-detail');
  if (!target) return;
  if (!agent) {
    target.innerHTML = '<div style="color:var(--muted);">No registry agents in this snapshot.</div>';
    return;
  }
  const status = healthStatus(agent);
  const uptime = agentUptime(agent);
  const skills = agent.skills || [];
  const tags = agent.tags || [];
  const inputFormats = listField(agent, 'input_formats', 'inputFormats', ['text/plain']);
  const outputFormats = listField(agent, 'output_formats', 'outputFormats', ['text/plain']);
  const security = pick(agent, 'security_schemes', 'securitySchemes') || {};
  const statusUrl = isHttpAgent(agent) ? endpoint(agent, '/status') : '';
  const chatDisabled = isHttpAgent(agent) && hasChat(agent) ? '' : ' disabled';
  const transportHtml = transportBadge(agent.transport).__html;
  target.innerHTML = `
    <div class="agent-detail-shell">
      <div class="agent-hero">
        <div class="agent-hero-main">
          <span class="agent-avatar">${esc(initials(agent.name || agent.url))}</span>
          <div>
            <h3>${esc(agent.name || '-')}</h3>
            <p>${esc(agent.description || 'No description advertised.')}</p>
            <div style="margin-top:10px;" class="tag-row">${pillList(tags, 'no tags')}</div>
          </div>
        </div>
        <div class="agent-hero-actions">
          <button class="mini-btn" data-icon="ping" onclick="pingAgent(${selectedAgentIndex})"${isHttpAgent(agent) ? '' : ' disabled'}>Ping</button>
          <button class="mini-btn" data-icon="chat" onclick="openChat(${selectedAgentIndex})"${chatDisabled}>Chat</button>
          ${statusUrl ? `<a class="mini-btn" data-icon="status" href="${esc(statusUrl)}" target="_blank" rel="noreferrer">Status</a>` : '<button class="mini-btn" data-icon="status" disabled>Status</button>'}
        </div>
      </div>

      <div class="agent-stat-grid">
        <div class="agent-stat"><div class="detail-label">Health</div><div class="detail-value">${statusDotHtml(status.state)} ${esc(status.detail || status.label)}</div></div>
        <div class="agent-stat"><div class="detail-label">Uptime</div><div class="detail-value">${esc(uptime.value)}</div><div class="agent-meta">${esc(uptime.hint)}</div></div>
        <div class="agent-stat"><div class="detail-label">Transport</div><div class="detail-value">${transportHtml}</div></div>
        <div class="agent-stat"><div class="detail-label">Protocol</div><div class="detail-value">${esc(protocolVersion(agent))}</div></div>
        <div class="agent-stat"><div class="detail-label">Role</div><div class="detail-value">${esc(agent.role || '-')}</div></div>
        <div class="agent-stat"><div class="detail-label">Version</div><div class="detail-value">${esc(agent.version || '-')}</div></div>
        <div class="agent-stat"><div class="detail-label">Inputs</div><div class="detail-value">${inputFormats.length}</div><div class="agent-meta">${esc(inputFormats.join(', '))}</div></div>
        <div class="agent-stat"><div class="detail-label">Outputs</div><div class="detail-value">${outputFormats.length}</div><div class="agent-meta">${esc(outputFormats.join(', '))}</div></div>
      </div>

      <div class="detail-item"><div class="detail-label">URL</div><div class="detail-value">${esc(agent.url || '-')}</div></div>

      <div>
        <div class="section-title"><h3>Capabilities</h3><span class="pill idle">${esc(Object.keys(agent.capabilities || {}).length)} advertised</span></div>
        <div class="tag-row">${capabilityPills(agent.capabilities || {})}</div>
      </div>

      <div>
        <div class="section-title"><h3>Security</h3><span class="pill idle">${esc(Object.keys(security).length)} scheme${Object.keys(security).length === 1 ? '' : 's'}</span></div>
        <div class="tag-row">${Object.keys(security).length ? Object.entries(security).map(([key, value]) => `<span class="pill">${esc(key)}${value?.type ? ` · ${esc(value.type)}` : ''}</span>`).join('') : '<span class="pill idle">none</span>'}</div>
      </div>

      <div>
        <div class="section-title"><h3>Skills and schemas</h3><span class="pill idle">${esc(skills.length)} skill${skills.length === 1 ? '' : 's'}</span></div>
        ${renderSkillSchemas(skills)}
      </div>
    </div>
  `;
  hydrateIcons(target);
}

async function pingAgent(index) {
  const agent = (snapshot.registry?.agents || [])[index];
  if (!agent) return;
  const key = agentKey(agent);
  if (!isHttpAgent(agent)) {
    health[key] = {ok: false, error: 'HTTP only'};
    render();
    return;
  }
  health[key] = {pending: true};
  render();
  try {
    const res = await fetch('/api/agents/ping', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: agent.url})
    });
    health[key] = await res.json();
  } catch (err) {
    health[key] = {ok: false, error: 'serve dashboard to ping'};
  }
  render();
}

async function pingAll() {
  const agents = snapshot.registry?.agents || [];
  for (let index = 0; index < agents.length; index++) {
    await pingAgent(index);
  }
}

function openChat(index) {
  selectChatAgent(index);
  showView('chat');
}

function selectChatAgent(index) {
  const agents = snapshot.registry?.agents || [];
  const nextIndex = Math.max(0, Math.min(Number(index) || 0, Math.max(agents.length - 1, 0)));
  if (nextIndex !== selectedAgentIndex) {
    chatRequestGeneration += 1;
    chatPending = false;
  }
  selectedAgentIndex = nextIndex;
  renderAgentDetail();
  renderChat();
}

function resetChat() {
  chatRequestGeneration += 1;
  chatMessages = [];
  chatPending = false;
  chatDebugStats = {sent: 0, latencies: [], lastLatency: null, lastError: null};
  chatSessionId = newChatSessionId();
  const sessionInput = document.getElementById('chat-session');
  const input = document.getElementById('chat-input');
  if (sessionInput) sessionInput.value = chatSessionId;
  if (input) input.value = '';
  renderChat();
}

function renderChat() {
  const agents = snapshot.registry?.agents || [];
  const select = document.getElementById('chat-agent-select');
  if (!select) return;
  selectedAgentIndex = Math.max(0, Math.min(selectedAgentIndex, Math.max(agents.length - 1, 0)));
  const sessionInput = document.getElementById('chat-session');
  if (!sessionInput.value) sessionInput.value = chatSessionId;
  chatSessionId = sessionInput.value || chatSessionId;
  select.innerHTML = agents.map((agent, index) => `<option value="${index}" ${index === selectedAgentIndex ? 'selected' : ''}>${esc(agent.name || agent.url || 'agent')}</option>`).join('');
  const agent = agents[selectedAgentIndex];
  const canChat = Boolean(agent && isHttpAgent(agent) && hasChat(agent));
  const status = agent ? healthStatus(agent) : {state: 'unknown', label: 'no agent', detail: 'No registry agents'};
  const statusClass = canChat ? 'ok' : status.state === 'offline' ? 'error' : status.state === 'pending' ? 'warn' : 'idle';
  document.getElementById('chat-avatar').textContent = agent ? initials(agent.name || agent.url) : 'A';
  document.getElementById('chat-title').textContent = agent ? (agent.name || agent.url) : 'Chat';
  document.getElementById('chat-subtitle').textContent = agent ? `${agent.transport || 'transport'} · ${agent.url || 'no url'}` : 'Select an agent';
  document.getElementById('chat-status').innerHTML = `${statusDotHtml(canChat ? status.state : status.state)} ${esc(canChat ? 'ready' : agent ? 'unavailable' : 'no agent')}`;
  document.getElementById('chat-status').className = `pill ${statusClass}`;
  document.getElementById('chat-agent-detail').innerHTML = agent
    ? `
      <div class="chat-agent-card">
        ${agentCell(agent).__html}
        <div class="detail-grid">
          <div class="detail-item"><div class="detail-label">Chat</div><div class="detail-value">${esc(canChat ? 'available' : 'unavailable')}</div></div>
          <div class="detail-item"><div class="detail-label">Probe</div><div class="detail-value">${esc(status.detail || status.label)}</div></div>
        </div>
        <div class="detail-item"><div class="detail-label">Endpoint</div><div class="detail-value">${esc(agent.url || '-')}</div></div>
        <div style="color:var(--muted);">${canChat ? 'POST /chat through the dashboard proxy.' : 'Chat requires an HTTP agent with has_llm=true.'}</div>
      </div>
    `
    : '<div style="color:var(--muted);">No agents available.</div>';
  const messages = chatMessages.length
    ? chatMessages
    : [{role: 'system', text: 'Select an HTTP LLM agent, then send a message through the dashboard proxy.', time: timeLabel()}];
  const visibleMessages = chatPending
    ? [...messages, {role: 'agent', text: 'Waiting for response', time: timeLabel(), pending: true}]
    : messages;
  document.getElementById('chat-messages').innerHTML = visibleMessages.map(message => renderChatMessage(message, agent)).join('');
  renderDebugPanel();
  handleChatInput();
  hydrateIcons();
  requestAnimationFrame(() => {
    const box = document.getElementById('chat-messages');
    if (box) box.scrollTop = box.scrollHeight;
  });
}

function renderChatMessage(message, agent) {
  const role = message.role || 'system';
  const label = role === 'user' ? 'You' : role === 'agent' ? (agent?.name || 'Agent') : 'System';
  const avatar = role === 'user' ? 'ME' : role === 'agent' ? initials(agent?.name || 'agent') : '!';
  const latency = message.latencyMs ? ` · ${message.latencyMs} ms` : '';
  const bubble = message.pending
    ? `${esc(message.text)} <span class="typing-dots"><span></span><span></span><span></span></span>`
    : esc(message.text);
  return `
    <div class="msg ${esc(role)} ${message.pending ? 'pending' : ''}">
      <div class="msg-avatar">${esc(avatar)}</div>
      <div class="msg-body">
        <div class="bubble">${bubble}</div>
        <div class="msg-meta"><span>${esc(label)}</span><span>${esc(message.time || '')}${esc(latency)}</span></div>
      </div>
    </div>
  `;
}

function handleChatInput() {
  const input = document.getElementById('chat-input');
  const send = document.getElementById('chat-send');
  if (!input || !send) return;
  const agent = (snapshot.registry?.agents || [])[selectedAgentIndex];
  const canChat = Boolean(agent && isHttpAgent(agent) && hasChat(agent));
  const text = input.value.trim();
  send.disabled = !canChat || chatPending || !text;
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 150) + 'px';
  const state = document.getElementById('chat-compose-state');
  if (state) state.textContent = chatPending ? 'waiting' : canChat ? (text ? `${text.length} chars` : 'ready') : 'unavailable';
}

function handleChatKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendChat();
  }
}

function toggleChatDebug() {
  chatDebugOpen = !chatDebugOpen;
  renderDebugPanel();
}

function renderDebugPanel() {
  const panel = document.getElementById('chat-debug-panel');
  if (!panel) return;
  panel.classList.toggle('visible', chatDebugOpen);
  const toggle = document.getElementById('chat-debug-toggle');
  if (toggle) toggle.className = `mini-btn ${chatDebugOpen ? 'primary' : ''}`;
  const avg = chatDebugStats.latencies.length
    ? Math.round(chatDebugStats.latencies.reduce((sum, value) => sum + value, 0) / chatDebugStats.latencies.length)
    : null;
  const latencyEl = document.getElementById('debug-latency');
  const avgEl = document.getElementById('debug-avg-latency');
  const countEl = document.getElementById('debug-count');
  const sessionEl = document.getElementById('debug-session');
  const errorEl = document.getElementById('debug-error');
  if (latencyEl) {
    latencyEl.textContent = chatDebugStats.lastLatency == null ? '-' : `${chatDebugStats.lastLatency} ms`;
    latencyEl.className = `debug-value ${chatDebugStats.lastLatency > 5000 ? 'warn' : ''}`;
  }
  if (avgEl) {
    avgEl.textContent = avg == null ? '-' : `${avg} ms`;
    avgEl.className = `debug-value ${avg > 5000 ? 'warn' : ''}`;
  }
  if (countEl) countEl.textContent = String(chatDebugStats.sent);
  if (sessionEl) sessionEl.textContent = chatSessionId;
  if (errorEl) {
    errorEl.textContent = chatDebugStats.lastError || 'none';
    errorEl.className = `debug-value ${chatDebugStats.lastError ? 'error' : ''}`;
  }
}

function recordChatDebug(latencyMs, error) {
  chatDebugStats.sent += 1;
  chatDebugStats.lastLatency = latencyMs;
  chatDebugStats.lastError = error || null;
  if (latencyMs != null) chatDebugStats.latencies.push(latencyMs);
}

async function sendChat() {
  const agent = (snapshot.registry?.agents || [])[selectedAgentIndex];
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  const canChat = Boolean(agent && isHttpAgent(agent) && hasChat(agent));
  if (!agent || !text || !canChat || chatPending) return;
  input.value = '';
  handleChatInput();
  chatSessionId = document.getElementById('chat-session').value || chatSessionId;
  const generation = ++chatRequestGeneration;
  const requestedAgentKey = agentKey(agent);
  const requestedSessionId = chatSessionId;
  chatMessages.push({role: 'user', text, time: timeLabel()});
  chatPending = true;
  renderChat();
  const started = performance.now();
  try {
    const res = await fetch('/api/agents/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: agent.url, message: text, session_id: chatSessionId})
    });
    const data = await res.json();
    const activeAgent = (snapshot.registry?.agents || [])[selectedAgentIndex];
    const activeSessionId = document.getElementById('chat-session')?.value || chatSessionId;
    if (
      generation !== chatRequestGeneration
      || !activeAgent
      || agentKey(activeAgent) !== requestedAgentKey
      || activeSessionId !== requestedSessionId
    ) return;
    const latencyMs = Math.round(performance.now() - started);
    recordChatDebug(latencyMs, data.error || null);
    chatMessages.push({role: data.error ? 'system' : 'agent', text: data.response || data.error || 'No response', time: timeLabel(), latencyMs});
  } catch (err) {
    if (generation !== chatRequestGeneration) return;
    const latencyMs = Math.round(performance.now() - started);
    recordChatDebug(latencyMs, 'Serve the dashboard locally to use chat actions.');
    chatMessages.push({role: 'system', text: 'Serve the dashboard locally to use chat actions.', time: timeLabel(), latencyMs});
  }
  chatPending = false;
  renderChat();
}

async function replayRun(id, recordKey) {
  if (!id) return;
  const generation = ++runReplayGeneration;
  const activeKey = recordKey || `report:${boundedSummaryText(id, 512)}`;
  selectedRunKey = activeKey;
  renderRuns();
  const panel = document.getElementById('replay-panel');
  const summary = document.getElementById('run-replay-summary');
  if (!panel) return;
  panel.setAttribute('aria-busy', 'true');
  if (summary) summary.textContent = 'Loading replay…';
  panel.className = 'run-replay-empty';
  panel.innerHTML = '<div><span class="trace-empty-icon" data-icon="refresh"></span><h3>Loading replay</h3><p>Reading the selected record from the connected store.</p></div>';
  hydrateIcons(panel);
  if (!window.__PROTOLINK_LIVE__) {
    if (summary) summary.textContent = 'Live dashboard required';
    panel.innerHTML = '<div><span class="trace-empty-icon" data-icon="timeline"></span><h3>Replay unavailable in a static snapshot</h3><p>Serve the dashboard locally and reconnect this store to load full replay events.</p></div>';
    panel.setAttribute('aria-busy', 'false');
    hydrateIcons(panel);
    return;
  }
  try {
    const recordKind = activeKey.startsWith('task:') ? 'task' : 'report';
    const replayUrl = '/api/runs/' + encodeURIComponent(id) + '?kind=' + encodeURIComponent(recordKind);
    const res = await fetch(replayUrl, {cache: 'no-store'});
    const view = await res.json();
    if (generation !== runReplayGeneration || selectedRunKey !== activeKey) return;
    if (!res.ok || view.error) throw new Error(view.error || `Replay request failed (${res.status})`);
    if (!view || view.source === 'missing') throw new Error('Run record not found in the connected store.');
    panel.className = '';
    panel.innerHTML = renderReplay(view);
    panel.setAttribute('aria-busy', 'false');
    if (summary) summary.textContent = `${(view.items || []).length} event${(view.items || []).length === 1 ? '' : 's'}`;
    hydrateIcons(panel);
  } catch (err) {
    if (generation !== runReplayGeneration) return;
    if (summary) summary.textContent = 'Replay unavailable';
    panel.className = 'run-replay-empty';
    panel.innerHTML = `<div><span class="trace-empty-icon" data-icon="status"></span><h3>Could not load replay</h3><p>${esc(err?.message || String(err))}</p></div>`;
    panel.setAttribute('aria-busy', 'false');
    hydrateIcons(panel);
  }
}

function renderReplay(view) {
  const allItems = Array.isArray(view.items) ? view.items : [];
  const items = allItems.slice(0, 500);
  const omitted = Math.max(0, allItems.length - items.length);
  const lifecycle = runLifecycle(view.final_task?.state || (items.some(item => item.severity === 'error') ? 'error' : 'completed'));
  const timeline = items.length
    ? `<div class="run-timeline">${items.map((item, index) => {
        const severity = ['error', 'warn'].includes(item.severity) ? item.severity : '';
        return `<div class="run-event ${severity}"><div class="run-event-rail"><span class="run-event-dot">${index + 1}</span></div><div class="run-event-card"><strong>${esc(boundedDisplayText(item.event_type, 'event', 160))}</strong><p>${esc(boundedDisplayText(item.summary, 'No summary', 1200))}</p><div class="run-event-meta"><span>${esc(timestampLabel(item.timestamp))}</span><span>${esc(boundedDisplayText(item.agent_name || view.agent_name, 'unassigned', 120))}</span>${item.task_id ? `<span>task ${esc(shortId(item.task_id, 26))}</span>` : ''}</div></div></div>`;
      }).join('')}</div>`
    : '<div class="panel-body"><div class="empty-muted">This record contains no replay events.</div></div>';
  return `
    <div class="run-replay-hero">
      <div class="run-replay-title"><div><h3>${esc(shortId(view.run_id || '-', 72))}</h3><p>${esc(boundedDisplayText(view.source, 'run', 40))} replay from the connected read-only store</p></div><span class="pill ${lifecycle.cls}">${esc(lifecycle.label)}</span></div>
      <div class="run-replay-facts">
        ${runReplayFact('Agent', boundedDisplayText(view.agent_name, 'unassigned', 120))}
        ${runReplayFact('Session', shortId(view.session_id || '-', 30))}
        ${runReplayFact('Trace', shortId(view.trace_id || '-', 30))}
        ${runReplayFact('Events', (view.items || []).length)}
      </div>
    </div>
    ${omitted ? `<div class="trace-limit-note">Showing the first ${formatCompactNumber(items.length)} of ${formatCompactNumber(allItems.length)} replay events to keep the timeline responsive.</div>` : ''}
    ${timeline}
  `;
}

function runReplayFact(label, value) {
  return `<div class="run-replay-fact"><span class="detail-label">${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}

function timeLabel() { return new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }

function renderStudio() {
  const canvas = document.getElementById('studio-canvas');
  const edgeLayer = document.getElementById('edge-layer');
  if (!canvas || !edgeLayer) return;
  for (const el of canvas.querySelectorAll('.node')) el.remove();
  edgeLayer.innerHTML = '';
  const nodeMap = Object.fromEntries((blueprint.nodes || []).map(n => [n.id, n]));
  for (const edge of blueprint.edges || []) {
    const a = nodeMap[edge.from], b = nodeMap[edge.to];
    if (!a || !b) continue;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', String(a.x + 165));
    line.setAttribute('y1', String(a.y + 36));
    line.setAttribute('x2', String(b.x));
    line.setAttribute('y2', String(b.y + 36));
    line.setAttribute('stroke', '#7a8799');
    line.setAttribute('stroke-width', '2');
    edgeLayer.appendChild(line);
  }
  for (const node of blueprint.nodes || []) {
    const el = document.createElement('div');
    el.className = `node studio-muted ${node.kind}`;
    el.style.left = `${node.x}px`;
    el.style.top = `${node.y}px`;
    el.innerHTML = `<div class="kind">${esc(node.kind)}</div><div class="label">${esc(node.label)}</div>`;
    canvas.appendChild(el);
  }
  const first = blueprint.nodes?.[0] || null;
  document.getElementById('node-label').value = first?.label || '';
  document.getElementById('node-kind').value = first?.kind || 'agent';
  document.getElementById('blueprint-json').textContent = JSON.stringify(blueprint, null, 2);
}

document.addEventListener('keydown', event => {
  if (!document.getElementById('view-telemetry')?.classList.contains('active')) return;
  if (event.target?.matches('input, select, textarea, button') || event.target?.closest?.('.inspector-json, .event-payload-preview')) return;
  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    stepTelemetryEvent(-1);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    stepTelemetryEvent(1);
  } else if (event.key === ' ') {
    event.preventDefault();
    toggleTelemetryPlayback();
  } else if (event.key === 'Escape') {
    stopTelemetryPlayback();
    updateTelemetryReplayDom();
  }
});

showView('__PROTOLINK_START_TAB_VALUE__');
render();
</script>
</body>
</html>"""
