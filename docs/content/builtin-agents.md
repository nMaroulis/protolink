# Built-in Agents

Built-in agents are small, configurable classes using the standard [Agent API](agent.md). Developers
choose their models, instructions, tools, backends, policies and application interfaces. The presets
reuse Agent's execution loop, invocation, streaming, state, storage and transport behavior.
`EchoAgent` is a deterministic utility for checking communication without a model.

| Agent | Built-in behavior | Import |
| --- | --- | --- |
| [`Assistant`](#assistant) | Clock/calculator plus optional calendar, email and user feedback | `from protolink import Assistant` |
| [`CodeAssistant`](#codeassistant) | Scoped files, optional recoverable edits, shell and Git | `from protolink import CodeAssistant` |
| [`ResearchAgent`](#researchagent) | Web research with bounded reads and source citations | `from protolink import ResearchAgent` |
| [`KnowledgeAgent`](#knowledgeagent) | Retrieval-grounded answers from configured knowledge | `from protolink import KnowledgeAgent` |
| [`DatabaseAgent`](#databaseagent) | Schema inspection, read-only SQL and calculator | `from protolink import DatabaseAgent` |
| [`ExplorerAgent`](#exploreragent) | Scoped file exploration, optional documents and Git reads | `from protolink import ExplorerAgent` |
| [`EchoAgent`](#echoagent) | Returns received content without inference or tool execution | `from protolink import EchoAgent` |

All are exported from `protolink` and `protolink.agents.builtins`. The complete tool catalog, backend setup,
authentication requirements and individual tool APIs are in [Built-in Tools](builtin-tools.md).

## Quick start

```python
from protolink import Assistant, CodeAssistant, EchoAgent

echo = EchoAgent()
print(await echo.invoke("Hello"))  # Hello, verbatim; no LLM needed.

assistant = Assistant(llm="mock", name="personal-assistant")
print(await assistant.invoke("Hello"))

coder = CodeAssistant(cwd=".")  # No model is needed for direct tool calls.
result = await coder.call_tool("calculator", expression="(18 + 6) / 3")
```

Use `invoke()` for general conversation; `ask()` retains the existing knowledge/RAG contract.
Supply a separate model instance to concurrently running agents when the model retains mutable state.
Construction registers tools and validates configuration without contacting accounts or starting a server.

## Assistant

```python
from protolink import Assistant
from protolink.tools import Gmail, GoogleCalendar

assistant = Assistant(
    llm=model,  # Optional for direct call_tool usage.
    calendar=GoogleCalendar(token),  # Omit a service to exclude its tools.
    email=Gmail(token, sender="me@example.com"),
    ask_user=handle_question,  # Optional async user-feedback callback.
    allow_write=True,  # Calendar creation and email drafts.
    allow_send=True,  # Separately opt into email delivery.
    approval_handler=approve,  # Normal Agent approval callback.
    state=["conversation"],
)
```

`model`, `handle_question`, `approve` and `token` are application-supplied dependencies.
Choose Google, Microsoft, IMAP/SMTP, or your own service adapters from the
[backend catalog](builtin-tools.md#calendar-and-email-backends). Clock and calculator
are always included. Reads and user questions are allowed by the preset's default policy; calendar
creation, drafts and delivery require approval. Both write flags default to `False`. Omitting an
approval handler leaves approval-gated calls blocked by the existing runtime; it never auto-approves.
Question answers clarify intent; they do not authorize a write.

Pass `name`, `description` and `url`, or a custom `card=AgentCard(...)`, for a different identity. Other keywords pass directly
to `Agent`, including `policy`, `system_prompt`, `transport`, `knowledge`, `storage` and `run_store`.
A supplied policy replaces the preset policy. New capabilities are denied by the preset's default policy;
explicitly configure them when adding more tools.

## CodeAssistant

```python
from protolink import CodeAssistant

coder = CodeAssistant(
    llm=model,
    cwd="/absolute/workspace",
    env={"PATH": "/usr/bin:/bin"},
    ask_user=handle_question,
    allow_git_write=True,
    approval_handler=approve,
)
print(await coder.invoke("Inspect the changes and run the relevant tests."))
```

The preset includes `read_file`, `list_files`, `search_files`, `run_shell`, `git` and `calculator`.
File tools are scoped to `cwd`, accept absolute paths and reject symlinks below the root; they currently require POSIX.
On other platforms the preset retains shell/Git support without installing file tools.
File/Git reads and questions are allowed; shell commands and Git writes require approval. Git writes also
need `allow_git_write=True` (default `False`). Shell execution can mutate host resources even when
Git writes are disabled. A working directory does not provide filesystem or network isolation.

`env=None` supplies only `PATH=os.defpath`; it does not copy the parent environment. Configure
credentials and author identity explicitly when needed. Tool factories offer timeout, output-limit,
executable and backend settings; replace a preset's tool with a configured factory for those options.
See [shell, Git and user interaction](builtin-tools.md#shell-and-git-tools).

For prepared file edits with previews, preconditions and persistent recovery records, supply a checkpoint store:

```python
from protolink import CodeAssistant, StorageCheckpointStore
from protolink.storage import SQLiteStorage

coder = CodeAssistant(
    llm=model,
    cwd="/absolute/workspace",
    checkpoints=StorageCheckpointStore(SQLiteStorage("edits.sqlite")),
    approval_handler=approve,
)
```

This adds `create_file`, `replace_file`, `edit_file`, `preview_change` and `restore_change`.
Both editing and restoration require approval under the default policy. File recovery records are
separate from `durability`, which checkpoints the execution itself. See
[filesystem changes and recovery](builtin-tools.md#filesystem-access) and [execution](execution-tools.md).

## ResearchAgent

`ResearchAgent` composes web search, URL fetching, clock and calculator. Its supplemental instructions
request primary sources, citations beside claims, verification beyond search snippets and explicit
distinctions between evidence and inference. Searches and reads use the existing bounded tools;
the preset adds no new inference action format or research workflow engine.

```python
from protolink import ResearchAgent

researcher = ResearchAgent(llm=model, search_engine="wikipedia", name="researcher")
answer = await researcher.invoke("Explain structured concurrency and cite the sources.")
```

`search_engine` selects the provider for `web_search`; the model supplies `query`, `max_results` and
`freshness` and cannot switch providers through that tool. The default is `"brave"`, which reads
`BRAVE_SEARCH_API_KEY` at invocation. `"wikipedia"` is keyless, searches English Wikipedia and
supports only `freshness="any"`. `"duckduckgo"` is a keyless, best-effort HTML interface.
`fetch_url` reads bounded text from public HTTP(S) URLs with the existing DNS/redirect checks.
No network request occurs at construction.

Pass `search_tool=...` or `fetch_tool=...` to replace either provider with a configured `BaseTool`.
Its own name and schema are advertised to the model; use `Tool.from_callable(...)` for application
functions. The default policy allows `network.read` and `user.interact` and denies other capabilities.
Custom providers own their credentials, network restrictions and output limits. See
[web search](builtin-tools.md#web-search) for provider behavior and limits.

## KnowledgeAgent

`KnowledgeAgent` connects the existing [Knowledge/RAG subsystem](rag.md) to a focused answer preset.
Its instructions request retrieval before domain answers, source citations and an explicit limitation
when evidence is absent or insufficient. It reuses the existing knowledge tools and citation metadata.

```python
from protolink import KnowledgeAgent

expert = KnowledgeAgent(llm=model, sources=["/absolute/docs"], name="docs-expert")
answer = await expert.invoke("How does checkpoint recovery work?")
```

`sources` creates a dependency-free in-memory index, populated lazily at the first search. Sources may
be local paths or `Document` values supported by the normal knowledge loaders. For persistent indexes,
custom retrieval, embeddings, filters, reranking or context limits, configure `Knowledge` explicitly:

```python
from protolink import KnowledgeAgent, create_knowledge

knowledge = create_knowledge("sqlite", path="knowledge.sqlite", name="handbook", sources=["/absolute/docs"])
expert = KnowledgeAgent(llm=model, knowledge=knowledge)
```

Supply either `sources` or `knowledge`. `knowledge` accepts a `Knowledge`, a retriever, or a sequence
of those objects. The default policy allows reads from the attached sources and indexing for managed
knowledge, so lazy ingestion can proceed. A supplied policy replaces these grants.

`invoke()` uses normal automatic retrieval: the model chooses the registered search tools.
`ask()` retains deterministic retrieval and returns the existing `RAGAnswer`, including hits and citations.
For durable execution use `invoke()` with the default `retrieval="auto"`; eager retrieval modes and
`ask()` remain outside that recovery contract. Citation and abstention instructions guide the model;
applications can use `invoke_typed()` and their own validation when they need a stricter answer contract.

## DatabaseAgent

`DatabaseAgent` exposes schema inspection, bounded read-only queries and calculator. Its instructions
request schema verification, bound parameters, explicit aggregates for totals and disclosure of
filters and truncation. The configured backend owns connections and read-only enforcement.

```python
from protolink import DatabaseAgent
from protolink.tools import SQLiteDatabase

analyst = DatabaseAgent(llm=model, database=SQLiteDatabase("sales.sqlite"))
answer = await analyst.invoke("What is the total revenue by region?")

rows = await analyst.call_tool(
    "query_database", sql="SELECT total FROM sales WHERE region = ?", parameters=["EU"], max_rows=20
)
```

The database must already exist. `SQLiteDatabase` opens it read-only, rejects writes and unsafe
operations and bounds returned data. For PostgreSQL or another service, implement `DatabaseBackend`
and pass it as `database`; a policy grant alone does not enforce read-only SQL on a custom connection.
The default policy allows `database.read` and user questions. See
[database tools](builtin-tools.md#database-queries) for backend contracts, query limits and timeouts.

## ExplorerAgent

`ExplorerAgent` is a read-only specialist for repositories, local documents and other scoped directories.
It installs bounded file reads, listing and search, with instructions to return focused evidence and
cite paths or document locations. No shell or editing tool is installed. It is useful independently
or as an owned subagent whose findings feed a parent task.

```python
from pathlib import Path
from protolink import ExplorerAgent

workspace = Path(".").resolve()
explorer = ExplorerAgent(llm=model, roots=[workspace], name="explorer")
answer = await explorer.invoke(f"Find the relevant tests inside {workspace} and cite their paths.")
```

`roots` is a sequence of existing directories. File paths must be absolute; file/document tools reject
escapes and symlinks below those roots and currently require POSIX. Set `documents=True` for
`read_document` and `search_document`, including located PDF/DOCX/XLSX/CSV/text extraction; optional
format dependencies apply. Set `git_cwd=workspace` to add structured Git reads, with optional `env`.
The Git directory must be inside a configured root. Native Git is a process backend, so file-tool
root checks do not sandbox every resource accessible to Git.

The default policy allows `filesystem.read` and user questions, plus `git.read` and `process.execute`
when Git is configured. Tool factories expose detailed byte, scan, extraction and process limits;
replace a registered tool when tighter application-specific limits are needed.

## Questions, durability and subagents

All model-driven presets accept `ask_user=handle_question` for live application feedback. With
`durability=...`, they automatically install `ask_user_tool()` even without a callback, so a question
can pause until the application supplies an answer after a restart:

```python
from protolink import Assistant, RunInterrupted

assistant = Assistant(durability="runs.sqlite")
try:
    await assistant.call_tool("ask_user", question="Which timezone should I use?")
except RunInterrupted as pause:
    # Save these identifiers in your application UI or job record.
    run_id = pause.run_id
    request_id = pause.interruption.request_id

# A later application process reconstructs the same configuration.
assistant = Assistant(durability="runs.sqlite")
result = await assistant.resume(run_id, request_id=request_id, answer="Europe/Zurich")
```

Questions clarify intent; approval remains a separate policy decision. Configured presets otherwise
use the same [execution and recovery](execution-tools.md#durable-execution) contract as `Agent`.

```python
from protolink import Agent, ExplorerAgent

explorer = ExplorerAgent(llm=explorer_model, roots=[workspace], name="explorer")
coordinator = Agent(llm=coordinator_model, name="coordinator", subagents=[explorer])
answer = await coordinator.invoke(f"Ask explorer to identify the tests in {workspace}, then summarize.")
```

The existing `agent_call` action routes to the configured child; no special preset/subagent prompt
format is required. Parent policies and shared budgets still apply. When a preset itself delegates,
its default policy denies undeclared capabilities: explicitly grant the required `agent.call` and
child capabilities in your own policy. Give each concurrently running agent a separate stateful model
instance. If a child uses only the parent's durable store and needs questions, explicitly register
`ask_user_tool()` on that child. See [Subagents](subagents.md) for ownership and lifecycle controls.

## EchoAgent

`EchoAgent` returns received content deterministically. Use it to verify transport wiring, task
round trips, streaming and delegation without a model or credentials.

```python
from protolink import EchoAgent, Task

echo = EchoAgent(name="echo")
assert await echo.invoke("  hello\n") == "  hello\n"
task = await echo.run_task(Task.create("hello"))
print(task.messages[-1].parts[0].content)  # hello
```

`invoke(text)` echoes the inference prompt verbatim, including empty strings and whitespace.
For `run_task()`, it processes only the latest message or artifact and adds a new agent message:
inference parts become `infer_output`; other parts are copied unchanged. Tool-call parts are echoed
as data in the response message and never executed. Streaming emits working/completed status events
with the final echoed task attached. Terminal tasks are returned without another echo. This utility
does not perform conversation reasoning; even if an LLM or tools are supplied, it does not invoke them.

## Customization and restoration

The presets are optional starting points. Register additional tools with
`add_tool()`, replace a tool with a configured factory, or compose the same capabilities directly on
an ordinary `Agent`. Their default policies deny capabilities beyond the preset, so explicitly update
the policy when adding capabilities. A supplied policy replaces the preset policy.

All accept `name`, `description` and `url`, or `card`, to change identity and standard Agent options such as
`system_prompt`, `approval_handler`, `transport`, `state`, `storage` and `run_store`. Model-driven presets
accept model objects or ordinary LLM aliases. A supplied `tools=[...]` entry takes precedence over a
preset tool with the same name. Configure callbacks in your own
application. User feedback clarifies intent; approval remains a separate policy decision.

Configured backends, credentials and callbacks are not serialized. Restore configurations through
`Agent.from_dict/from_yaml`, then re-register the configured tools and policies as needed. The
[Tool catalog](builtin-tools.md#registration-and-policy) explains the parameterless/configured distinction.
Configured search providers must also be reattached. For deterministic echo behavior, reconstruct
`EchoAgent` itself; restoring its dictionary through `Agent.from_dict()` creates an ordinary Agent.

## Offline example

```bash
python examples/builtin_assistants.py
python examples/builtin_agents.py
```

[`builtin_assistants.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_assistants.py)
exercises Assistant and CodeAssistant, including model question/answer continuation, shell/Git,
calendar/email, clock and calculator. It uses a temporary repository, a mock model and in-memory
services. Its automatic approval callback is specific to the demo. See the
[tool examples](builtin-tools.md#examples) for the general-purpose tools and concrete service backends.

[`builtin_agents.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_agents.py)
demonstrates ResearchAgent, KnowledgeAgent, DatabaseAgent, ExplorerAgent and EchoAgent with fixture
web providers, local knowledge, a temporary SQLite database and scoped files. Scripted models build
answers from actual tool results; the example needs no network access or API keys.
