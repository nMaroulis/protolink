# ruff: noqa: E501
"""Dependency-free frontend assets for the Protolink Studio dashboard view.

The dashboard renderer embeds these strings into its standalone HTML document.
Studio intentionally uses browser-native CSS, DOM, pointer, file, clipboard, and
download APIs so the standard Protolink package does not need a frontend build
step or third-party JavaScript dependency.
"""

from __future__ import annotations

__all__ = ["STUDIO_CSS", "STUDIO_HTML", "STUDIO_JS"]


STUDIO_CSS = r"""
.studio-root {
  --studio-agent: #0f9f92;
  --studio-agent-soft: #dff6f2;
  --studio-llm: #5665d8;
  --studio-llm-soft: #e8ebff;
  --studio-tool: #d65b48;
  --studio-tool-soft: #fde9e4;
  --studio-registry: #bd7d11;
  --studio-registry-soft: #fff3cf;
  --studio-flow: #7c4dba;
  --studio-flow-soft: #f0e7fb;
  --studio-module: #3b718f;
  --studio-module-soft: #e2f1f7;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
}
.studio-root [hidden] { display: none !important; }
.studio-topbar { grid-row: 1; }
.studio-workspace { grid-row: 2; }
.studio-root.has-notice { grid-template-rows: auto auto minmax(0, 1fr); }
.studio-root.has-notice .studio-notice { grid-row: 2; }
.studio-root.has-notice .studio-workspace { grid-row: 3; }
.studio-topbar {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background:
    radial-gradient(circle at 92% 10%, rgba(86,101,216,.14), transparent 28%),
    radial-gradient(circle at 66% 120%, rgba(15,159,146,.15), transparent 34%),
    linear-gradient(135deg, #fff 0%, #f8fbff 58%, #f3fbf9 100%);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.studio-topbar::before { content: ""; position: absolute; inset: 0 0 auto; height: 3px; background: linear-gradient(90deg, var(--studio-llm), var(--studio-agent) 54%, var(--studio-tool)); }
.studio-heading { min-width: 0; }
.studio-heading h1 { display: flex; align-items: center; gap: 10px; }
.studio-heading .lede { max-width: 690px; }
.studio-beta {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(15,159,146,.24);
  border-radius: 999px;
  padding: 2px 7px;
  color: var(--teal);
  background: var(--teal-soft);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.studio-commandbar {
  display: grid;
  justify-items: end;
  gap: 9px;
  min-width: min(100%, 520px);
}
.studio-command-row { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.studio-command-row .btn { min-height: 32px; padding: 6px 9px; box-shadow: none; }
.studio-command-row .btn.is-danger { color: var(--coral); border-color: rgba(214,91,72,.28); }
.studio-command-row .btn.is-danger:not(:disabled) { background: #fff8f6; }
.studio-command-row .studio-build-action { color: #3542a0; border-color: rgba(86,101,216,.28); background: var(--indigo-soft); }
.studio-command-row .studio-output-launcher { color: #354158; border-color: #ccd5e2; background: #f4f7fb; }
.studio-command-row .studio-output-launcher[data-active="true"] { color: #fff; border-color: #273449; background: #111827; }
.studio-runtime-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 10px;
  background: rgba(255,255,255,.82);
  color: var(--muted);
  font-size: 12px;
  font-weight: 720;
}
.studio-runtime-pill[data-state="running"] { color: var(--green); border-color: rgba(36,138,87,.24); background: var(--green-soft); }
.studio-runtime-pill[data-state="error"] { color: var(--coral); border-color: rgba(214,91,72,.24); background: var(--coral-soft); }
.studio-runtime-pill[data-state="starting"],
.studio-runtime-pill[data-state="stopping"] { color: var(--amber); border-color: rgba(189,125,17,.24); background: var(--amber-soft); }
.studio-notice {
  display: none;
  align-items: flex-start;
  gap: 9px;
  min-height: 38px;
  padding: 9px 12px;
  border: 1px solid rgba(86,101,216,.20);
  border-radius: 9px;
  background: var(--indigo-soft);
  color: #36429b;
}
.studio-notice.is-visible { display: flex; }
.studio-notice[data-tone="success"] { color: var(--green); background: var(--green-soft); border-color: rgba(36,138,87,.20); }
.studio-notice[data-tone="warning"] { color: #78500b; background: var(--amber-soft); border-color: rgba(189,125,17,.24); }
.studio-notice[data-tone="error"] { color: #8e3527; background: var(--coral-soft); border-color: rgba(214,91,72,.24); }
.studio-notice-mark { width: 8px; height: 8px; margin-top: 6px; border-radius: 999px; background: currentColor; flex: 0 0 auto; }
.studio-workspace {
  display: grid;
  grid-template-columns: clamp(190px, 18%, 220px) minmax(0, 1fr) clamp(270px, 25%, 300px);
  gap: 10px;
  align-items: stretch;
  min-width: 0;
  min-height: 650px;
}
.studio-panel {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: rgba(255,255,255,.96);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
}
.studio-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 13px 14px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #fff, #fafcff);
}
.studio-panel-title { min-width: 0; }
.studio-panel-title h2 { margin: 0; font-size: 14px; }
.studio-panel-title p { margin: 3px 0 0; color: var(--muted); font-size: 11px; }
.studio-palette { display: grid; grid-template-rows: auto auto minmax(0, 1fr); max-height: 720px; }
.studio-search-wrap { padding: 10px 12px; border-bottom: 1px solid #edf1f6; }
.studio-search {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 9px;
  background: #fbfcfe;
}
.studio-palette-list { padding: 10px; overflow: auto; display: grid; align-content: start; gap: 8px; }
.studio-palette-item {
  width: 100%;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--studio-kind, var(--teal));
  border-radius: 9px;
  padding: 9px;
  color: var(--ink);
  background: linear-gradient(180deg, #fff, #fbfcfe);
  text-align: left;
  cursor: pointer;
  transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
}
.studio-palette-item:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--studio-kind, var(--teal)) 46%, #d7dee9); box-shadow: 0 8px 18px color-mix(in srgb, var(--studio-kind, var(--teal)) 12%, rgba(24,33,47,.08)); }
.studio-palette-item:focus-visible { outline-color: color-mix(in srgb, var(--studio-kind, var(--teal)) 36%, transparent); }
.studio-palette-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--studio-kind, var(--teal));
  background: var(--studio-kind-soft, var(--teal-soft));
  font-weight: 820;
  text-transform: uppercase;
}
.studio-palette-copy { display: grid; gap: 1px; min-width: 0; }
.studio-palette-copy strong { font-size: 12px; }
.studio-palette-copy span { color: var(--muted); font-size: 10px; line-height: 1.35; }
.studio-palette-plus { color: var(--muted); font-size: 18px; }
.studio-kind-agent { --studio-kind: var(--studio-agent); --studio-kind-soft: var(--studio-agent-soft); --studio-kind-text: #08766d; }
.studio-kind-llm { --studio-kind: var(--studio-llm); --studio-kind-soft: var(--studio-llm-soft); --studio-kind-text: #3f4bac; }
.studio-kind-tool { --studio-kind: var(--studio-tool); --studio-kind-soft: var(--studio-tool-soft); --studio-kind-text: #a83e2f; }
.studio-kind-registry { --studio-kind: var(--studio-registry); --studio-kind-soft: var(--studio-registry-soft); --studio-kind-text: #835507; }
.studio-kind-flow { --studio-kind: var(--studio-flow); --studio-kind-soft: var(--studio-flow-soft); --studio-kind-text: #623a91; }
.studio-kind-module { --studio-kind: var(--studio-module); --studio-kind-soft: var(--studio-module-soft); --studio-kind-text: #2d607b; }
.studio-canvas-panel { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-width: 0; overflow: hidden; }
.studio-canvas-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 52px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(90deg, #fff, #f7fbff 54%, #f3fbf9);
}
.studio-project-summary { display: grid; gap: 1px; min-width: 0; }
.studio-project-summary strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.studio-project-summary span { color: var(--muted); font-size: 11px; }
.studio-canvas-actions { display: flex; align-items: center; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.studio-canvas-actions .mini-btn { background: rgba(255,255,255,.88); }
.studio-camera-controls {
  display: inline-flex;
  align-items: stretch;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255,255,255,.9);
  box-shadow: 0 3px 10px rgba(46,61,82,.06);
}
.studio-camera-controls .mini-btn {
  min-width: 31px;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.studio-camera-controls .mini-btn + .mini-btn { border-left: 1px solid var(--line); }
.studio-camera-controls .studio-zoom-level { min-width: 52px; padding-inline: 8px; font-variant-numeric: tabular-nums; }
.studio-canvas-viewport {
  position: relative;
  min-height: 570px;
  overflow: hidden;
  background: #e4eaf1;
  box-shadow: inset 0 0 35px rgba(66,84,110,.08);
  overscroll-behavior: contain;
  touch-action: none;
  cursor: grab;
  user-select: none;
}
.studio-canvas-viewport.is-panning { cursor: grabbing; }
.studio-canvas-viewport:focus-visible { outline: 2px solid var(--indigo); outline-offset: -2px; }
.studio-visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.studio-canvas-camera {
  --studio-grid-size: 24px;
  --studio-grid-origin-x: 0px;
  --studio-grid-origin-y: 0px;
  position: relative;
  width: 3000px;
  height: 1800px;
  min-width: 100%;
  min-height: 100%;
  background-color: #e4eaf1;
  background-image:
    radial-gradient(circle, rgba(99,113,134,.30) .65px, transparent .95px),
    linear-gradient(145deg, #e4eaf1, #e0e8ec);
  background-position:
    var(--studio-grid-origin-x) var(--studio-grid-origin-y),
    0 0;
  background-size:
    var(--studio-grid-size) var(--studio-grid-size),
    100% 100%;
  background-repeat: repeat, no-repeat;
}
.studio-canvas {
  --studio-world-edge: 1px;
  --studio-world-shadow: 18px;
  position: absolute;
  inset: 0 auto auto 0;
  width: 3000px;
  height: 1800px;
  transform-origin: 0 0;
  will-change: transform;
  background-color: rgba(252,253,255,.72);
  background-image:
    radial-gradient(circle at 18% 16%, rgba(86,101,216,.10), transparent 26%),
    radial-gradient(circle at 76% 72%, rgba(15,159,146,.10), transparent 28%),
    linear-gradient(145deg, rgba(255,255,255,.20), rgba(238,246,249,.12));
  background-size: 100% 100%, 100% 100%, 100% 100%;
  outline: var(--studio-world-edge) solid rgba(75,91,119,.52);
  outline-offset: calc(0px - var(--studio-world-edge));
  box-shadow:
    0 0 var(--studio-world-shadow) rgba(46,61,82,.18),
    inset 0 0 0 var(--studio-world-edge) rgba(255,255,255,.72);
}
.studio-edge-layer, .studio-node-layer { position: absolute; inset: 0; width: 100%; height: 100%; }
.studio-edge-layer { overflow: visible; }
.studio-node-layer { pointer-events: none; }
.studio-edge-line {
  fill: none;
  stroke: #8190a5;
  stroke-width: 2.25;
  vector-effect: non-scaling-stroke;
  pointer-events: none;
  transition: stroke .16s ease, stroke-width .16s ease, filter .16s ease;
}
.studio-edge-line.is-selected { stroke: var(--indigo); stroke-width: 3; filter: drop-shadow(0 2px 4px rgba(86,101,216,.25)); }
.studio-edge-hit { fill: none; stroke: transparent; stroke-width: 18; vector-effect: non-scaling-stroke; pointer-events: stroke; cursor: pointer; }
.studio-edge-hit:focus-visible + .studio-edge-line,
.studio-edge-hit:hover + .studio-edge-line { stroke: var(--indigo); stroke-width: 3; }
.studio-node {
  position: absolute;
  width: 196px;
  min-height: 112px;
  pointer-events: auto;
  border: 1px solid rgba(117,132,153,.34);
  border-top: 4px solid var(--studio-kind, var(--teal));
  border-radius: 11px;
  background: rgba(255,255,255,.98);
  box-shadow: 0 9px 22px rgba(24,33,47,.12);
  user-select: none;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
  touch-action: none;
}
.studio-node:hover { box-shadow: 0 16px 34px rgba(24,33,47,.18); }
.studio-node.is-selected { border-color: var(--studio-kind, var(--teal)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--studio-kind, var(--teal)) 16%, transparent), 0 17px 36px rgba(24,33,47,.18); }
.studio-node.is-dragging { transform: scale(1.015); z-index: 8; cursor: grabbing; transition: none; }
.studio-node.is-connection-source { box-shadow: 0 0 0 4px rgba(86,101,216,.18), 0 17px 36px rgba(24,33,47,.18); }
.studio-node-main {
  width: 100%;
  min-height: 108px;
  display: grid;
  align-content: start;
  gap: 6px;
  border: 0;
  border-radius: 7px;
  padding: 11px 15px 12px;
  color: var(--ink);
  background: radial-gradient(circle at 100% 0, color-mix(in srgb, var(--studio-kind-soft, #f7fafc) 72%, transparent), transparent 52%);
  text-align: left;
  cursor: grab;
}
.studio-node-main:active { cursor: grabbing; }
.studio-node-main:focus-visible { outline: 3px solid color-mix(in srgb, var(--studio-kind, var(--teal)) 28%, transparent); outline-offset: 3px; }
.studio-node-topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.studio-node-kind { color: var(--studio-kind-text, var(--studio-kind, var(--teal))); font-size: 9px; font-weight: 820; letter-spacing: .07em; text-transform: uppercase; }
.studio-node-id { color: #8793a4; font: 9px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.studio-node-label { font-size: 14px; line-height: 1.25; overflow-wrap: anywhere; }
.studio-node-summary { color: var(--muted); font-size: 10px; line-height: 1.35; overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.studio-port {
  position: absolute;
  top: 50%;
  width: 22px;
  height: 30px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  color: #64748b;
  cursor: crosshair;
  transform: translateY(-50%);
}
.studio-port::before {
  content: "";
  width: 12px;
  height: 12px;
  border: 2px solid #fff;
  border-radius: 999px;
  background: var(--studio-kind, var(--teal));
  box-shadow: 0 0 0 1px rgba(78,91,110,.38), 0 3px 8px rgba(24,33,47,.18);
  transition: transform .15s ease, box-shadow .15s ease;
}
.studio-port:hover::before, .studio-port:focus-visible::before { transform: scale(1.28); box-shadow: 0 0 0 4px rgba(86,101,216,.16); }
.studio-port-in { left: -12px; }
.studio-port-out { right: -12px; }
.studio-port-in.is-compatible::before { animation: studioPortPulse 1.2s ease-in-out infinite; }
.studio-port-in.is-incompatible { opacity: .30; cursor: not-allowed; }
@keyframes studioPortPulse { 0%, 100% { box-shadow: 0 0 0 1px rgba(78,91,110,.38); } 50% { box-shadow: 0 0 0 6px rgba(86,101,216,.16); } }
.studio-canvas-empty {
  position: absolute;
  left: 50%;
  top: 45%;
  width: min(430px, calc(100vw - 90px));
  padding: 25px;
  border: 1px dashed #b8c5d5;
  border-radius: 14px;
  background: rgba(255,255,255,.78);
  color: var(--muted);
  text-align: center;
  transform: translate(-50%, -50%);
  pointer-events: none;
}
.studio-canvas-empty strong { display: block; margin-bottom: 5px; color: var(--ink); font-size: 17px; }
.studio-connection-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 38px;
  padding: 7px 12px;
  border-top: 1px solid var(--line);
  background: #fbfcfe;
  color: var(--muted);
  font-size: 11px;
}
.studio-connection-bar.is-active { color: #3f4da5; background: var(--indigo-soft); }
.studio-inspector { display: grid; grid-template-rows: auto auto minmax(0, 1fr); max-height: 720px; }
.studio-inspector-tabs { display: flex; gap: 5px; padding: 9px 11px 0; }
.studio-inspector-tab {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 5px 10px;
  color: var(--muted);
  background: #fff;
  cursor: pointer;
  font-size: 11px;
}
.studio-inspector-tab[aria-selected="true"] { color: var(--indigo); border-color: rgba(86,101,216,.25); background: var(--indigo-soft); font-weight: 760; }
.studio-inspector-body { min-height: 0; padding: 12px; overflow: auto; }
.studio-inspector-empty { display: grid; place-items: center; min-height: 280px; padding: 24px; color: var(--muted); text-align: center; }
.studio-selection-hero {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: linear-gradient(135deg, #fff, var(--studio-kind-soft, #f7fafc));
}
.studio-selection-hero .studio-palette-icon { width: 38px; height: 38px; }
.studio-selection-copy { min-width: 0; }
.studio-selection-copy strong { display: block; overflow-wrap: anywhere; }
.studio-selection-copy span { color: var(--muted); font-size: 10px; }
.studio-fieldset { display: grid; gap: 10px; margin: 0; padding: 0; border: 0; }
.studio-fieldset + .studio-fieldset { margin-top: 15px; padding-top: 14px; border-top: 1px solid #edf1f6; }
.studio-fieldset legend { padding: 0; color: var(--ink); font-size: 11px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.studio-field { display: grid; gap: 5px; min-width: 0; }
.studio-field > label { color: var(--muted); font-size: 11px; font-weight: 670; }
.studio-field input:not([type="checkbox"]),
.studio-field select,
.studio-field textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 9px;
  background: #fff;
  color: var(--ink);
}
.studio-field textarea { min-height: 76px; resize: vertical; font: inherit; }
.studio-field textarea.studio-json-input { min-height: 108px; color: #dbe7f5; background: #111827; border-color: #273449; font: 10px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.studio-field textarea[aria-invalid="true"] { border-color: var(--coral); box-shadow: 0 0 0 3px rgba(214,91,72,.12); }
.studio-field-hint { color: var(--muted); font-size: 10px; line-height: 1.4; }
.studio-check-field { display: flex; align-items: flex-start; gap: 8px; }
.studio-check-field input { margin-top: 3px; accent-color: var(--teal); }
.studio-check-field label { color: var(--ink); font-size: 11px; }
.studio-check-field span { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; }
.studio-inspector-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 14px; }
.studio-inspector-actions .mini-btn.is-danger { color: var(--coral); border-color: rgba(214,91,72,.28); }
.studio-output-dialog {
  width: min(760px, calc(100vw - 32px));
  height: calc(100dvh - 32px);
  max-width: none;
  max-height: none;
  margin: 16px 16px 16px auto;
  padding: 0;
  border: 1px solid rgba(112,128,150,.34);
  border-top: 3px solid var(--studio-llm);
  border-radius: 16px;
  color: var(--ink);
  background: #111827;
  box-shadow: 0 30px 90px rgba(15,23,42,.34);
  overflow: hidden;
}
.studio-output-dialog[open] { display: grid; grid-template-rows: auto auto auto minmax(0, 1fr); }
.studio-output-dialog::backdrop { background: rgba(15,23,42,.30); backdrop-filter: blur(3px); }
.studio-output-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(90deg, #fff, #f8fbff);
}
.studio-output-title h2 { margin: 0; font-size: 14px; }
.studio-output-title p { margin: 3px 0 0; color: var(--muted); font-size: 11px; }
.studio-output-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.studio-output-close { width: 30px; padding: 0; font-size: 18px; line-height: 1; }
.studio-output-tabs { display: flex; gap: 5px; padding: 10px 14px 0; background: #f8fafc; overflow-x: auto; }
.studio-output-tab {
  border: 1px solid #d9e1ec;
  border-bottom: 0;
  border-radius: 7px 7px 0 0;
  padding: 6px 10px;
  color: #607086;
  background: #eef2f7;
  cursor: pointer;
  font-size: 11px;
}
.studio-output-tab[aria-selected="true"] { color: #e5edf7; background: #111827; border-color: #263247; }
.studio-output-meta { min-height: 32px; padding: 8px 14px; color: #9eabc0; background: #111827; font-size: 10px; border-bottom: 1px solid #263247; }
.studio-output-code {
  margin: 0;
  min-width: 0;
  min-height: 0;
  max-height: none;
  overflow: auto;
  padding: 16px;
  white-space: pre;
  tab-size: 4;
  color: #dbe7f5;
  background: #111827;
  font: 11px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.studio-output-code:focus-visible { outline: 3px solid rgba(15,159,146,.35); outline-offset: -3px; }
.studio-output-code.is-empty { display: grid; place-items: center; padding: 40px; color: #9eabc0; text-align: center; white-space: pre-wrap; }
.studio-hidden-input { position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.studio-static-note { color: var(--amber); }
@media (min-width: 1121px) {
  .main.studio-main { height: var(--studio-main-height, 100dvh); overflow: hidden; }
  .main.studio-main #view-studio.active,
  .main.studio-main .studio-root { height: 100%; min-height: 0; }
  .main.studio-main .studio-workspace { height: 100%; min-height: 0; }
  .main.studio-main .studio-palette,
  .main.studio-main .studio-inspector { max-height: none; }
  .main.studio-main .studio-canvas-viewport { min-height: 0; }
}
@media (max-width: 1120px) {
  .studio-topbar { flex-direction: column; }
  .studio-heading .lede { display: none; }
  .studio-commandbar { width: 100%; justify-items: start; }
  .studio-command-row { justify-content: flex-start; }
  .studio-workspace { grid-template-columns: 214px minmax(0, 1fr); }
  .studio-inspector { grid-column: 1 / -1; max-height: 560px; }
  .studio-inspector-body { max-height: 470px; }
}
@media (max-width: 760px) {
  .studio-topbar { padding: 15px; }
  .studio-command-row .btn { flex: 1 1 auto; }
  .studio-workspace { grid-template-columns: 1fr; min-height: 0; }
  .studio-palette, .studio-inspector { max-height: none; }
  .studio-palette-list { display: flex; grid-template-columns: none; overflow-x: auto; overflow-y: hidden; padding: 9px; }
  .studio-palette-item { flex: 0 0 190px; min-height: 70px; }
  .studio-palette-copy span { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
  .studio-canvas-panel, .studio-inspector { grid-column: auto; }
  .studio-canvas-viewport { min-height: 520px; max-height: 66vh; }
  .studio-output-head { flex-direction: column; }
  .studio-output-actions { justify-content: flex-start; }
  .studio-output-dialog { width: calc(100vw - 16px); height: calc(100dvh - 16px); margin: 8px; border-radius: 13px; }
}
@media (max-width: 480px) {
  .studio-palette-list { display: flex; }
  .studio-command-row { width: 100%; }
  .studio-command-row .btn { width: 100%; }
  .studio-canvas-toolbar { align-items: flex-start; flex-direction: column; }
  .studio-canvas-actions { justify-content: flex-start; }
}
@media (min-width: 1121px) and (max-height: 760px) {
  .studio-topbar { padding: 12px 14px; }
  .studio-heading .lede { display: none; }
  .studio-workspace { gap: 9px; }
  .studio-panel-head { padding-block: 10px; }
}
"""


