# CLI

Protolink ships with a command-line interface for project scaffolding, local health checks, registry inspection, run replay and regression diffing, and local dashboard access to runtime and telemetry data.

The CLI is meant to be the shortest path from "I have a Protolink project" to "I can see what is installed, what agents are registered, what happened during a run, and how my agent topology is shaped." It does not replace the Python API. Instead, it sits on top of the same public runtime contracts that applications use directly: `AgentCard`, `RunContext`, `RunEvent`, `RunReport`, `SQLiteRunStore`, and registry discovery.

Use the CLI in three common moments:

- **First setup**: create a starter agent and confirm optional dependencies with `protolink doctor`.
- **Local debugging and regression checks**: inspect registry entries, list stored runs, replay a timeline, compare stored reports, and explore local trace JSONL without writing custom scripts.
- **Developer presentation**: open the dashboard when you want a visual view of runs, agents, telemetry, or the active Studio topology builder.

Most inspection commands support both human-readable terminal output and JSON. Use text while working interactively; use `--json` when integrating with CI, shell scripts, notebooks, or another application.

## Installation

The CLI is installed with the package:

```bash
uv add protolink
```

For development from source:

```bash
uv pip install -e ".[dev]"
```

Verify the entry point:

```bash
protolink --help
```

The top-level help shows the command groups:

```text
init       Create starter files.
doctor     Check local Protolink readiness.
registry   Inspect a running registry.
run        Inspect stored runs.
dashboard  Open the local Protolink dashboard.
```

## Create a Starter Agent

Create a one-file starter agent:

```bash
protolink init agent
```

