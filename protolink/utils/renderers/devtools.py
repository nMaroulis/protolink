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

    def render_dashboard(self, snapshot: dict[str, Any], *, start_tab: str = "dashboard") -> str:
        """Render the dashboard shell with an embedded initial snapshot."""
        snapshot_json = _safe_json(snapshot)
        return _dashboard_html(snapshot_json, start_tab=start_tab)


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


def _dashboard_html(snapshot_json: str, *, start_tab: str = "dashboard", title: str = "Protolink Dashboard") -> str:
    """Return the dashboard HTML document."""
    safe_title = escape(title)
    safe_start_tab = start_tab if start_tab in {"dashboard", "runs", "registry", "chat", "studio"} else "dashboard"
    return (
        _DASHBOARD_TEMPLATE.replace("__PROTOLINK_TITLE__", safe_title)
        .replace("__PROTOLINK_SNAPSHOT_JSON__", snapshot_json)
        .replace("__PROTOLINK_START_TAB_VALUE__", safe_start_tab)
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
.shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
.side { background: var(--nav); color: #f8fafc; padding: 22px 18px; display: flex; flex-direction: column; gap: 20px; border-right: 1px solid rgba(255,255,255,.08); }
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
.side-foot { margin-top: auto; color: #bac5d4; font-size: 12px; line-height: 1.5; }
.main { padding: 24px; overflow: auto; }
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
.grid { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
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
.replay-list { display: grid; gap: 8px; }
.timeline-item { display: grid; grid-template-columns: 140px 1fr; gap: 10px; border-left: 3px solid var(--indigo); padding: 8px 0 8px 12px; }
.timeline-item.error { border-left-color: var(--coral); }
.timeline-item.warn { border-left-color: var(--amber); }
.timeline-time { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.timeline-main { display: grid; gap: 2px; }
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
  .side { position: sticky; top: 0; z-index: 5; }
  .grid, .bands, .studio-layout, .chat-layout { grid-template-columns: 1fr; }
  .agent-hero { grid-template-columns: 1fr; }
  .agent-hero-actions { justify-content: flex-start; }
  .agent-stat-grid, .schema-grid { grid-template-columns: 1fr; }
  .debug-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
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
    </div>
    <nav class="nav">
      <button id="nav-dashboard" onclick="showView('dashboard')"><span class="nav-label" data-icon="dashboard">Dashboard</span></button>
      <button id="nav-registry" onclick="showView('registry')"><span class="nav-label" data-icon="registry">Registry</span></button>
      <button id="nav-runs" onclick="showView('runs')"><span class="nav-label" data-icon="timeline">Runs</span></button>
      <button id="nav-chat" onclick="showView('chat')"><span class="nav-label" data-icon="chat">Chat</span></button>
      <button id="nav-studio" onclick="showView('studio')"><span class="nav-label" data-icon="studio">Studio</span> <span class="soon-mini">Soon</span></button>
    </nav>
    <div class="side-foot">Local devtools over registry cards, run reports, agent status, and chat.</div>
  </aside>
  <main class="main">
    <section id="view-dashboard" class="view">
      <div class="top">
        <div>
          <p class="kicker">Local runtime view</p>
          <h1>Dashboard</h1>
          <p class="lede">Inspect persisted task snapshots, run reports, registry cards, agent health, and chat-ready HTTP agents from one local surface.</p>
        </div>
        <div class="actions"><button class="btn primary" data-icon="refresh" onclick="refresh()">Refresh</button><button class="btn" data-icon="ping" onclick="pingAll()">Ping all</button></div>
      </div>
      <div class="alerts" id="alerts"></div>
      <div class="grid" id="metrics"></div>
      <div class="dashboard-stack"><div class="panel"><h2>Registry <span class="online-summary" id="dashboard-registry-summary"></span></h2><div class="panel-note">For full agent details, schemas, transports, and security metadata, open the Registry tab.</div><div id="health-table"></div></div></div>
    </section>
    <section id="view-runs" class="view">
      <div class="top"><div><p class="kicker">Replay substrate</p><h1>Runs</h1><p class="lede">Task snapshots and run reports from the configured SQLite run store.</p></div><div class="actions"><button class="btn" data-icon="refresh" onclick="refresh()">Refresh</button></div></div>
      <div class="panel"><h2>Run store</h2><div id="runs-table"></div></div>
      <div class="panel"><h2>Replay</h2><div class="panel-body" id="replay-panel">Select a run or task to replay it from the live dashboard server.</div></div>
    </section>
    <section id="view-registry" class="view">
      <div class="top"><div><p class="kicker">Discovery</p><h1>Registry</h1><p class="lede">Agent cards currently visible to the dashboard snapshot, with status probes and chat entry points for HTTP agents.</p></div><div class="actions"><button class="btn" data-icon="refresh" onclick="refresh()">Refresh</button><button class="btn" data-icon="ping" onclick="pingAll()">Ping all</button></div></div>
      <div class="panel"><h2>Agents</h2><div id="registry-table"></div></div>
      <div class="panel"><h2>Selected agent</h2><div class="panel-body" id="agent-detail"></div></div>
    </section>
    <section id="view-chat" class="view">
      <div class="top"><div><p class="kicker">Agent chat</p><h1>Chat</h1><p class="lede">Talk to any HTTP agent that advertises LLM chat support. Static dashboard files show the panel, while live chat requires the served dashboard.</p></div><div class="actions"><button class="btn" data-icon="refresh" onclick="refresh()">Refresh</button></div></div>
      <div class="chat-layout">
        <aside class="chat-sidebar">
          <div class="field"><label>Agent</label><select id="chat-agent-select" onchange="selectChatAgent(this.value)"></select></div>
          <div class="field"><label>Session</label><input id="chat-session" oninput="chatSessionId = this.value || chatSessionId; renderDebugPanel()" /></div>
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
let snapshot = window.__PROTOLINK_SNAPSHOT__;
let blueprint = JSON.parse(JSON.stringify(snapshot.studio?.blueprint || {nodes: [], edges: []}));
let selectedAgentIndex = 0;
let chatMessages = [];
let health = {};
let chatSessionId = newChatSessionId();
let chatPending = false;
let chatDebugOpen = false;
let chatDebugStats = {sent: 0, latencies: [], lastLatency: null, lastError: null};

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
  tool: '<path d="m14.7 6.3 3-3a3 3 0 0 1-4 4l-7.4 7.4a2 2 0 1 0 3 3l7.4-7.4a3 3 0 0 1 4-4l-3 3"/>'
};

function icon(name) {
  const body = ICON_PATHS[name] || ICON_PATHS.spark;
  return `<svg class="icon icon-${escAttr(name)}" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
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
  for (const el of document.querySelectorAll('.view')) el.classList.remove('active');
  for (const el of document.querySelectorAll('.nav button')) el.classList.remove('active');
  document.getElementById('view-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'chat') renderChat();
  if (name === 'studio') renderStudio();
  hydrateIcons();
}

async function refresh() {
  try {
    const res = await fetch('/api/snapshot');
    if (res.ok) snapshot = await res.json();
  } catch (_) {}
  blueprint = blueprint.nodes?.length ? blueprint : JSON.parse(JSON.stringify(snapshot.studio?.blueprint || {nodes: [], edges: []}));
  render();
}

function render() {
  const agents = snapshot.registry?.agents || [];
  const tasks = snapshot.runs?.tasks || [];
  const reports = snapshot.runs?.reports || [];
  const onlineCount = agents.filter(agent => healthStatus(agent).state === 'online').length;
  const alerts = [];
  if (snapshot.registry?.error) alerts.push('Registry: ' + snapshot.registry.error);
  if (snapshot.runs?.error) alerts.push('Run store: ' + snapshot.runs.error);
  document.getElementById('alerts').innerHTML = alerts.map(message => `<div class="alert">${esc(message)}</div>`).join('');
  document.getElementById('side-store').textContent = 'Store: ' + (snapshot.runs?.store || 'not configured');
  document.getElementById('metrics').innerHTML = [
    metric('Agents', agents.length, onlineCount ? `${onlineCount} online` : snapshot.registry?.url || 'snapshot', 'teal', 'registry', 'registry'),
    metric('Tasks', tasks.length, 'open in Runs', 'indigo', 'runs', 'timeline'),
    metric('Reports', reports.length, 'stored run reports', 'amber', 'runs', 'play'),
    metric('Store', raw(storeStateHtml(Boolean(snapshot.runs?.store), snapshot.runs?.error)), snapshot.runs?.error || 'local run store', snapshot.runs?.error ? 'coral' : 'teal', 'runs', 'status')
  ].join('');
  const registrySummary = document.getElementById('dashboard-registry-summary');
  if (registrySummary) registrySummary.innerHTML = `${statusDotHtml(onlineCount ? 'online' : agents.length ? 'unknown' : 'runtime')} ${esc(agents.length ? `${agents.length} visible` : 'no agents')}`;
  document.getElementById('health-table').innerHTML = table(['Agent', 'URL', 'Health', 'Actions'], agents.slice(0, 8).map((a, index) => agentHealthRow(a, index)));
  document.getElementById('runs-table').innerHTML = table(['Kind', 'ID', 'Session', 'Agent', 'Time'], [
    ...reports.map(r => ['report', replayButton(r.run_id), r.session_id || '-', r.agent_name || '-', r.created_at || '-']),
    ...tasks.map(t => ['task', replayButton(t.run_id || t.task_id), t.session_id || '-', t.agent_name || '-', t.updated_at || '-'])
  ]);
  document.getElementById('registry-table').innerHTML = table(['Agent', 'Transport', 'URL', 'Capabilities', 'Health', 'Actions'], agents.map((a, index) => registryRow(a, index)));
  renderAgentDetail();
  renderChat();
  renderStudio();
  hydrateIcons();
}

function metric(label, value, hint, accent, view, iconName) {
  const action = view ? ` onclick="showView('${escAttr(view)}')"` : '';
  return `<button type="button" class="metric" data-accent="${esc(accent || 'teal')}"${action}><div class="metric-top"><div class="label">${esc(label)}</div><span class="metric-icon">${icon(iconName || 'dashboard')}</span></div><div class="value">${cellHtml(value)}</div><div class="hint">${esc(hint || '')}</div></button>`;
}
function storeStateHtml(isOn, error) {
  const state = isOn && !error ? 'on' : 'off';
  const dot = isOn && !error ? 'online' : 'offline';
  return `<span class="store-state ${state}">${statusDotHtml(dot)}${esc(state)}</span>`;
}
function agentKey(agent) { return agent.url || agent.name || 'agent'; }
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
  if (!value) return '-';
  const numeric = Number(value);
  const date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
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
  return raw(`<span class="transport-badge ${escAttr(transportKind(label))}">${esc(label)}</span>`);
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
function statusDotHtml(state) { return `<span class="status-dot ${escAttr(state || 'unknown')}"></span>`; }
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
function replayButton(id) {
  if (!id) return '-';
  return raw(`<button class="mini-btn" data-icon="play" onclick="replayRun('${escAttr(id)}')">${esc(id)}</button>`);
}
function pill(value) { const cls = value === 'completed' ? 'ok' : value === 'failed' ? 'error' : value === 'canceled' ? 'warn' : ''; return raw(`<span class="pill ${cls}">${esc(value || '-')}</span>`); }
function table(headers, rows) {
  if (!rows.length) return '<div style="padding:14px;color:var(--muted);">(none)</div>';
  return `<table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cellHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
function raw(html) { return {__html: html}; }
function cellHtml(cell) { return cell && typeof cell === 'object' && '__html' in cell ? cell.__html : esc(cell); }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escAttr(value) { return String(value ?? '').replace(/[\\\\'"]/g, c => '\\\\' + c).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

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
  selectedAgentIndex = Math.max(0, Math.min(Number(index) || 0, Math.max(agents.length - 1, 0)));
  renderAgentDetail();
  renderChat();
}

function resetChat() {
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
    const latencyMs = Math.round(performance.now() - started);
    recordChatDebug(latencyMs, data.error || null);
    chatMessages.push({role: data.error ? 'system' : 'agent', text: data.response || data.error || 'No response', time: timeLabel(), latencyMs});
  } catch (err) {
    const latencyMs = Math.round(performance.now() - started);
    recordChatDebug(latencyMs, 'Serve the dashboard locally to use chat actions.');
    chatMessages.push({role: 'system', text: 'Serve the dashboard locally to use chat actions.', time: timeLabel(), latencyMs});
  }
  chatPending = false;
  renderChat();
}

async function replayRun(id) {
  if (!id) return;
  const panel = document.getElementById('replay-panel');
  panel.innerHTML = '<span class="pill warn">loading</span>';
  try {
    const res = await fetch('/api/runs/' + encodeURIComponent(id));
    const view = await res.json();
    panel.innerHTML = renderReplay(view);
  } catch (err) {
    panel.innerHTML = '<span class="pill error">Serve the dashboard to replay stored runs.</span>';
  }
}

function renderReplay(view) {
  if (!view || view.source === 'missing') return '<span class="pill error">Run not found</span>';
  const items = view.items || [];
  if (!items.length) return '<span class="pill idle">No replay events</span>';
  return `<div class="replay-list">${items.map(item => `<div class="timeline-item ${esc(item.severity || '')}"><div class="timeline-time">${esc(item.timestamp || '-')}</div><div class="timeline-main"><strong>${esc(item.event_type || '-')}</strong><span>${esc(item.summary || '')}</span><span class="msg-meta">${esc(item.agent_name || view.agent_name || '-')}</span></div></div>`).join('')}</div>`;
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

showView('__PROTOLINK_START_TAB_VALUE__');
render();
</script>
</body>
</html>"""
