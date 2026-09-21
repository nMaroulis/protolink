import ApiReference, { ApiField, ApiFields, ApiSection } from '@site/src/components/ApiReference';

# Built-in Tools

Built-in tools are optional capabilities that developers can compose into any `Agent`. This page
is the complete catalog, including generated calls, configuration, backends, limits, and examples.
Import factories from `protolink.tools` or `protolink.tools.builtins`. For the tool interfaces,
custom Python tools, and MCP adapters, see the [Tool API](tool.md). For ready-made compositions,
see [Built-in Agents](builtin-agents.md).

## Catalog

| Factory | Generated tools | Capabilities | Requirements |
| --- | --- | --- | --- |
| [`web_search()`](#web-search) | `web_search` | `network.read` | Brave token for the default engine; Wikipedia and DuckDuckGo are keyless |
| [`fetch_url()`](#url-fetch) | `fetch_url` | `network.read` | Standard library |
| [`calculator()`](#calculator-and-current-datetime) | `calculator` | None | Standard library |
| [`current_datetime()`](#calculator-and-current-datetime) | `current_datetime` | None | System timezone data for non-UTC zones |
| [`process_tool()`](#command-execution) | `execute_command` | `process.execute` | Host executable or application execution backend |
| [`shell_tool()`](#shell-and-git-tools) | `run_shell` | `process.execute`, `shell.execute` | Configured shell and working directory |
| [`git_tool()`](#shell-and-git-tools) | `git` | `process.execute`, `git.read` or `git.write` | Git executable and working directory |
| [`ask_user_tool()`](#user-questions-and-continuation) | `ask_user` | `user.interact` | Application async callback |
| [`filesystem_tools()`](#filesystem-access) | `read_file`, `list_files`, `search_files`; optional `create_file`, `replace_file`, `edit_file`, `preview_change`, `restore_change` | `filesystem.read`, `filesystem.write`, `filesystem.restore` | Explicit POSIX roots; checkpoints for writes |
| [`storage_tools()`](#json-storage) | `get_value`, `list_keys`; optional `set_value`, `delete_value` | `storage.read`, `storage.write` | Application `Storage` namespace |
| [`http_tool()`](#http-apis) | `http_request` or a configured name | `network.read` or `network.write` | `integrations` extra and fixed API root |
| [`document_tools()`](#document-extraction) | `read_document`, `search_document` | `filesystem.read` | Explicit POSIX roots; `documents` extra for PDF/DOCX/XLSX |
| [`database_tools()`](#database-queries) | `database_schema`, `query_database` | `database.read` | `SQLiteDatabase` or an application backend |
| [`calendar_tools()`](#calendar-integration) | `list_calendar_events`; optional `create_calendar_event` | `calendar.read`, `calendar.write` | Calendar backend; `integrations` extra for Google/Microsoft |
| [`email_tools()`](#email-integration) | `list_email_messages`, `read_email`; optional `create_email_draft`, `send_email` | `email.read`, `email.write`, `email.send` | Email backend; `integrations` extra for Gmail/Outlook, standard library for IMAP/SMTP |

## Registration and policy

```python
from protolink import Agent, AgentCard, CapabilityPolicy
from protolink.storage import InMemoryStorage
from protolink.tools import calculator, current_datetime, filesystem_tools, storage_tools

agent = Agent(
    AgentCard(name="app", description="Application capabilities", url="runtime://app"),
    policy=CapabilityPolicy({"filesystem.read": "allow", "storage.read": "allow"}, default_effect="deny"),
)
for tool in (
    calculator(),
    current_datetime(),
    *filesystem_tools(roots=["/absolute/workspace"]),
    *storage_tools(InMemoryStorage(namespace="application-values")),
):
    agent.add_tool(tool)

result = await agent.call_tool("read_file", path="/absolute/workspace/README.md")
```

Register only the capabilities your application needs. Factories return fresh tools and do not
start processes or contact accounts; configured factories can validate local resources during setup.
No model is required for `call_tool`. Add an LLM to use the tools during inference. Calls through an
Agent share its validation, policy, approvals, budgets, cancellation, events, and skill advertising.

The ordinary `Agent` policy is allow-by-default. Configure it explicitly, including approval for
writes where needed. The [execution guide](execution-tools.md) covers approval handlers, run handles,
and recovery inventory. Tool arguments, previews, and results can appear in model history and reports;
apply application redaction where appropriate and treat external content as untrusted data.

`web_search`, `fetch_url`, `calculator`, and `current_datetime` return ordinary `Tool` objects.
Calling those objects directly bypasses Agent policy and runtime controls. All other factories return
`PreparedTool` objects, which reject direct calls and must execute through the Agent authorization path.

The four parameterless factories serialize by stable built-in identity. Configured factories, backend
instances, credentials, and callbacks must be reattached after `Agent.from_dict/from_yaml`. Declarative
first-party policies can serialize; custom policy implementations and approval callbacks are supplied
as overrides. See the [Agent serialization API](agent.md#agent-serialization-methods).

## Web search

`web_search()` has one normalized result contract across three explicit engines:

- `engine="brave"` is the default. It uses the [Brave Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get) and reads `BRAVE_SEARCH_API_KEY` from the environment only when invoked. The key is not captured by the Tool, stored in Agent configuration, or required merely to import or register the factory.
- `engine="duckduckgo"` needs no API key or additional dependency. It reads DuckDuckGo's published [non-JavaScript HTML search](https://duckduckgo.com/duckduckgo-help-pages/features/non-javascript) as a best-effort interface.
- `engine="wikipedia"` needs no API key or additional dependency. It uses English Wikipedia's documented [REST page-search API](https://www.mediawiki.org/wiki/API:REST_API/Reference#Search_pages), which is the reliable keyless choice for encyclopedia and factual discovery. It supports `freshness="any"` only.

Engine selection is per call and there is no silent fallback. A missing Brave key therefore remains a clear configuration error instead of unexpectedly sending the query to another provider.

```bash
export BRAVE_SEARCH_API_KEY="your-key"
```

```python
result = await agent.call_tool(
    "web_search",
    query="Python 3.14 release notes",
    max_results=5,
)

keyless_result = await agent.call_tool(
    "web_search",
    query="What is the capital of Greece?",
    engine="wikipedia",
)

best_effort_result = await agent.call_tool(
    "web_search",
    query="Python structured concurrency",
    engine="duckduckgo",
    freshness="month",
)
```

For a complete Agent-path CLI, see [`examples/builtin_web_search.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_web_search.py). It registers the built-in with an explicit `network.read` policy, supports all three engines, and prints the normalized JSON result:

```bash
# Keyless search through Wikipedia's documented API (example default)
python examples/builtin_web_search.py "What is the capital of Greece?"

# Documented Brave API
export BRAVE_SEARCH_API_KEY="your-key"
python examples/builtin_web_search.py "Python structured concurrency" --engine brave

# Keyless, best-effort DuckDuckGo HTML search
python examples/builtin_web_search.py "Python structured concurrency" --engine duckduckgo
```

Running the example without a query only prints its CLI help, so it is safe to inspect without credentials or a network request.

<ApiReference
  kind="factory"
  path="protolink.tools.web_search"
  signature={`web_search() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/web.py#L766"
>

Create a fresh `Tool` named `web_search`. The factory does not make a request and does not read the Brave credential; provider selection and credential lookup happen only when the returned tool is invoked.

<ApiSection title="Returns">
  <ApiFields ariaLabel="web_search factory return value">
    <ApiField name="tool" type="Tool">
      A native tool tagged <code>builtin</code>, <code>web</code>, <code>search</code>, and <code>read-only</code>, with the <code>network.read</code> capability and a bounded provider-neutral output schema.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="web_search generated tool arguments">
    <ApiField name="query" type="str" required>
      Search text after surrounding whitespace is removed. It must contain 1–400 characters and no more than 50 whitespace-separated words.
    </ApiField>
    <ApiField name="max_results" type="int" defaultValue="5">
      Maximum normalized results returned to the model. Accepted range: 1–10.
    </ApiField>
    <ApiField name="freshness" type={'"any" | "day" | "week" | "month" | "year"'} defaultValue={'"any"'}>
      Optional result-age filter. Wikipedia accepts only <code>"any"</code>; requesting another value with that engine raises <code>ValueError</code>.
    </ApiField>
    <ApiField name="engine" type={'"brave" | "duckduckgo" | "wikipedia"'} defaultValue={'"brave"'}>
      Explicit provider. Brave requires <code>BRAVE_SEARCH_API_KEY</code>; DuckDuckGo and Wikipedia are keyless and never selected as a silent fallback.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns from invocation">
  <ApiFields ariaLabel="web_search generated tool result">
    <ApiField name="result" type="dict[str, Any]">
      Contains the normalized query, selected provider, ranked result objects, <code>more_results_available</code>, and <code>untrusted_content=True</code>. Each result includes title, URL, snippet, and an explicit sponsored marker.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="web_search errors">
    <ApiField name="ValueError">
      Invalid query length, word count, result limit, freshness, provider selection, or missing Brave credential.
    </ApiField>
    <ApiField name="RuntimeError">
      Provider response, content, challenge, HTTP, decoding, or bounded-transfer failures.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

The tool normalizes all three engines into provider-neutral JSON-compatible data and bounds the result count and text placed into model context. Every result includes `sponsored`; Brave and Wikipedia results use `False`, while recognized DuckDuckGo advertisements stay in provider order with `sponsored=True`. Every engine uses a fixed HTTPS endpoint with DNS validation, a 2,000,000-byte response limit, a 10-second transport deadline, and no redirects. Wikipedia excerpts are converted from bounded provider markup to plain text. DuckDuckGo organic redirect links are decoded locally and validated; sponsored click URLs remain intact. Results also include the selected `provider`, `more_results_available`, and the explicit marker `untrusted_content=True`.

DuckDuckGo's HTML page is a human-facing interface rather than a versioned developer API. It can change markup, rate-limit automated requests, or return a human-verification challenge. ProtoLink does not spoof a browser, suppress or discard recognized advertising, retry a challenge, or attempt to bypass one; it raises a clear error that points to Wikipedia as the keyless alternative. Applications distributing a DuckDuckGo-backed integration should review DuckDuckGo's [URL-parameter and partnership guidance](https://duckduckgo.com/duckduckgo-help-pages/settings/params). Use Wikipedia for reliable keyless encyclopedia search or Brave when a documented, general-web provider contract is required. With every engine, search queries leave the process, and titles, URLs, snippets, and page content are untrusted external data. Do not treat search output as instructions, executable content, or proof that a claim is correct.

## URL fetch

`fetch_url()` retrieves bounded textual content from a public HTTP or HTTPS URL. It rejects credentials in URLs, non-HTTP schemes, and private, loopback, link-local, reserved, or otherwise non-public targets. Redirect destinations are resolved and validated again before they are followed. Responses are subject to redirect, timeout, byte, character, and supported-text-content limits; the result reports when extracted text was truncated.

```python
page = await agent.call_tool("fetch_url", url="https://example.com/")
```

<ApiReference
  kind="factory"
  path="protolink.tools.fetch_url"
  signature={`fetch_url() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/web.py#L831"
>

Create a fresh `Tool` named `fetch_url`. Construction is side-effect free; DNS resolution and network access begin only when the returned tool is invoked.

<ApiSection title="Returns">
  <ApiFields ariaLabel="fetch_url factory return value">
    <ApiField name="tool" type="Tool">
      A native read-only web tool with the <code>network.read</code> capability, public-destination validation, bounded redirects and bytes, and an explicit output schema.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="fetch_url generated tool arguments">
    <ApiField name="url" type="str" required>
      Public HTTP or HTTPS URL of at most 2,048 characters. Embedded credentials, nonstandard ports, unsafe address ranges, HTTPS downgrades, and non-public redirect targets are rejected.
    </ApiField>
    <ApiField name="max_chars" type="int" defaultValue="12000">
      Maximum readable text characters returned after download and decoding. Accepted range: 1–50,000; transfer bytes are bounded separately.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns from invocation">
  <ApiFields ariaLabel="fetch_url generated tool result">
    <ApiField name="result" type="dict[str, Any]">
      Final validated URL, HTTP status, normalized content type, extracted title, bounded text, truncation flag, and <code>untrusted_content=True</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="fetch_url errors">
    <ApiField name="ValueError">
      Invalid URL shape, scheme, credentials, port, address, redirect destination, or character limit.
    </ApiField>
    <ApiField name="RuntimeError">
      HTTP, redirect, timeout, response-size, content-type, charset, or HTML-decoding failures.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

After each destination is DNS-validated, the transfer is limited to 1,000,000 bytes, four validated redirects, and a 10-second transport deadline for each request or redirect before the `max_chars` return bound is applied. DNS lookup uses the host operating system's resolver and is not included in that transport deadline. These restrictions reduce accidental server-side request forgery and context exhaustion; they do not make remote content trustworthy. Treat returned text as untrusted input and keep application-specific authorization at the Agent policy boundary.

## Calculator and current datetime

`calculator()` evaluates a deliberately small arithmetic grammar rather than Python code. It never uses `eval`, rejects names and function calls, and enforces expression-complexity, exponent, magnitude, and finite-result limits.

`current_datetime()` returns structured current-time data for the requested timezone. UTC works without a host timezone database; other IANA zones use the system database, or the `tzdata` package when a host does not provide one. Invalid or unavailable timezone identifiers raise a clear tool error rather than silently falling back to local machine time.

```python
calculation = await calculator()(expression="(18 + 6) / 3")
now = await current_datetime()(timezone="Europe/Zurich")
```

### calculator

<ApiReference
  kind="factory"
  path="protolink.tools.calculator"
  signature={`calculator() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/calculator.py#L104"
>

Create a fresh pure arithmetic tool. The returned callable parses a restricted Python expression AST; it never uses `eval` and cannot resolve names, attributes, calls, booleans, or complex values.

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="calculator generated tool arguments">
    <ApiField name="expression" type="str" required>
      Arithmetic expression of 1–256 characters using numbers, parentheses, unary signs, and <code>+</code>, <code>-</code>, <code>*</code>, <code>/</code>, <code>//</code>, <code>%</code>, or <code>**</code>. Syntax-tree size, exponent size, numeric magnitude, and finite-result limits prevent resource-heavy evaluation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="calculator result">
    <ApiField name="result" type="dict[str, int | float | str]">
      The trimmed original <code>expression</code> and its finite numeric <code>result</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="calculator errors">
    <ApiField name="ValueError">
      Empty or invalid arithmetic, unsupported syntax, division by zero, oversized powers or values, excessive complexity, and non-finite results.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### current_datetime

<ApiReference
  kind="factory"
  path="protolink.tools.current_datetime"
  signature={`current_datetime() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/clock.py#L67"
>

Create a fresh timezone-aware clock tool. UTC requires no external service or timezone database; other IANA identifiers are resolved through the host database or the optional `tzdata` package.

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="current_datetime generated tool arguments">
    <ApiField name="timezone" type="str" defaultValue={'"UTC"'}>
      IANA timezone name of at most 100 characters. The tool never silently substitutes host-local time for an unknown zone.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="current_datetime result">
    <ApiField name="result" type="dict[str, Any]">
      Requested timezone, ISO-8601 timestamp, date, time, weekday, UTC offset, and Unix timestamp.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="current_datetime errors">
    <ApiField name="ValueError">
      Empty, oversized, unknown, or unavailable timezone identifiers.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

---

## Command execution

```python
import sys
from protolink import Agent, AgentCard, ApprovalDecision, CapabilityPolicy
from protolink.tools.builtins import process_tool


async def approve(request, context):
    # Present request.action.artifacts in your application's authenticated UI.
    approved = await application_ui.confirm(request.to_dict())
    return ApprovalDecision(approved=approved, request_id=request.request_id)


agent = Agent(
    AgentCard(name="commands", description="Command execution", url="runtime://commands"),
    policy=CapabilityPolicy({"process.execute": "require_approval"}),
    approval_handler=approve,
)
agent.add_tool(process_tool())
result = await agent.call_tool(
    "execute_command",
    argv=[sys.executable, "-c", "print('hello')"],
    cwd="/absolute/working/directory",
    env={},
    timeout_seconds=10,
    max_output_bytes=4096,
)
print(result.exit_code, result.stdout, result.truncated)
```

`application_ui` is application code. For a runnable, harmless approval callback, see
[`command_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/command_agent.py).
No LLM or server is required. Registration does not launch a process, and calling the prepared tool directly raises:
execution must pass through an Agent's authorization pipeline.

### Public interfaces

| Interface | Purpose |
| --- | --- |
| `process_tool(*, backend=None, max_timeout_seconds=300, max_output_bytes=1048576)` | Factory for the `execute_command` tool; factory limits are ceilings. |
| `execute_command(argv, cwd, env, timeout_seconds=60, max_output_bytes=65536)` | Tool arguments. `argv`, `cwd`, and `env` are required. |
| `ProcessSpec` | Exact argv, resolved cwd, environment mapping, timeout, and combined output-byte cap. |
| `ProcessResult` | `exit_code`, `stdout`, `stderr`, `truncated`, `timed_out`, `canceled`, `duration_seconds`, `budget_exceeded`. |
| `ExecutionBackend` | `boundary: str` and `async execute(spec, execution) -> ProcessResult`. |
| `LocalExecutionBackend` | The first-party host implementation. |
| `ProcessCancelledError` | Native `asyncio.CancelledError` subclass with a partial typed `.result`. |

Backend/result types are in `protolink.tools.builtins.process`. A future remote or container backend can implement this
protocol; ProtoLink does not implement those backends in this release. Backend implementations are trusted application
code and must honor the approved specification and live execution limits.

The local backend uses an argument array without an implicit shell. Environment inheritance is explicit: `env={}`
starts with no inherited environment variables; pass a deliberately selected mapping to allow others. Supply an
absolute executable, an explicit relative executable path, or a `PATH` entry in `env`. Preparation resolves the
executable and directory before presenting their exact values, limits, and execution boundary for authorization.
An explicitly requested shell executable can still interpret its own arguments.

**This is host execution, not a sandbox.** It does not restrict filesystem or network access. POSIX process groups
are killed and reaped on timeout, cancellation, and normal exit to clean up ordinary descendants. Descendants that
create their own session can escape group cleanup. Windows cleanup covers the immediate child only. These limits
bound wall time and captured output, not CPU, memory, disk writes, or arbitrary external effects.

Stdout and stderr are drained concurrently. Their combined retained/emitted output is capped in bytes; excess bytes
are discarded while pipes continue draining. Text uses UTF-8 replacement decoding. `process.output` events carry
`channel` and `text`; `process.finished` includes termination facts, including partial output on cancellation.
Task cancellation retains its native `canceled` lifecycle state. Nonzero exit codes and command timeouts are typed
results; an application completion predicate determines whether those outcomes satisfy its task.

Native task budgets are checked before launch, including time spent awaiting approval. Process time is also bounded
by the remaining runtime budget. Multiple direct calls with the same live `RunContext` share their tool budget;
serialization preserves configured limits, not live execution counters. Delegated tool dispatch counts against its
parent's tool budget and the recipient enforces inherited task limits. These are task-local limits, not a distributed
atomic accounting service for arbitrary parallel agent graphs.

## Shell and Git tools

```python
from protolink.tools import shell_tool, git_tool

agent.add_tool(shell_tool(cwd="/absolute/workspace"))
agent.add_tool(git_tool(cwd="/absolute/workspace", allow_write=True))
output = await agent.call_tool("run_shell", command="printf 'hello\n' | sort")
changes = await agent.call_tool("git", operation="diff", staged=True)
```

| Factory | Model-facing arguments | Capabilities |
| --- | --- | --- |
| `shell_tool(*, cwd, env=None, shell="/bin/sh", timeout_seconds=60, max_output_bytes=65536, backend=None)` | `run_shell(command)` | `process.execute`, `shell.execute` |
| `git_tool(*, cwd, allow_write=False, env=None, executable="git", timeout_seconds=60, max_output_bytes=65536, backend=None)` | `git(operation, paths=None, revision=None, staged=False, message=None, max_count=10)` | `process.execute` and either `git.read` or `git.write` |

Both factories resolve the directory/executable at registration without launching a process. The application
owns these settings; the model cannot increase limits or replace the environment. `env=None` supplies only
`PATH=os.defpath`; an explicit mapping is the complete copied environment. Both return the same `ProcessResult`
and emit the same process events as `process_tool()`. Exact resolved argv, cwd, environment, and limits appear
in the approval preview. Runtime action payloads keep model arguments in `arguments` and the resolved process
specification in `process`. Denial prevents execution; timeout/cancellation reuse native process cleanup.

Shell scripts support pipelines, redirects, and ordinary shell syntax. Each call starts a fresh noninteractive
POSIX-compatible shell (`-c`); changes to working directory or variables do not persist. Windows users need
an installed compatible shell and its executable path. `cwd` is not an access boundary: scripts can access
other host paths and the network. For finer argv control, keep using `process_tool()`.

Git exposes these operations:

| Operation | Supported options |
| --- | --- |
| `status` | Optional literal `paths`; short output with branch information. |
| `diff` | Optional `paths`, `revision`, and `staged=True` for index changes. |
| `log` | Optional `paths`, `revision` (default HEAD), and `max_count` from 1–100. |
| `show` | Optional `paths` and `revision` (default HEAD). |
| `add` | Required nonempty `paths`; stages those paths, including deletions. |
| `commit` | Required nonblank `message`; commits **all staged changes**, including existing ones. |

Paths are literal, relative to the configured directory; absolute paths and `..` components are rejected.
Revisions cannot inject command options. Unsupported option combinations fail before authorization. Writing
needs `allow_write=True` and a policy permitting `git.write`; disabled writes are absent from the advertised
operation enum. Nonzero Git exit codes remain typed results. The tool does not roll back commits/index edits
or expose push, reset, checkout, or arbitrary flags. Repository state can change during approval: previews
bind commands, not a transaction over the index/HEAD, so inspect staged changes before committing.

The adapter disables system/global Git configuration, terminal prompts, optional locks, hooks, fsmonitor,
signing, external diff, and textconv. Repository configuration still applies, and staging clean filters may
execute code. Read/write capabilities classify requested operations; they do not sandbox untrusted repositories.
These switches follow the [Git](https://git-scm.com/docs/git) and
[diff](https://git-scm.com/docs/git-diff) command contracts.

## User questions and continuation

```python
from protolink.tools import UserInputRequest, ask_user_tool


async def handle_question(request: UserInputRequest) -> str | None:
    # Application UI returns text, or None when the user declines.
    return await application_ui.ask(request.to_dict())


agent.add_tool(ask_user_tool(handle_question, timeout_seconds=300))
answer = await agent.call_tool("ask_user", question="Which format?", options=["JSON", "CSV"])
print(answer.status, answer.answer)
```

`application_ui` is your UI adapter. The model-facing API is `ask_user(question, options=None)`.
When invoked by the inference loop, the tool awaits your async callback, then puts its result in normal
tool history before the next model step. The task stays working during the wait. This does not suspend
or resume a task across process restarts and does not use `input-required` as a durable checkpoint.

`UserInputRequest` has `request_id`, `question`, immutable suggested `options`, `run_id`, `task_id`, and
`action_id`; standalone tool calls have no task ID. IDs correlate simultaneous calls but do not authenticate
responders. `UserInputResult` contains `request_id`, `status`, and `answer`. Suggested answers never restrict
free text. Questions are limited to 8,000 characters and ten distinct nonblank options of up to 500 characters.
The callback returns nonblank text (up to `max_answer_chars=16384`) or `None` to decline.

`answered` retains the exact answer. `declined` and `timed_out` have no answer; neither selects a default or
gives consent. A callback exception is a tool failure. Native task cancellation interrupts the callback;
run-budget expiry raises the existing budget error. The question timeout defaults to 300 seconds and is
bounded by the remaining run budget. Callbacks should release pending UI state in `finally`; they must not
block the event loop. For a simple terminal adapter, offload `input()` to a thread and serialize prompts,
noting that cancellation cannot interrupt a blocking stdin read in that thread.

Events are `user_input.requested` with a request, `user_input.answered`/`user_input.declined` with a result,
and `user_input.timed_out`, `user_input.canceled`, or `user_input.failed` with the request ID. Existing
run/task/action correlation remains available. Questions and answers enter history/events, so use an
appropriate redaction policy for sensitive content. The capability is `user.interact`; answering a question
does not approve shell execution, sending email, or other side effects.

The [offline assistant example](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_assistants.py)
shows the model receiving feedback and continuing. See [Built-in Agents](builtin-agents.md) for
the small agent presets that compose these tools with calendar and email integrations.

## Filesystem access

The shell can perform file operations too. Dedicated file tools give developers structured arguments,
bounded results, and a `filesystem.read` capability without granting shell execution. Recoverable
edits reuse file previews and checkpoints. Register whichever interface your application needs;
the filesystem roots do not restrict a separately registered shell tool.

```python
from protolink import StorageCheckpointStore
from protolink.storage import SQLiteStorage
from protolink.tools import filesystem_tools

# Omitting checkpoints exposes only reads/listing/search.
tools = filesystem_tools(roots=["/absolute/workspace"])

# Supplying checkpoints explicitly enables writes and recovery too.
tools = filesystem_tools(
    roots=["/absolute/workspace"],
    checkpoints=StorageCheckpointStore(SQLiteStorage("recovery.db", namespace="file-changes")),
    max_file_bytes=8 * 1024 * 1024,
)
```

| Tool | Arguments | Capability |
| --- | --- | --- |
| `read_file` | `path`, `offset=0`, `max_chars=20000` | `filesystem.read` |
| `list_files` | `path`, `pattern="*"`, `recursive=False`, `max_results=100` | `filesystem.read` |
| `search_files` | `path`, `query`, `pattern="*"`, `case_sensitive=False`, `max_results=100` | `filesystem.read` |
| `create_file` | `path`, `content` | `filesystem.write` |
| `replace_file` | `path`, `content` | `filesystem.write` |
| `edit_file` | `path`, `old_text`, `new_text`, `replace_all=False` | `filesystem.write` |
| `preview_change` | `change_id` | `filesystem.read` |
| `restore_change` | `change_id` | `filesystem.restore` |

Paths must be absolute and inside a configured root. Symlinks and special files appear as
`type="other"` in listings and are not searched. Reads reject symlinks, special files, invalid UTF-8,
and NUL-containing binary content. Root aliases such as macOS `/tmp` are resolved at registration.
The existing POSIX descriptor-based implementation supplies these boundaries; it is not an OS sandbox.

`read_file` returns `path`, `content`, and `next_offset`. Offsets count Unicode characters; `max_chars`
is 1–20,000. Each call reads the current bounded file, so continue only while the file is unchanged.
`list_files` matches a filename glob. `search_files` recursively matches literal text and returns
paths, one-based line numbers, and up to 500 characters per matching line; `text_truncated` indicates
a shortened line. Results follow filesystem traversal order rather than a stable sorted snapshot.

Listing/search return `items`, `scanned`, `skipped`, and `truncated`. `max_results` is 1–1,000.
Traversal visits at most 10,000 entries and 20 directory levels. Search reads at most 32 MiB of file
content in total, applies the per-file cap, and skips binary/unreadable/oversized files. Check both
`truncated` and `skipped` before treating an empty result as exhaustive. Reads run on workers;
cancellation stops waiting while bounded work may finish afterward.

`edit_file` performs exact, case-sensitive UTF-8 replacement. Empty or missing matches fail before
approval; multiple matches require `replace_all=True`. Approval includes the diff and exact preimage.
A changed file or parent directory causes a conflict before applying the edit. Writes return the
existing recovery identifiers. See [write recovery](#write-recovery) below for persistence and restoration semantics.

### Write recovery

```python
from protolink import StorageCheckpointStore
from protolink.storage import SQLiteStorage
from protolink.tools.builtins import filesystem_tools

checkpoints = StorageCheckpointStore(SQLiteStorage("application.db", namespace="file-changes"))
for tool in filesystem_tools(roots=["/absolute/workspace"], checkpoints=checkpoints):
    agent.add_tool(tool)

change = await agent.call_tool("replace_file", path="/absolute/workspace/note.txt", content="new content\n")
preview = await agent.call_tool("preview_change", change_id=change["change_id"])
restored = await agent.call_tool("restore_change", change_id=change["change_id"])
```

Configure `filesystem.write` and `filesystem.restore` with `require_approval` for separately approved mutation and
restoration. Recovery preview uses `filesystem.read`. ProtoLink's backward-compatible default capability policy allows
actions, so installing a tool alone does not require a human approval. The runnable
[`recoverable_files.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_capabilities/recoverable_files.py)
shows both successful restoration and a conflict.

| Tool | Preconditions and result |
| --- | --- |
| `create_file(path, content)` | Target must remain absent; creates UTF-8 bytes with mode `0600`. |
| `replace_file(path, content)` | Existing regular file must match the approved bytes, mode, identity, and parent directory. |
| `edit_file(path, old_text, new_text, replace_all=False)` | Exact match requirements and the approved preimage must still hold. |
| `preview_change(change_id)` | Returns a restoration diff, current conflict flag, saved state, and uncertainty flag. |
| `restore_change(change_id)` | Requires a saved `applied` change and the exact expected postimage; restores bytes/mode or removes a created file. |

`filesystem_tools(*, roots, checkpoints=None, max_file_bytes=8388608)` returns three read tools.
Supplying checkpoints adds five write/recovery tools, including `edit_file`. All paths must be
absolute and beneath explicit roots; `..`, symlinks beneath roots, and nonregular files are rejected. Missing parent
directories are not created. Prepared diff artifacts are tied to the canonical target and preimage; both are checked
again after approval. Files are replaced atomically using a temporary file in the same directory, with fsync of
the file and parent directory. Creation atomically refuses a concurrently created target.

`FilesystemResource` implements the small `Resource` protocol: `read(resource_id)` and
`replace(expected_snapshot, data, mode)`. `ResourceRevision`, `ResourceSnapshot`, `ResourceChange`, `CheckpointStore`,
and `StorageCheckpointStore` live in `protolink.core.resources`. The filesystem implementation currently requires
POSIX descriptor-relative APIs and rejects Windows. Regular file bytes and mode bits are preserved; ownership,
ACLs, extended attributes, and timestamps are not restored. An OS sandbox is required to defend against hostile
concurrent filesystem manipulation; the final compare/rename is not a lock respected by arbitrary external writers.

Recovery information is persisted **before** mutation. Records correlate the resource with an action, task, and run;
states include `prepared`, `applied`, `restoring`, `restored`, `failed`, and `uncertain`. If an interrupted mutation
leaves a `prepared` or `restoring` record, inspection reports uncertainty. Failure to save the initial record prevents
mutation. Failure after a possible write leaves an uncertainty marker; no automatic replay or restoration occurs.
Restoration conflicts raise `ResourceConflictError`. Recovery of an uncertain operation requires application-led
inspection; this release deliberately does not guess whether its effect occurred.

Recovery storage is a dedicated namespace with one live writer. Keep it outside mutable allowed roots where practical.
It contains lossless original bytes, so protect it as application data. Resource recovery, conversation history, and
execution suspension/resumption are separate concepts. Multiple file writes are not an atomic transaction, and
arbitrary process/tool effects are not reversible.

## JSON storage

```python
from protolink.storage import SQLiteStorage
from protolink.tools import storage_tools

tools = storage_tools(
    SQLiteStorage("application.db", namespace="tool-values"),
    allow_write=True,
    max_value_bytes=65536,
    max_store_bytes=1048576,
    max_keys=1000,
)
```

| Tool | Arguments | Capability |
| --- | --- | --- |
| `get_value` | `key` | `storage.read` |
| `list_keys` | `prefix=""`, `offset=0`, `limit=100` | `storage.read` |
| `set_value` | `key`, `value` | `storage.write` |
| `delete_value` | `key` | `storage.write` |

Writes require `allow_write=True` and the agent's policy. Keys are nonblank strings of at most 256
characters. Values are JSON data; non-finite numbers and oversized values are rejected. Missing keys
return `found=False`; stored JSON null returns `found=True, value=None`. Results are detached copies.
`list_keys` sorts keys, filters by literal prefix, and returns `next_offset`; offsets can shift during
mutation. `limit` is 1–1,000. Deleting an absent key is a no-op.

The tools reuse the synchronous `Storage` contract. Their namespace contains one JSON object, with
every update loading and saving that map. Give the bundle exclusive ownership of a dedicated namespace
and reuse its tools to share their lock. Keep Agent state and checkpoints in separate namespaces.
`Storage` has no cross-process transaction or compare-and-swap contract. Adapters should be fast because
operations run without an asyncio suspension; data limits do not bound backend I/O time.

## HTTP APIs

```python
import os
from protolink.tools import http_tool

agent.add_tool(
    http_tool(
        "https://api.example.com/v1/",
        headers=lambda: {"Authorization": f"Bearer {os.environ['API_TOKEN']}"},
        allowed_methods=["GET", "POST"],
        name="application_api",
    )
)
result = await agent.call_tool("application_api", path="items", query={"limit": "10"})
```

`http_tool(base_url, *, headers=None, allowed_methods=("GET", "HEAD"), allow_http=False,
timeout_seconds=30, max_request_bytes=1048576, max_response_bytes=1048576, name="http_request")`
returns one tool with arguments `path=""`, `method="GET"`, `query=None`, and `body=None`.
`query` is a string-to-string mapping; `body` is optional JSON. GET/HEAD reject bodies and require
`network.read`. Explicitly enabled POST/PUT/PATCH/DELETE/OPTIONS require `network.write`. Their exact
method, normalized path, query, and body appear in approval previews. Configure write approval in
your policy. A GET request's actual effects still depend on the selected service.

The developer fixes the origin and base path: `items` and `/items` both address `/v1/items` above.
Absolute URLs, authority overrides, traversal, embedded queries/fragments, and encoded variants are
rejected. `allow_http=True` permits a deliberately selected plain HTTP endpoint. Internal services
are allowed because destinations come from application configuration.

Headers are copied at registration or resolved from a sync/async callback per request. The model
cannot supply authentication or routing headers. Redirects, ambient proxies, and retries are disabled.
Responses contain `status_code`, selected headers, `body`, and `body_encoding` (`json`, `text`, or
`base64`). Errors and redirects are returned for interpretation, without following them. Response
limits apply to decoded body bytes; binary output is base64 encoded afterward. HTTPX clients close
on completion or cancellation. A canceled write may already have been accepted remotely.

## Document extraction

```python
from protolink.tools import document_tools

for tool in document_tools(roots=["/absolute/documents"]):
    agent.add_tool(tool)
document = await agent.call_tool("read_document", path="/absolute/documents/report.pdf")
```

`document_tools(*, roots, max_file_bytes=8388608, max_output_chars=20000, max_sections=100,
max_archive_bytes=33554432, timeout_seconds=30)` exposes `read_document(path)` and
`search_document(path, query, max_results=20)`, both requiring `filesystem.read`. Search accepts
1–100 results. The filesystem tools' absolute-path, POSIX root, and symlink rules apply.

| Format | Extraction |
| --- | --- |
| UTF-8 TXT/MD/RST/LOG/JSON/YAML/XML | Text, without executing or interpreting embedded content |
| CSV/TSV | Rows with string cells and one-based row locations |
| PDF | Page text and page numbers; requires `pypdf` |
| DOCX | Top-level body paragraphs/table rows in order; requires `python-docx` |
| XLSX | Worksheet rows and cached cell values; requires `openpyxl` |

Install optional parsers with `pip install 'protolink[documents]'`. PDF-only installations can use
`protolink[rag-pdf]`. Results contain `metadata` (path, format, input bytes), located `sections`, and
`truncated`. Sections hold text or table rows with string `cells`, limited to 100 columns. Text/cell
characters share the output limit. Search matches literal text without case sensitivity inside this
bounded extraction, returning located snippets. `truncated=True` means extraction or results are incomplete.

PDF provides no OCR or reconstruction of table geometry; see
[pypdf's extraction limits](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
Word uses the [body block API](https://python-docx.readthedocs.io/en/latest/api/document.html), and
spreadsheets use [read-only mode](https://openpyxl.readthedocs.io/en/stable/optimized.html) with cached
values. Formulas are not evaluated; missing caches produce empty cells. Macros and remote links are
not executed. Encrypted documents are unsupported. Office archive entry counts and declared expanded
sizes are checked before parsing. Worker timeouts stop waiting but cannot forcibly stop a parser or
guarantee a hard memory ceiling. Use process isolation for hostile documents.

## Database queries

```python
from protolink.tools import SQLiteDatabase, database_tools

for tool in database_tools(SQLiteDatabase("application.sqlite")):
    agent.add_tool(tool)
schema = await agent.call_tool("database_schema")
rows = await agent.call_tool(
    "query_database",
    sql="SELECT id, name FROM items WHERE category = ? ORDER BY id",
    parameters=["example"],
    max_rows=100,
)
```

`database_tools(backend, *, timeout_seconds=30)` exposes `database_schema()` and
`query_database(sql, parameters=None, max_rows=100)`, both requiring `database.read`. Parameters
are a list for positional placeholders or a mapping for named placeholders, containing strings,
numbers, booleans, or null. `max_rows` is 1–1,000. SQL and parameters appear in previews/reports.

`SQLiteDatabase(path, *, timeout_seconds=5, max_result_bytes=1048576, max_tables=100)` selects an
existing database file. It opens fresh read-only connections and never creates a database; in-memory
connections are unsupported. Queries use bound parameters, a SQLite authorizer, runtime limits, and
a progress deadline. Writes, ATTACH, PRAGMA, explicit transactions, and extension loading are rejected
using [SQLite's connection APIs](https://docs.python.org/3/library/sqlite3.html). Cancellation interrupts
the worker's connection. Queries are not automatically retried.

Schema results contain tables/views and columns with a truncation flag. Query results use `columns`,
positional `rows`, and `truncated`, preserving duplicate column names. Blobs become `{"base64": "..."}`.
Row/JSON byte caps bound output; oversized individual SQLite values fail before transfer. Results
can be empty and truncated if the first row exceeds the output limit. Use SQL filters and ordering
to narrow queries. No database mutation tools are included.

Implement the async `DatabaseBackend` protocol for another database: `describe_schema()` and
`query(*, sql, parameters, max_rows)`, returning JSON-compatible dictionaries. Adapters own credentials,
connections, read-only enforcement, limits, and cancellation. The wrapper does not parse SQL dialects.

## Calendar and email backends

| Backend | Service | Authentication |
| --- | --- | --- |
| `GoogleCalendar` | Google Calendar | OAuth access token or token callback |
| `Gmail` | Gmail | OAuth access token or token callback |
| `OutlookCalendar` | Microsoft 365 / Outlook calendar | OAuth access token or token callback |
| `OutlookEmail` | Microsoft 365 / Outlook mailbox | OAuth access token or token callback |
| `IMAPEmail` | Standard TLS IMAP and optional SMTP | Password/app-password or password callback |

All backends work with the same `Assistant`, `calendar_tools()`, and `email_tools()` APIs.
You can mix services, such as a Microsoft calendar and an IMAP mailbox. Construction never connects
to an account. The tool descriptions tell the model which search syntax the selected backend uses.

## Calendar integration

```python
from protolink.tools import GoogleCalendar, calendar_tools

for tool in calendar_tools(GoogleCalendar(token, calendar_id="primary"), allow_write=True):
    agent.add_tool(tool)
```

`calendar_tools(backend, *, allow_write=False, timeout_seconds=30)` returns prepared tools:

| Tool | Arguments | Capability |
| --- | --- | --- |
| `list_calendar_events` | `start`, `end`, `query=""`, `max_results=20`, `page_token=None` | `calendar.read` |
| `create_calendar_event` | `title`, `start`, `end`, `description=""`, `location=""` | `calendar.write` |

Start/end are ISO 8601 timestamps with explicit offsets; end must follow start. Listing returns events
overlapping the interval, including recurring instances and all-day events. `max_results` is 1–100.
Results use `items` and `next_page_token`; keep the same backend, interval, query, and page size for
another page. An empty page can still have a next token. Google and Microsoft event objects retain
their original service fields, including their different representations of all-day boundaries.

Creation returns the service event object with its `id`. This version creates personal timed events:
it does not invite attendees, create recurring/all-day events, modify existing events, or delete events.
Applications choose the user's timezone and check scheduling conflicts. Invalid intervals are rejected
before an approval is requested or a backend is called.

Implement the small async `CalendarBackend` protocol to use another service. Its two methods are
`list_events(*, start, end, query, max_results, page_token)` and
`create_event(*, title, start, end, description, location)`, both returning JSON-compatible dictionaries.
The offline example implements this interface without any account.

## Email integration

```python
from protolink.tools import Gmail, email_tools

for tool in email_tools(Gmail(token, sender="me@example.com"), allow_write=True, allow_send=True):
    agent.add_tool(tool)
```

`email_tools(backend, *, allow_write=False, allow_send=False, timeout_seconds=30)` returns:

| Tool | Arguments | Capability |
| --- | --- | --- |
| `list_email_messages` | `query=""`, `max_results=20`, `page_token=None` | `email.read` |
| `read_email` | `message_id` | `email.read` |
| `create_email_draft` | `to`, `subject`, `body` | `email.write` |
| `send_email` | `to`, `subject`, `body` | `email.send` |

`allow_write` includes drafts, and `allow_send` independently includes sending. Drafting never delivers
mail. Queries use provider syntax, such as Gmail's `is:unread newer_than:7d`. Lists return one page of
message identifiers in `items`, with `next_page_token`; keep the same backend, query, and page size
while continuing, and fetch content with `read_email`. Reads do not mark mail read. All built-in
backends return selected headers, snippet, a plain-text `body` capped at 20,000 characters,
`body_truncated`, `has_attachments`, and `html_body_omitted`. Gmail and IMAP decode nested MIME text
parts and declared charsets; Outlook requests plain text from Graph. Attachment content is never
returned to the model. IMAP fetches the bounded MIME message including attachment bytes; the HTTP
backends do not request attachments separately. HTML-only MIME bodies are omitted.

Compose operations accept 1–50 bare ASCII recipient addresses, a nonblank subject up to 1,000
characters, and a nonblank plain-text body up to 200,000 characters. Header injection is rejected
before approval. Gmail's fixed `sender` is required for composing and must be the authenticated
address or a configured send-as alias. This version does not compose attachments, CC/BCC, HTML,
or threaded replies. Gmail sending returns service message/thread IDs; draft creation returns draft
and message identifiers. Other backends return the statuses described below. None claims delivery
to the recipient's inbox.

Implement `EmailBackend` for another service: async `list_messages(*, query, max_results, page_token)`,
`get_message(*, message_id)`, `create_draft(*, to, subject, body)`, and
`send_message(*, to, subject, body)`, returning JSON-compatible dictionaries. Read-only adapters need
only implement the methods enabled in their tool bundle. An optional `query_help` string on either
backend protocol's implementation adds search guidance to the model-facing tool description.

## Microsoft 365 and Outlook

```python
from protolink import Assistant
from protolink.tools import OutlookCalendar, OutlookEmail

# token is your access token or a sync/async callback returning one.
assistant = Assistant(calendar=OutlookCalendar(token), email=OutlookEmail(token))

# Select an explicit user and calendar when needed.
calendar = OutlookCalendar(token, user_id="me@example.com", calendar_id="calendar-id")
email = OutlookEmail(token, user_id="me@example.com")
```

Both constructors default to `user_id="me"` for delegated OAuth access. Application tokens require
an explicit user ID or principal name. `calendar_id=None` selects that user's default calendar.
All calls stay on the global `graph.microsoft.com/v1.0` endpoint; national-cloud endpoints are not
supported. Grant access to the selected user/calendar/mailbox in your application registration:

| Operation | Microsoft Graph permission |
| --- | --- |
| Calendar reading | `Calendars.Read` |
| Calendar creation | `Calendars.ReadWrite` |
| Email reading/search | `Mail.Read` |
| Email drafts | `Mail.ReadWrite` |
| Email sending | `Mail.Send` |

Shared resources can require additional delegated permissions or mailbox access rights. Permissions,
consent, and token refresh are application-owned; a token callback must keep the same account.

Calendar listing uses [calendarView](https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0)
to expand recurring occurrences within the requested interval. `query` filters each returned page by
a case-insensitive substring in subject, body preview, or location. Follow `next_page_token` even
when filtering produces an empty page. Creating an event converts the supplied offsets to equivalent
UTC instants and sends a personal event with no attendees.

Email queries use [Microsoft Graph message search](https://learn.microsoft.com/en-us/graph/search-query-parameter),
for example `subject:review` or `from:person@example.com`. Search is capped at 1,000 matching messages;
an empty query lists the mailbox in descending received-time order. Message requests use immutable
IDs, and reads request plain text without changing read status.

Microsoft continuation tokens belong to the existing backend instance, selected resource, and query
arguments. Restart listing after recreating a backend or changing those arguments. Continuation links
are validated against the original HTTPS host and collection before use. They cannot switch users,
calendars, or mailboxes.

Draft creation returns the Graph draft object and `id`. Sending saves a copy to Sent Items and returns
`{"status": "accepted"}`. Microsoft's [sendMail response](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
is HTTP 202 with no message ID and does not confirm completed delivery.

## Standard IMAP and SMTP

```python
import os

from protolink import Assistant
from protolink.tools import IMAPEmail

mail = IMAPEmail(
    "me@example.com",
    lambda: os.environ["MAIL_PASSWORD"],
    imap_host="imap.example.com",
    smtp_host="smtp.example.com",  # Omit for read/draft-only access.
    drafts_mailbox="Drafts",  # Explicit existing folder; omit if drafts aren't needed.
)
assistant = Assistant(email=mail)
# To expose drafts/sending, supply allow_write/allow_send and an approval handler.
```

`IMAPEmail` uses only the Python standard library. Passwords can be strings or no-argument sync/async
callbacks, resolved once per operation. Use an app password if your provider requires one and supports
this authentication method. OAuth-only accounts should use `Gmail` or `OutlookEmail`.

IMAP always uses implicit TLS, normally port 993. SMTP uses implicit TLS on port 465 by default.
For submission servers on port 587, set `smtp_starttls=True`; STARTTLS must succeed before login.
Override `imap_port` or `smtp_port` for other TLS endpoints. Default TLS contexts validate server
certificates and hostnames; an optional `ssl_context` lets your application supply its own trust
configuration. There is no plaintext fallback.

`sender` defaults to the login username; supply a bare ASCII address when your login name is not an
address or when using an authorized alias. `mailbox="INBOX"` selects the folder being read.
Mailbox names and usernames must be ASCII; encode international mailbox names as IMAP modified UTF-7.
`drafts_mailbox` names an existing folder: the backend does not discover or create it. `smtp_host` is
required only for sending, and SMTP submission does not itself append a second copy to Sent.

Search is literal ASCII text across headers and body; it is not Gmail or raw IMAP search syntax.
Empty query means all messages. Pages descend by UID; subsequent pages exclude new arrivals, while
expunged messages may disappear. IDs and cursors include the selected account/folder's identity and
UIDVALIDITY. A changed UIDVALIDITY rejects stale IDs/tokens so they cannot silently reference another
message. Use IDs from `list_email_messages` with the same account and folder.

Reads select the mailbox read-only, fetch size first, and use `BODY.PEEK[]` without setting Seen.
`max_message_bytes=2097152` caps both fetched MIME bytes and composed message bytes; oversized messages
are rejected. Returned plain text is additionally capped at 20,000 characters. These behaviors use
Python's [IMAP](https://docs.python.org/3/library/imaplib.html) and
[SMTP](https://docs.python.org/3/library/smtplib.html) interfaces.

Drafts are appended with the Draft flag and return `status="drafted"`, `mailbox`, and an RFC Message-ID
in `message_id`. This local header value is not an IMAP ID for `read_email`. Sending returns:

```python
{
    "status": "partially_accepted",  # Or "accepted" or "rejected".
    "message_id": "<generated-rfc-message-id@example.com>",
    "accepted": ["one@example.com"],
    "refused": [{"address": "two@example.com", "code": 550}],
}
```

Acceptance means the SMTP server accepted those recipients; it is not final delivery confirmation.
Partial rejection does not undo accepted recipients, and nothing is automatically resent. Private
server response text is excluded from results and `MailBackendError` exceptions.

## Service authentication, policy, and lifecycle

Google and Microsoft adapters accept an access-token string or a no-argument sync/async callback that returns a fresh
access token for each request. OAuth consent, scopes, refreshing, secure storage, and account selection
belong to the application. Tokens are never model arguments, approval previews, or serialized agent
configuration. Keep callbacks on the same account when refreshing credentials.
For Google, use these scopes (prefixed by `https://www.googleapis.com/auth/`):

| Operation | Scope |
| --- | --- |
| Calendar reading | `calendar.events.readonly` or `calendar.events` |
| Calendar creation | `calendar.events` |
| Email reading/search | `gmail.readonly` |
| Email drafts | `gmail.compose` |
| Email sending | `gmail.send` or `gmail.compose` |

For provider details, see Google's [event listing](https://developers.google.com/workspace/calendar/api/v3/reference/events/list),
[event creation](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[message listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), and
[message sending](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send) contracts.

Factories do not contact accounts. Service tools must execute through an Agent's native policy pipeline;
direct prepared-tool calls fail closed. Configured targets and exact arguments are attached as previews.
Unlike the assistant presets, the ordinary `Agent` policy remains allow-by-default: configure it explicitly
when registering tool bundles yourself. For example:

```python
from protolink import CapabilityPolicy

policy = CapabilityPolicy(
    {
        "calendar.read": "allow",
        "email.read": "allow",
        "calendar.write": "require_approval",
        "email.write": "require_approval",
        "email.send": "require_approval",
        "user.interact": "allow",
    },
    default_effect="deny",
)
```

Each operation has a timeout, further bounded by the remaining run budget. Google and Microsoft HTTP clients close
on success, errors, timeout, and cancellation, reject redirects, cap response data at 2 MiB, and never
retry automatically. `GoogleAPIError.status_code` and `MicrosoftGraphError.status_code` expose HTTP
failures without copying remote error bodies into exceptions.

IMAP/SMTP operations run on worker threads with fresh connections, closed after each operation.
`timeout_seconds=15` on `IMAPEmail` bounds individual socket operations; the tool factory's timeout
bounds the overall await. Cancellation interrupts an established socket. DNS/connection setup can
finish later; workers check cancellation before login and writes, including after connection setup.
A timed-out/canceled write may already have occurred remotely: inspect the calendar/mailbox before
retrying. Provider errors do not imply an unchanged account.

Service content is untrusted data and can enter model history and reports. Apply the existing run/store
redaction policy for sensitive application data. Configured tool closures, tokens, backends, and question
callbacks are not restored from dict/YAML. Load with `Agent.from_dict/from_yaml`, then re-register the
configured factories; the simple parameterless built-ins keep their existing round-trip behavior.

## Examples

| Example | Coverage |
| --- | --- |
| [`generic_tools.py`](https://github.com/nMaroulis/protolink/blob/main/examples/generic_tools.py) | Filesystem reads/search/edits/recovery, storage CRUD, HTTP, CSV extraction/search, and real SQLite on one ordinary Agent |
| [`builtin_assistants.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_assistants.py) | Shell, all six Git operations, model question/answer continuation, in-memory calendar/email, clock, and calculator |
| [`service_backends.py`](https://github.com/nMaroulis/protolink/blob/main/examples/service_backends.py) | Google Calendar, Gmail, Outlook Calendar, Outlook Email, and IMAP/SMTP using offline transport fixtures |
| [`builtin_web_search.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_web_search.py) | Public web search with explicit engine selection and policy; a query performs network requests |

```bash
python examples/builtin_assistants.py
pip install 'protolink[integrations]'
python examples/generic_tools.py
python examples/service_backends.py
```

The first three examples use temporary/local resources or mock transports without external accounts
or real email delivery. Their automatic approval callbacks are specific to those demonstrations.
Real PDF/DOCX/XLSX parsing is also covered by the document-format regression tests. The web search
example prints help without network requests when run without a query.