This writes `agent.py` in the current directory. The generated file uses the top-level API:

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, Task, create_llm
```

The default starter runs immediately without an API key by executing a local tool call. If `OPENAI_API_KEY` is set, it also enables LLM inference through `create_llm("openai", ...)`.

The generated file is intentionally small but not toy-shaped. It demonstrates the important runtime idea in Protolink: the agent is the object you plug modules into. A starter can have an LLM, tools, telemetry, state, policy, and transport later, but it starts from one readable Python file so users can see the shape before they scale it.

Run it:

```bash
uv run python agent.py
```

## Output Path

Pass a path to choose where the starter is created:

```bash
protolink init agent examples/my_agent.py
```

Parent directories are created automatically.

## Templates

Use `--template` to choose a starter style:

```bash
protolink init agent --template basic
protolink init agent tool_agent.py --template tool
```

Available templates:

| Template | Purpose |
| --- | --- |
| `basic` | Agent with a local tool, optional OpenAI LLM, conversation state, and local tracing. |
| `tool` | Tool-only local agent for the smallest runnable example. |

Choose `basic` when you want the first file to show the usual agent shape: local tool registration, optional model usage, and local trace telemetry. Choose `tool` when you want a dependency-light baseline that proves the task/tool path works without involving an LLM.

## Overwrite Protection

The CLI will not overwrite an existing file unless `--force` is provided:

```bash
protolink init agent --force
```

## Doctor

Check local readiness:

```bash
protolink doctor
```

`doctor` answers "is this environment ready for the kind of Protolink work I am about to do?" It always reports the installed Protolink version and optional dependency groups. Optional extras are warnings, not failures, because a tool-only or runtime-transport project can be perfectly valid without every provider, metrics, or telemetry dependency installed.

Use JSON for automation:

```bash
protolink doctor --json
```

JSON output keeps the same status model as the text output:

- `ok`: the check is ready.
- `warn`: the environment is usable, but a capability is missing or not initialized.
- `error`: an explicitly requested probe failed.

Probe live surfaces:

```bash
protolink doctor --agent-url http://127.0.0.1:8010 --registry-url http://127.0.0.1:9010 --store runs.db
```

When `--agent-url` is provided, the CLI probes the agent card endpoint at `/.well-known/agent.json`. When `--registry-url` is provided, it probes `/agents/`. When `--store` is provided, it checks whether the SQLite file exists and contains Protolink-like task or run-report tables.

This makes `doctor` useful both as a local sanity check and as a support artifact. If a user says "my agent cannot be discovered" or "run replay is empty," asking them to paste `protolink doctor --registry-url ... --store ... --json` gives you the high-level environment shape immediately.

## Registry

List agents from a running HTTP registry:

```bash
protolink registry list --url http://127.0.0.1:9010
```

The registry command talks to the registry over its public HTTP API. It does not import your registry process or read private in-memory state. That keeps the command honest: if `registry list` can see an agent, another HTTP client should be able to discover it too.

Filter by name, role, or tag:

```bash
protolink registry list --url http://127.0.0.1:9010 --role orchestrator --tag research
```

Filters are sent as discovery query parameters and map to the registry's `filter_by` model. Repeating `--tag` asks for agents matching those tags. The text output is intentionally compact: name, transport, URL, and enabled capabilities. Use `--json` when you need the full `AgentCard` payload, including skills, metadata, auth schemes, and any custom fields.

Inspect a single agent by name or URL:

```bash
protolink registry inspect planner --url http://127.0.0.1:9010
```

`inspect` is a convenience wrapper around registry listing. It fetches the current registry cards and selects the card whose `name` or `url` matches the selector. This is helpful when a registry has many agents and you want to check one advertised capability before wiring delegation or a flow step to it.

## Runs

List persisted task snapshots and run reports:

```bash
protolink run list --store runs.db
```

Run commands read the durable `SQLiteRunStore`. They are offline by design: the agent does not need to be running, and no model or tool is executed. If your application persists task snapshots or run reports, you can inspect them later from a terminal, CI artifact, or copied database file.

Replay a stored run report or task snapshot:

```bash
protolink run replay run_123 --store runs.db
```

`run replay` prefers a full `RunReport`, then falls back to a task snapshot with the same task ID or run ID.

The difference matters:

- A **task snapshot** tells you the final serialized task state: submitted, working, completed, failed, canceled, messages, artifacts, and metadata.
- A **run report** tells you the timeline: task status events, context preparation, LLM calls, budget warnings, policy decisions, approvals, tool actions, delegated-agent calls, artifacts, and final task state when recorded.

Use `run list` first when you do not remember the run ID. Use `run replay` when you want to understand why a run behaved a certain way. Use `--json` if you want to feed the replay into another renderer or a golden-run assertion workflow.

Compare two run reports from the same store:

```bash
protolink run diff baseline_run candidate_run --store runs.db
```

`run diff` loads reports only; unlike `run replay`, it does not fall back to task snapshots. It canonicalizes known ProtoLink runtime-envelope identifiers, timestamps, sequence counters, and runtime-derived timing fields, then compares the remaining report content. Application-owned tool payloads and report metadata remain exact. This lets CI detect changes in event sequences, actions, approvals, artifacts, metrics, and final task output.

The command compares facts that have already been recorded; it does not run either agent. Execute the candidate separately with the same input and controlled or captured model, tool, and external-service dependencies before comparing it with the baseline. A comparison against live dependencies can show what changed, but it cannot make those dependencies deterministic. Final reports are the usual regression input, although the API and CLI do not enforce a task lifecycle state.

The exit status is designed for automation:

| Exit | Meaning |
| --- | --- |
| `0` | The normalized reports match. |
| `1` | The reports contain behavioral differences. |
| `2` | One or both report IDs are missing from the store. |

Use `--json` for a structured result containing the baseline and candidate selectors, `status` (`match`, `changed`, or `missing`), missing IDs, changed sections, and path-level differences. The default text view prints `Normalized run report diff: BASELINE -> CANDIDATE`, followed by `Result: MATCH` or `Result: CHANGED`. Both text and JSON output apply ProtoLink's default redaction policy to baseline and candidate values in a difference; the JSON Pointer path remains visible.

## Dashboard

Open the local dashboard:

```bash
protolink dashboard \
  --store runs.db \
  --traces traces.jsonl \
  --registry-url http://127.0.0.1:9010 \
  --open
