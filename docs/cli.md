# CLI

Protolink ships with a command-line interface for project scaffolding, local health checks, registry inspection, run replay, and the local dashboard developer tools.

The CLI is meant to be the shortest path from "I have a Protolink project" to "I can see what is installed, what agents are registered, what happened during a run, and how my agent topology is shaped." It does not replace the Python API. Instead, it sits on top of the same public runtime contracts that applications use directly: `AgentCard`, `RunContext`, `RunEvent`, `RunReport`, `SQLiteRunStore`, and registry discovery.

Use the CLI in three common moments:

- **First setup**: create a starter agent and confirm optional dependencies with `protolink doctor`.
- **Local debugging**: inspect registry entries, list stored runs, and replay a run timeline without writing custom scripts.
- **Developer presentation**: open the dashboard when you want a visual view of runs, agents, and the future Studio preview.

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

## Dashboard

Open the local dashboard:

```bash
protolink dashboard --store runs.db --registry-url http://127.0.0.1:9010 --open
```

The dashboard is a local, dependency-free HTML surface over the same collectors used by the CLI. It is useful when a run has enough events that a table is easier to scan than terminal output, or when you want to show registered agents and stored run reports side by side.

Write a static dashboard snapshot:

```bash
protolink dashboard --store runs.db --output dashboard.html
```

Static output is useful for demos, bug reports, and notebooks because the generated file embeds the current snapshot. It will not live-refresh, but it can be opened without starting a server.

The dashboard still has a Studio tab, but it is deliberately disabled and marked as coming soon. It previews the future direction without exposing a public `protolink studio` command before the blueprint format and execution story are ready.

See [Developer Tools](devtools.md) for the architecture, renderer APIs, and provider-free example.

## Command Reference

```bash
protolink init agent [path] [--template basic|tool] [--force]
protolink doctor [--agent-url URL] [--registry-url URL] [--store PATH] [--json]
protolink registry list --url URL [--name NAME] [--role ROLE] [--tag TAG] [--json]
protolink registry inspect SELECTOR --url URL [--json]
protolink run list [--store PATH] [--limit N] [--json]
protolink run replay RUN_ID [--store PATH] [--json]
protolink dashboard [--store PATH] [--registry-url URL] [--host HOST] [--port PORT] [--open] [--output PATH]
```

| Argument | Description |
| --- | --- |
| `path` | Output file path. Defaults to `agent.py`. |
| `--template` | Starter template to use. Defaults to `basic`. |
| `--force` | Overwrite the output file if it already exists. |
