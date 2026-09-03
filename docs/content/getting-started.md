import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Getting Started

This guide shows how to install and start using Protolink.

The following article on 📝 [level-up coding on medium](https://levelup.gitconnected.com/your-first-autonomous-agent-mesh-easier-than-you-think-ce697b3dd87a) also gives a hands-on guide and overview of Protolink.

## Installation

Protolink is published on PyPI and can be installed with either `uv` (recommended) or `pip`.

### Basic Installation

This installs the base package without optional extras:

```bash
# Using uv (recommended)
uv add protolink

# Using pip
pip install protolink
```

### Optional Dependencies

Protolink exposes several extras to enable additional functionality:


<Tabs groupId="doc-tabs-1">
<TabItem value="uv" label="uv" default>

```bash
# Install with all optional dependencies
uv add "protolink[all]"

# HTTP support (for web-based agents)
uv add "protolink[http]"

# All supported LLM libraries
uv add "protolink[llms]"

# Optional local PDF ingestion for RAG
uv add "protolink[rag-pdf]"

# Development (all extras + testing tools)
uv add "protolink[dev]"
```

</TabItem>
<TabItem value="pip" label="pip">

```bash
# Install with all optional dependencies
pip install "protolink[all]"

# HTTP support (for web-based agents)
pip install "protolink[http]"

# All supported LLM libraries
pip install "protolink[llms]"

# Optional local PDF ingestion for RAG
pip install "protolink[rag-pdf]"

# Development (all extras + testing tools)
pip install "protolink[dev]"
```

</TabItem>
<TabItem value="source-checkout" label="Source checkout">

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink

# Editable install for local development
uv pip install -e ".[dev]"
```

</TabItem>
</Tabs>
:::info[Optional extras]

You usually only need the extras that match your use case. `protolink[llms]` installs every supported LLM SDK, so production projects may prefer installing only the provider libraries they actually use. Dependency-free in-memory and SQLite [RAG](rag.md) are part of the base package; `protolink[rag-pdf]` is needed only when the built-in loader reads local PDF files.

:::
For development from source:

```bash
git clone https://github.com/nmaroulis/protolink.git
cd protolink
uv pip install -e ".[dev]"
```

:::info[A2A from the first agent]

Even the smallest ProtoLink agent uses the A2A model: `AgentCard` declares identity and capabilities, while `Task`, `Message`, `Part`, and `Artifact` carry work and results. `transport="http"` serves ProtoLink's native API by default. Add `a2a=True` when the agent should also expose and consume the [A2A 1.0](https://a2a-protocol.org/latest/specification/) JSON-RPC boundary. This is additive: native endpoints and native peer calls remain available. See [A2A Core and 1.0 Compatibility](a2a.md) for the exact scope.

:::

## First Agent

Save this as `agent.py` and run `python agent.py`. It uses only the base package:

```python
from protolink import Agent, AgentCard

agent = Agent(
    card=AgentCard(
        name="calculator",
        description="Adds numbers",
        url="runtime://calculator",
    ),
    transport="runtime",
    verbosity=0,
)

@agent.tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

print(agent.sync.call_tool("add", a=2, b=3))  # 5
```

No model, API key, server process, or network connection is needed. The decorator infers the tool name from `add`, the description from its cleaned docstring, and the schemas from its type hints. Both synchronous and asynchronous functions work. `@agent.tool()` and explicit metadata such as `@agent.tool(name="sum", description="Add two numbers")` are also supported.

For an existing function, call `agent.add_tool(add)`. The same call works on another agent, and synchronous functions, asynchronous functions, bound methods, and callable objects all use the same metadata inference. Use `Tool.from_callable(add, ...)` when you need custom schemas, tags, or permission metadata; see [Native Tools](tool.md#native-tools).

`call_tool()` validates arguments, applies the Agent's policy and approval rules, and returns the raw result. Calling `add(2, 3)` remains an ordinary Python call and bypasses those Agent controls. Registration never executes the function.

### Keep the complete task

Use `run_task()` when you need lifecycle state, artifacts, run metadata, cancellation by task ID, or configured run storage:

```python
from protolink import Task, TaskExecutionError

task = Task.create_tool_call(tool_name="add", args={"a": 2, "b": 3})
result = agent.sync.run_task(task)

try:
    result.raise_for_status()
except TaskExecutionError as exc:
    print(exc.task.state.value)
else:
    print(result.state.value)  # completed
    print(result.get_last_part_content().result)  # 5
```

`run_task()` returns the complete task, including a returned failed or canceled state. `raise_for_status()` returns the same task or raises `TaskExecutionError` for those two states; it does not wait for completion. Exceptions raised directly during execution still propagate with their original types. Direct `call_tool()` errors also propagate unchanged.

### Add inference

`invoke()` lets an LLM answer or choose tools. Try the API with the provider-free mock first:

```python
from protolink import create_llm

agent.llm = create_llm("mock", default_response="Hello from ProtoLink")
print(agent.sync.invoke("Say hello"))  # Hello from ProtoLink
```

Replace the mock with a configured [LLM backend](llm.md) for real inference. An LLM may require an installed SDK, a running local model server, or provider credentials; direct tool calls require none of them.

`invoke()` returns the final part's content and raises `TaskExecutionError` when its task is failed or canceled. It preserves structured results such as `ToolOutput` in explicit tool-call mode. Prefer `call_tool()` when you already know the tool and want its raw return value, or `run_task()` when your application needs the full task. `ask()` adds deterministic retrieval before inference and returns a `RAGAnswer`; see [RAG](rag.md).

Conversation memory is opt-in with `state=["conversation"]`. Supply an explicit `session_id` for each conversation in `invoke()` and `ask()`, especially when serving multiple users. Their convenience defaults reuse a shared session per method; they do not create an isolated conversation for every call.

### Async applications and notebooks

The `.sync` facade is for blocking scripts. In an async function or a notebook with an active event loop, await the same methods directly:

```python
result = await agent.call_tool("add", a=2, b=3)
response = await agent.invoke("Say hello", session_id="conversation-123")
```

Calling `.sync` from an active event loop raises an actionable `RuntimeError` before a coroutine is created.

### Serve the agent over HTTP

Install the HTTP extra with `uv add "protolink[http]"`, then create a service:

```python
from protolink import Agent, AgentCard

agent = Agent(
    card=AgentCard(
        name="calculator",
        description="Adds numbers",
        url="http://127.0.0.1:8020",
    ),
    transport="http",
)

@agent.tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

agent.start()
```

`start()` runs the service until stopped. The same tool is now available to peers through the native task API. Add `a2a=True` for the supported A2A 1.0 boundary, or add an LLM for inference and browser chat. Registry discovery, [built-in tools](tool.md#built-in-tools), and [MCP tools](tool.md) can be attached independently as your application grows.


### Using the CLI

Create a runnable one-file starter agent:

```bash
protolink init agent
uv run python agent.py
```

The default starter uses the top-level API:

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, Task, create_llm
```

It runs locally without an API key by executing a tool call directly. If `OPENAI_API_KEY` is set, it also enables LLM inference. Use `--template tool` for a tool-only starter or `--force` to overwrite an existing file.