STUDIO_HTML = r"""
<section id="view-studio" class="view">
  <div class="studio-root" aria-labelledby="studio-title">
    <header class="studio-topbar">
      <div class="studio-heading">
        <p class="kicker">Visual runtime builder</p>
        <h1 id="studio-title">Protolink Studio <span class="studio-beta">Local</span></h1>
        <p class="lede">Compose agents, models, tools, registries, flows, and runtime modules on one canvas, then export the blueprint or generate ordinary Protolink Python.</p>
      </div>
      <div class="studio-commandbar" aria-label="Studio commands">
        <div class="studio-command-row">
          <span class="studio-runtime-pill" id="studio-runtime-pill" data-state="idle"><span class="status-dot runtime"></span><span id="studio-runtime-label">Editor ready</span></span>
          <button type="button" class="btn" id="studio-undo" onclick="studioUndo()">Undo</button>
          <button type="button" class="btn" id="studio-redo" onclick="studioRedo()">Redo</button>
          <button type="button" class="btn" id="studio-reset" data-icon="reset" onclick="studioResetProject()">Restore starter</button>
          <button type="button" class="btn is-danger" id="studio-clear" onclick="studioClearProject()">Clear canvas</button>
        </div>
        <div class="studio-command-row">
          <button type="button" class="btn" id="studio-import-json" data-icon="upload" onclick="studioOpenImport()">Import JSON</button>
          <button type="button" class="btn" id="studio-export-json" data-icon="download" onclick="studioExportJson()">Export JSON</button>
          <button type="button" class="btn studio-build-action" id="studio-generate" data-icon="details" onclick="studioGenerateCode()">Generate Python</button>
          <button type="button" class="btn studio-output-launcher" id="studio-open-code" aria-haspopup="dialog" aria-controls="studio-output-dialog" aria-expanded="false" onclick="studioOpenOutput('python')">Code</button>
          <button type="button" class="btn studio-output-launcher" id="studio-open-logs" aria-haspopup="dialog" aria-controls="studio-output-dialog" aria-expanded="false" onclick="studioOpenOutput('logs')">Logs</button>
          <button type="button" class="btn primary" id="studio-run" data-icon="play" onclick="studioRunProject()">Run</button>
          <button type="button" class="btn is-danger" id="studio-stop" onclick="studioStopProject()">Stop</button>
        </div>
      </div>
    </header>

    <div class="studio-notice" id="studio-notice" role="status" aria-live="polite">
      <span class="studio-notice-mark" aria-hidden="true"></span>
      <span id="studio-notice-text"></span>
    </div>

    <input class="studio-hidden-input" id="studio-import-file" type="file" accept="application/json,.json" aria-label="Import Studio blueprint JSON" />

    <div class="studio-workspace">
      <aside class="studio-panel studio-palette" aria-labelledby="studio-palette-title">
        <div class="studio-panel-head">
          <div class="studio-panel-title"><h2 id="studio-palette-title">Components</h2><p>Click to add to the canvas.</p></div>
          <span class="pill idle" id="studio-palette-count">6</span>
        </div>
        <div class="studio-search-wrap"><input class="studio-search" id="studio-palette-search" type="search" placeholder="Find a component…" aria-label="Filter Studio components" /></div>
        <div class="studio-palette-list" id="studio-palette-list"></div>
      </aside>

      <section class="studio-panel studio-canvas-panel" aria-labelledby="studio-canvas-title">
        <div class="studio-canvas-toolbar">
          <div class="studio-project-summary"><strong id="studio-canvas-title">Studio project</strong><span id="studio-canvas-summary">0 nodes · 0 connections</span></div>
          <div class="studio-canvas-actions">
            <button type="button" class="mini-btn" id="studio-project-settings" onclick="studioShowProjectSettings()">Project settings</button>
            <div class="studio-camera-controls" role="group" aria-label="Canvas zoom controls">
              <button type="button" class="mini-btn" id="studio-zoom-out" aria-label="Zoom out" onclick="studioZoomBy(-1)">−</button>
              <button type="button" class="mini-btn studio-zoom-level" id="studio-zoom-level" aria-label="Reset zoom to 100 percent" aria-live="polite" onclick="studioResetZoom()">100%</button>
              <button type="button" class="mini-btn" id="studio-zoom-in" aria-label="Zoom in" onclick="studioZoomBy(1)">+</button>
            </div>
            <button type="button" class="mini-btn" id="studio-fit-view" onclick="studioFitView()">Fit project</button>
            <button type="button" class="mini-btn" id="studio-fit-selection" onclick="studioFocusSelection()">Find selection</button>
            <button type="button" class="mini-btn" id="studio-delete-selection" onclick="studioDeleteSelection()">Delete selected</button>
          </div>
        </div>
        <div class="studio-canvas-viewport" id="studio-canvas-viewport" role="region" aria-label="Studio topology canvas" aria-describedby="studio-canvas-help" tabindex="0">
          <span class="studio-visually-hidden" id="studio-canvas-help">The lightly outlined surface is the draggable work area. Drag empty space to pan. Use Control or Command plus the wheel to zoom. Press plus, minus, zero, or F while the canvas is focused for zoom controls.</span>
          <div class="studio-canvas-camera" id="studio-canvas-camera">
            <div class="studio-canvas" id="studio-canvas">
              <svg class="studio-edge-layer" id="studio-edge-layer" viewBox="0 0 3000 1800" aria-label="Topology connections"></svg>
              <div class="studio-node-layer" id="studio-node-layer"></div>
              <div class="studio-canvas-empty" id="studio-canvas-empty"><strong>Build your first mesh</strong>Choose a component from the palette. Connect a node's right output port to another node's left input port.</div>
            </div>
          </div>
        </div>
        <div class="studio-connection-bar" id="studio-connection-bar">
          <span id="studio-connection-text">Tip: click an output dot, then a compatible input dot.</span>
          <button type="button" class="mini-btn" id="studio-cancel-connection" onclick="studioCancelConnection()" hidden>Cancel connection</button>
        </div>
      </section>

      <aside class="studio-panel studio-inspector" aria-labelledby="studio-inspector-title">
        <div class="studio-panel-head">
          <div class="studio-panel-title"><h2 id="studio-inspector-title">Inspector</h2><p>Declarative, exportable settings.</p></div>
          <span class="pill idle" id="studio-selection-kind">Project</span>
        </div>
        <div class="studio-inspector-tabs" role="tablist" aria-label="Studio inspector" onkeydown="studioInspectorTabKeydown(event)">
          <button type="button" class="studio-inspector-tab" id="studio-tab-selection" role="tab" aria-controls="studio-inspector-body" aria-selected="true" tabindex="0" onclick="studioSetInspectorTab('selection')">Selection</button>
          <button type="button" class="studio-inspector-tab" id="studio-tab-project" role="tab" aria-controls="studio-inspector-body" aria-selected="false" tabindex="-1" onclick="studioSetInspectorTab('project')">Project</button>
        </div>
        <div class="studio-inspector-body" id="studio-inspector-body" role="tabpanel" aria-live="polite"></div>
      </aside>
    </div>

    <dialog class="studio-output-dialog" id="studio-output-dialog" aria-labelledby="studio-output-title" aria-describedby="studio-output-description" oncancel="studioHandleOutputCancel(event)" onclose="studioHandleOutputClosed()" onmousedown="studioHandleOutputBackdrop(event)">
      <div class="studio-output-head">
        <div class="studio-output-title"><h2 id="studio-output-title">Output</h2><p id="studio-output-description">Inspect the portable blueprint, generated Python, or runtime logs.</p></div>
        <div class="studio-output-actions">
          <button type="button" class="mini-btn" id="studio-copy-python" onclick="studioCopyPython()">Copy Python</button>
          <button type="button" class="mini-btn primary" id="studio-download-python" data-icon="download" onclick="studioDownloadPython()">Download Python</button>
          <button type="button" class="mini-btn studio-output-close" id="studio-close-output" aria-label="Close output panel" onclick="studioCloseOutput()">&times;</button>
        </div>
      </div>
      <div class="studio-output-tabs" role="tablist" aria-label="Studio output" onkeydown="studioOutputTabKeydown(event)">
        <button type="button" class="studio-output-tab" id="studio-output-tab-python" role="tab" aria-controls="studio-output-code" aria-selected="true" tabindex="0" onclick="studioSetOutputTab('python')">Python</button>
        <button type="button" class="studio-output-tab" id="studio-output-tab-blueprint" role="tab" aria-controls="studio-output-code" aria-selected="false" tabindex="-1" onclick="studioSetOutputTab('blueprint')">Blueprint JSON</button>
        <button type="button" class="studio-output-tab" id="studio-output-tab-logs" role="tab" aria-controls="studio-output-code" aria-selected="false" tabindex="-1" onclick="studioSetOutputTab('logs')">Runtime logs</button>
      </div>
      <div class="studio-output-meta" id="studio-output-meta" role="status" aria-live="polite">Python generation requires the served dashboard.</div>
      <pre class="studio-output-code" id="studio-output-code" tabindex="0" role="tabpanel"></pre>
    </dialog>
  </div>
</section>
"""


