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
    safe_start_tab = start_tab if start_tab in {"dashboard", "runs", "registry", "studio"} else "dashboard"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{safe_title}</title>
<style>
:root {{
  --bg: #f4f6f9;
  --ink: #18212f;
  --muted: #6c7484;
  --line: #d8dee8;
  --panel: #ffffff;
  --panel-2: #f1f5f9;
  --nav: #151d2a;
  --teal: #0f9f92;
  --teal-soft: #dff6f2;
  --coral: #d65b48;
  --coral-soft: #fde9e4;
  --amber: #bd7d11;
  --amber-soft: #fff3cf;
  --indigo: #5665d8;
  --indigo-soft: #e8ebff;
  --green: #248a57;
  --shadow: 0 16px 42px rgba(24, 33, 47, .10);
  --shadow-soft: 0 8px 22px rgba(24, 33, 47, .08);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  min-height: 100vh;
  background: linear-gradient(180deg, #edf2f7 0%, #f8fafc 34%, var(--bg) 100%);
  color: var(--ink);
  font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
button, input, select {{ font: inherit; }}
.shell {{ display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }}
.side {{ background: var(--nav); color: #f8fafc; padding: 22px 18px; display: flex; flex-direction: column; gap: 20px; border-right: 1px solid rgba(255,255,255,.08); }}
.brand {{ font-size: 20px; font-weight: 780; letter-spacing: 0; }}
.sub {{ color: #bac5d4; font-size: 12px; margin-top: 2px; }}
.side-meta {{ display: grid; gap: 8px; padding: 12px; border: 1px solid rgba(255,255,255,.10); border-radius: 8px; background: rgba(255,255,255,.05); }}
.side-meta span {{ color: #c7d2e0; font-size: 12px; }}
.nav {{ display: grid; gap: 7px; }}
.nav button {{ text-align: left; border: 0; border-radius: 8px; padding: 10px 12px; color: #dbe4ef; background: transparent; cursor: pointer; display: flex; align-items: center; justify-content: space-between; min-height: 40px; }}
.nav button:hover {{ background: rgba(255,255,255,.08); }}
.nav button.active {{ color: #fff; background: rgba(15,159,146,.26); box-shadow: inset 3px 0 0 var(--teal); }}
.soon-mini {{ font-size: 10px; color: #fff; background: rgba(189,125,17,.95); border-radius: 999px; padding: 2px 6px; }}
.main {{ padding: 24px; overflow: auto; }}
.top {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; margin-bottom: 18px; }}
.kicker {{ margin: 0 0 4px; color: var(--teal); font-size: 12px; font-weight: 760; text-transform: uppercase; letter-spacing: .06em; }}
h1 {{ margin: 0; font-size: 26px; letter-spacing: 0; }}
.lede {{ margin: 6px 0 0; max-width: 720px; color: var(--muted); }}
.actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.btn {{ border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 8px 11px; cursor: pointer; color: var(--ink); box-shadow: var(--shadow-soft); }}
.btn.primary {{ background: var(--teal); border-color: var(--teal); color: #fff; }}
.btn:disabled {{ opacity: .48; cursor: not-allowed; box-shadow: none; }}
.alerts {{ display: grid; gap: 8px; margin-bottom: 14px; }}
.alert {{ border: 1px solid var(--amber); background: var(--amber-soft); color: #6d4608; border-radius: 8px; padding: 10px 12px; }}
.grid {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }}
.metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; box-shadow: var(--shadow-soft); min-height: 96px; position: relative; overflow: hidden; }}
.metric::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--teal); }}
.metric[data-accent="indigo"]::before {{ background: var(--indigo); }}
.metric[data-accent="amber"]::before {{ background: var(--amber); }}
.metric[data-accent="coral"]::before {{ background: var(--coral); }}
.metric .label {{ color: var(--muted); font-size: 12px; }}
.metric .value {{ font-size: 30px; font-weight: 800; margin-top: 4px; letter-spacing: 0; }}
.bands {{ display: grid; grid-template-columns: minmax(360px, 1fr) minmax(360px, 1fr); gap: 14px; }}
.panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); overflow: hidden; }}
.panel h2 {{ margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line); font-size: 15px; display: flex; align-items: center; justify-content: space-between; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f6; text-align: left; vertical-align: top; }}
th {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; background: #fbfcfe; }}
td {{ font-size: 13px; }}
.pill {{ display: inline-flex; border-radius: 999px; padding: 2px 8px; font-size: 12px; border: 1px solid var(--line); background: var(--panel-2); font-weight: 650; }}
.ok {{ color: var(--green); }}
.warn {{ color: var(--amber); }}
.error {{ color: var(--coral); }}
.view {{ display: none; }}
.view.active {{ display: block; }}
.studio-layout {{ display: grid; grid-template-columns: 220px 1fr 280px; gap: 12px; min-height: 660px; }}
.palette, .props {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; box-shadow: var(--shadow); opacity: .68; }}
.palette h2, .props h2 {{ font-size: 14px; margin: 0 0 10px; }}
.palette .btn {{ width: 100%; margin-bottom: 8px; text-align: left; }}
.canvas-wrap {{ position: relative; background: #edf1f5; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; box-shadow: var(--shadow); }}
.canvas {{ position: relative; min-height: 660px; background-image: linear-gradient(#dce4ee 1px, transparent 1px), linear-gradient(90deg, #dce4ee 1px, transparent 1px); background-size: 32px 32px; }}
.edge-layer {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
.node {{ position: absolute; width: 165px; min-height: 72px; border-radius: 8px; border: 1px solid var(--line); background: #fff; box-shadow: 0 10px 24px rgba(23,32,42,.13); user-select: none; }}
.node .kind {{ padding: 7px 9px 0; font-size: 11px; color: var(--muted); text-transform: uppercase; }}
.node .label {{ padding: 2px 9px 10px; font-weight: 740; }}
.node.agent {{ border-top: 4px solid var(--teal); }}
.node.llm {{ border-top: 4px solid var(--indigo); }}
.node.tool {{ border-top: 4px solid var(--coral); }}
.node.registry {{ border-top: 4px solid var(--amber); }}
.node.selected {{ outline: 3px solid rgba(15,159,146,.25); }}
.studio-muted {{ pointer-events: none; filter: saturate(.72); opacity: .62; }}
.studio-lock {{ position: absolute; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(244,246,249,.68); backdrop-filter: blur(2px); }}
.studio-lock-inner {{ max-width: 420px; text-align: center; border: 1px solid var(--line); background: rgba(255,255,255,.92); border-radius: 8px; padding: 22px; box-shadow: var(--shadow); }}
.studio-lock-inner h2 {{ margin: 0 0 6px; font-size: 22px; }}
.studio-lock-inner p {{ margin: 0; color: var(--muted); }}
.field {{ display: grid; gap: 5px; margin-bottom: 10px; }}
.field label {{ color: var(--muted); font-size: 12px; }}
.field input, .field select {{ border: 1px solid var(--line); border-radius: 7px; padding: 8px; background: #fff; }}
.code {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; background: #111827; color: #e5e7eb; border-radius: 8px; padding: 12px; max-height: 260px; overflow: auto; }}
@media (max-width: 1080px) {{
  .shell {{ grid-template-columns: 1fr; }}
  .side {{ position: sticky; top: 0; z-index: 5; }}
  .grid, .bands, .studio-layout {{ grid-template-columns: 1fr; }}
}}
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
      <button id="nav-studio" onclick="showView('studio')">Studio <span class="soon-mini">Soon</span></button>
    </nav>
  </aside>
  <main class="main">
    <section id="view-dashboard" class="view">
      <div class="top">
        <div>
          <p class="kicker">Local runtime view</p>
          <h1>Dashboard</h1>
          <p class="lede">Inspect persisted task snapshots, run reports, and registry cards without re-running model calls or tools.</p>
        </div>
        <div class="actions"><button class="btn" onclick="refresh()">Refresh</button><button class="btn primary" onclick="showView('studio')">Studio Preview</button></div>
      </div>
      <div class="alerts" id="alerts"></div>
      <div class="grid" id="metrics"></div>
      <div class="bands"><div class="panel"><h2>Recent tasks</h2><div id="task-table"></div></div><div class="panel"><h2>Recent reports</h2><div id="report-table"></div></div></div>
    </section>
    <section id="view-runs" class="view">
      <div class="top"><div><p class="kicker">Replay substrate</p><h1>Runs</h1><p class="lede">Task snapshots and run reports from the configured SQLite run store.</p></div><div class="actions"><button class="btn" onclick="refresh()">Refresh</button></div></div>
      <div class="panel"><h2>Run store</h2><div id="runs-table"></div></div>
    </section>
    <section id="view-registry" class="view">
      <div class="top"><div><p class="kicker">Discovery</p><h1>Registry</h1><p class="lede">Agent cards currently visible to the dashboard snapshot.</p></div><div class="actions"><button class="btn" onclick="refresh()">Refresh</button></div></div>
      <div class="panel"><h2>Agents</h2><div id="registry-table"></div></div>
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
            <div class="studio-lock"><div class="studio-lock-inner"><h2>Coming soon</h2><p>Studio will return as a proper canvas builder for agents, LLMs, tools, registries, and flow blueprints. For now, this page is a disabled preview inside the dashboard.</p></div></div>
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
window.__PROTOLINK_SNAPSHOT__ = {snapshot_json};
let snapshot = window.__PROTOLINK_SNAPSHOT__;
let blueprint = JSON.parse(JSON.stringify(snapshot.studio?.blueprint || {{nodes: [], edges: []}}));

function showView(name) {{
  for (const el of document.querySelectorAll('.view')) el.classList.remove('active');
  for (const el of document.querySelectorAll('.nav button')) el.classList.remove('active');
  document.getElementById('view-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  if (name === 'studio') renderStudio();
}}

async function refresh() {{
  try {{
    const res = await fetch('/api/snapshot');
    if (res.ok) snapshot = await res.json();
  }} catch (_) {{}}
  blueprint = blueprint.nodes?.length ? blueprint : JSON.parse(JSON.stringify(snapshot.studio?.blueprint || {{nodes: [], edges: []}}));
  render();
}}

function render() {{
  const agents = snapshot.registry?.agents || [];
  const tasks = snapshot.runs?.tasks || [];
  const reports = snapshot.runs?.reports || [];
  const alerts = [];
  if (snapshot.registry?.error) alerts.push('Registry: ' + snapshot.registry.error);
  if (snapshot.runs?.error) alerts.push('Run store: ' + snapshot.runs.error);
  document.getElementById('alerts').innerHTML = alerts.map(message => `<div class="alert">${{esc(message)}}</div>`).join('');
  document.getElementById('side-store').textContent = 'Store: ' + (snapshot.runs?.store || 'not configured');
  document.getElementById('metrics').innerHTML = [
    metric('Agents', agents.length, snapshot.registry?.url || 'snapshot', 'teal'),
    metric('Tasks', tasks.length, 'snapshots', 'indigo'),
    metric('Reports', reports.length, 'stored runs', 'amber'),
    metric('Store', snapshot.runs?.store ? 'on' : 'off', snapshot.runs?.error || 'local', snapshot.runs?.error ? 'coral' : 'teal')
  ].join('');
  document.getElementById('task-table').innerHTML = table(['Task', 'State', 'Run', 'Updated'], tasks.slice(0, 8).map(t => [t.task_id, pill(t.state), t.run_id || '-', t.updated_at || '-']));
  document.getElementById('report-table').innerHTML = table(['Run', 'Session', 'Agent', 'Created'], reports.slice(0, 8).map(r => [r.run_id, r.session_id || '-', r.agent_name || '-', r.created_at || '-']));
  document.getElementById('runs-table').innerHTML = table(['Kind', 'ID', 'Session', 'Agent', 'Time'], [
    ...reports.map(r => ['report', r.run_id, r.session_id || '-', r.agent_name || '-', r.created_at || '-']),
    ...tasks.map(t => ['task', t.task_id, t.session_id || '-', t.agent_name || '-', t.updated_at || '-'])
  ]);
  document.getElementById('registry-table').innerHTML = table(['Name', 'Transport', 'URL', 'Capabilities'], agents.map(a => [a.name || '-', a.transport || '-', a.url || '-', enabledCaps(a.capabilities || {{}})]));
  renderStudio();
}}

function metric(label, value, hint, accent) {{ return `<div class="metric" data-accent="${{esc(accent || 'teal')}}"><div class="label">${{esc(label)}}</div><div class="value">${{esc(String(value))}}</div><div class="label">${{esc(hint || '')}}</div></div>`; }}
function enabledCaps(caps) {{ return Object.entries(caps).filter(([,v]) => v === true).map(([k]) => k).join(', ') || '-'; }}
function pill(value) {{ const cls = value === 'completed' ? 'ok' : value === 'failed' ? 'error' : value === 'canceled' ? 'warn' : ''; return raw(`<span class="pill ${{cls}}">${{esc(value || '-')}}</span>`); }}
function table(headers, rows) {{
  if (!rows.length) return '<div style="padding:14px;color:var(--muted);">(none)</div>';
  return `<table><thead><tr>${{headers.map(h => `<th>${{esc(h)}}</th>`).join('')}}</tr></thead><tbody>${{rows.map(row => `<tr>${{row.map(cell => `<td>${{cellHtml(cell)}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`;
}}
function raw(html) {{ return {{__html: html}}; }}
function cellHtml(cell) {{ return cell && typeof cell === 'object' && '__html' in cell ? cell.__html : esc(cell); }}
function esc(value) {{ return String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}

function renderStudio() {{
  const canvas = document.getElementById('studio-canvas');
  const edgeLayer = document.getElementById('edge-layer');
  if (!canvas || !edgeLayer) return;
  for (const el of canvas.querySelectorAll('.node')) el.remove();
  edgeLayer.innerHTML = '';
  const nodeMap = Object.fromEntries((blueprint.nodes || []).map(n => [n.id, n]));
  for (const edge of blueprint.edges || []) {{
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
  }}
  for (const node of blueprint.nodes || []) {{
    const el = document.createElement('div');
    el.className = `node studio-muted ${{node.kind}}`;
    el.style.left = `${{node.x}}px`;
    el.style.top = `${{node.y}}px`;
    el.innerHTML = `<div class="kind">${{esc(node.kind)}}</div><div class="label">${{esc(node.label)}}</div>`;
    canvas.appendChild(el);
  }}
  const first = blueprint.nodes?.[0] || null;
  document.getElementById('node-label').value = first?.label || '';
  document.getElementById('node-kind').value = first?.kind || 'agent';
  document.getElementById('blueprint-json').textContent = JSON.stringify(blueprint, null, 2);
}}

showView('{safe_start_tab}');
render();
</script>
</body>
</html>"""
