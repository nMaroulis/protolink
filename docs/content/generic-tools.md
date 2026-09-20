# General-purpose built-in tools

These factories provide capabilities developers can compose into any `Agent`: filesystem access,
JSON storage, HTTP requests, document extraction, and database queries. They do not select a role,
model, workflow, or application data model. Import them from `protolink.tools` or
`protolink.tools.builtins` and register each returned tool on your agent.

```python
from protolink import Agent, AgentCard, CapabilityPolicy
from protolink.storage import InMemoryStorage
from protolink.tools import filesystem_tools, storage_tools

agent = Agent(
    AgentCard(name="app", description="Application tools", url="runtime://app"),
    policy=CapabilityPolicy({"filesystem.read": "allow", "storage.read": "allow"}, default_effect="deny"),
)
for tool in (
    *filesystem_tools(roots=["/absolute/workspace"]),
    *storage_tools(InMemoryStorage(namespace="application-values")),
):
    agent.add_tool(tool)

result = await agent.call_tool("read_file", path="/absolute/workspace/README.md")
```

No LLM is required for `call_tool`. Add your model for inference. All factories return native
prepared tools: direct calls fail closed, and execution uses validation, capabilities, approvals,
budgets, and events. Ordinary `Agent` policy is allow-by-default; configure it explicitly.
Credentials and configured backends stay outside tool arguments and must be reattached after
Agent restoration. Tool arguments/results may appear in model history and reports.

| Factory | Default tools | Optional dependencies |
| --- | --- | --- |
| `filesystem_tools(roots=...)` | `read_file`, `list_files`, `search_files` | None; POSIX required |
| `storage_tools(storage)` | `get_value`, `list_keys` | None |
| `http_tool(base_url)` | `http_request` with GET/HEAD | `integrations` (HTTPX) |
| `document_tools(roots=...)` | `read_document`, `search_document` | `documents` for PDF/DOCX/XLSX; POSIX required |
| `database_tools(backend)` | `database_schema`, `query_database` | None for `SQLiteDatabase` |

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
existing recovery identifiers. See [filesystem changes and restoration](execution-tools.md#filesystem-changes-and-restoration).

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

## Complete offline example

```bash
pip install 'protolink[integrations]'
python examples/generic_tools.py
```

[`generic_tools.py`](https://github.com/nMaroulis/protolink/blob/main/examples/generic_tools.py) exercises
all five families on an ordinary `Agent`: file reads/search/edits/recovery, storage CRUD, HTTP reads
and writes through a mock transport, CSV extraction/search, and real SQLite operations. It checks
approvals with temporary resources and a demo-specific automatic approval callback. No model,
account, network socket, or production database is used.