```

`--telemetry traces.jsonl` is an alias for `--traces traces.jsonl`.

The dashboard is a local, dependency-free HTML surface over the same collectors used by the CLI. It is useful when a run has enough events that a table is easier to scan than terminal output, or when you want to show registered agents, health probes, agent chat, stored run reports, local telemetry, and a visual Studio topology side by side.

`--store` is optional for the dashboard. When it is omitted, an existing `./runs.db` is discovered automatically; no database is created when that file is absent. In a served dashboard, the Registry and Runs pages can connect or change their sources for the lifetime of that dashboard process. Registry URLs are fetched by the local dashboard server; run stores must already exist and are opened read-only. Source changes are accepted only from a loopback client and are not written to project configuration. Static snapshots show the source controls but cannot connect server-side sources.

Write a static dashboard snapshot:

```bash
protolink dashboard --store runs.db --output dashboard.html
```

Static output is useful for demos, bug reports, and notebooks because the generated file embeds the current snapshot. It will not live-refresh, but it can be opened without starting a server. Its Telemetry view can still inspect a JSONL file chosen with **Open JSONL**, and Studio can edit, persist locally, import, and export a JSON blueprint in the browser. Python generation and Studio execution require the served dashboard.

When the dashboard is served, it can call the local JSON endpoints behind the page:

- `/api/snapshot` refreshes registry and run-store data.
- `/api/sources/registry` connects or changes the session-only registry URL.
- `/api/sources/runs` connects or changes an existing SQLite run store in read-only mode.
- `/api/runs/{run_id}` loads the same replay projection used by `protolink run replay`.
- `/api/traces?limit=...&cursor=...` returns a bounded recent-first page of telemetry summaries.
- `/api/traces/{record_id}` lazily loads one selected telemetry record.
- `/api/agents/ping` probes an HTTP agent's `/status` endpoint and returns latency/status data.
- `/api/agents/chat` proxies a message to an HTTP LLM agent's `POST /chat` endpoint.
- `GET /studio` opens the same dashboard with Studio selected.
- `GET /api/studio/catalog` lists supported node kinds, transports, providers, tools, flows, and module implementations.
- `POST /api/studio/generate` validates a blueprint and returns generated Python plus its filename, normalized blueprint, warnings, and digest.
- `GET /api/studio/status` returns the current Studio subprocess state and recent output.
- `POST /api/studio/run` starts one generated project, and `POST /api/studio/stop` stops it by run ID.

Ping and chat require HTTP agent URLs from the registry. Runtime-only demo agents still appear in the registry, but they are marked as runtime agents because there is no network endpoint for the browser dashboard to ping.

The Telemetry view uses the path supplied by `--traces` for server-backed inspection. It pages completed task records in recent-first order, keeps a rolling window of at most 500 summaries, and loads the selected record's spans, events, inputs, outputs, metadata, and raw JSON only on demand. This avoids placing a long-lived system's complete trace file in `/api/snapshot` or rendering every historical record at once while still allowing continued navigation into older history. The browser's **Open JSONL** control provides the same bounded, lazy-detail workflow for a file selected locally instead of a CLI-configured path.

Each JSONL line is a completed task record. Related or delegated tasks can share a `trace_id`, so the dashboard treats that field as a correlation key and groups the distinct task records beneath it; it does not assume that a trace ID uniquely identifies one line. Blank or malformed records are skipped and reported. An incomplete final line from an active writer is tolerated as a partial write and can appear after a later refresh once it is complete. A 16 MB per-record detail limit and bounded reverse scans protect the dashboard from pathological payloads; opaque continuation cursors let the server move past a physical line that is itself larger than one scan page.

Trace payloads remain local, but local does not automatically mean non-sensitive. The browser file picker reads the selected file in the page rather than uploading it to a hosted service. The dashboard server binds to `127.0.0.1` by default, rejects unexpected HTTP `Host` names, and accepts action POSTs only as same-origin JSON requests. Studio **Run** and **Stop** are limited to loopback clients. If you set `--host` to `0.0.0.0` or another non-loopback address, other network clients may be able to reach trace details, registry data, generated Studio code, agent probes, and the chat proxy; use an IP address with wildcard binds, and only broaden the binding on a trusted network with appropriate access controls.

The dashboard landing view puts five cards at the top: Agents, Tasks, Reports, Telemetry, and Store. Agents opens the registry view; Telemetry opens the bounded trace explorer; and Tasks, Reports, and Store route to Runs. Runs uses a compact, searchable recent-record browser beside a detailed correlation hero and event timeline. Only compact task/report indexes are embedded in the snapshot; full replay data is loaded after selection. Under the cards, the dashboard keeps Registry as the primary table so agent discovery and health stay immediately visible. The sidebar places Registry directly after Dashboard and shows the running Protolink version at the bottom.

The dashboard chat view also includes a Debug toggle for local agent probing. It tracks the last chat latency, average latency for the current dashboard session, sent-message count, current session ID, and the last proxy or agent error. This mirrors the standalone chat renderer's debugging affordance while keeping the dashboard centered on registry-driven agent discovery. Enter sends the active chat prompt; Shift+Enter preserves a newline. Use Reset when you want to clear the current local conversation and start a fresh dashboard session.

The selected-agent panel shows the agent card as an operational profile: health, uptime when reported by `/status`, role, version, protocol, transport, endpoint, input/output formats, security schemes, capability flags, tags, skills, and advertised skill schemas.

The Studio tab is an active visual builder for Agent, LLM, Tool, Registry, Flow, and Module nodes. Compatible connections carry a relation and order, while the inspector exposes supported transports, providers, schemas, flows, and operational modules. In served mode, **Generate Python** opens readable public-API code that can be copied or downloaded; **Run** and **Stop** manage one local generated subprocess with live status and bounded logs. Closing the dashboard stops that child process and removes its temporary script.

Studio blueprints are declarative JSON and do not evaluate arbitrary Python. Built-in tools generate working integrations, while custom tools generate safe placeholder handlers for later editing. Put environment-variable names, never raw credentials, in secret settings. Studio can be opened with an optional blueprint JSON file via `protolink studio [blueprint.json]` or through the dashboard at `/studio`.

See [Protolink Studio](studio.md) for the complete visual-builder guide, and [Developer Tools](devtools.md) for the surrounding dashboard architecture, renderer APIs, and provider-free example.

## Command Reference

```bash
protolink --version
protolink init agent [path] [--template basic|tool] [--force]
protolink doctor [--agent-url URL] [--registry-url URL] [--store PATH] [--json]
protolink registry list --url URL [--name NAME] [--role ROLE] [--tag TAG] [--json]
protolink registry inspect SELECTOR --url URL [--json]
protolink run list [--store PATH] [--limit N] [--json]
protolink run replay RUN_ID [--store PATH] [--json]
protolink run diff BASELINE CANDIDATE [--store PATH] [--json]
protolink dashboard [--store PATH] [--traces PATH] [--registry-url URL] [--host HOST] [--port PORT] [--open] [--output PATH]
protolink studio [BLUEPRINT_JSON] [--ip HOST] [--port PORT]
```

| Argument | Description |
| --- | --- |
| `path` | Output file path. Defaults to `agent.py`. |
| `--template` | Starter template to use. Defaults to `basic`. |
| `--force` | Overwrite the output file if it already exists. |
| `--traces PATH`, `--telemetry PATH` | Local telemetry JSONL source for the dashboard. The two option names are aliases. |
| `--store PATH` | Optional SQLite source for the dashboard. When omitted, an existing `./runs.db` is used or a store can be connected from the served Runs page. |
| `--host` | Dashboard bind host. Defaults to loopback (`127.0.0.1`); a non-loopback value can expose local debug data to the network. |
