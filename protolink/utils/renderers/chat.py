# ruff: noqa: E501
"""
Chat UI renderer for Protolink agents with LLM capabilities.

Generates a self-contained HTML/CSS/JS chat interface that communicates
with the agent's /chat endpoint via POST requests.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from protolink.models import AgentCard


def _fmt(value: str | None, default: str = "—") -> str:
    return escape(value) if value else default


def to_chat_html(
    agent: AgentCard,
    llm_info: dict[str, Any] | None = None,
    start_time: float | None = None,
) -> str:
    """Render a premium chat UI for an agent with LLM capabilities.

    Args:
        agent: The agent's card with metadata.
        llm_info: Dict with keys like 'provider', 'model', 'model_type', 'model_params'.
        start_time: Unix timestamp when the agent started.

    Returns:
        Complete HTML document string.
    """
    llm_info = llm_info or {}
    provider = _fmt(llm_info.get("provider"))
    model = _fmt(llm_info.get("model"))
    model_type = _fmt(llm_info.get("model_type"))
    params = llm_info.get("model_params", {})

    skills_html = ""
    for s in agent.skills:
        skills_html += f'<span class="skill-tag">{escape(s.id)}</span>'
    if not skills_html:
        skills_html = '<span class="skill-tag muted">No skills</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_fmt(agent.name)} · Chat</title>
<link rel="icon" href="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/logo_sm.png" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
/* ── Design tokens ────────────────────────────────────────── */
:root {{
  --bg: #06080f;
  --surface: rgba(14, 18, 32, .92);
  --surface-2: rgba(22, 28, 50, .80);
  --border: rgba(99, 102, 241, .18);
  --border-hover: rgba(99, 102, 241, .40);
  --text: #e8eaf0;
  --text-muted: #7c819a;
  --accent: #818cf8;
  --accent-bright: #a5b4fc;
  --accent-soft: rgba(99, 102, 241, .12);
  --accent-glow: rgba(99, 102, 241, .30);
  --user-bg: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  --agent-bg: var(--surface-2);
  --ok: #34d399;
  --radius: 16px;
  --radius-sm: 10px;
  --font: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
  --transition: .2s cubic-bezier(.4,0,.2,1);
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  display: flex;
  overflow: hidden;
}}

/* ── Sidebar ──────────────────────────────────────────────── */
.sidebar {{
  width: 300px;
  min-width: 300px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  backdrop-filter: blur(16px);
  transition: transform var(--transition);
  z-index: 10;
}}

.sidebar-header {{
  padding: 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 12px;
}}

.sidebar-header img {{
  height: 30px;
  border-radius: 8px;
  opacity: .85;
  transition: opacity var(--transition);
}}

.sidebar-header img:hover {{ opacity: 1; }}

.sidebar-header h1 {{
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -.01em;
  background: linear-gradient(135deg, var(--accent-bright), var(--accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}

.agent-desc {{
  padding: 16px 20px;
  font-size: .82rem;
  color: var(--text-muted);
  line-height: 1.55;
  border-bottom: 1px solid var(--border);
}}

/* ── Info sections ────────────────────────────────────────── */
.info-section {{
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}}

.info-section h3 {{
  font-size: .65rem;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: var(--text-muted);
  margin-bottom: 10px;
  font-weight: 600;
}}

.info-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}}

.info-item {{
  background: var(--accent-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  transition: border-color var(--transition), box-shadow var(--transition);
}}

.info-item:hover {{
  border-color: var(--border-hover);
  box-shadow: 0 0 12px var(--accent-soft);
}}

.info-label {{
  font-size: .6rem;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  margin-bottom: 3px;
}}

.info-value {{
  font-size: .82rem;
  font-weight: 600;
  word-break: break-all;
}}

.skill-tags {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}

.skill-tag {{
  background: var(--accent-soft);
  border: 1px solid var(--border);
  color: var(--accent-bright);
  padding: 4px 10px;
  border-radius: 999px;
  font-size: .7rem;
  font-weight: 500;
  transition: all var(--transition);
}}

.skill-tag:hover {{
  border-color: var(--accent);
  box-shadow: 0 0 8px var(--accent-soft);
}}

.skill-tag.muted {{ color: var(--text-muted); }}

.sidebar-footer {{
  margin-top: auto;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: .68rem;
  color: var(--text-muted);
}}

.status-dot {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ok);
  font-weight: 600;
  font-size: .7rem;
}}

.status-dot::before {{
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
  animation: pulse 2s infinite;
}}

@keyframes pulse {{
  0%,100% {{ box-shadow: 0 0 0 0 rgba(52,211,153,.6); }}
  50% {{ box-shadow: 0 0 10px 4px rgba(52,211,153,.15); }}
}}

/* ── Chat area ────────────────────────────────────────────── */
.chat-area {{
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background:
    radial-gradient(ellipse 900px 500px at 30% -5%, rgba(99,102,241,.06), transparent),
    radial-gradient(ellipse 600px 400px at 80% 10%, rgba(124,58,237,.04), transparent),
    var(--bg);
}}

.chat-topbar {{
  height: 56px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 12px;
  backdrop-filter: blur(8px);
  background: rgba(6, 8, 15, .6);
}}

.toggle-sidebar {{
  display: none;
  background: none;
  border: 1px solid var(--border);
  color: var(--text);
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 1.1rem;
  transition: all var(--transition);
}}

.toggle-sidebar:hover {{ border-color: var(--accent); color: var(--accent); }}

.topbar-title {{ font-size: .9rem; font-weight: 600; }}

.topbar-model {{
  margin-left: auto;
  font-size: .72rem;
  color: var(--text-muted);
  background: var(--accent-soft);
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
}}

/* ── Messages ─────────────────────────────────────────────── */
.messages {{
  flex: 1;
  overflow-y: auto;
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  scroll-behavior: smooth;
}}

.messages::-webkit-scrollbar {{ width: 5px; }}
.messages::-webkit-scrollbar-track {{ background: transparent; }}
.messages::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 99px; }}

.msg {{
  display: flex;
  gap: 12px;
  max-width: 75%;
  animation: msgIn .35s cubic-bezier(.4,0,.2,1);
}}

@keyframes msgIn {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

.msg.user {{ align-self: flex-end; flex-direction: row-reverse; }}
.msg.agent {{ align-self: flex-start; }}

.msg-avatar {{
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: .8rem;
  font-weight: 700;
  flex-shrink: 0;
  border: 1px solid var(--border);
}}

.msg.user .msg-avatar {{
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  color: #fff;
}}

.msg.agent .msg-avatar {{
  background: var(--surface-2);
  color: var(--accent-bright);
}}

.msg-bubble {{
  padding: 12px 16px;
  border-radius: var(--radius);
  font-size: .88rem;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
  position: relative;
}}

.msg.user .msg-bubble {{
  background: var(--user-bg);
  color: #fff;
  border-bottom-right-radius: 4px;
}}

.msg.agent .msg-bubble {{
  background: var(--agent-bg);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}}

.msg-time {{
  font-size: .6rem;
  color: var(--text-muted);
  margin-top: 4px;
  text-align: right;
  opacity: 0;
  transition: opacity var(--transition);
}}

.msg:hover .msg-time {{ opacity: 1; }}

/* ── Typing indicator ─────────────────────────────────────── */
.typing {{
  display: none;
  align-self: flex-start;
  gap: 12px;
  align-items: flex-end;
}}

.typing.visible {{ display: flex; }}

.typing-dots {{
  background: var(--agent-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
  display: flex;
  gap: 5px;
}}

.typing-dots span {{
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  opacity: .4;
  animation: blink 1.4s infinite both;
}}

.typing-dots span:nth-child(2) {{ animation-delay: .2s; }}
.typing-dots span:nth-child(3) {{ animation-delay: .4s; }}

@keyframes blink {{
  0%,80%,100% {{ opacity: .4; transform: scale(1); }}
  40% {{ opacity: 1; transform: scale(1.15); }}
}}

/* ── Welcome ──────────────────────────────────────────────── */
.welcome {{
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  text-align: center;
  padding: 40px;
}}

.welcome-icon {{
  width: 64px;
  height: 64px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(99,102,241,.15), rgba(124,58,237,.15));
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.8rem;
  animation: float 3s ease-in-out infinite;
}}

@keyframes float {{
  0%,100% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-6px); }}
}}

.welcome h2 {{
  font-size: 1.3rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--text), var(--accent-bright));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}

.welcome p {{ color: var(--text-muted); font-size: .88rem; max-width: 420px; line-height: 1.6; }}

/* ── Input area ───────────────────────────────────────────── */
.input-area {{
  padding: 16px 24px 20px;
  border-top: 1px solid var(--border);
  background: rgba(6, 8, 15, .5);
  backdrop-filter: blur(12px);
}}

.input-wrap {{
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 6px 6px 18px;
  transition: border-color var(--transition), box-shadow var(--transition);
}}

.input-wrap:focus-within {{
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft), 0 0 20px var(--accent-glow);
}}

.input-wrap textarea {{
  flex: 1;
  background: none;
  border: none;
  color: var(--text);
  font-family: var(--font);
  font-size: .88rem;
  resize: none;
  outline: none;
  max-height: 120px;
  padding: 10px 0;
  line-height: 1.5;
}}

.input-wrap textarea::placeholder {{ color: var(--text-muted); }}

.send-btn {{
  width: 42px;
  height: 42px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
  box-shadow: 0 4px 14px rgba(79, 70, 229, .35);
}}

.send-btn:hover {{
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(79, 70, 229, .5);
}}

.send-btn:active {{ transform: scale(.95); }}

.send-btn:disabled {{
  opacity: .5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}}

.send-btn svg {{ width: 18px; height: 18px; }}

/* ── Responsive ───────────────────────────────────────────── */
@media (max-width: 768px) {{
  .sidebar {{
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    transform: translateX(-100%);
    box-shadow: 4px 0 30px rgba(0,0,0,.5);
  }}
  .sidebar.open {{ transform: translateX(0); }}
  .toggle-sidebar {{ display: flex; align-items: center; justify-content: center; }}
  .msg {{ max-width: 90%; }}
}}
</style>
</head>
<body>

<!-- Sidebar -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/logo_sm.png" alt="Protolink" />
    <h1>{_fmt(agent.name)}</h1>
  </div>

  <div class="agent-desc">{_fmt(agent.description)}</div>

  <div class="info-section">
    <h3>LLM Configuration</h3>
    <div class="info-grid">
      <div class="info-item">
        <div class="info-label">Provider</div>
        <div class="info-value">{provider}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Model</div>
        <div class="info-value">{model}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Type</div>
        <div class="info-value">{model_type}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Temperature</div>
        <div class="info-value">{params.get("temperature", "—")}</div>
      </div>
    </div>
  </div>

  <div class="info-section">
    <h3>Agent Info</h3>
    <div class="info-grid">
      <div class="info-item">
        <div class="info-label">Version</div>
        <div class="info-value">{_fmt(agent.version)}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Protocol</div>
        <div class="info-value">{_fmt(agent.protocol_version)}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Transport</div>
        <div class="info-value">{_fmt(agent.transport.upper() if agent.transport else None)}</div>
      </div>
      <div class="info-item">
        <div class="info-label">Endpoint</div>
        <div class="info-value">{_fmt(agent.url)}</div>
      </div>
    </div>
  </div>

  <div class="info-section">
    <h3>Skills</h3>
    <div class="skill-tags">{skills_html}</div>
  </div>

  <div class="sidebar-footer">
    <span class="status-dot">ONLINE</span>
    <span>Uptime: <span id="uptime">0s</span></span>
  </div>
</aside>

<!-- Chat -->
<main class="chat-area">
  <div class="chat-topbar">
    <button class="toggle-sidebar" id="toggle-btn" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>
    <span class="topbar-title">Chat with {_fmt(agent.name)}</span>
    <span class="topbar-model">{provider} · {model}</span>
  </div>

  <div class="messages" id="messages">
    <div class="welcome" id="welcome">
      <div class="welcome-icon">💬</div>
      <h2>Start a Conversation</h2>
      <p>Chat directly with <strong>{_fmt(agent.name)}</strong>. This agent is powered by <strong>{model}</strong> and is ready to assist you.</p>
    </div>
  </div>

  <div class="typing" id="typing">
    <div class="msg-avatar" style="background:var(--surface-2);color:var(--accent-bright);border:1px solid var(--border);width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:700;">A</div>
    <div class="typing-dots"><span></span><span></span><span></span></div>
  </div>

  <div class="input-area">
    <div class="input-wrap">
      <textarea id="input" rows="1" placeholder="Type a message…" autofocus></textarea>
      <button class="send-btn" id="send-btn" onclick="sendMessage()" disabled>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>
  </div>
</main>

<script>
const startTime = {start_time or 0};
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const typingEl = document.getElementById("typing");
const welcomeEl = document.getElementById("welcome");
let sessionId = "chat_" + Math.random().toString(36).slice(2, 10);

/* ── Uptime ─────────────────────────────────────────────── */
function updateUptime() {{
  if (!startTime) return;
  const d = Math.floor(Date.now() / 1000 - startTime);
  const h = Math.floor(d / 3600), m = Math.floor((d % 3600) / 60), s = d % 60;
  document.getElementById("uptime").textContent = `${{h}}h ${{m}}m ${{s}}s`;
}}
setInterval(updateUptime, 1000);
updateUptime();

/* ── Auto-resize textarea ───────────────────────────────── */
inputEl.addEventListener("input", () => {{
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
  sendBtn.disabled = !inputEl.value.trim();
}});

inputEl.addEventListener("keydown", (e) => {{
  if (e.key === "Enter" && !e.shiftKey) {{
    e.preventDefault();
    if (inputEl.value.trim()) sendMessage();
  }}
}});

/* ── Time formatter ─────────────────────────────────────── */
function timeStr() {{
  return new Date().toLocaleTimeString([], {{ hour: "2-digit", minute: "2-digit" }});
}}

/* ── Add message to DOM ─────────────────────────────────── */
function addMessage(text, role) {{
  if (welcomeEl) welcomeEl.style.display = "none";
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${{role}}`;
  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = role === "user" ? "U" : "A";
  const col = document.createElement("div");
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = text;
  const time = document.createElement("div");
  time.className = "msg-time";
  time.textContent = timeStr();
  col.appendChild(bubble);
  col.appendChild(time);
  wrapper.appendChild(avatar);
  wrapper.appendChild(col);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}}

/* ── Send message ───────────────────────────────────────── */
async function sendMessage() {{
  const text = inputEl.value.trim();
  if (!text) return;

  addMessage(text, "user");
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendBtn.disabled = true;

  typingEl.classList.add("visible");
  messagesEl.scrollTop = messagesEl.scrollHeight;

  try {{
    const res = await fetch("/chat", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ message: text, session_id: sessionId }}),
    }});
    const data = await res.json();
    typingEl.classList.remove("visible");
    addMessage(data.response || data.error || "No response", "agent");
  }} catch (err) {{
    typingEl.classList.remove("visible");
    addMessage("⚠ Connection error: " + err.message, "agent");
  }}
}}
</script>
</body>
</html>
"""