STUDIO_JS = r"""
const STUDIO_STORAGE_KEY = 'protolink.studio.blueprint.v1';
const STUDIO_NODE_KINDS = ['agent', 'llm', 'tool', 'registry', 'flow', 'module'];
const STUDIO_NODE_KIND_SET = new Set(STUDIO_NODE_KINDS);
const STUDIO_NODE_WIDTH = 196;
const STUDIO_NODE_HEIGHT = 112;
const STUDIO_CANVAS_WIDTH = 3000;
const STUDIO_CANVAS_HEIGHT = 1800;
const STUDIO_ZOOM_MIN = .1;
const STUDIO_ZOOM_MAX = 1.75;
const STUDIO_ZOOM_STEP = .1;
const STUDIO_FIT_PADDING = 54;
const STUDIO_HISTORY_LIMIT = 60;
const STUDIO_IMPORT_MAX_BYTES = 1024 * 1024;
const STUDIO_ENV_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/;
const STUDIO_SECRET_KEYS = new Set([
  'access_token', 'api_key', 'auth_token', 'authorization', 'client_secret',
  'cookie', 'credentials', 'passphrase', 'password', 'private_key',
  'proxy_authorization', 'refresh_token', 'secret', 'secret_key',
  'session_token', 'set_cookie', 'token', 'x_api_key',
]);
const STUDIO_LLM_API_KEY_PROVIDERS = new Set([
  'openai', 'anthropic', 'gemini', 'grok', 'deepseek', 'huggingface',
  'lmstudio', 'openai-compatible', 'vllm',
]);
const STUDIO_LLM_BASE_URL_PROVIDERS = new Set([
  'openai', 'anthropic', 'gemini', 'grok', 'deepseek', 'ollama', 'lmstudio',
  'openai-compatible', 'vllm', 'llama.cpp-server',
]);
const STUDIO_LLM_HEADER_PROVIDERS = new Set([
  'ollama', 'lmstudio', 'openai-compatible', 'vllm', 'llama.cpp-server',
]);
const STUDIO_LLM_TOOL_CALLING_PROVIDERS = new Set([
  'grok', 'deepseek', 'ollama', 'lmstudio', 'openai-compatible', 'vllm',
  'llama.cpp-server', 'llama.cpp-local',
]);
const STUDIO_KIND_META = {
  agent: {label: 'Agent', short: 'A', description: 'Identity, prompting, state, transport, and runtime behavior.'},
  llm: {label: 'LLM', short: 'L', description: 'Provider and model settings referenced by one or more agents.'},
  tool: {label: 'Tool', short: 'T', description: 'A built-in capability or an editable custom tool stub.'},
  registry: {label: 'Registry', short: 'R', description: 'Discovery boundary for agents and flows.'},
  flow: {label: 'Flow', short: 'F', description: 'Pipeline, parallel, router, or graph orchestration.'},
  module: {label: 'Module', short: 'M', description: 'Storage, telemetry, logging, policy, knowledge, or auth.'},
};
const STUDIO_FALLBACK_CATALOG = {
  schema_version: 1,
  node_kinds: [...STUDIO_NODE_KINDS],
  transports: ['runtime', 'http', 'sse', 'websocket', 'grpc', 'json-rpc', 'sse-json-rpc'],
  llm_providers: ['mock', 'openai', 'anthropic', 'gemini', 'grok', 'deepseek', 'huggingface', 'ollama', 'lmstudio', 'openai-compatible', 'vllm', 'llama.cpp-server', 'llama.cpp-local'],
  builtin_tools: ['calculator', 'current_datetime', 'fetch_url', 'web_search'],
  flow_types: ['pipeline', 'parallel', 'router', 'graph'],
  module_types: ['storage', 'telemetry', 'logger', 'run_store', 'policy', 'knowledge', 'auth'],
  module_implementations: {
    storage: ['memory', 'sqlite'],
    telemetry: ['local', 'langsmith', 'langfuse'],
    logger: ['console', 'file', 'quiet'],
    run_store: ['sqlite'],
    policy: ['capability'],
    knowledge: ['memory', 'sqlite'],
    auth: ['bearer'],
  },
};

function studioClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function studioString(value, fallback = '', limit = 1000) {
  const text = value == null ? '' : String(value);
  return (text || fallback).slice(0, limit);
}

function studioFinite(value, fallback, maximum) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, Math.min(maximum, Math.round(number)));
}

function studioCatalogList(value, fallback) {
  if (!Array.isArray(value)) return [...fallback];
  const items = value.map(item => studioString(item, '', 80)).filter(Boolean);
  return items.length ? [...new Set(items)] : [...fallback];
}

function studioMergeCatalog(value) {
  const source = value && typeof value === 'object' ? value : {};
  const implementations = {};
  const rawImplementations = source.module_implementations && typeof source.module_implementations === 'object'
    ? source.module_implementations
    : {};
  for (const moduleType of studioCatalogList(source.module_types, STUDIO_FALLBACK_CATALOG.module_types)) {
    implementations[moduleType] = studioCatalogList(
      rawImplementations[moduleType],
      STUDIO_FALLBACK_CATALOG.module_implementations[moduleType] || ['custom'],
    );
  }
  return {
    schema_version: Number(source.schema_version || 1),
    node_kinds: STUDIO_NODE_KINDS.filter(kind => studioCatalogList(source.node_kinds, STUDIO_NODE_KINDS).includes(kind)),
    transports: studioCatalogList(source.transports, STUDIO_FALLBACK_CATALOG.transports),
    llm_providers: studioCatalogList(source.llm_providers, STUDIO_FALLBACK_CATALOG.llm_providers),
    builtin_tools: studioCatalogList(source.builtin_tools, STUDIO_FALLBACK_CATALOG.builtin_tools),
    flow_types: studioCatalogList(source.flow_types, STUDIO_FALLBACK_CATALOG.flow_types),
    module_types: studioCatalogList(source.module_types, STUDIO_FALLBACK_CATALOG.module_types),
    module_implementations: implementations,
  };
}

function studioRandomSuffix() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  if (window.crypto?.getRandomValues) {
    const bytes = new Uint8Array(8);
    window.crypto.getRandomValues(bytes);
    return [...bytes].map(item => item.toString(16).padStart(2, '0')).join('');
  }
  return Math.random().toString(36).slice(2, 14);
}

function studioNewId(prefix, used = null) {
  let candidate = '';
  do candidate = `${prefix}-${studioRandomSuffix()}`;
  while (used?.has(candidate));
  return candidate;
}

function studioSafeId(value, prefix, used) {
  let candidate = studioString(value, '', 64).trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  if (!/^[A-Za-z0-9]/.test(candidate)) candidate = '';
  if (!candidate || used.has(candidate)) candidate = studioNewId(prefix, used);
  used.add(candidate);
  return candidate;
}

function studioSlug(value, fallback = 'component') {
  const slug = studioString(value, '', 80)
    .normalize('NFKD')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
  return slug || fallback;
}

function studioDefaultConfig(kind, label) {
  const name = studioSlug(label, kind);
  if (kind === 'agent') return {
    name,
    description: `${label} agent.`,
    url: `runtime://${name}`,
    transport: 'runtime',
    role: 'worker',
    version: '1.0.0',
    system_prompt: '',
    skills: 'auto',
    state: [],
    verbosity: 1,
    discovery_ttl: 0,
    registry_heartbeat_interval: null,
    expose_chat: true,
    override_system_prompt: false,
    a2a: false,
    register: true,
    retrieval: 'auto',
    capabilities: {},
    security_schemes: {},
    interfaces: [],
    tags: [],
    input_formats: ['text/plain'],
    output_formats: ['text/plain'],
    transport_config: {},
    transport_options: {},
  };
  if (kind === 'llm') return {
    provider: 'mock',
    model: 'mock-gpt',
    api_key_env: '',
    base_url: '',
    headers: {},
    default_response: 'Studio agent is ready.',
    model_params: {temperature: 0.2},
    supports_tool_calling: false,
    metrics_enabled: true,
    advanced: {},
  };
  if (kind === 'tool') return {
    implementation: 'builtin',
    builtin: 'calculator',
    name,
    description: `${label} tool.`,
    input_schema: {type: 'object', properties: {}, additionalProperties: true},
    output_schema: {type: 'object'},
    tags: [],
    capabilities: [],
    args: {},
    examples: [],
    response_template: `${label} completed.`,
  };
  if (kind === 'registry') return {
    url: `runtime://${name}`,
    transport: 'runtime',
    verbosity: 1,
    entry_ttl_seconds: null,
    transport_config: {},
    transport_options: {},
  };
  if (kind === 'flow') return {
    name,
    flow_type: 'pipeline',
    routing_prompt: 'Choose the best route.',
  };
  return {
    module_type: 'storage',
    implementation: 'memory',
    name,
    namespace: name,
    path: '',
    secret_env: '',
  };
}

function studioNormalizeBlueprint(value) {
  const source = value && typeof value === 'object' ? value : {};
  const projectSource = source.project && typeof source.project === 'object' ? source.project : {};
  const usedNodeIds = new Set();
  const nodes = [];
  for (const [index, rawNode] of (Array.isArray(source.nodes) ? source.nodes : []).slice(0, 200).entries()) {
    if (!rawNode || typeof rawNode !== 'object') continue;
    const kind = studioString(rawNode.kind, 'agent', 20).toLowerCase();
    if (!STUDIO_NODE_KIND_SET.has(kind)) continue;
    const id = studioSafeId(rawNode.id, kind, usedNodeIds);
    const label = studioString(rawNode.label, STUDIO_KIND_META[kind].label, 100).trim() || STUDIO_KIND_META[kind].label;
    const rawConfig = rawNode.config && typeof rawNode.config === 'object' && !Array.isArray(rawNode.config)
      ? rawNode.config
      : {};
    nodes.push({
      id,
      kind,
      label,
      x: studioFinite(rawNode.x, 80 + (index % 4) * 250, STUDIO_CANVAS_WIDTH - STUDIO_NODE_WIDTH - 20),
      y: studioFinite(rawNode.y, 70 + Math.floor(index / 4) * 170, STUDIO_CANVAS_HEIGHT - STUDIO_NODE_HEIGHT - 20),
      config: {...studioDefaultConfig(kind, label), ...studioClone(rawConfig)},
    });
  }
  const nodeIds = new Set(nodes.map(node => node.id));
  const usedEdgeIds = new Set();
  const edges = [];
  for (const [index, rawEdge] of (Array.isArray(source.edges) ? source.edges : []).slice(0, 400).entries()) {
    if (!rawEdge || typeof rawEdge !== 'object') continue;
    const from = studioString(rawEdge.from, '', 64).trim();
    const to = studioString(rawEdge.to, '', 64).trim();
    if (!nodeIds.has(from) || !nodeIds.has(to) || from === to) continue;
    edges.push({
      id: studioSafeId(rawEdge.id || `edge-${index + 1}`, 'edge', usedEdgeIds),
      from,
      to,
      relation: studioString(rawEdge.relation, 'auto', 32).trim().toLowerCase().replace(/\s+/g, '_') || 'auto',
      label: studioString(rawEdge.label, '', 80),
      order: Number.isFinite(Number(rawEdge.order)) ? Math.trunc(Number(rawEdge.order)) : index + 1,
    });
  }
  return {
    version: 1,
    project: {
      name: studioString(projectSource.name, 'my_protolink_mesh', 80).trim() || 'my_protolink_mesh',
      description: studioString(projectSource.description, 'A visual Protolink agent mesh.', 500),
    },
    nodes,
    edges,
  };
}

function studioReadPersistedBlueprint() {
  try {
    const text = window.localStorage.getItem(STUDIO_STORAGE_KEY);
    if (!text || text.length > STUDIO_IMPORT_MAX_BYTES) return null;
    const value = JSON.parse(text);
    if (studioContainsEmbeddedSecret(value)) {
      window.localStorage.removeItem(STUDIO_STORAGE_KEY);
      return null;
    }
    return value && typeof value === 'object' ? value : null;
  } catch (_) {
    return null;
  }
}

function studioContainsEmbeddedSecret(value, key = '', seen = new Set()) {
  if (!value || typeof value !== 'object') return false;
  if (seen.has(value)) return false;
  seen.add(value);
  if (Array.isArray(value)) return value.some(item => studioContainsEmbeddedSecret(item, '', seen));
  for (const [rawKey, item] of Object.entries(value)) {
    const normalized = rawKey.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    if (normalized.endsWith('_env') && item != null && item !== '' && (
      typeof item !== 'string' || !STUDIO_ENV_NAME_PATTERN.test(item)
    )) return true;
    if (STUDIO_SECRET_KEYS.has(normalized) && item != null && item !== '') return true;
    if (studioContainsEmbeddedSecret(item, rawKey, seen)) return true;
  }
  return false;
}

let studioCatalog = studioMergeCatalog(snapshot.studio?.catalog);
const studioSnapshotBlueprint = studioNormalizeBlueprint(snapshot.studio?.blueprint || {nodes: [], edges: []});
const studioPersistedBlueprint = studioReadPersistedBlueprint();
const studioInitialBlueprint = snapshot.studio?.loaded
  ? studioSnapshotBlueprint
  : (studioPersistedBlueprint || studioSnapshotBlueprint);
let studioPersistenceTimer = null;
let studioNoticeTimer = null;
let studioStatusTimer = null;
let studioStatusPending = false;
let studioGeneration = 0;
let studioFieldSequence = 0;
let studioOutputReturnFocus = null;
let studioRestoreOutputFocus = true;
let studioPanSession = null;
let studioSuppressCanvasClick = false;
let studioSpacePan = false;
let studioNodeDragActive = false;
let studioCameraResizeObserver = null;
let studioCameraResizeFrame = null;
let studioState = {
  blueprint: studioNormalizeBlueprint(studioInitialBlueprint),
  resetBlueprint: studioClone(studioSnapshotBlueprint),
  history: [],
  future: [],
  selectedNodeId: null,
  selectedEdgeId: null,
  connectionSourceId: null,
  inspectorTab: 'selection',
  outputTab: window.__PROTOLINK_LIVE__ ? 'python' : 'blueprint',
  paletteQuery: '',
  busy: null,
  code: null,
  codeFilename: null,
  codeWarnings: [],
  codeStale: true,
  runtime: {state: 'idle', running: false, run_id: null, logs: []},
  notice: null,
  camera: {zoom: 1, offsetX: 0, offsetY: 0, initialized: false},
};

function syncStudioSnapshot(source) {
  if (!source || typeof source !== 'object') return;
  studioCatalog = studioMergeCatalog(source.catalog || studioCatalog);
}

function studioNodeById(nodeId) {
  return studioState.blueprint.nodes.find(node => node.id === nodeId) || null;
}

function studioEdgeById(edgeId) {
  return studioState.blueprint.edges.find(edge => edge.id === edgeId) || null;
}

function studioDesignSnapshot() {
  return studioClone(studioState.blueprint);
}

function studioDesignKey(value = studioState.blueprint) {
  return JSON.stringify(value);
}

function studioRecordHistory(before) {
  if (!before || studioDesignKey(before) === studioDesignKey()) return false;
  studioState.history.push(before);
  if (studioState.history.length > STUDIO_HISTORY_LIMIT) studioState.history.shift();
  studioState.future = [];
  studioAfterDesignChange();
  return true;
}

function studioMutate(mutator, message = null) {
  const before = studioDesignSnapshot();
  mutator(studioState.blueprint);
  const changed = studioRecordHistory(before);
  if (changed && message) studioSetNotice(message, 'success');
  return changed;
}

function studioAfterDraftChange() {
  studioState.codeStale = true;
  studioSchedulePersistence();
  studioRenderCanvasSummary();
  studioRenderOutput();
  studioRenderControls();
}

function studioAfterDesignChange() {
  studioAfterDraftChange();
  studioRenderCanvas();
  studioRenderInspector();
}

function studioSchedulePersistence() {
  window.clearTimeout(studioPersistenceTimer);
  studioPersistenceTimer = window.setTimeout(studioPersistBlueprint, 160);
}

function studioPersistBlueprint() {
  try {
    if (studioContainsEmbeddedSecret(studioState.blueprint)) {
      studioSetNotice('Studio did not persist this draft because it appears to contain an embedded secret. Use an *_env field instead.', 'error');
      return;
    }
    window.localStorage.setItem(STUDIO_STORAGE_KEY, studioDesignKey());
  } catch (_) {
    studioSetNotice('This browser could not persist the Studio draft. JSON export still works.', 'warning');
  }
}

function studioSetNotice(message, tone = 'info', timeoutMs = 4200) {
  studioState.notice = {message: studioString(message, '', 4000), tone};
  studioRenderNotice();
  window.clearTimeout(studioNoticeTimer);
  if (timeoutMs > 0) {
    studioNoticeTimer = window.setTimeout(() => {
      studioState.notice = null;
      studioRenderNotice();
    }, timeoutMs);
  }
}

function studioRenderNotice() {
  const target = document.getElementById('studio-notice');
  const text = document.getElementById('studio-notice-text');
  if (!target || !text) return;
  const notice = studioState.notice;
  target.classList.toggle('is-visible', Boolean(notice?.message));
  document.querySelector('.studio-root')?.classList.toggle('has-notice', Boolean(notice?.message));
  target.dataset.tone = notice?.tone || 'info';
  text.textContent = notice?.message || '';
}

function studioKindClass(kind) {
  return `studio-kind-${STUDIO_NODE_KIND_SET.has(kind) ? kind : 'module'}`;
}

function studioElement(tag, className = '', textValue = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (textValue != null) element.textContent = String(textValue);
  return element;
}

function studioSvgElement(tag) {
  return document.createElementNS('http://www.w3.org/2000/svg', tag);
}

function studioNodeSummary(node) {
  const config = node.config || {};
  if (node.kind === 'agent') return `${config.transport || 'runtime'} · ${config.role || 'worker'} · ${config.url || 'URL required'}`;
  if (node.kind === 'llm') return `${config.provider || 'provider'} · ${config.model || 'model not set'}`;
  if (node.kind === 'tool') return config.implementation === 'builtin' ? `Built-in · ${config.builtin || 'choose tool'}` : `Custom stub · ${config.name || node.label}`;
  if (node.kind === 'registry') return `${config.transport || 'runtime'} · ${config.url || 'URL required'}`;
  if (node.kind === 'flow') return `${config.flow_type || 'pipeline'} · ${config.name || node.label}`;
  return `${config.module_type || 'module'} · ${config.implementation || 'implementation'}`;
}

function studioConnectionAllowed(source, target) {
  if (!source || !target || source.id === target.id) return false;
  const pair = new Set([source.kind, target.kind]);
  const has = (...values) => values.length === pair.size && values.every(value => pair.has(value));
  if (has('agent', 'llm') || has('agent', 'tool') || has('agent', 'registry')) return true;
  if (has('flow', 'registry') || has('agent', 'module') || has('agent', 'flow')) return true;
  if (pair.size === 1 && (pair.has('flow') || pair.has('agent'))) return true;
  if (has('module', 'registry')) {
    const moduleNode = source.kind === 'module' ? source : target;
    return moduleNode.config?.module_type === 'storage';
  }
  return false;
}

function studioInferRelation(source, target) {
  const kinds = new Set([source.kind, target.kind]);
  if (kinds.has('llm')) return 'llm';
  if (kinds.has('tool')) return 'tool';
  if (kinds.has('registry')) return 'registry';
  if (kinds.has('module')) return source.kind === 'module'
    ? studioString(source.config?.module_type, 'module', 32)
    : studioString(target.config?.module_type, 'module', 32);
  if (kinds.has('flow') || (source.kind === 'agent' && target.kind === 'agent')) return 'step';
  return 'auto';
}

function studioEdgePath(source, target) {
  const x1 = source.x + STUDIO_NODE_WIDTH;
  const y1 = source.y + STUDIO_NODE_HEIGHT / 2;
  const x2 = target.x;
  const y2 = target.y + STUDIO_NODE_HEIGHT / 2;
  const spread = Math.max(58, Math.min(190, Math.abs(x2 - x1) * .48));
  const direction = x2 >= x1 ? 1 : -1;
  return `M ${x1} ${y1} C ${x1 + spread * direction} ${y1}, ${x2 - spread * direction} ${y2}, ${x2} ${y2}`;
}

function studioRenderPalette() {
  const list = document.getElementById('studio-palette-list');
  const count = document.getElementById('studio-palette-count');
  if (!list || !count) return;
  const query = studioState.paletteQuery.trim().toLowerCase();
  const kinds = studioCatalog.node_kinds.filter(kind => {
    const meta = STUDIO_KIND_META[kind];
    return meta && (!query || `${meta.label} ${meta.description}`.toLowerCase().includes(query));
  });
  list.replaceChildren();
  for (const kind of kinds) {
    const meta = STUDIO_KIND_META[kind];
    const button = studioElement('button', `studio-palette-item ${studioKindClass(kind)}`);
    button.type = 'button';
    button.dataset.kind = kind;
    button.setAttribute('aria-label', `Add ${meta.label} node`);
    button.addEventListener('click', () => studioAddNode(kind));
    const icon = studioElement('span', 'studio-palette-icon', meta.short);
    icon.setAttribute('aria-hidden', 'true');
    const copy = studioElement('span', 'studio-palette-copy');
    copy.append(studioElement('strong', '', meta.label), studioElement('span', '', meta.description));
    const plus = studioElement('span', 'studio-palette-plus', '+');
    plus.setAttribute('aria-hidden', 'true');
    button.append(icon, copy, plus);
    list.append(button);
  }
  if (!kinds.length) {
    const empty = studioElement('p', 'empty', 'No components match this filter.');
    list.append(empty);
  }
  count.textContent = String(kinds.length);
}

function studioClampZoom(value) {
  const zoom = Number(value);
  if (!Number.isFinite(zoom)) return studioState.camera.zoom;
  return Math.max(STUDIO_ZOOM_MIN, Math.min(STUDIO_ZOOM_MAX, zoom));
}

function studioApplyCamera() {
  const viewport = document.getElementById('studio-canvas-viewport');
  const camera = document.getElementById('studio-canvas-camera');
  const canvas = document.getElementById('studio-canvas');
  if (!viewport || !camera || !canvas) return false;
  const zoom = studioClampZoom(studioState.camera.zoom);
  const scaledWidth = STUDIO_CANVAS_WIDTH * zoom;
  const scaledHeight = STUDIO_CANVAS_HEIGHT * zoom;
  const offsetX = viewport.clientWidth / 2;
  const offsetY = viewport.clientHeight / 2;
  studioState.camera.zoom = zoom;
  studioState.camera.offsetX = offsetX;
  studioState.camera.offsetY = offsetY;
  camera.style.width = `${scaledWidth + viewport.clientWidth}px`;
  camera.style.height = `${scaledHeight + viewport.clientHeight}px`;
  camera.style.setProperty('--studio-grid-size', `${Math.max(8, 24 * zoom)}px`);
  camera.style.setProperty('--studio-grid-origin-x', `${offsetX}px`);
  camera.style.setProperty('--studio-grid-origin-y', `${offsetY}px`);
  canvas.style.setProperty('--studio-world-edge', `${1 / zoom}px`);
  canvas.style.setProperty('--studio-world-shadow', `${18 / zoom}px`);
  canvas.style.left = `${offsetX}px`;
  canvas.style.top = `${offsetY}px`;
  canvas.style.transform = `scale(${zoom})`;

  const percentage = Math.round(zoom * 100);
  const level = document.getElementById('studio-zoom-level');
  if (level) {
    level.textContent = `${percentage}%`;
    level.setAttribute('aria-label', `Zoom is ${percentage} percent. Reset zoom to 100 percent`);
  }
  const zoomOut = document.getElementById('studio-zoom-out');
  const zoomIn = document.getElementById('studio-zoom-in');
  if (zoomOut) zoomOut.disabled = zoom <= STUDIO_ZOOM_MIN + .001;
  if (zoomIn) zoomIn.disabled = zoom >= STUDIO_ZOOM_MAX - .001;
  return true;
}

function studioScreenToCanvas(clientX, clientY) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport) return {x: 0, y: 0};
  const rect = viewport.getBoundingClientRect();
  const localX = Number(clientX) - rect.left - viewport.clientLeft;
  const localY = Number(clientY) - rect.top - viewport.clientTop;
  const zoom = studioState.camera.zoom || 1;
  return {
    x: (viewport.scrollLeft + localX - studioState.camera.offsetX) / zoom,
    y: (viewport.scrollTop + localY - studioState.camera.offsetY) / zoom,
  };
}

function studioScrollCamera(left, top, animate = false) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport) return;
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  viewport.scrollTo({
    left: Math.max(0, left),
    top: Math.max(0, top),
    behavior: animate && !reduceMotion ? 'smooth' : 'auto',
  });
}

function studioCenterWorldPoint(worldX, worldY, animate = false) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport) return;
  const zoom = studioState.camera.zoom;
  studioScrollCamera(
    studioState.camera.offsetX + worldX * zoom - viewport.clientWidth / 2,
    studioState.camera.offsetY + worldY * zoom - viewport.clientHeight / 2,
    animate,
  );
}

function studioSetZoom(nextZoom, options = {}) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport || studioNodeDragActive) return;
  const oldZoom = studioState.camera.zoom;
  const zoom = studioClampZoom(nextZoom);
  if (Math.abs(zoom - oldZoom) < .0001) return;
  const rect = viewport.getBoundingClientRect();
  const localX = Number.isFinite(options.clientX)
    ? options.clientX - rect.left - viewport.clientLeft
    : viewport.clientWidth / 2;
  const localY = Number.isFinite(options.clientY)
    ? options.clientY - rect.top - viewport.clientTop
    : viewport.clientHeight / 2;
  const worldX = (viewport.scrollLeft + localX - studioState.camera.offsetX) / oldZoom;
  const worldY = (viewport.scrollTop + localY - studioState.camera.offsetY) / oldZoom;
  studioState.camera.zoom = zoom;
  studioApplyCamera();
  studioScrollCamera(
    studioState.camera.offsetX + worldX * zoom - localX,
    studioState.camera.offsetY + worldY * zoom - localY,
  );
}

function studioZoomBy(direction) {
  const next = Math.round((studioState.camera.zoom + Number(direction) * STUDIO_ZOOM_STEP) * 10) / 10;
  studioSetZoom(next);
}

function studioResetZoom() {
  studioSetZoom(1);
}

function studioFitView({animate = true, announce = true} = {}) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport || !viewport.clientWidth || !viewport.clientHeight) return false;
  const nodes = studioState.blueprint.nodes;
  if (!nodes.length) {
    studioState.camera.zoom = 1;
    studioApplyCamera();
    studioCenterWorldPoint(STUDIO_CANVAS_WIDTH / 2, STUDIO_CANVAS_HEIGHT / 2, animate);
    if (announce) studioSetNotice('The empty canvas is centered at 100%.', 'info');
    return true;
  }
  const left = Math.min(...nodes.map(node => node.x));
  const top = Math.min(...nodes.map(node => node.y));
  const right = Math.max(...nodes.map(node => node.x + STUDIO_NODE_WIDTH));
  const bottom = Math.max(...nodes.map(node => node.y + STUDIO_NODE_HEIGHT));
  const availableWidth = Math.max(1, viewport.clientWidth - STUDIO_FIT_PADDING * 2);
  const availableHeight = Math.max(1, viewport.clientHeight - STUDIO_FIT_PADDING * 2);
  studioState.camera.zoom = studioClampZoom(Math.min(
    1,
    availableWidth / Math.max(1, right - left),
    availableHeight / Math.max(1, bottom - top),
  ));
  studioApplyCamera();
  studioCenterWorldPoint((left + right) / 2, (top + bottom) / 2, animate);
  if (announce) studioSetNotice(`Project fitted at ${Math.round(studioState.camera.zoom * 100)}%.`, 'info');
  return true;
}

function studioInitializeCamera() {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport || !viewport.clientWidth || !viewport.clientHeight) return;
  if (!studioState.camera.initialized) {
    studioState.camera.initialized = true;
    studioFitView({animate: false, announce: false});
    return;
  }
  studioApplyCamera();
}

function studioScheduleCamera({fit = false} = {}) {
  window.requestAnimationFrame(() => {
    studioFitWorkspace();
    window.requestAnimationFrame(() => {
      if (fit) {
        studioState.camera.initialized = true;
        studioFitView({animate: false, announce: false});
      } else {
        studioInitializeCamera();
      }
    });
  });
}

function studioNextNodePosition() {
  const viewport = document.getElementById('studio-canvas-viewport');
  const index = studioState.blueprint.nodes.length;
  const zoom = studioState.camera.zoom || 1;
  const originX = viewport
    ? (viewport.scrollLeft + viewport.clientWidth / 2 - studioState.camera.offsetX) / zoom - STUDIO_NODE_WIDTH / 2
    : STUDIO_CANVAS_WIDTH / 2 - STUDIO_NODE_WIDTH / 2;
  const originY = viewport
    ? (viewport.scrollTop + viewport.clientHeight / 2 - studioState.camera.offsetY) / zoom - STUDIO_NODE_HEIGHT / 2
    : STUDIO_CANVAS_HEIGHT / 2 - STUDIO_NODE_HEIGHT / 2;
  const stepX = STUDIO_NODE_WIDTH + 34;
  const stepY = STUDIO_NODE_HEIGHT + 34;
  const positions = [[0, 0]];
  for (let radius = 1; radius <= 6; radius += 1) {
    for (let row = -radius; row <= radius; row += 1) {
      for (let column = -radius; column <= radius; column += 1) {
        if (Math.max(Math.abs(row), Math.abs(column)) === radius) positions.push([column, row]);
      }
    }
  }
  for (const [column, row] of positions) {
    const x = Math.max(20, studioFinite(originX + column * stepX, 80, STUDIO_CANVAS_WIDTH - STUDIO_NODE_WIDTH - 20));
    const y = Math.max(20, studioFinite(originY + row * stepY, 70, STUDIO_CANVAS_HEIGHT - STUDIO_NODE_HEIGHT - 20));
    const available = studioState.blueprint.nodes.every(node => (
      Math.abs(node.x - x) >= STUDIO_NODE_WIDTH + 18
      || Math.abs(node.y - y) >= STUDIO_NODE_HEIGHT + 18
    ));
    if (available) return {x, y};
  }
  return {
    x: 30 + (index % 7) * stepX,
    y: 30 + (Math.floor(index / 7) % 6) * stepY,
  };
}

function studioAddNode(kind) {
  if (!STUDIO_NODE_KIND_SET.has(kind)) return;
  if (studioState.blueprint.nodes.length >= 200) {
    studioSetNotice('Studio blueprints are limited to 200 nodes.', 'warning');
    return;
  }
  const used = new Set(studioState.blueprint.nodes.map(node => node.id));
  const id = studioNewId(kind, used);
  const count = studioState.blueprint.nodes.filter(node => node.kind === kind).length + 1;
  const label = `${STUDIO_KIND_META[kind].label} ${count}`;
  const position = studioNextNodePosition();
  studioMutate(blueprintValue => {
    blueprintValue.nodes.push({id, kind, label, ...position, config: studioDefaultConfig(kind, label)});
  }, `${label} added.`);
  studioState.selectedNodeId = id;
  studioState.selectedEdgeId = null;
  studioState.inspectorTab = 'selection';
  studioRender();
  window.requestAnimationFrame(() => {
    studioFocusSelection();
    document.querySelector(`[data-studio-node-id="${CSS.escape(id)}"] .studio-node-main`)?.focus({preventScroll: true});
  });
}

function studioRenderCanvasSummary() {
  const title = document.getElementById('studio-canvas-title');
  const summary = document.getElementById('studio-canvas-summary');
  if (!title || !summary) return;
  title.textContent = studioState.blueprint.project.name;
  const nodeCount = studioState.blueprint.nodes.length;
  const edgeCount = studioState.blueprint.edges.length;
  summary.textContent = `${nodeCount} ${nodeCount === 1 ? 'node' : 'nodes'} · ${edgeCount} ${edgeCount === 1 ? 'connection' : 'connections'}`;
}

function studioSelectNode(nodeId, focusInspector = false) {
  if (!studioNodeById(nodeId)) return;
  studioState.selectedNodeId = nodeId;
  studioState.selectedEdgeId = null;
  studioState.inspectorTab = 'selection';
  studioUpdateCanvasSelection();
  studioRenderInspector();
  studioRenderControls();
  if (focusInspector) document.getElementById('studio-inspector-body')?.focus?.();
}

function studioSelectEdge(edgeId) {
  if (!studioEdgeById(edgeId)) return;
  studioState.selectedEdgeId = edgeId;
  studioState.selectedNodeId = null;
  studioState.inspectorTab = 'selection';
  studioUpdateCanvasSelection();
  studioRenderInspector();
  studioRenderControls();
}

function studioUpdateCanvasSelection() {
  for (const nodeElement of document.querySelectorAll('[data-studio-node-id]')) {
    const selected = nodeElement.dataset.studioNodeId === studioState.selectedNodeId;
    nodeElement.classList.toggle('is-selected', selected);
    nodeElement.classList.toggle('is-connection-source', nodeElement.dataset.studioNodeId === studioState.connectionSourceId);
    nodeElement.querySelector('.studio-node-main')?.setAttribute('aria-pressed', String(selected));
  }
  for (const line of document.querySelectorAll('[data-studio-edge-line]')) {
    line.classList.toggle('is-selected', line.dataset.studioEdgeLine === studioState.selectedEdgeId);
  }
}

function studioRenderEdges() {
  const layer = document.getElementById('studio-edge-layer');
  if (!layer) return;
  layer.replaceChildren();
  for (const edge of studioState.blueprint.edges) {
    const source = studioNodeById(edge.from);
    const target = studioNodeById(edge.to);
    if (!source || !target) continue;
    const pathValue = studioEdgePath(source, target);
    const label = `${source.label} to ${target.label}, ${edge.relation || 'connection'}`;
    const hit = studioSvgElement('path');
    hit.setAttribute('d', pathValue);
    hit.setAttribute('class', 'studio-edge-hit');
    hit.setAttribute('tabindex', '0');
    hit.setAttribute('role', 'button');
    hit.setAttribute('aria-label', `Select connection ${label}`);
    hit.dataset.studioEdgeId = edge.id;
    hit.addEventListener('click', event => {
      event.stopPropagation();
      studioSelectEdge(edge.id);
    });
    hit.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        studioSelectEdge(edge.id);
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        studioState.selectedEdgeId = edge.id;
        studioDeleteSelection();
      }
    });
    const line = studioSvgElement('path');
    line.setAttribute('d', pathValue);
    line.setAttribute('class', 'studio-edge-line');
    line.dataset.studioEdgeLine = edge.id;
    layer.append(hit, line);
  }
  studioUpdateCanvasSelection();
}

function studioStartDrag(event, nodeId) {
  if (event.button !== 0 || studioSpacePan || studioPanSession) return;
  const node = studioNodeById(nodeId);
  const nodeElement = event.currentTarget.closest('.studio-node');
  const dragHandle = event.currentTarget;
  if (!node || !nodeElement) return;
  event.preventDefault();
  event.stopPropagation();
  studioSelectNode(nodeId);
  const before = studioDesignSnapshot();
  const startX = event.clientX;
  const startY = event.clientY;
  const originX = node.x;
  const originY = node.y;
  const zoom = studioState.camera.zoom || 1;
  let moved = false;
  studioNodeDragActive = true;
  nodeElement.classList.add('is-dragging');
  dragHandle.setPointerCapture?.(event.pointerId);

  const move = moveEvent => {
    const nextX = studioFinite(originX + (moveEvent.clientX - startX) / zoom, originX, STUDIO_CANVAS_WIDTH - STUDIO_NODE_WIDTH - 20);
    const nextY = studioFinite(originY + (moveEvent.clientY - startY) / zoom, originY, STUDIO_CANVAS_HEIGHT - STUDIO_NODE_HEIGHT - 20);
    moved = moved || nextX !== originX || nextY !== originY;
    node.x = nextX;
    node.y = nextY;
    nodeElement.style.left = `${nextX}px`;
    nodeElement.style.top = `${nextY}px`;
    studioRenderEdges();
  };
  const finish = () => {
    dragHandle.removeEventListener('pointermove', move);
    dragHandle.removeEventListener('pointerup', finish);
    dragHandle.removeEventListener('pointercancel', finish);
    dragHandle.removeEventListener('lostpointercapture', finish);
    nodeElement.classList.remove('is-dragging');
    studioNodeDragActive = false;
    if (moved) studioRecordHistory(before);
  };
  dragHandle.addEventListener('pointermove', move);
  dragHandle.addEventListener('pointerup', finish);
  dragHandle.addEventListener('pointercancel', finish);
  dragHandle.addEventListener('lostpointercapture', finish);
}

function studioMoveNodeWithKeyboard(event, nodeId) {
  const deltaByKey = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
  if (!deltaByKey[event.key]) return false;
  event.preventDefault();
  const scale = event.shiftKey ? 24 : 8;
  const [dx, dy] = deltaByKey[event.key];
  studioMutate(blueprintValue => {
    const node = blueprintValue.nodes.find(item => item.id === nodeId);
    if (!node) return;
    node.x = studioFinite(node.x + dx * scale, node.x, STUDIO_CANVAS_WIDTH - STUDIO_NODE_WIDTH - 20);
    node.y = studioFinite(node.y + dy * scale, node.y, STUDIO_CANVAS_HEIGHT - STUDIO_NODE_HEIGHT - 20);
  });
  studioRenderCanvas();
  document.querySelector(`[data-studio-node-id="${CSS.escape(nodeId)}"] .studio-node-main`)?.focus({preventScroll: true});
  return true;
}

function studioCreateNodeElement(node) {
  const meta = STUDIO_KIND_META[node.kind];
  const article = studioElement('article', `studio-node ${studioKindClass(node.kind)}`);
  article.dataset.studioNodeId = node.id;
  article.style.left = `${node.x}px`;
  article.style.top = `${node.y}px`;
  article.setAttribute('aria-label', `${meta.label} node ${node.label}`);

  const input = studioElement('button', 'studio-port studio-port-in');
  input.type = 'button';
  input.title = `Connect into ${node.label}`;
  input.setAttribute('aria-label', `Use ${node.label} as connection target`);
  input.addEventListener('click', event => {
    event.stopPropagation();
    studioCompleteConnection(node.id);
  });

  const main = studioElement('button', 'studio-node-main');
  main.type = 'button';
  main.setAttribute('aria-pressed', String(studioState.selectedNodeId === node.id));
  main.addEventListener('click', () => studioSelectNode(node.id));
  main.addEventListener('pointerdown', event => studioStartDrag(event, node.id));
  main.addEventListener('dblclick', () => {
    studioSelectNode(node.id);
    studioRenderInspector();
    document.querySelector('#studio-inspector-body input')?.focus();
  });
  main.addEventListener('keydown', event => {
    if (studioMoveNodeWithKeyboard(event, node.id)) return;
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      studioState.selectedNodeId = node.id;
      studioDeleteSelection();
    }
  });
  const topLine = studioElement('span', 'studio-node-topline');
  topLine.append(
    studioElement('span', 'studio-node-kind', meta.label),
    studioElement('span', 'studio-node-id', node.id),
  );
  main.append(topLine, studioElement('strong', 'studio-node-label', node.label), studioElement('span', 'studio-node-summary', studioNodeSummary(node)));

  const output = studioElement('button', 'studio-port studio-port-out');
  output.type = 'button';
  output.title = `Connect from ${node.label}`;
  output.setAttribute('aria-label', `Start connection from ${node.label}`);
  output.addEventListener('click', event => {
    event.stopPropagation();
    studioStartConnection(node.id);
  });
  article.append(input, main, output);
  return article;
}

function studioRenderConnectionState() {
  const bar = document.getElementById('studio-connection-bar');
  const text = document.getElementById('studio-connection-text');
  const cancel = document.getElementById('studio-cancel-connection');
  if (!bar || !text || !cancel) return;
  const source = studioNodeById(studioState.connectionSourceId);
  bar.classList.toggle('is-active', Boolean(source));
  cancel.hidden = !source;
  text.textContent = source
    ? `Connecting from ${source.label}. Choose a glowing input port; Escape cancels.`
    : 'Tip: click an output dot, then a compatible input dot.';
  for (const nodeElement of document.querySelectorAll('[data-studio-node-id]')) {
    const node = studioNodeById(nodeElement.dataset.studioNodeId);
    const port = nodeElement.querySelector('.studio-port-in');
    if (!port) continue;
    const compatible = source && studioConnectionAllowed(source, node);
    port.classList.toggle('is-compatible', Boolean(compatible));
    port.classList.toggle('is-incompatible', Boolean(source && !compatible));
  }
  studioUpdateCanvasSelection();
}

function studioRenderCanvas() {
  const layer = document.getElementById('studio-node-layer');
  const empty = document.getElementById('studio-canvas-empty');
  if (!layer || !empty) return;
  layer.replaceChildren(...studioState.blueprint.nodes.map(studioCreateNodeElement));
  empty.hidden = studioState.blueprint.nodes.length > 0;
  studioRenderEdges();
  studioRenderCanvasSummary();
  studioRenderConnectionState();
}

function studioStartConnection(nodeId) {
  if (!studioNodeById(nodeId)) return;
  studioState.connectionSourceId = nodeId;
  studioState.selectedNodeId = nodeId;
  studioState.selectedEdgeId = null;
  studioRenderConnectionState();
  studioRenderInspector();
}

function studioCompleteConnection(targetId) {
  const source = studioNodeById(studioState.connectionSourceId);
  const target = studioNodeById(targetId);
  if (!source) {
    studioSetNotice('Choose an output port first.', 'warning');
    return;
  }
  if (!studioConnectionAllowed(source, target)) {
    studioSetNotice(`${source.label} cannot connect to ${target?.label || 'that target'}.`, 'warning');
    return;
  }
  if (studioState.blueprint.edges.length >= 400) {
    studioSetNotice('Studio blueprints are limited to 400 connections.', 'warning');
    return;
  }
  const duplicate = studioState.blueprint.edges.some(edge => edge.from === source.id && edge.to === target.id);
  if (duplicate) {
    studioSetNotice('That directed connection already exists.', 'warning');
    return;
  }
  if (source.kind === 'flow' && target.kind === 'flow' && studioWouldCreateFlowCycle(source.id, target.id)) {
    studioSetNotice('That connection would create a nested-flow cycle.', 'warning');
    return;
  }
  const edgeId = studioNewId('edge', new Set(studioState.blueprint.edges.map(edge => edge.id)));
  studioMutate(blueprintValue => {
    blueprintValue.edges.push({
      id: edgeId,
      from: source.id,
      to: target.id,
      relation: studioInferRelation(source, target),
      label: '',
      order: blueprintValue.edges.length + 1,
    });
  }, `${source.label} connected to ${target.label}.`);
  studioState.connectionSourceId = null;
  studioState.selectedNodeId = null;
  studioState.selectedEdgeId = edgeId;
  studioRender();
}

function studioWouldCreateFlowCycle(sourceId, targetId) {
  const pending = [targetId];
  const visited = new Set();
  while (pending.length) {
    const nodeId = pending.pop();
    if (nodeId === sourceId) return true;
    if (visited.has(nodeId)) continue;
    visited.add(nodeId);
    for (const edge of studioState.blueprint.edges) {
      if (edge.from === nodeId && studioNodeById(edge.to)?.kind === 'flow') pending.push(edge.to);
    }
  }
  return false;
}

function studioCancelConnection() {
  studioState.connectionSourceId = null;
  studioRenderConnectionState();
}

function studioFocusSelection() {
  const viewport = document.getElementById('studio-canvas-viewport');
  const node = studioNodeById(studioState.selectedNodeId);
  const edge = studioEdgeById(studioState.selectedEdgeId);
  const source = edge ? studioNodeById(edge.from) : null;
  const target = edge ? studioNodeById(edge.to) : null;
  if (!viewport || (!node && (!source || !target))) {
    studioSetNotice('Select a node or connection first.', 'warning');
    return;
  }
  const centerX = node
    ? node.x + STUDIO_NODE_WIDTH / 2
    : (source.x + target.x + STUDIO_NODE_WIDTH) / 2;
  const centerY = node
    ? node.y + STUDIO_NODE_HEIGHT / 2
    : (source.y + target.y + STUDIO_NODE_HEIGHT) / 2;
  studioCenterWorldPoint(centerX, centerY, true);
}

function studioDeleteSelection() {
  const nodeId = studioState.selectedNodeId;
  const edgeId = studioState.selectedEdgeId;
  if (!nodeId && !edgeId) {
    studioSetNotice('Select a node or connection to delete.', 'warning');
    return;
  }
  studioMutate(blueprintValue => {
    if (nodeId) {
      blueprintValue.nodes = blueprintValue.nodes.filter(node => node.id !== nodeId);
      blueprintValue.edges = blueprintValue.edges.filter(edge => edge.from !== nodeId && edge.to !== nodeId);
    } else {
      blueprintValue.edges = blueprintValue.edges.filter(edge => edge.id !== edgeId);
    }
  }, nodeId ? 'Node and its connections deleted.' : 'Connection deleted.');
  studioState.selectedNodeId = null;
  studioState.selectedEdgeId = null;
  if (studioState.connectionSourceId === nodeId) studioState.connectionSourceId = null;
  studioRender();
}

function studioDuplicateSelection() {
  const original = studioNodeById(studioState.selectedNodeId);
  if (!original) return;
  const id = studioNewId(original.kind, new Set(studioState.blueprint.nodes.map(node => node.id)));
  const duplicate = studioClone(original);
  duplicate.id = id;
  duplicate.label = `${original.label} copy`.slice(0, 100);
  duplicate.x = studioFinite(original.x + 36, original.x, STUDIO_CANVAS_WIDTH - STUDIO_NODE_WIDTH - 20);
  duplicate.y = studioFinite(original.y + 36, original.y, STUDIO_CANVAS_HEIGHT - STUDIO_NODE_HEIGHT - 20);
  if (duplicate.config?.name) duplicate.config.name = studioSlug(duplicate.label, id);
  studioMutate(blueprintValue => blueprintValue.nodes.push(duplicate), `${duplicate.label} added.`);
  studioState.selectedNodeId = id;
  studioRender();
}

function studioRefreshNodeDisplay(node) {
  const element = document.querySelector(`[data-studio-node-id="${CSS.escape(node.id)}"]`);
  if (!element) return;
  const label = element.querySelector('.studio-node-label');
  const summary = element.querySelector('.studio-node-summary');
  if (label) label.textContent = node.label;
  if (summary) summary.textContent = studioNodeSummary(node);
  element.setAttribute('aria-label', `${STUDIO_KIND_META[node.kind].label} node ${node.label}`);
}

function studioFieldId(prefix = 'field') {
  studioFieldSequence += 1;
  return `studio-${prefix}-${studioFieldSequence}`;
}

function studioCreateField(parent, labelText, value, options, onValue) {
  const settings = options || {};
  const field = studioElement('div', 'studio-field');
  const id = studioFieldId(settings.idPrefix || 'field');
  const label = studioElement('label', '', labelText);
  label.htmlFor = id;
  let control;
  if (settings.type === 'select') {
    control = studioElement('select');
    const choices = [...new Set([...(settings.choices || []), value == null ? '' : String(value)])];
    for (const choice of choices) {
      const option = studioElement('option', '', settings.labels?.[choice] || choice);
      option.value = choice;
      option.selected = String(choice) === String(value ?? '');
      control.append(option);
    }
  } else if (settings.type === 'textarea' || settings.type === 'json') {
    control = studioElement('textarea', settings.type === 'json' ? 'studio-json-input' : '');
    control.value = settings.type === 'json' ? JSON.stringify(value ?? {}, null, 2) : studioString(value, '', settings.maxLength || 10000);
    if (settings.rows) control.rows = settings.rows;
  } else {
    control = studioElement('input');
    control.type = settings.type === 'number' ? 'number' : 'text';
    control.value = value == null ? '' : String(value);
    if (settings.min != null) control.min = String(settings.min);
    if (settings.max != null) control.max = String(settings.max);
    if (settings.step != null) control.step = String(settings.step);
    if (settings.placeholder) control.placeholder = settings.placeholder;
    control.autocomplete = 'off';
  }
  control.id = id;
  if (settings.required) control.required = true;
  if (settings.maxLength && control.tagName !== 'SELECT') control.maxLength = settings.maxLength;
  field.append(label, control);
  if (settings.hint) field.append(studioElement('span', 'studio-field-hint', settings.hint));
  parent.append(field);

  if (settings.type === 'json') {
    control.addEventListener('change', () => {
      try {
        const parsed = JSON.parse(control.value || '{}');
        const validContainer = settings.jsonKind === 'array'
          ? Array.isArray(parsed)
          : Boolean(parsed && typeof parsed === 'object' && !Array.isArray(parsed));
        if (!validContainer) throw new Error(settings.jsonKind === 'array' ? 'Expected a JSON array.' : 'Expected a JSON object.');
        const before = studioDesignSnapshot();
        onValue(parsed);
        control.setAttribute('aria-invalid', 'false');
        studioRecordHistory(before);
      } catch (error) {
        control.setAttribute('aria-invalid', 'true');
        studioSetNotice(`Invalid JSON in ${labelText}: ${error.message}`, 'error', 0);
      }
    });
    return control;
  }

  if (settings.type === 'select') {
    control.addEventListener('change', () => {
      const before = studioDesignSnapshot();
      onValue(control.value);
      studioRecordHistory(before);
      if (settings.rerender) studioRenderInspector();
    });
    return control;
  }

  let before = null;
  const parseValue = raw => {
    if (settings.type === 'number') {
      if (raw === '' && settings.optional) return null;
      const number = Number(raw);
      if (!Number.isFinite(number)) return settings.optional ? null : 0;
      return settings.integer ? Math.trunc(number) : number;
    }
    if (settings.type === 'array') return raw.split(',').map(item => item.trim()).filter(Boolean);
    return studioString(raw, '', settings.maxLength || 10000);
  };
  control.addEventListener('focus', () => { before = studioDesignSnapshot(); });
  control.addEventListener('input', () => {
    if (!before) before = studioDesignSnapshot();
    onValue(parseValue(control.value));
    studioAfterDraftChange();
  });
  const commit = () => {
    if (before) studioRecordHistory(before);
    before = null;
  };
  control.addEventListener('change', commit);
  control.addEventListener('blur', commit);
  return control;
}

function studioCreateCheck(parent, labelText, checked, hint, onValue) {
  const field = studioElement('div', 'studio-check-field');
  const id = studioFieldId('check');
  const input = studioElement('input');
  input.type = 'checkbox';
  input.id = id;
  input.checked = Boolean(checked);
  const label = studioElement('label');
  label.htmlFor = id;
  label.append(document.createTextNode(labelText));
  if (hint) label.append(studioElement('span', '', hint));
  field.append(input, label);
  parent.append(field);
  input.addEventListener('change', () => {
    const before = studioDesignSnapshot();
    onValue(input.checked);
    studioRecordHistory(before);
  });
  return input;
}

function studioFieldset(title) {
  const fieldset = studioElement('fieldset', 'studio-fieldset');
  fieldset.append(studioElement('legend', '', title));
  return fieldset;
}

function studioSetNodeConfig(node, key, value) {
  node.config[key] = value;
  studioRefreshNodeDisplay(node);
}

function studioRenderNodeInspector(body, node) {
  const meta = STUDIO_KIND_META[node.kind];
  const hero = studioElement('div', `studio-selection-hero ${studioKindClass(node.kind)}`);
  const icon = studioElement('span', 'studio-palette-icon', meta.short);
  icon.setAttribute('aria-hidden', 'true');
  const copy = studioElement('div', 'studio-selection-copy');
  copy.append(studioElement('strong', '', node.label), studioElement('span', '', `${meta.label} · ${node.id}`));
  hero.append(icon, copy);
  body.append(hero);

  const identity = studioFieldset('Node');
  studioCreateField(identity, 'Canvas label', node.label, {maxLength: 100, required: true}, value => {
    node.label = value.trim() || meta.label;
    studioRefreshNodeDisplay(node);
  });
  identity.append(studioElement('span', 'studio-field-hint', 'Node IDs are stable and intentionally read-only so connections stay valid.'));
  body.append(identity);

  const config = studioFieldset(`${meta.label} configuration`);
  const set = (key, value) => studioSetNodeConfig(node, key, value);
  if (node.kind === 'agent') {
    studioCreateField(config, 'Runtime name', node.config.name, {required: true, maxLength: 100}, value => set('name', value));
    studioCreateField(config, 'Description', node.config.description, {type: 'textarea', maxLength: 500, rows: 3}, value => set('description', value));
    studioCreateField(config, 'Role', node.config.role, {type: 'select', choices: ['worker', 'orchestrator', 'gateway', 'interface', 'observer']}, value => set('role', value));
    studioCreateField(config, 'URL', node.config.url, {required: true, maxLength: 2048, hint: 'Use runtime://name for in-process agents or a transport-compatible network URL.'}, value => set('url', value));
    studioCreateField(config, 'Transport', node.config.transport, {type: 'select', choices: studioCatalog.transports}, value => set('transport', value));
    studioCreateField(config, 'Credentials environment variable', node.config.credentials_env, {maxLength: 100, hint: 'Optional environment variable name passed to the transport and agent.'}, value => set('credentials_env', value.trim()));
    studioCreateField(config, 'Version', node.config.version, {maxLength: 40}, value => set('version', value));
    studioCreateField(config, 'System prompt', node.config.system_prompt, {type: 'textarea', maxLength: 20000, rows: 5}, value => set('system_prompt', value));
    studioCreateField(config, 'Skills mode', node.config.skills, {type: 'select', choices: ['auto', 'fixed']}, value => set('skills', value));
    studioCreateField(config, 'State modules', (node.config.state || []).join(', '), {type: 'array', hint: 'Comma-separated: conversation, tools, task, flow.'}, value => set('state', value));
    studioCreateField(config, 'Retrieval', node.config.retrieval, {type: 'select', choices: ['auto', 'always', 'required']}, value => set('retrieval', value));
    studioCreateField(config, 'Verbosity', node.config.verbosity, {type: 'number', min: 0, max: 2, step: 1, integer: true}, value => set('verbosity', value));
    studioCreateField(config, 'Discovery TTL', node.config.discovery_ttl ?? 0, {type: 'number', min: 0, step: 1, integer: true}, value => set('discovery_ttl', value));
    studioCreateField(config, 'Registry heartbeat seconds', node.config.registry_heartbeat_interval, {type: 'number', min: 0.001, step: 0.1, optional: true}, value => set('registry_heartbeat_interval', value));
    studioCreateField(config, 'Tags', (node.config.tags || []).join(', '), {type: 'array', hint: 'Comma-separated.'}, value => set('tags', value));
    studioCreateField(config, 'Input formats', (node.config.input_formats || []).join(', '), {type: 'array'}, value => set('input_formats', value));
    studioCreateField(config, 'Output formats', (node.config.output_formats || []).join(', '), {type: 'array'}, value => set('output_formats', value));
    studioCreateCheck(config, 'Expose chat', node.config.expose_chat, 'Expose the agent chat interface.', value => set('expose_chat', value));
    studioCreateCheck(config, 'Enable A2A', node.config.a2a, 'Requires the HTTP transport.', value => set('a2a', value));
    studioCreateCheck(config, 'Register on start', node.config.register, 'Register this agent when the generated project starts.', value => set('register', value));
    studioCreateCheck(config, 'Override system prompt', node.config.override_system_prompt, '', value => set('override_system_prompt', value));
    studioCreateField(config, 'Capabilities', node.config.capabilities, {type: 'json'}, value => set('capabilities', value));
    studioCreateField(config, 'Security schemes', node.config.security_schemes ?? {}, {type: 'json'}, value => set('security_schemes', value));
    studioCreateField(config, 'Interfaces', node.config.interfaces ?? [], {type: 'json', jsonKind: 'array', hint: 'Agent interface objects as a JSON array.'}, value => set('interfaces', value));
    studioCreateField(config, 'Transport config', node.config.transport_config, {type: 'json'}, value => set('transport_config', value));
    studioCreateField(config, 'Transport options', node.config.transport_options, {type: 'json'}, value => set('transport_options', value));
  } else if (node.kind === 'llm') {
    const provider = node.config.provider || 'mock';
    studioCreateField(config, 'Provider', provider, {type: 'select', choices: studioCatalog.llm_providers, rerender: true}, value => {
      set('provider', value);
      if (!STUDIO_LLM_API_KEY_PROVIDERS.has(value)) set('api_key_env', '');
      if (!STUDIO_LLM_BASE_URL_PROVIDERS.has(value)) set('base_url', '');
      if (!STUDIO_LLM_HEADER_PROVIDERS.has(value)) set('headers', {});
      if (!STUDIO_LLM_TOOL_CALLING_PROVIDERS.has(value)) set('supports_tool_calling', false);
    });
    studioCreateField(config, 'Model', node.config.model, {required: true, maxLength: 200}, value => set('model', value));
    if (STUDIO_LLM_API_KEY_PROVIDERS.has(provider)) studioCreateField(config, 'API key environment variable', node.config.api_key_env, {maxLength: 100, hint: 'Name only, for example OPENAI_API_KEY. Secrets are never stored in the blueprint.'}, value => set('api_key_env', value.trim()));
    if (STUDIO_LLM_BASE_URL_PROVIDERS.has(provider)) studioCreateField(config, 'Base URL', node.config.base_url, {maxLength: 2048}, value => set('base_url', value));
    if (STUDIO_LLM_HEADER_PROVIDERS.has(provider)) studioCreateField(config, 'Headers', node.config.headers ?? {}, {type: 'json', hint: 'Non-secret request headers. Keep credentials in environment variables.'}, value => set('headers', value));
    if (provider === 'mock') studioCreateField(config, 'Mock response', node.config.default_response, {type: 'textarea', maxLength: 5000, rows: 3}, value => set('default_response', value));
    studioCreateField(config, 'Model parameters', node.config.model_params, {type: 'json'}, value => set('model_params', value));
    if (STUDIO_LLM_TOOL_CALLING_PROVIDERS.has(provider)) studioCreateCheck(config, 'Tool calling', node.config.supports_tool_calling, 'Declare model-side tool-call support.', value => set('supports_tool_calling', value));
    studioCreateCheck(config, 'Metrics', node.config.metrics_enabled, 'Collect model metrics when supported.', value => set('metrics_enabled', value));
    studioCreateField(config, 'Maximum parse failures', node.config.max_parse_failures, {type: 'number', min: 0, step: 1, integer: true, optional: true}, value => set('max_parse_failures', value));
    studioCreateField(config, 'Advanced provider options', node.config.advanced, {type: 'json'}, value => set('advanced', value));
  } else if (node.kind === 'tool') {
    studioCreateField(config, 'Implementation', node.config.implementation, {type: 'select', choices: ['builtin', 'custom'], rerender: true}, value => set('implementation', value));
    if (node.config.implementation === 'builtin') {
      studioCreateField(config, 'Built-in tool', node.config.builtin, {type: 'select', choices: studioCatalog.builtin_tools}, value => set('builtin', value));
    }
    studioCreateField(config, 'Function name', node.config.name, {required: true, maxLength: 100}, value => set('name', value));
    studioCreateField(config, 'Description', node.config.description, {type: 'textarea', maxLength: 1000, rows: 3}, value => set('description', value));
    if (node.config.implementation === 'custom') {
      studioCreateField(config, 'Stub response', node.config.response_template, {type: 'textarea', maxLength: 5000, rows: 3}, value => set('response_template', value));
    }
    studioCreateField(config, 'Tags', (node.config.tags || []).join(', '), {type: 'array'}, value => set('tags', value));
    studioCreateField(config, 'Capabilities', (node.config.capabilities || []).join(', '), {type: 'array'}, value => set('capabilities', value));
    studioCreateField(config, 'Default arguments', node.config.args ?? {}, {type: 'json', hint: 'JSON-safe defaults passed through Tool.args.'}, value => set('args', value));
    studioCreateField(config, 'Examples', node.config.examples ?? [], {type: 'json', jsonKind: 'array', hint: 'JSON-safe Tool examples.'}, value => set('examples', value));
    studioCreateField(config, 'Input schema', node.config.input_schema, {type: 'json'}, value => set('input_schema', value));
    studioCreateField(config, 'Output schema', node.config.output_schema, {type: 'json'}, value => set('output_schema', value));
  } else if (node.kind === 'registry') {
    studioCreateField(config, 'URL', node.config.url, {required: true, maxLength: 2048}, value => set('url', value));
    studioCreateField(config, 'Transport', node.config.transport, {type: 'select', choices: studioCatalog.transports}, value => set('transport', value));
    studioCreateField(config, 'Credentials environment variable', node.config.credentials_env, {maxLength: 100}, value => set('credentials_env', value.trim()));
    studioCreateField(config, 'Verbosity', node.config.verbosity, {type: 'number', min: 0, max: 2, step: 1, integer: true}, value => set('verbosity', value));
    studioCreateField(config, 'Entry TTL seconds', node.config.entry_ttl_seconds, {type: 'number', min: 0.001, step: 0.1, optional: true}, value => set('entry_ttl_seconds', value));
    studioCreateField(config, 'Transport config', node.config.transport_config, {type: 'json'}, value => set('transport_config', value));
    studioCreateField(config, 'Transport options', node.config.transport_options, {type: 'json'}, value => set('transport_options', value));
  } else if (node.kind === 'flow') {
    studioCreateField(config, 'Flow name', node.config.name, {required: true, maxLength: 100}, value => set('name', value));
    studioCreateField(config, 'Flow type', node.config.flow_type, {type: 'select', choices: studioCatalog.flow_types}, value => set('flow_type', value));
    studioCreateField(config, 'Router prompt', node.config.routing_prompt, {type: 'textarea', maxLength: 5000, rows: 4, hint: 'Used by router flows; harmless for other flow types.'}, value => set('routing_prompt', value));
    if (node.config.flow_type === 'graph') studioCreateField(config, 'Entry node ID', node.config.entry_node, {maxLength: 64, hint: 'Optional connected agent node ID. The first connected node is used when empty.'}, value => set('entry_node', value.trim()));
  } else {
    studioRenderModuleFields(config, node, set);
  }
  body.append(config);

  const actions = studioElement('div', 'studio-inspector-actions');
  const duplicate = studioElement('button', 'mini-btn', 'Duplicate node');
  duplicate.type = 'button';
  duplicate.addEventListener('click', studioDuplicateSelection);
  const remove = studioElement('button', 'mini-btn is-danger', 'Delete node');
  remove.type = 'button';
  remove.addEventListener('click', studioDeleteSelection);
  actions.append(duplicate, remove);
  body.append(actions);
}

function studioRenderModuleFields(config, node, set) {
  studioCreateField(config, 'Module type', node.config.module_type, {type: 'select', choices: studioCatalog.module_types, rerender: true}, value => {
    set('module_type', value);
    const choices = studioCatalog.module_implementations[value] || ['custom'];
    set('implementation', choices[0]);
  });
  const implementations = studioCatalog.module_implementations[node.config.module_type] || ['custom'];
  studioCreateField(config, 'Implementation', node.config.implementation, {type: 'select', choices: implementations, rerender: true}, value => set('implementation', value));
  studioCreateField(config, 'Name', node.config.name, {required: true, maxLength: 100}, value => set('name', value));
  if (node.config.module_type === 'storage') {
    studioCreateField(config, 'Namespace', node.config.namespace, {maxLength: 100}, value => set('namespace', value));
    studioCreateField(config, 'Database path', node.config.path, {maxLength: 500, placeholder: 'storage.db'}, value => set('path', value));
    if (node.config.implementation === 'sqlite') studioCreateField(config, 'Table name', node.config.table_name ?? 'storage', {maxLength: 100}, value => set('table_name', value));
    studioCreateField(config, 'TTL seconds', node.config.ttl, {type: 'number', min: 1, step: 1, integer: true, optional: true}, value => set('ttl', value));
  } else if (node.config.module_type === 'telemetry') {
    if (node.config.implementation === 'local') {
      studioCreateField(config, 'Trace file', node.config.path, {maxLength: 500, placeholder: 'traces.jsonl'}, value => set('path', value));
      studioCreateField(config, 'Maximum traces', node.config.max_traces ?? 1000, {type: 'number', min: 1, step: 1, integer: true}, value => set('max_traces', value));
      studioCreateCheck(config, 'Capture payloads', node.config.capture_payloads ?? true, '', value => set('capture_payloads', value));
    } else if (node.config.implementation === 'langsmith') {
      studioCreateField(config, 'API key environment variable', node.config.api_key_env, {maxLength: 100}, value => set('api_key_env', value.trim()));
      studioCreateField(config, 'Project name', node.config.project_name, {maxLength: 100}, value => set('project_name', value));
    } else {
      studioCreateField(config, 'Public key environment variable', node.config.public_key_env, {maxLength: 100}, value => set('public_key_env', value.trim()));
      studioCreateField(config, 'Secret key environment variable', node.config.secret_key_env, {maxLength: 100}, value => set('secret_key_env', value.trim()));
      studioCreateField(config, 'Host', node.config.host, {maxLength: 2048}, value => set('host', value));
    }
  } else if (node.config.module_type === 'logger') {
    studioCreateField(config, 'Log level', node.config.level ?? 'INFO', {type: 'select', choices: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']}, value => set('level', value));
    if (node.config.implementation === 'file') studioCreateField(config, 'Log file', node.config.path, {maxLength: 500, placeholder: 'protolink.log'}, value => set('path', value));
  } else if (node.config.module_type === 'run_store') {
    studioCreateField(config, 'Database path', node.config.path, {maxLength: 500, placeholder: 'runs.db'}, value => set('path', value));
    studioCreateField(config, 'Table prefix', node.config.table_prefix ?? 'protolink', {maxLength: 80}, value => set('table_prefix', value));
  } else if (node.config.module_type === 'policy') {
    studioCreateField(config, 'Default effect', node.config.default_effect ?? 'allow', {type: 'select', choices: ['allow', 'deny']}, value => set('default_effect', value));
    studioCreateField(config, 'Rules', node.config.rules ?? {}, {type: 'json'}, value => set('rules', value));
  } else if (node.config.module_type === 'knowledge') {
    studioCreateField(config, 'Description', node.config.description, {type: 'textarea', rows: 3, maxLength: 1000}, value => set('description', value));
    studioCreateField(config, 'Sources', Array.isArray(node.config.sources) ? node.config.sources.join(', ') : '', {type: 'array'}, value => set('sources', value));
    studioCreateField(config, 'Default result count', node.config.default_k ?? 5, {type: 'number', min: 1, max: 50, step: 1, integer: true}, value => set('default_k', value));
    studioCreateField(config, 'Context character limit', node.config.context_max_chars ?? 12000, {type: 'number', min: 1, step: 1, integer: true}, value => set('context_max_chars', value));
    if (node.config.implementation === 'sqlite') {
      studioCreateField(config, 'Database path', node.config.path, {maxLength: 500, placeholder: 'knowledge.db'}, value => set('path', value));
      studioCreateField(config, 'Namespace', node.config.namespace, {maxLength: 100}, value => set('namespace', value));
    }
  } else if (node.config.module_type === 'auth') {
    studioCreateField(config, 'Secret environment variable', node.config.secret_env, {required: true, maxLength: 100, hint: 'Environment variable name only; never paste the secret value.'}, value => set('secret_env', value.trim()));
    studioCreateField(config, 'Algorithm', node.config.algorithm ?? 'HS256', {maxLength: 40}, value => set('algorithm', value));
    studioCreateField(config, 'Issuer', node.config.issuer, {maxLength: 200}, value => set('issuer', value));
    studioCreateField(config, 'Audience', node.config.audience, {maxLength: 200}, value => set('audience', value));
    studioCreateField(config, 'Leeway seconds', node.config.leeway_seconds ?? 0, {type: 'number', min: 0, step: 1, integer: true}, value => set('leeway_seconds', value));
  }
}

function studioRenderEdgeInspector(body, edge) {
  const source = studioNodeById(edge.from);
  const target = studioNodeById(edge.to);
  const hero = studioElement('div', 'studio-selection-hero studio-kind-flow');
  const icon = studioElement('span', 'studio-palette-icon', '↗');
  icon.setAttribute('aria-hidden', 'true');
  const copy = studioElement('div', 'studio-selection-copy');
  copy.append(
    studioElement('strong', '', `${source?.label || edge.from} → ${target?.label || edge.to}`),
    studioElement('span', '', `Connection · ${edge.id}`),
  );
  hero.append(icon, copy);
  body.append(hero);
  const config = studioFieldset('Connection');
  studioCreateField(config, 'Relation', edge.relation, {required: true, maxLength: 32, hint: 'Examples: llm, tool, registry, storage, step.'}, value => {
    edge.relation = value.trim().toLowerCase().replace(/\s+/g, '_') || 'auto';
  });
  studioCreateField(config, 'Label', edge.label, {maxLength: 80}, value => { edge.label = value; });
  studioCreateField(config, 'Order', edge.order, {type: 'number', step: 1, integer: true}, value => { edge.order = value; });
  body.append(config);
  const help = studioElement('p', 'studio-field-hint', 'Connections are directed from the right output port to the left input port. Click another connection on the canvas to inspect it.');
  body.append(help);
  const actions = studioElement('div', 'studio-inspector-actions');
  const remove = studioElement('button', 'mini-btn is-danger', 'Delete connection');
  remove.type = 'button';
  remove.addEventListener('click', studioDeleteSelection);
  actions.append(remove);
  body.append(actions);
}

function studioRenderProjectInspector(body) {
  const hero = studioElement('div', 'studio-selection-hero studio-kind-registry');
  const icon = studioElement('span', 'studio-palette-icon', 'P');
  icon.setAttribute('aria-hidden', 'true');
  const copy = studioElement('div', 'studio-selection-copy');
  copy.append(studioElement('strong', '', studioState.blueprint.project.name), studioElement('span', '', 'Portable Studio project settings'));
  hero.append(icon, copy);
  body.append(hero);
  const settings = studioFieldset('Project');
  studioCreateField(settings, 'Project name', studioState.blueprint.project.name, {required: true, maxLength: 80, hint: 'Used to name generated code and runtime output.'}, value => {
    studioState.blueprint.project.name = value.trim() || 'my_protolink_mesh';
    studioRenderCanvasSummary();
  });
  studioCreateField(settings, 'Description', studioState.blueprint.project.description, {type: 'textarea', maxLength: 500, rows: 4}, value => {
    studioState.blueprint.project.description = value;
  });
  body.append(settings);
  const portability = studioFieldset('Portability');
  portability.append(studioElement('p', 'studio-field-hint', 'The JSON blueprint contains topology and declarative configuration. Keep credentials in environment variables referenced by *_env fields.'));
  const exportButton = studioElement('button', 'mini-btn', 'Export blueprint JSON');
  exportButton.type = 'button';
  exportButton.addEventListener('click', studioExportJson);
  portability.append(exportButton);
  body.append(portability);
}

function studioRenderInspector() {
  const body = document.getElementById('studio-inspector-body');
  const selectionTab = document.getElementById('studio-tab-selection');
  const projectTab = document.getElementById('studio-tab-project');
  const kind = document.getElementById('studio-selection-kind');
  if (!body || !selectionTab || !projectTab || !kind) return;
  const projectActive = studioState.inspectorTab === 'project';
  selectionTab.setAttribute('aria-selected', String(!projectActive));
  selectionTab.tabIndex = projectActive ? -1 : 0;
  projectTab.setAttribute('aria-selected', String(projectActive));
  projectTab.tabIndex = projectActive ? 0 : -1;
  body.setAttribute('aria-labelledby', projectActive ? 'studio-tab-project' : 'studio-tab-selection');
  body.replaceChildren();
  if (projectActive) {
    kind.textContent = 'Project';
    kind.className = 'pill idle';
    studioRenderProjectInspector(body);
    return;
  }
  const node = studioNodeById(studioState.selectedNodeId);
  const edge = studioEdgeById(studioState.selectedEdgeId);
  if (node) {
    kind.textContent = STUDIO_KIND_META[node.kind].label;
    kind.className = `pill ${studioKindClass(node.kind)}`;
    studioRenderNodeInspector(body, node);
  } else if (edge) {
    kind.textContent = 'Connection';
    kind.className = 'pill studio-kind-flow';
    studioRenderEdgeInspector(body, edge);
  } else {
    kind.textContent = 'None';
    kind.className = 'pill idle';
    const empty = studioElement('div', 'studio-inspector-empty');
    const copy = studioElement('div');
    copy.append(studioElement('strong', '', 'Nothing selected'), studioElement('p', '', 'Select a node or connection on the canvas, or open Project settings.'));
    empty.append(copy);
    body.append(empty);
  }
}

function studioSetInspectorTab(tab) {
  studioState.inspectorTab = tab === 'project' ? 'project' : 'selection';
  studioRenderInspector();
}

function studioShowProjectSettings() {
  studioSetInspectorTab('project');
  document.getElementById('studio-tab-project')?.focus();
}

function studioOpenOutput(tab = studioState.outputTab) {
  const dialog = document.getElementById('studio-output-dialog');
  if (!dialog) return;
  studioSetOutputTab(tab);
  if (!dialog.open) {
    studioOutputReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    studioRestoreOutputFocus = true;
    dialog.showModal();
  }
  studioSyncOutputLaunchers();
  window.requestAnimationFrame(() => {
    document.getElementById(`studio-output-tab-${studioState.outputTab}`)?.focus();
  });
}

function studioCloseOutput({restoreFocus = true} = {}) {
  const dialog = document.getElementById('studio-output-dialog');
  studioRestoreOutputFocus = restoreFocus;
  if (dialog?.open) dialog.close();
  else studioHandleOutputClosed();
}

function studioHandleOutputClosed() {
  studioSyncOutputLaunchers();
  const returnFocus = studioOutputReturnFocus;
  studioOutputReturnFocus = null;
  if (studioRestoreOutputFocus && returnFocus?.isConnected) returnFocus.focus({preventScroll: true});
  studioRestoreOutputFocus = true;
}

function studioHandleOutputCancel(event) {
  event.preventDefault();
  studioCloseOutput();
}

function studioHandleOutputBackdrop(event) {
  if (event.target !== event.currentTarget) return;
  const rect = event.currentTarget.getBoundingClientRect();
  const inside = event.clientX >= rect.left && event.clientX <= rect.right
    && event.clientY >= rect.top && event.clientY <= rect.bottom;
  if (!inside) studioCloseOutput();
}

function studioInspectorTabKeydown(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const project = event.key === 'ArrowRight' || event.key === 'End';
  studioSetInspectorTab(project ? 'project' : 'selection');
  document.getElementById(project ? 'studio-tab-project' : 'studio-tab-selection')?.focus();
}

function studioSetOutputTab(tab) {
  studioState.outputTab = ['python', 'blueprint', 'logs'].includes(tab) ? tab : 'blueprint';
  studioRenderOutput();
}

function studioSyncOutputLaunchers() {
  const open = Boolean(document.getElementById('studio-output-dialog')?.open);
  const codeActive = open && studioState.outputTab !== 'logs';
  const logsActive = open && studioState.outputTab === 'logs';
  const code = document.getElementById('studio-open-code');
  const logs = document.getElementById('studio-open-logs');
  code?.setAttribute('aria-expanded', String(open));
  logs?.setAttribute('aria-expanded', String(open));
  if (code) code.dataset.active = String(codeActive);
  if (logs) logs.dataset.active = String(logsActive);
}

function studioOutputTabKeydown(event) {
  const tabs = ['python', 'blueprint', 'logs'];
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  let index = tabs.indexOf(studioState.outputTab);
  if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = tabs.length - 1;
  else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  studioSetOutputTab(tabs[index]);
  document.getElementById(`studio-output-tab-${tabs[index]}`)?.focus();
}

function studioRenderOutput() {
  const code = document.getElementById('studio-output-code');
  const meta = document.getElementById('studio-output-meta');
  const title = document.getElementById('studio-output-title');
  if (!code || !meta) return;
  for (const tab of ['python', 'blueprint', 'logs']) {
    const button = document.getElementById(`studio-output-tab-${tab}`);
    if (!button) continue;
    const selected = studioState.outputTab === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  code.setAttribute('aria-labelledby', `studio-output-tab-${studioState.outputTab}`);
  let empty = false;
  if (studioState.outputTab === 'blueprint') {
    if (title) title.textContent = 'Blueprint JSON';
    code.textContent = JSON.stringify(studioState.blueprint, null, 2);
    meta.textContent = `Schema v${studioState.blueprint.version} · ${studioState.blueprint.nodes.length} nodes · portable JSON`;
  } else if (studioState.outputTab === 'logs') {
    if (title) title.textContent = 'Runtime logs';
    const logs = Array.isArray(studioState.runtime.logs) ? studioState.runtime.logs.map(line => studioString(line, '', 10000)) : [];
    empty = !logs.length;
    code.textContent = logs.length ? logs.join('\n') : 'No runtime output yet. Run the project from a served local dashboard to stream logs here.';
    const state = studioString(studioState.runtime.state, 'idle', 40);
    const exit = studioState.runtime.exit_code == null ? '' : ` · exit ${studioState.runtime.exit_code}`;
    meta.textContent = `${state}${exit} · ${logs.length} log ${logs.length === 1 ? 'line' : 'lines'}`;
  } else if (!window.__PROTOLINK_LIVE__) {
    if (title) title.textContent = 'Generated Python';
    empty = true;
    code.textContent = 'Python generation is available when this dashboard is served by Protolink.\n\nThe complete visual editor and JSON import/export remain available in this static file.';
    meta.textContent = 'Static editor · serve the dashboard to generate and run code';
  } else if (!studioState.code) {
    if (title) title.textContent = 'Generated Python';
    empty = true;
    code.textContent = 'Select “Generate Python” to validate this blueprint and create a standalone Protolink script.';
    meta.textContent = 'No generated Python yet';
  } else {
    if (title) title.textContent = 'Generated Python';
    code.textContent = studioState.code;
    const stale = studioState.codeStale ? ' · draft changed—regenerate before use' : '';
    const warnings = studioState.codeWarnings.length ? ` · ${studioState.codeWarnings.length} warning${studioState.codeWarnings.length === 1 ? '' : 's'}` : '';
    meta.textContent = `${studioState.codeFilename || 'generated.py'}${stale}${warnings}`;
  }
  code.classList.toggle('is-empty', empty);
  studioSyncOutputLaunchers();
}

function studioRenderRuntime() {
  const pill = document.getElementById('studio-runtime-pill');
  const label = document.getElementById('studio-runtime-label');
  if (!pill || !label) return;
  if (!window.__PROTOLINK_LIVE__) {
    pill.dataset.state = 'static';
    label.textContent = 'Static editor';
    return;
  }
  const state = studioString(studioState.runtime.state, 'idle', 40);
  pill.dataset.state = state;
  if (studioState.busy === 'run') label.textContent = 'Starting…';
  else if (studioState.busy === 'stop') label.textContent = 'Stopping…';
  else if (studioState.runtime.running) label.textContent = `Running · ${studioState.runtime.pid || 'local'}`;
  else if (state === 'error') label.textContent = 'Runtime error';
  else if (state === 'stopped') label.textContent = 'Stopped';
  else label.textContent = 'Editor ready';
}

function studioRenderControls() {
  const live = Boolean(window.__PROTOLINK_LIVE__);
  const busy = Boolean(studioState.busy);
  const generatedCurrent = Boolean(studioState.code && !studioState.codeStale);
  const setDisabled = (id, disabled, title = '') => {
    const button = document.getElementById(id);
    if (!button) return;
    button.disabled = disabled;
    button.title = title;
  };
  setDisabled('studio-undo', !studioState.history.length || busy);
  setDisabled('studio-redo', !studioState.future.length || busy);
  setDisabled('studio-clear', busy || Boolean(studioState.runtime.running), studioState.runtime.running ? 'Stop the active project before clearing the canvas' : 'Clear every node and connection');
  setDisabled('studio-generate', !live || busy, live ? 'Validate and generate Python' : 'Available in the served dashboard');
  setDisabled('studio-run', !live || busy || Boolean(studioState.runtime.running), live ? 'Generate and run this project locally' : 'Available in the served dashboard');
  setDisabled('studio-stop', !live || busy || !studioState.runtime.running, live ? 'Stop the active Studio process' : 'Available in the served dashboard');
  const stop = document.getElementById('studio-stop');
  if (stop) stop.hidden = !live || (!studioState.runtime.running && studioState.busy !== 'stop');
  setDisabled('studio-copy-python', !live || busy || !generatedCurrent, !live ? 'Available in the served dashboard' : generatedCurrent ? 'Copy generated Python' : 'Generate current Python first');
  setDisabled('studio-download-python', !live || busy || !generatedCurrent, !live ? 'Available in the served dashboard' : generatedCurrent ? 'Download generated Python' : 'Generate current Python first');
  setDisabled('studio-delete-selection', !studioState.selectedNodeId && !studioState.selectedEdgeId);
  setDisabled('studio-fit-selection', !studioState.selectedNodeId && !studioState.selectedEdgeId, 'Select a node or connection to center it');
  studioRenderRuntime();
}

function studioErrorMessage(payload, fallback) {
  if (Array.isArray(payload?.issues) && payload.issues.length) {
    return payload.issues.slice(0, 8).map(item => studioString(item, '', 500)).join(' · ');
  }
  return studioString(payload?.error, fallback, 4000) || fallback;
}

async function studioRequest(path, method = 'GET', body = null) {
  const options = {method, cache: 'no-store', headers: {Accept: 'application/json'}};
  if (body != null) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let payload = null;
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(studioErrorMessage(payload, `Studio request failed (${response.status}).`));
  return payload || {};
}

async function studioGenerateCode(options = {}) {
  if (!window.__PROTOLINK_LIVE__) {
    studioSetNotice('Python generation requires a served Protolink dashboard.', 'warning');
    return false;
  }
  const generation = ++studioGeneration;
  studioState.busy = 'generate';
  studioRenderControls();
  if (!options.quiet) studioSetNotice('Validating blueprint and generating Python…', 'info', 0);
  try {
    const payload = await studioRequest('/api/studio/generate', 'POST', {blueprint: studioState.blueprint});
    if (generation !== studioGeneration) return false;
    studioState.code = studioString(payload.code, '', 2_000_000);
    studioState.codeFilename = studioString(payload.filename, 'protolink_studio.py', 180);
    studioState.codeWarnings = Array.isArray(payload.warnings) ? payload.warnings.map(item => studioString(item, '', 1000)) : [];
    studioState.codeStale = false;
    studioState.outputTab = 'python';
    if (!options.quiet && options.openOutput !== false) studioOpenOutput('python');
    studioSetNotice(
      studioState.codeWarnings.length ? `Python generated with ${studioState.codeWarnings.length} warning(s).` : 'Python generated successfully.',
      studioState.codeWarnings.length ? 'warning' : 'success',
    );
    return true;
  } catch (error) {
    studioSetNotice(error.message || 'Could not generate Python.', 'error', 0);
    return false;
  } finally {
    if (generation === studioGeneration) studioState.busy = null;
    studioRenderOutput();
    studioRenderControls();
  }
}

async function studioCopyText(textValue) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(textValue);
    return;
  }
  const textarea = studioElement('textarea');
  textarea.value = textValue;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();
  if (!copied) throw new Error('Clipboard access was unavailable.');
}

async function studioCopyPython() {
  if (!studioState.code || studioState.codeStale) {
    const generated = await studioGenerateCode({quiet: true});
    if (!generated) return;
  }
  try {
    await studioCopyText(studioState.code);
    studioSetNotice('Generated Python copied to the clipboard.', 'success');
  } catch (error) {
    studioSetNotice(error.message || 'Could not copy Python.', 'error');
  }
}

function studioDownloadText(filename, contents, mimeType) {
  const blob = new Blob([contents], {type: mimeType});
  const url = URL.createObjectURL(blob);
  const link = studioElement('a');
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 500);
}

async function studioDownloadPython() {
  if (!studioState.code || studioState.codeStale) {
    const generated = await studioGenerateCode({quiet: true});
    if (!generated) return;
  }
  const safeFilename = studioString(studioState.codeFilename, 'protolink_studio.py', 180).replace(/[^A-Za-z0-9._-]+/g, '_') || 'protolink_studio.py';
  studioDownloadText(safeFilename, studioState.code, 'text/x-python;charset=utf-8');
  studioSetNotice(`${safeFilename} downloaded.`, 'success');
}

function studioExportJson() {
  const filename = `${studioSlug(studioState.blueprint.project.name, 'protolink_studio')}.studio.json`;
  studioDownloadText(filename, `${JSON.stringify(studioState.blueprint, null, 2)}\n`, 'application/json;charset=utf-8');
  studioSetNotice(`${filename} exported.`, 'success');
}

function studioOpenImport() {
  const input = document.getElementById('studio-import-file');
  if (!input) return;
  input.value = '';
  input.click();
}

async function studioImportFile(file) {
  if (!file) return;
  if (file.size > STUDIO_IMPORT_MAX_BYTES) {
    studioSetNotice('Studio JSON imports are limited to 1 MB.', 'error');
    return;
  }
  try {
    const textValue = await file.text();
    const parsed = JSON.parse(textValue);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('The blueprint root must be a JSON object.');
    if (studioContainsEmbeddedSecret(parsed)) throw new Error('The blueprint appears to contain an embedded secret. Replace secret values with *_env variable names before importing.');
    const normalized = studioNormalizeBlueprint(parsed);
    const before = studioDesignSnapshot();
    studioState.blueprint = normalized;
    studioState.selectedNodeId = null;
    studioState.selectedEdgeId = null;
    studioState.connectionSourceId = null;
    studioState.camera.initialized = false;
    studioRecordHistory(before);
    studioRender();
    studioScheduleCamera({fit: true});
    studioSetNotice(`Imported ${normalized.nodes.length} nodes and ${normalized.edges.length} connections.`, 'success');
  } catch (error) {
    studioSetNotice(`Could not import Studio JSON: ${error.message}`, 'error', 0);
  }
}

function studioRestoreBlueprint(value) {
  studioState.blueprint = studioNormalizeBlueprint(value);
  studioState.selectedNodeId = null;
  studioState.selectedEdgeId = null;
  studioState.connectionSourceId = null;
  studioState.codeStale = true;
  studioSchedulePersistence();
  studioRender();
}

function studioUndo() {
  if (!studioState.history.length || studioState.busy) return;
  const current = studioDesignSnapshot();
  const previous = studioState.history.pop();
  studioState.future.push(current);
  studioRestoreBlueprint(previous);
  studioSetNotice('Undid the last Studio change.', 'info');
}

function studioRedo() {
  if (!studioState.future.length || studioState.busy) return;
  const current = studioDesignSnapshot();
  const next = studioState.future.pop();
  studioState.history.push(current);
  studioRestoreBlueprint(next);
  studioSetNotice('Redid the Studio change.', 'info');
}

function studioResetProject() {
  if (studioState.busy) return;
  if (!window.confirm('Reset Studio to the packaged starter blueprint? This change can be undone.')) return;
  const before = studioDesignSnapshot();
  studioState.blueprint = studioNormalizeBlueprint(studioState.resetBlueprint);
  studioState.selectedNodeId = null;
  studioState.selectedEdgeId = null;
  studioState.connectionSourceId = null;
  studioState.camera.initialized = false;
  studioRecordHistory(before);
  studioRender();
  studioScheduleCamera({fit: true});
  studioSetNotice('Studio reset to the starter blueprint.', 'success');
}

function studioClearProject() {
  if (studioState.busy) return;
  if (studioState.runtime.running) {
    studioSetNotice('Stop the active Studio project before clearing the canvas.', 'warning');
    return;
  }
  if (!window.confirm('Clear every node and connection from Studio? You can restore them with Undo.')) return;
  const before = studioDesignSnapshot();
  studioState.blueprint = studioNormalizeBlueprint({
    version: 1,
    project: {name: 'untitled_studio', description: 'A new Protolink Studio project.'},
    nodes: [],
    edges: [],
  });
  studioState.selectedNodeId = null;
  studioState.selectedEdgeId = null;
  studioState.connectionSourceId = null;
  studioState.camera.zoom = 1;
  studioState.camera.initialized = false;
  studioState.code = null;
  studioState.codeFilename = null;
  studioState.codeWarnings = [];
  studioState.codeStale = true;
  studioState.outputTab = 'blueprint';
  studioGeneration += 1;
  window.clearTimeout(studioPersistenceTimer);
  studioRecordHistory(before);
  studioPersistBlueprint();
  studioCloseOutput({restoreFocus: false});
  studioRender();
  studioScheduleCamera({fit: true});
  studioSetNotice('Canvas cleared. Undo is available.', 'success');
}

function studioApplyRuntime(payload) {
  if (!payload || typeof payload !== 'object') return;
  studioState.runtime = {
    state: studioString(payload.state, payload.running ? 'running' : 'idle', 40),
    running: Boolean(payload.running),
    run_id: typeof payload.run_id === 'string' ? payload.run_id : null,
    project: studioString(payload.project, '', 100),
    pid: Number.isFinite(Number(payload.pid)) ? Number(payload.pid) : null,
    started_at: studioString(payload.started_at, '', 100),
    exit_code: payload.exit_code == null ? null : Number(payload.exit_code),
    logs: Array.isArray(payload.logs) ? payload.logs.slice(-2000).map(item => studioString(item, '', 10000)) : [],
  };
  studioRenderRuntime();
  studioRenderOutput();
  studioRenderControls();
}

async function studioRefreshStatus({quiet = true} = {}) {
  if (!window.__PROTOLINK_LIVE__ || studioStatusPending) return;
  studioStatusPending = true;
  try {
    studioApplyRuntime(await studioRequest('/api/studio/status'));
  } catch (error) {
    if (!quiet) studioSetNotice(error.message || 'Could not read Studio runtime status.', 'error');
  } finally {
    studioStatusPending = false;
  }
}

async function studioRunProject() {
  if (!window.__PROTOLINK_LIVE__) {
    studioSetNotice('Running a project requires a served local Protolink dashboard.', 'warning');
    return;
  }
  if (studioState.runtime.running || studioState.busy) return;
  if (!studioState.code || studioState.codeStale) {
    const generated = await studioGenerateCode({quiet: true});
    if (!generated) return;
  }
  studioState.busy = 'run';
  studioRenderControls();
  studioSetNotice('Starting the Studio project locally…', 'info', 0);
  try {
    const payload = await studioRequest('/api/studio/run', 'POST', {blueprint: studioState.blueprint});
    studioApplyRuntime(payload);
    studioState.outputTab = 'logs';
    studioOpenOutput('logs');
    studioSetNotice('Studio project started.', 'success');
  } catch (error) {
    studioSetNotice(error.message || 'Could not start the Studio project.', 'error', 0);
  } finally {
    studioState.busy = null;
    studioRenderControls();
  }
}

async function studioStopProject() {
  if (!window.__PROTOLINK_LIVE__ || studioState.busy || !studioState.runtime.run_id) return;
  studioState.busy = 'stop';
  studioRenderControls();
  studioSetNotice('Stopping the Studio project…', 'info', 0);
  try {
    const payload = await studioRequest('/api/studio/stop', 'POST', {run_id: studioState.runtime.run_id});
    studioApplyRuntime(payload);
    studioState.outputTab = 'logs';
    studioOpenOutput('logs');
    studioSetNotice('Studio project stopped.', 'success');
  } catch (error) {
    studioSetNotice(error.message || 'Could not stop the Studio project.', 'error', 0);
  } finally {
    studioState.busy = null;
    studioRenderControls();
  }
}

let studioMounted = false;

function studioFitWorkspace() {
  const main = document.querySelector('.main');
  if (!main || !document.getElementById('view-studio')?.classList.contains('active')) {
    main?.style.removeProperty('--studio-main-height');
    return;
  }
  const top = Math.max(0, main.getBoundingClientRect().top);
  main.style.setProperty('--studio-main-height', `${Math.max(520, window.innerHeight - top)}px`);
}

function studioStartPan(event) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport || studioNodeDragActive || studioPanSession) return;
  const interactive = event.target.closest?.('.studio-node, .studio-edge-hit, button, input, textarea, select, [contenteditable="true"]');
  const middleButton = event.button === 1;
  const spaceDrag = event.button === 0 && studioSpacePan;
  const backgroundDrag = event.button === 0 && !interactive;
  if (!middleButton && !spaceDrag && !backgroundDrag) return;
  event.preventDefault();
  viewport.focus({preventScroll: true});
  studioPanSession = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: viewport.scrollLeft,
    scrollTop: viewport.scrollTop,
    moved: false,
  };
  viewport.classList.add('is-panning');
  viewport.setPointerCapture?.(event.pointerId);
}

function studioMovePan(event) {
  const viewport = document.getElementById('studio-canvas-viewport');
  const session = studioPanSession;
  if (!viewport || !session || session.pointerId !== event.pointerId) return;
  event.preventDefault();
  const dx = event.clientX - session.startX;
  const dy = event.clientY - session.startY;
  if (Math.hypot(dx, dy) > 3) session.moved = true;
  viewport.scrollLeft = session.scrollLeft - dx;
  viewport.scrollTop = session.scrollTop - dy;
}

function studioFinishPan(event) {
  const viewport = document.getElementById('studio-canvas-viewport');
  const session = studioPanSession;
  if (!viewport || !session || session.pointerId !== event.pointerId) return;
  studioPanSession = null;
  viewport.classList.remove('is-panning');
  if (event.type !== 'lostpointercapture' && viewport.hasPointerCapture?.(event.pointerId)) {
    viewport.releasePointerCapture(event.pointerId);
  }
  if (session.moved) {
    studioSuppressCanvasClick = true;
    window.setTimeout(() => { studioSuppressCanvasClick = false; }, 0);
  }
}

function studioWheelCanvas(event) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport || studioNodeDragActive) return;
  event.preventDefault();
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
  if (event.ctrlKey || event.metaKey) {
    const delta = event.deltaY * unit;
    if (!delta) return;
    studioSetZoom(studioState.camera.zoom * Math.exp(-delta * .0018), {
      clientX: event.clientX,
      clientY: event.clientY,
    });
    return;
  }
  let deltaX = event.deltaX * unit;
  let deltaY = event.deltaY * unit;
  if (event.shiftKey && Math.abs(deltaX) < Math.abs(deltaY)) {
    deltaX = deltaY;
    deltaY = 0;
  }
  viewport.scrollLeft += deltaX;
  viewport.scrollTop += deltaY;
}

function studioCanvasKeydown(event) {
  const viewport = document.getElementById('studio-canvas-viewport');
  if (!viewport || event.target !== viewport || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key === '+' || event.key === '=') {
    event.preventDefault();
    studioZoomBy(1);
  } else if (event.key === '-' || event.key === '_') {
    event.preventDefault();
    studioZoomBy(-1);
  } else if (event.key === '0') {
    event.preventDefault();
    studioResetZoom();
  } else if (event.key.toLowerCase() === 'f') {
    event.preventDefault();
    studioFitView();
  } else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
    event.preventDefault();
    const distance = event.shiftKey ? 140 : 48;
    if (event.key === 'ArrowLeft') viewport.scrollLeft -= distance;
    if (event.key === 'ArrowRight') viewport.scrollLeft += distance;
    if (event.key === 'ArrowUp') viewport.scrollTop -= distance;
    if (event.key === 'ArrowDown') viewport.scrollTop += distance;
  }
}

function studioResizeWorkspace() {
  studioFitWorkspace();
  window.requestAnimationFrame(studioApplyCamera);
}

function studioRender() {
  studioRenderPalette();
  studioRenderCanvas();
  studioRenderInspector();
  studioRenderOutput();
  studioRenderNotice();
  studioRenderControls();
}

function renderStudio() {
  if (!studioMounted) {
    studioMounted = true;
    studioRender();
    studioScheduleCamera();
    return;
  }
  studioRenderPalette();
  studioRenderCanvasSummary();
  studioRenderOutput();
  studioRenderControls();
  studioRenderNotice();
  studioScheduleCamera();
}

function studioInstallEvents() {
  const search = document.getElementById('studio-palette-search');
  search?.addEventListener('input', () => {
    studioState.paletteQuery = search.value;
    studioRenderPalette();
  });
  document.getElementById('studio-import-file')?.addEventListener('change', event => {
    studioImportFile(event.target.files?.[0] || null);
  });
  const viewport = document.getElementById('studio-canvas-viewport');
  viewport?.addEventListener('pointerdown', studioStartPan);
  viewport?.addEventListener('pointermove', studioMovePan);
  viewport?.addEventListener('pointerup', studioFinishPan);
  viewport?.addEventListener('pointercancel', studioFinishPan);
  viewport?.addEventListener('lostpointercapture', studioFinishPan);
  viewport?.addEventListener('wheel', studioWheelCanvas, {passive: false});
  viewport?.addEventListener('keydown', studioCanvasKeydown);
  if (viewport && window.ResizeObserver) {
    studioCameraResizeObserver = new ResizeObserver(() => {
      window.cancelAnimationFrame(studioCameraResizeFrame);
      studioCameraResizeFrame = window.requestAnimationFrame(studioApplyCamera);
    });
    studioCameraResizeObserver.observe(viewport);
  }
  viewport?.addEventListener('click', event => {
    if (!studioSuppressCanvasClick) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    studioSuppressCanvasClick = false;
  }, true);
  viewport?.addEventListener('click', event => {
    if (event.target.closest?.('.studio-node, .studio-edge-hit, button, input, textarea, select, [contenteditable="true"]')) return;
    studioState.selectedNodeId = null;
    studioState.selectedEdgeId = null;
    studioUpdateCanvasSelection();
    studioRenderInspector();
    studioRenderControls();
  });
  document.addEventListener('keydown', event => {
    if (!document.getElementById('view-studio')?.classList.contains('active')) return;
    const editing = event.target?.matches?.('input, textarea, select, [contenteditable="true"]');
    if (event.key === 'Escape' && document.getElementById('studio-output-dialog')?.open) {
      event.preventDefault();
      studioCloseOutput();
      return;
    }
    if (event.key === 'Escape' && studioState.connectionSourceId) {
      event.preventDefault();
      studioCancelConnection();
      return;
    }
    if (editing) return;
    if (event.key === ' ' && !event.repeat && (event.target === viewport || event.target === document.body)) {
      event.preventDefault();
      studioSpacePan = true;
      return;
    }
    const modifier = event.metaKey || event.ctrlKey;
    if (modifier && !event.altKey && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      event.shiftKey ? studioRedo() : studioUndo();
    } else if (modifier && !event.altKey && event.key.toLowerCase() === 'y') {
      event.preventDefault();
      studioRedo();
    } else if ((event.key === 'Delete' || event.key === 'Backspace') && (studioState.selectedNodeId || studioState.selectedEdgeId)) {
      event.preventDefault();
      studioDeleteSelection();
    }
  });
  document.addEventListener('keyup', event => {
    if (event.key === ' ') studioSpacePan = false;
  });
  window.addEventListener('blur', () => { studioSpacePan = false; });
  window.addEventListener('resize', studioResizeWorkspace);
}

studioInstallEvents();
if (window.__PROTOLINK_LIVE__) {
  studioRefreshStatus();
  studioStatusTimer = window.setInterval(() => studioRefreshStatus(), 1600);
}
"""
