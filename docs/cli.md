# CLI

Protolink ships with a small command-line interface for project scaffolding and developer workflows.

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

## Overwrite Protection

The CLI will not overwrite an existing file unless `--force` is provided:

```bash
protolink init agent --force
```

## Command Reference

```bash
protolink init agent [path] [--template basic|tool] [--force]
```

| Argument | Description |
| --- | --- |
| `path` | Output file path. Defaults to `agent.py`. |
| `--template` | Starter template to use. Defaults to `basic`. |
| `--force` | Overwrite the output file if it already exists. |
