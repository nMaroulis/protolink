# ruff: noqa: E501
"""Text and HTML renderers for Protolink developer tools."""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape
from typing import Any

from protolink.devtools.models import DoctorReport, RunReplayView


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
.brand { font-size: 20px; font-weight: 780; letter-spacing: 0; }
.sub { color: #bac5d4; font-size: 12px; margin-top: 2px; }
.side-meta { display: grid; gap: 8px; padding: 12px; border: 1px solid rgba(255,255,255,.10); border-radius: 8px; background: rgba(255,255,255,.05); }
.side-meta span { color: #c7d2e0; font-size: 12px; overflow-wrap: anywhere; }
.nav { display: grid; gap: 7px; }
.nav button { text-align: left; border: 0; border-radius: 8px; padding: 10px 12px; color: #dbe4ef; background: transparent; cursor: pointer; display: flex; align-items: center; justify-content: space-between; min-height: 40px; }
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
.btn, .mini-btn { border: 1px solid var(--line); background: var(--panel); border-radius: 8px; cursor: pointer; color: var(--ink); text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; }
.btn { padding: 8px 11px; box-shadow: var(--shadow-soft); }
.mini-btn { min-height: 28px; padding: 4px 8px; font-size: 12px; box-shadow: none; }
.btn:hover, .mini-btn:hover { border-color: rgba(15,159,146,.42); box-shadow: 0 0 0 3px rgba(15,159,146,.10); }
.btn.primary, .mini-btn.primary { background: var(--teal); border-color: var(--teal); color: #fff; }
.btn:disabled, .mini-btn:disabled { opacity: .48; cursor: not-allowed; box-shadow: none; }
.alerts { display: grid; gap: 8px; margin-bottom: 14px; }
.alert { border: 1px solid var(--amber); background: var(--amber-soft); color: #6d4608; border-radius: 8px; padding: 10px 12px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.metric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; box-shadow: var(--shadow-soft); min-height: 96px; position: relative; overflow: hidden; }
.metric::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--teal); }
.metric[data-accent="indigo"]::before { background: var(--indigo); }
.metric[data-accent="amber"]::before { background: var(--amber); }
.metric[data-accent="coral"]::before { background: var(--coral); }
.metric .label { color: var(--muted); font-size: 12px; }
.metric .value { font-size: 30px; font-weight: 800; margin-top: 4px; letter-spacing: 0; overflow-wrap: anywhere; }
.bands { display: grid; grid-template-columns: minmax(360px, 1fr) minmax(360px, 1fr); gap: 14px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); overflow: hidden; }
.panel + .panel { margin-top: 14px; }
.panel h2 { margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line); font-size: 15px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.panel-body { padding: 14px 16px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; border-bottom: 1px solid #edf1f6; text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; background: #fbfcfe; }
td { font-size: 13px; overflow-wrap: anywhere; }
.pill { display: inline-flex; border-radius: 999px; padding: 2px 8px; font-size: 12px; border: 1px solid var(--line); background: var(--panel-2); font-weight: 650; white-space: nowrap; }
.pill.ok { color: var(--green); background: var(--green-soft); border-color: rgba(36,138,87,.18); }
.pill.warn { color: var(--amber); background: var(--amber-soft); border-color: rgba(189,125,17,.22); }
.pill.error { color: var(--coral); background: var(--coral-soft); border-color: rgba(214,91,72,.20); }
.pill.idle { color: var(--muted); }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.detail-item { border: 1px solid var(--line); background: var(--panel-2); border-radius: 8px; padding: 10px 12px; }
.detail-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 2px; }
.detail-value { font-weight: 700; overflow-wrap: anywhere; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.view { display: none; }
.view.active { display: block; }
.chat-layout { display: grid; grid-template-columns: minmax(260px, 340px) minmax(0, 1fr); gap: 14px; align-items: stretch; }
.chat-sidebar { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); padding: 14px; display: grid; gap: 12px; align-content: start; }
.chat-box { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); display: grid; grid-template-rows: auto 1fr auto; min-height: 640px; overflow: hidden; }
.chat-head { padding: 14px 16px; border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.messages { padding: 18px; overflow: auto; background: linear-gradient(180deg, #fbfcfe 0%, #f5f8fb 100%); display: flex; flex-direction: column; gap: 12px; }
.msg { display: grid; gap: 4px; max-width: min(680px, 88%); }
.msg.user { align-self: flex-end; }
.msg.agent, .msg.system { align-self: flex-start; }
.bubble { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fff; white-space: pre-wrap; box-shadow: 0 5px 18px rgba(24,33,47,.06); }
.msg.user .bubble { background: var(--teal); color: #fff; border-color: var(--teal); }
.msg.system .bubble { background: var(--amber-soft); border-color: rgba(189,125,17,.26); color: #6d4608; }
.msg-meta { color: var(--muted); font-size: 11px; }
.chat-compose { border-top: 1px solid var(--line); padding: 12px; display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end; }
.chat-compose textarea { width: 100%; min-height: 48px; max-height: 140px; resize: vertical; border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
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
}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div>
      <div class="brand">Protolink</div>
      <div class="sub">runtime dashboard</div>
    </div>
    <div class="side-meta">
      <span>Local inspection</span>
      <span id="side-store">Store: -</span>
    </div>
    <nav class="nav">
      <button id="nav-dashboard" onclick="showView('dashboard')">Dashboard</button>
      <button id="nav-runs" onclick="showView('runs')">Runs</button>
      <button id="nav-registry" onclick="showView('registry')">Registry</button>
      <button id="nav-chat" onclick="showView('chat')">Chat</button>
      <button id="nav-studio" onclick="showView('studio')">Studio <span class="soon-mini">Soon</span></button>
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
        <div class="actions"><button class="btn" onclick="refresh()">Refresh</button><button class="btn" onclick="pingAll()">Ping all</button><button class="btn primary" onclick="showView('studio')">Studio Preview</button></div>
      </div>
      <div class="alerts" id="alerts"></div>
      <div class="grid" id="metrics"></div>
      <div class="bands"><div class="panel"><h2>Recent tasks</h2><div id="task-table"></div></div><div class="panel"><h2>Registry health</h2><div id="health-table"></div></div></div>
    </section>
    <section id="view-runs" class="view">
      <div class="top"><div><p class="kicker">Replay substrate</p><h1>Runs</h1><p class="lede">Task snapshots and run reports from the configured SQLite run store.</p></div><div class="actions"><button class="btn" onclick="refresh()">Refresh</button></div></div>
      <div class="panel"><h2>Run store</h2><div id="runs-table"></div></div>
      <div class="panel"><h2>Replay</h2><div class="panel-body" id="replay-panel">Select a run or task to replay it from the live dashboard server.</div></div>
    </section>
    <section id="view-registry" class="view">
      <div class="top"><div><p class="kicker">Discovery</p><h1>Registry</h1><p class="lede">Agent cards currently visible to the dashboard snapshot, with status probes and chat entry points for HTTP agents.</p></div><div class="actions"><button class="btn" onclick="refresh()">Refresh</button><button class="btn" onclick="pingAll()">Ping all</button></div></div>
      <div class="panel"><h2>Agents</h2><div id="registry-table"></div></div>
      <div class="panel"><h2>Selected agent</h2><div class="panel-body" id="agent-detail"></div></div>
    </section>
    <section id="view-chat" class="view">
      <div class="top"><div><p class="kicker">Agent chat</p><h1>Chat</h1><p class="lede">Talk to any HTTP agent that advertises LLM chat support. Static dashboard files show the panel, while live chat requires the served dashboard.</p></div><div class="actions"><button class="btn" onclick="refresh()">Refresh</button></div></div>
      <div class="chat-layout">
        <aside class="chat-sidebar">
          <div class="field"><label>Agent</label><select id="chat-agent-select" onchange="selectChatAgent(this.value)"></select></div>
          <div class="field"><label>Session</label><input id="chat-session" /></div>
          <div id="chat-agent-detail"></div>
        </aside>
        <div class="chat-box">
          <div class="chat-head"><strong id="chat-title">Chat</strong><span class="pill idle" id="chat-status">idle</span></div>
          <div class="messages" id="chat-messages"></div>
          <div class="chat-compose"><textarea id="chat-input" placeholder="Type a message to the selected agent"></textarea><button class="btn primary" id="chat-send" onclick="sendChat()">Send</button></div>
        </div>
      </div>
    </section>
    <section id="view-studio" class="view">
      <div class="top"><div><p class="kicker">Canvas preview</p><h1>Protolink Studio</h1><p class="lede">The visual agent builder is disabled while the blueprint format settles.</p></div><div class="actions"><button class="btn" disabled>Connect</button><button class="btn primary" disabled>Export JSON</button></div></div>
      <div class="studio-layout">
        <aside class="palette">
          <h2>Palette</h2>
          <button class="btn" disabled>Add Agent</button>
          <button class="btn" disabled>Add LLM</button>
          <button class="btn" disabled>Add Tool</button>
          <button class="btn" disabled>Add Registry</button>
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
          <button class="btn" disabled>Delete</button>
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
let chatSessionId = "dashboard_" + Math.random().toString(36).slice(2, 10);

function showView(name) {
  for (const el of document.querySelectorAll('.view')) el.classList.remove('active');
  for (const el of document.querySelectorAll('.nav button')) el.classList.remove('active');
  document.getElementById('view-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'chat') renderChat();
  if (name === 'studio') renderStudio();
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
  const alerts = [];
  if (snapshot.registry?.error) alerts.push('Registry: ' + snapshot.registry.error);
  if (snapshot.runs?.error) alerts.push('Run store: ' + snapshot.runs.error);
  document.getElementById('alerts').innerHTML = alerts.map(message => `<div class="alert">${esc(message)}</div>`).join('');
  document.getElementById('side-store').textContent = 'Store: ' + (snapshot.runs?.store || 'not configured');
  document.getElementById('metrics').innerHTML = [
    metric('Agents', agents.length, snapshot.registry?.url || 'snapshot', 'teal'),
    metric('Tasks', tasks.length, 'snapshots', 'indigo'),
    metric('Reports', reports.length, 'stored runs', 'amber'),
    metric('Store', snapshot.runs?.store ? 'on' : 'off', snapshot.runs?.error || 'local', snapshot.runs?.error ? 'coral' : 'teal')
  ].join('');
  document.getElementById('task-table').innerHTML = table(['Task', 'State', 'Run', 'Updated'], tasks.slice(0, 8).map(t => [t.task_id, pill(t.state), t.run_id || '-', t.updated_at || '-']));
  document.getElementById('health-table').innerHTML = table(['Agent', 'URL', 'Health', 'Actions'], agents.slice(0, 8).map((a, index) => agentHealthRow(a, index)));
  document.getElementById('runs-table').innerHTML = table(['Kind', 'ID', 'Session', 'Agent', 'Time'], [
    ...reports.map(r => ['report', replayButton(r.run_id), r.session_id || '-', r.agent_name || '-', r.created_at || '-']),
    ...tasks.map(t => ['task', replayButton(t.run_id || t.task_id), t.session_id || '-', t.agent_name || '-', t.updated_at || '-'])
  ]);
  document.getElementById('registry-table').innerHTML = table(['Agent', 'Transport', 'URL', 'Capabilities', 'Health', 'Actions'], agents.map((a, index) => registryRow(a, index)));
  renderAgentDetail();
  renderChat();
  renderStudio();
}

function metric(label, value, hint, accent) { return `<div class="metric" data-accent="${esc(accent || 'teal')}"><div class="label">${esc(label)}</div><div class="value">${esc(String(value))}</div><div class="label">${esc(hint || '')}</div></div>`; }
function enabledCaps(caps) { return Object.entries(caps).filter(([,v]) => v === true).map(([k]) => k).join(', ') || '-'; }
function agentKey(agent) { return agent.url || agent.name || 'agent'; }
function isHttpAgent(agent) { return /^https?:\\/\\//.test(String(agent.url || '')); }
function hasChat(agent) { return Boolean(agent.capabilities?.has_llm); }
function endpoint(agent, path) { return String(agent.url || '').replace(/\\/+$/, '') + path; }
function agentHealth(agent) {
  const item = health[agentKey(agent)];
  if (item?.pending) return raw('<span class="pill warn">pinging</span>');
  if (!isHttpAgent(agent)) return raw('<span class="pill idle">runtime</span>');
  if (!item) return raw('<span class="pill idle">unknown</span>');
  if (item.ok) return raw(`<span class="pill ok">${esc(item.latency_ms ?? '-')} ms</span>`);
  return raw(`<span class="pill error">${esc(item.error || 'offline')}</span>`);
}
function agentActions(agent, index) {
  const pingDisabled = isHttpAgent(agent) ? '' : ' disabled';
  const chatDisabled = isHttpAgent(agent) && hasChat(agent) ? '' : ' disabled';
  const status = isHttpAgent(agent) ? `<a class="mini-btn" href="${esc(endpoint(agent, '/status'))}" target="_blank" rel="noreferrer">Status</a>` : '<button class="mini-btn" disabled>Status</button>';
  return raw(`<div class="actions"><button class="mini-btn" onclick="selectAgent(${index})">Details</button><button class="mini-btn" onclick="pingAgent(${index})"${pingDisabled}>Ping</button><button class="mini-btn" onclick="openChat(${index})"${chatDisabled}>Chat</button>${status}</div>`);
}
function agentHealthRow(agent, index) { return [agent.name || '-', agent.url || '-', agentHealth(agent), agentActions(agent, index)]; }
function registryRow(agent, index) {
  const name = `<button class="mini-btn" onclick="selectAgent(${index})">${esc(agent.name || '-')}</button>`;
  return [raw(name), agent.transport || '-', agent.url || '-', enabledCaps(agent.capabilities || {}), agentHealth(agent), agentActions(agent, index)];
}
function replayButton(id) {
  if (!id) return '-';
  return raw(`<button class="mini-btn" onclick="replayRun('${escAttr(id)}')">${esc(id)}</button>`);
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
  const skills = (agent.skills || []).map(skill => typeof skill === 'string' ? skill : skill.id || skill.name || JSON.stringify(skill));
  const tags = agent.tags || [];
  target.innerHTML = `
    <div class="detail-grid">
      <div class="detail-item"><div class="detail-label">Name</div><div class="detail-value">${esc(agent.name || '-')}</div></div>
      <div class="detail-item"><div class="detail-label">Role</div><div class="detail-value">${esc(agent.role || '-')}</div></div>
      <div class="detail-item"><div class="detail-label">Transport</div><div class="detail-value">${esc(agent.transport || '-')}</div></div>
      <div class="detail-item"><div class="detail-label">Protocol</div><div class="detail-value">${esc(agent.protocol_version || '-')}</div></div>
      <div class="detail-item"><div class="detail-label">URL</div><div class="detail-value">${esc(agent.url || '-')}</div></div>
      <div class="detail-item"><div class="detail-label">Capabilities</div><div class="detail-value">${esc(enabledCaps(agent.capabilities || {}))}</div></div>
    </div>
    <div style="margin-top:12px;color:var(--muted);">${esc(agent.description || '')}</div>
    <div style="margin-top:12px;" class="tag-row">${[...tags, ...skills].map(item => `<span class="pill">${esc(item)}</span>`).join('') || '<span class="pill idle">no tags or skills</span>'}</div>
  `;
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
  selectedAgentIndex = Math.max(0, Number(index) || 0);
  renderAgentDetail();
  renderChat();
}

function renderChat() {
  const agents = snapshot.registry?.agents || [];
  const select = document.getElementById('chat-agent-select');
  if (!select) return;
  if (!document.getElementById('chat-session').value) document.getElementById('chat-session').value = chatSessionId;
  select.innerHTML = agents.map((agent, index) => `<option value="${index}" ${index === selectedAgentIndex ? 'selected' : ''}>${esc(agent.name || agent.url || 'agent')}</option>`).join('');
  const agent = agents[selectedAgentIndex];
  const canChat = Boolean(agent && isHttpAgent(agent) && hasChat(agent));
  document.getElementById('chat-title').textContent = agent ? `Chat with ${agent.name || agent.url}` : 'Chat';
  document.getElementById('chat-status').textContent = canChat ? 'ready' : agent ? 'unavailable' : 'no agent';
  document.getElementById('chat-status').className = `pill ${canChat ? 'ok' : 'idle'}`;
  document.getElementById('chat-send').disabled = !canChat;
  document.getElementById('chat-agent-detail').innerHTML = agent
    ? `<div class="detail-item"><div class="detail-label">Endpoint</div><div class="detail-value">${esc(agent.url || '-')}</div></div><div style="margin-top:8px;color:var(--muted);">${canChat ? 'POST /chat through the dashboard proxy.' : 'Chat requires an HTTP agent with has_llm=true.'}</div>`
    : '<div style="color:var(--muted);">No agents available.</div>';
  const messages = chatMessages.length
    ? chatMessages
    : [{role: 'system', text: 'Select an HTTP LLM agent, then send a message through the dashboard proxy.', time: timeLabel()}];
  document.getElementById('chat-messages').innerHTML = messages.map(message => `<div class="msg ${esc(message.role)}"><div class="bubble">${esc(message.text)}</div><div class="msg-meta">${esc(message.time || '')}</div></div>`).join('');
}

async function sendChat() {
  const agent = (snapshot.registry?.agents || [])[selectedAgentIndex];
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!agent || !text) return;
  input.value = '';
  chatSessionId = document.getElementById('chat-session').value || chatSessionId;
  chatMessages.push({role: 'user', text, time: timeLabel()});
  chatMessages.push({role: 'agent', text: 'Waiting for response...', time: timeLabel()});
  renderChat();
  try {
    const res = await fetch('/api/agents/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: agent.url, message: text, session_id: chatSessionId})
    });
    const data = await res.json();
    chatMessages.pop();
    chatMessages.push({role: data.error ? 'system' : 'agent', text: data.response || data.error || 'No response', time: timeLabel()});
  } catch (err) {
    chatMessages.pop();
    chatMessages.push({role: 'system', text: 'Serve the dashboard locally to use chat actions.', time: timeLabel()});
  }
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
