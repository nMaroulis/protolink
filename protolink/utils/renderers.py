# ruff: noqa: E501
"""
HTML and text renderers for Protolink agents.

These utilities provide human-readable representations of AgentCard
instances without introducing UI frameworks or runtime dependencies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protolink.models import AgentCard


def _fmt(value: str | None, default: str = "—") -> str:
    """Format optional values safely for display."""
    return escape(value) if value else default


def _list(items: list[str], empty: str = "None") -> str:
    """Render a list as HTML <li> items."""
    if not items:
        return f"<li><em>{empty}</em></li>"
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def _now_utc() -> str:
    """Human-friendly UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def to_status_html(agent: AgentCard, start_time: float) -> str:
    """Render a stylish agent status page with logo, ping, favicon, and uptime."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{escape(agent.name)} · Agent Status</title>
<link rel="icon" href="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/logo_sm.png" />
<style>
:root {{
  --bg: #070b1a;
  --card: rgba(17, 22, 42, 0.85);
  --border: rgba(56, 189, 248, 0.25);
  --text: #e5e7eb;
  --muted: #9ca3af;
  --accent: #38bdf8;
  --accent-soft: rgba(56,189,248,.15);
  --ok: #22c55e;
  --fail: #ef4444;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background:
    radial-gradient(800px 400px at 20% -10%, #11162a, transparent),
    radial-gradient(600px 300px at 80% 10%, #0b3a55, transparent),
    var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont;
  display: grid;
  place-items: center;
  min-height: 100vh;
}}
.logo {{ display: flex; align-items: center; gap: 10px; }}
.logo img {{ height: 28px; width: auto; border-radius: 6px; opacity: 0.9; }}
.logo img:hover {{ opacity: 1; }}
.card {{
  width: min(520px, 92vw);
  background: var(--card);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 26px 28px;
  box-shadow: 0 20px 60px rgba(0,0,0,.6), inset 0 0 0 1px rgba(255,255,255,.02);
  transition: transform .2s ease, box-shadow .2s ease;
}}
.card:hover {{ transform: translateY(-2px); box-shadow: 0 30px 80px rgba(0,0,0,.7); }}
header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}}
header h1 {{ font-size: 1.3rem; margin: 0; font-weight: 600; letter-spacing: .2px; }}
.status {{
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: .8rem;
  font-weight: 600;
  color: var(--ok);
}}
.status::before {{
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 0 rgba(34,197,94,.7);
  animation: pulse 2s infinite;
}}
@keyframes pulse {{
  0% {{ box-shadow: 0 0 0 0 rgba(34,197,94,.7); }}
  70% {{ box-shadow: 0 0 0 8px rgba(34,197,94,0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(34,197,94,0); }}
}}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px 18px; margin-bottom: 20px; }}
.label {{ font-size: .7rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}
.value {{ font-size: .9rem; word-break: break-all; }}
section {{ margin-top: 18px; }}
section h2 {{ font-size: .75rem; margin: 0 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }}
ul {{ margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }}
ul li {{ background: var(--accent-soft); border: 1px solid var(--border); padding: 4px 10px; border-radius: 999px; font-size: .75rem; }}
.actions {{ margin-top: 22px; display: flex; align-items: center; gap: 12px; }}
button {{
  background: linear-gradient(135deg, transparent, rgba(56,189,248,.08));
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 14px;
  border-radius: 10px;
  cursor: pointer;
  font-size: .8rem;
  transition: all .15s ease;
}}
button:hover {{ border-color: var(--accent); color: var(--accent); box-shadow: 0 0 0 3px rgba(56,189,248,.15); }}
button:disabled {{ opacity: .6; cursor: not-allowed; }}
.ping-result {{ font-size: .75rem; color: var(--muted); }}
footer {{ margin-top: 22px; display: flex; justify-content: space-between; font-size: .7rem; color: var(--muted); border-top: 1px solid var(--border); padding-top: 10px; }}
.uptime {{ font-size: .75rem; color: var(--accent); }}

</style>
</head>
<body>
  <div class="card">

    <header>
      <div class="logo">
        <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/logo_sm.png" alt="Protolink logo" />
        <h1>{_fmt(agent.name)}</h1>
      </div>
      <div id="status" class="status">RUNNING</div>
    </header>

    <div class="grid">
      <div>
        <div class="label">Version</div>
        <div class="value">{_fmt(agent.version)}</div>
      </div>
      <div>
        <div class="label">Protocol</div>
        <div class="value">{_fmt(agent.protocol_version)}</div>
      </div>
      <div>
        <div class="label">Transport</div>
        <div class="value">{_fmt(agent.transport.upper())}</div>
      </div>
      <div>
        <div class="label">Endpoint</div>
        <div class="value">{_fmt(agent.url)}</div>
      </div>
    </div>

    <section>
      <h2>Skills</h2>
      <ul>{_list([s.name for s in agent.skills], empty="No skills declared")}</ul>
    </section>

    <section>
      <h2>Formats</h2>
      <ul>{_list(agent.input_formats + agent.output_formats, empty="text/plain")}</ul>
    </section>

    <div class="actions">
      <button id="ping-btn" onclick="ping()">Ping agent</button>
      <span id="ping-result" class="ping-result"></span>
      <span class="uptime">Uptime: <span id="uptime">0s</span></span>
    </div>

    <footer>
      <span>Tags: {", ".join(agent.tags) or "none"}</span>
      <span>{_now_utc()}</span>
    </footer>
  </div>

<script>
let startTime = {start_time};
function updateUptime() {{
  const diff = Math.floor((Date.now()/1000 - startTime));
  const hours = Math.floor(diff/3600);
  const mins = Math.floor((diff%3600)/60);
  const secs = diff%60;
  document.getElementById("uptime").textContent = `${{hours}}h ${{mins}}m ${{secs}}s`;
}}
setInterval(updateUptime, 1000);
updateUptime();

async function ping() {{
  const btn = document.getElementById("ping-btn");
  const result = document.getElementById("ping-result");
  const status = document.getElementById("status");

  btn.disabled = true;
  result.textContent = "Pinging…";

  try {{
    const res = await fetch("/", {{ method: "GET" }});
    if(res.ok){{
      result.textContent = "✅ Agent reachable";
      status.style.color = "var(--ok)";
      status.textContent = "RUNNING";
    }} else {{
      result.textContent = "❌ Ping failed";
      status.style.color = "var(--fail)";
      status.textContent = "OFFLINE";
    }}
  }} catch {{
    result.textContent = "❌ Ping failed";
    status.style.color = "var(--fail)";
    status.textContent = "OFFLINE";
  }} finally {{
    setTimeout(() => {{
      result.textContent = "";
      btn.disabled = false;
    }}, 3000);
  }}
}}
</script>
</body>
</html>
"""
