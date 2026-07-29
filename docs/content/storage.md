import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Storage

ProtoLink provides pluggable storage for Agent state, process-local caches, and
durable execution records. Persistence depends on the selected backend:
`SQLiteStorage` survives restarts, while `InMemoryStorage` intentionally does
not.

## Storage Types

Protolink currently supports the following storage implementations:

- **`SQLiteStorage`** - namespaced JSON key/value persistence in a local
  SQLite database.
- **`InMemoryStorage`** - process-local object storage with optional sliding
  time-to-live expiration.
- **`SQLiteRunStore`** - indexed task snapshots and run reports for replay,
  audit, and regression workflows.

You can implement a custom state backend by subclassing `Storage`, or implement
the structural `RunStore` protocol when execution records belong in an
application database.

## Configuration

Using storage with an agent is straightforward:

1. **Instantiate the Storage implementation**:

   ```python
   from protolink.storage import SQLiteStorage

   storage = SQLiteStorage(
       db_path="agent_memory.db",
       namespace="my_agent"
   )
   ```

2. **Pass the Storage instance to your Agent**:

   ```python
   from protolink.agents import Agent
   from protolink.models import AgentCard

   agent_card = AgentCard(
       url="http://localhost:8020",
       name="memory_agent",
       description="Agent with long-term memory"
   )

   agent = Agent(
       card=agent_card,
       transport="http",
       storage=storage,
       state=["conversation"]  # Enables persistence for specific modules
   )
   ```

:::tip[Namespacing]

The `namespace` parameter in `SQLiteStorage` allows you to isolate data for different agents or contexts within the same database file.

:::
---

## Storage API Reference

This section provides a detailed API reference for the Storage module.

:::tip[Unified Storage Interface]

**Protolink provides a consistent CRUD interface for all storage backends.** Whether you are using SQLite, a cloud database, or a simple JSON file, you interact with them through the same standard methods: `save()`, `load()`, `update()`, and `delete()`.

:::

<ApiSurface
  eyebrow="Persistence module"
  title="Storage"
  path="protolink.storage"
  description="The storage surfaces used for namespaced Agent state, process-local TTL values, registry persistence, and indexed execution records."
  pills={[
    "CRUD interface",
    "SQLite implementation",
    "In-memory TTL",
    "Namespaced data",
    "Durable run records",
    "Custom backends",
  ]}
  cards={[
    {
      title: "Base class",
      text: "Defines the common save, load, update, and delete contract for storage backends.",
      code: "Storage",
    },
    {
      title: "SQLite",
      text: "Persists JSON-serialized data under a namespace inside a local SQLite database.",
      code: "SQLiteStorage",
    },
    {
      title: "Memory",
      text: "Keeps arbitrary Python objects in-process with optional sliding expiration.",
      code: "InMemoryStorage",
    },
    {
      title: "Run records",
      text: "Indexes task snapshots and normalized run reports separately from agent state.",
      code: "SQLiteRunStore",
    },
    {
      title: "Agent state",
      text: "Automatically persists conversation history and gives the other state modules a shared storage extension point.",
      code: "state=[...]",
    },
  ]}
/>

## Generic storage contract

### Storage

<ApiReference
  kind="abstract class"
  path="protolink.storage.Storage"
  signature={`class Storage`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/base.py#L7"
>

Define the synchronous, single-value persistence contract used by ProtoLink
state modules. A storage instance represents one logical namespace: callers save
or replace its complete value, load it, or delete it.

<ApiSection title="Abstract methods">
  <ApiFields ariaLabel="Storage abstract methods">
    <ApiField name="save" type="(data: Any) -> None">
      Persist a complete namespace value.
    </ApiField>
    <ApiField name="load" type="() -> Any">
      Return the stored value, normally <code>None</code> when absent.
    </ApiField>
    <ApiField name="update" type="(data: Any) -> None">
      Replace or otherwise update the namespace according to backend semantics.
    </ApiField>
    <ApiField name="delete" type="() -> None">
      Remove the namespace value.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Synchronous interface">
  These methods are ordinary blocking functions. A database or network-backed
  custom implementation should manage blocking I/O appropriately when called
  from an asynchronous Agent.
</ApiCallout>

</ApiReference>

### Storage.save

<ApiReference
  kind="abstract method"
  path="protolink.storage.Storage.save"
  signature={`save(
    data: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/base.py#L16"
>

Persist the supplied value as the current contents of this storage namespace.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Storage.save parameters">
    <ApiField name="data" type="Any" required>
      Backend-specific value. Implementations decide whether it must be
      serializable, whether it is copied, and whether saving replaces existing
      data.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Storage.save return value">
    <ApiField name="None" type="None">
      Persistence is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Storage.load

<ApiReference
  kind="abstract method"
  path="protolink.storage.Storage.load"
  signature={`load() -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/base.py#L25"
>

Load the current namespace value.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Storage.load return value">
    <ApiField name="data" type="Any">
      Backend-specific value, conventionally <code>None</code> when no value is
      stored. The interface cannot distinguish an absent value from an
      explicitly stored <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Storage.update

<ApiReference
  kind="abstract method"
  path="protolink.storage.Storage.update"
  signature={`update(
    data: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/base.py#L34"
>

Update the namespace using backend-specific semantics. Both built-in
implementations make this exactly equivalent to `save()`; it is not a partial
dictionary merge.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Storage.update parameters">
    <ApiField name="data" type="Any" required>
      New complete value for the built-in backends.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Storage.update return value">
    <ApiField name="None" type="None">
      Updating is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Storage.delete

<ApiReference
  kind="abstract method"
  path="protolink.storage.Storage.delete"
  signature={`delete() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/base.py#L43"
>

Remove the current namespace value.

<ApiSection title="Returns">
  <ApiFields ariaLabel="Storage.delete return value">
    <ApiField name="None" type="None">
      Built-in deletion is idempotent: deleting a missing namespace is not an
      error.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## SQLite key/value storage

### SQLiteStorage

<ApiReference
  kind="class"
  path="protolink.storage.SQLiteStorage"
  signature={`class SQLiteStorage(
    db_path: str = "storage.db",
    table_name: str = "storage",
    namespace: str = "default",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/sqlite.py#L11"
>

Persist one JSON-serializable value per namespace in a small SQLite table.
Construction validates the table identifier, opens or creates the database, and
creates the table when it is missing.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteStorage constructor parameters">
    <ApiField name="db_path" type="str" defaultValue={'"storage.db"'}>
      SQLite database path. SQLite creates the file when possible; the parent
      directory itself is not created by this class.
    </ApiField>
    <ApiField name="table_name" type="str" defaultValue={'"storage"'}>
      Table containing <code>key</code> and JSON <code>value</code> columns.
      It must satisfy Python's <code>str.isidentifier()</code> check before it
      is interpolated into SQL.
    </ApiField>
    <ApiField name="namespace" type="str" defaultValue={'"default"'}>
      Primary key for this storage instance's value. Multiple instances can
      share a database and table while using different namespaces.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="SQLiteStorage attributes">
    <ApiField name="db_path" type="str">
      Configured database path.
    </ApiField>
    <ApiField name="table_name" type="str">
      Validated table identifier.
    </ApiField>
    <ApiField name="namespace" type="str">
      Active row key.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteStorage constructor errors">
    <ApiField name="ValueError">
      Raised for a table name that is not a valid Python identifier.
    </ApiField>
    <ApiField name="sqlite3.Error">
      Database creation, connection, schema, permission, and locking errors
      propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Connection model">
  Construction and every CRUD call open a short-lived SQLite connection.
  ProtoLink does not configure busy timeouts, WAL mode, migrations, encryption,
  or cross-process coordination for this minimal adapter.
</ApiCallout>

</ApiReference>

### SQLiteStorage.save

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteStorage.save"
  signature={`save(
    data: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/sqlite.py#L53"
>

JSON-encode a value and insert or replace the row for the active namespace.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteStorage.save parameters">
    <ApiField name="data" type="Any" required>
      Value accepted by Python's <code>json.dumps()</code>. Tuple and other JSON
      conversions follow standard-library behavior.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteStorage.save return value">
    <ApiField name="None" type="None">
      The transaction is committed before the method returns.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteStorage.save errors">
    <ApiField name="TypeError / ValueError">
      JSON serialization errors propagate before the database write.
    </ApiField>
    <ApiField name="sqlite3.Error">
      Connection, locking, statement, and commit errors propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteStorage.load

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteStorage.load"
  signature={`load() -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/sqlite.py#L66"
>

Read and JSON-decode the current namespace row.

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteStorage.load return value">
    <ApiField name="data" type="Any">
      Deserialized JSON value, or <code>None</code> when the namespace has no
      row. An explicitly saved JSON <code>null</code> also loads as
      <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteStorage.load errors">
    <ApiField name="json.JSONDecodeError">
      Raised if another writer or manual edit stored invalid JSON.
    </ApiField>
    <ApiField name="sqlite3.Error">
      Database connection and query errors propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteStorage.update

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteStorage.update"
  signature={`update(
    data: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/sqlite.py#L79"
>

Replace the namespace value by calling `save(data)`. The operation is an upsert,
so it also creates a row that does not already exist.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteStorage.update parameters">
    <ApiField name="data" type="Any" required>
      Complete JSON-serializable replacement value.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteStorage.update return value">
    <ApiField name="None" type="None">
      Returns after the delegated save transaction commits.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteStorage.delete

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteStorage.delete"
  signature={`delete() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/sqlite.py#L86"
>

Delete the row for the active namespace and commit the transaction.

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteStorage.delete return value">
    <ApiField name="None" type="None">
      Missing rows are ignored, making deletion idempotent.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteStorage.delete errors">
    <ApiField name="sqlite3.Error">
      Connection, locking, statement, and commit errors propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## In-memory storage

### InMemoryStorage

<ApiReference
  kind="class"
  path="protolink.storage.InMemoryStorage"
  signature={`class InMemoryStorage(
    namespace: str = "default",
    ttl: int | None = None,
    store: dict[str, tuple[Any, float]] | None = None,
    ttl_heap: list[tuple[float, str]] | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/memory.py#L10"
>

Keep arbitrary Python objects in a dictionary-backed namespace. Loads use
sliding expiration: a successful access refreshes the entry timestamp and
pushes a new expiration marker when TTL is enabled.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="InMemoryStorage constructor parameters">
    <ApiField name="namespace" type="str" defaultValue={'"default"'}>
      Dictionary key owned by this wrapper.
    </ApiField>
    <ApiField name="ttl" type="int | None" defaultValue="None">
      Sliding lifetime in seconds. <code>None</code> disables expiration.
      Values are stored without validation, so zero or negative values expire
      on the next sufficiently later access.
    </ApiField>
    <ApiField name="store" type="dict[str, tuple[Any, float]] | None" defaultValue="None">
      Optional backing dictionary of values and last-touch timestamps. When
      omitted, all default instances share a class-level process store.
    </ApiField>
    <ApiField name="ttl_heap" type="list[tuple[float, str]] | None" defaultValue="None">
      Optional min-heap of expiration timestamps and namespaces. Pair a custom
      store with its own heap whenever TTL is enabled; otherwise save/load
      markers for the custom store enter the unrelated class-global heap.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="InMemoryStorage attributes">
    <ApiField name="namespace" type="str">
      Active dictionary key.
    </ApiField>
    <ApiField name="ttl" type="int | None">
      Sliding expiration configured on this wrapper.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Shared objects and TTLs">
  Values are stored and returned by reference, not copied. The default backing
  dictionary and heap are shared across instances and are not synchronized for
  concurrent threads. <code>cleanup_expired()</code> applies the calling
  instance's TTL while inspecting the shared heap, so instances sharing a
  backing store should use one consistent TTL policy.
</ApiCallout>

</ApiReference>

### InMemoryStorage.save

<ApiReference
  kind="method"
  path="protolink.storage.InMemoryStorage.save"
  signature={`save(
    data: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/memory.py#L59"
>

Store the object reference with the current wall-clock timestamp and, when TTL
is enabled, push its calculated expiration onto the heap.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="InMemoryStorage.save parameters">
    <ApiField name="data" type="Any" required>
      Any Python object. No serialization or copy is performed.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="InMemoryStorage.save return value">
    <ApiField name="None" type="None">
      Existing namespace values are replaced.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### InMemoryStorage.load

<ApiReference
  kind="method"
  path="protolink.storage.InMemoryStorage.load"
  signature={`load() -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/memory.py#L72"
>

Return the current object when present and unexpired. Successful reads refresh
the timestamp, making the configured TTL idle-based rather than a fixed
time-since-save limit.

<ApiSection title="Returns">
  <ApiFields ariaLabel="InMemoryStorage.load return value">
    <ApiField name="data" type="Any">
      The exact stored object reference, or <code>None</code> when missing or
      expired. An expired entry is removed lazily.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Touch semantics">
  Every successful load rewrites the entry timestamp. With TTL enabled it also
  adds a new heap marker; stale older markers are discarded later by
  <code>cleanup_expired()</code>.
</ApiCallout>

</ApiReference>

### InMemoryStorage.update

<ApiReference
  kind="method"
  path="protolink.storage.InMemoryStorage.update"
  signature={`update(
    data: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/memory.py#L100"
>

Replace or create the namespace value through `save(data)`, resetting its last
touch and expiration marker.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="InMemoryStorage.update parameters">
    <ApiField name="data" type="Any" required>
      Complete replacement object.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="InMemoryStorage.update return value">
    <ApiField name="None" type="None">
      The method has the same side effects as <code>save()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### InMemoryStorage.delete

<ApiReference
  kind="method"
  path="protolink.storage.InMemoryStorage.delete"
  signature={`delete() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/memory.py#L112"
>

Remove the active namespace from the backing dictionary.

<ApiSection title="Returns">
  <ApiFields ariaLabel="InMemoryStorage.delete return value">
    <ApiField name="None" type="None">
      Missing namespaces are ignored. Existing heap markers are left in place
      and discarded as stale during future cleanup.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### InMemoryStorage.cleanup_expired

<ApiReference
  kind="method"
  path="protolink.storage.InMemoryStorage.cleanup_expired"
  signature={`cleanup_expired() -> int`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/memory.py#L119"
>

Pop elapsed heap markers and proactively remove entries whose latest stored
timestamp is also older than the calling instance's TTL.

<ApiSection title="Returns">
  <ApiFields ariaLabel="InMemoryStorage.cleanup_expired return value">
    <ApiField name="removed" type="int">
      Number of backing-store entries deleted. Returns zero when the heap is
      empty, TTL is disabled on the caller, or only stale markers were found.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Complexity">
  <ApiFields ariaLabel="InMemoryStorage.cleanup_expired complexity">
    <ApiField name="time" type="O(M log N)">
      <code>M</code> is the number of elapsed heap markers and
      <code>N</code> is heap size.
    </ApiField>
    <ApiField name="space" type="O(N)">
      Repeated touches can temporarily create multiple markers for one
      namespace.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Durable execution records

Generic `Storage` holds the current value for one state namespace. `RunStore`
solves a different problem: it preserves indexed task snapshots and normalized
run reports so an application can retrieve, replay, compare, or audit past
executions.

:::tip[View runs in Devtools]

Open a local run store with `protolink dashboard --store runs.db --open`.

:::

### TaskRecord

<ApiReference
  kind="frozen dataclass"
  path="protolink.storage.TaskRecord"
  signature={`class TaskRecord(
    task_id: str,
    state: str,
    run_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    agent_name: str | None = None,
    task: dict[str, Any] = field(default_factory=dict),
    metadata: dict[str, Any] = field(default_factory=dict),
    created_at: str | None = None,
    updated_at: str = field(default_factory=utc_now),
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L24"
>

Represent the searchable index fields and serialized payload for one persisted
task snapshot.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="TaskRecord constructor parameters">
    <ApiField name="task_id" type="str" required>
      Stable task identifier and SQLite primary key.
    </ApiField>
    <ApiField name="state" type="str" required>
      Serialized task lifecycle state.
    </ApiField>
    <ApiField name="run_id" type="str | None" defaultValue="None">
      Correlated logical execution run.
    </ApiField>
    <ApiField name="session_id" type="str | None" defaultValue="None">
      Correlated application or conversation session.
    </ApiField>
    <ApiField name="trace_id" type="str | None" defaultValue="None">
      Correlated observability trace.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Agent name supplied when the snapshot was saved.
    </ApiField>
    <ApiField name="task" type="dict[str, Any]" defaultValue="{}">
      Serialized <code>Task.to_dict()</code> payload.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Caller-owned index-record metadata, separate from fields inside the task.
    </ApiField>
    <ApiField name="created_at" type="str | None" defaultValue="None">
      Timestamp copied from the task when available.
    </ApiField>
    <ApiField name="updated_at" type="str" defaultValue="utc_now()">
      Timestamp of this persisted snapshot.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Shallow immutability">
  Field assignment is blocked, but the nested <code>task</code> and
  <code>metadata</code> dictionaries remain mutable.
</ApiCallout>

</ApiReference>

### TaskRecord.to_dict

<ApiReference
  kind="method"
  path="protolink.storage.TaskRecord.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L51"
>

Return all task-record fields in a serialization-friendly mapping.

<ApiSection title="Returns">
  <ApiFields ariaLabel="TaskRecord.to_dict return value">
    <ApiField name="record" type="dict[str, Any]">
      New outer dictionary containing the ten record fields. Nested task and
      metadata dictionaries are reused rather than deep-copied.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RunReportRecord

<ApiReference
  kind="frozen dataclass"
  path="protolink.storage.RunReportRecord"
  signature={`class RunReportRecord(
    run_id: str,
    session_id: str | None = None,
    trace_id: str | None = None,
    agent_name: str | None = None,
    report: dict[str, Any] = field(default_factory=dict),
    metadata: dict[str, Any] = field(default_factory=dict),
    created_at: str = field(default_factory=utc_now),
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L68"
>

Represent the indexed identity and serialized payload for one persisted
`RunReport`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="RunReportRecord constructor parameters">
    <ApiField name="run_id" type="str" required>
      Logical run identifier and SQLite primary key.
    </ApiField>
    <ApiField name="session_id" type="str | None" defaultValue="None">
      Session copied from the report context when available.
    </ApiField>
    <ApiField name="trace_id" type="str | None" defaultValue="None">
      Trace copied from the report context when available.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Agent name supplied by the saving application.
    </ApiField>
    <ApiField name="report" type="dict[str, Any]" defaultValue="{}">
      Serialized <code>RunReport.to_dict()</code> payload.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any]" defaultValue="{}">
      Caller-owned record metadata.
    </ApiField>
    <ApiField name="created_at" type="str" defaultValue="utc_now()">
      Timestamp at which the record was persisted.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Shallow immutability">
  The record is frozen, while its nested report and metadata dictionaries remain
  mutable references.
</ApiCallout>

</ApiReference>

### RunReportRecord.to_dict

<ApiReference
  kind="method"
  path="protolink.storage.RunReportRecord.to_dict"
  signature={`to_dict() -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L79"
>

Return all run-report record fields in a new outer mapping.

<ApiSection title="Returns">
  <ApiFields ariaLabel="RunReportRecord.to_dict return value">
    <ApiField name="record" type="dict[str, Any]">
      Mapping containing run/session/trace/agent identity, report payload,
      metadata, and creation time. Nested mappings are not deep-copied.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### RunStore

<ApiReference
  kind="protocol"
  path="protolink.storage.RunStore"
  signature={`class RunStore(Protocol)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L92"
>

Define the structural interface an Agent can use for durable task and report
records. Implementations do not need to inherit from this protocol, and the
protocol itself cannot be instantiated.

<ApiSection title="Task methods">
  <ApiFields ariaLabel="RunStore task methods">
    <ApiField name="save_task" type="(Task, *, context=None, agent_name=None, metadata=None) -> TaskRecord">
      Persist or replace a task snapshot.
    </ApiField>
    <ApiField name="get_task" type="(task_id: str) -> Task | None">
      Reconstruct a task payload by ID.
    </ApiField>
    <ApiField name="get_task_record" type="(task_id: str) -> TaskRecord | None">
      Load the serialized record and index metadata by ID.
    </ApiField>
    <ApiField name="list_task_records" type="(*, limit=100, session_id=None, run_id=None, state=None, agent_name=None) -> list[TaskRecord]">
      Query recent task records using optional indexed filters.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Report methods">
  <ApiFields ariaLabel="RunStore report methods">
    <ApiField name="save_report" type="(RunReport, *, run_id=None, agent_name=None, metadata=None) -> RunReportRecord">
      Persist or replace a normalized run report.
    </ApiField>
    <ApiField name="get_report" type="(run_id: str) -> RunReport | None">
      Reconstruct a report by run ID.
    </ApiField>
    <ApiField name="get_report_record" type="(run_id: str) -> RunReportRecord | None">
      Load the serialized report record by ID.
    </ApiField>
    <ApiField name="list_report_records" type="(*, limit=100, session_id=None, agent_name=None) -> list[RunReportRecord]">
      Query recent report records using optional indexed filters.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Protocol scope">
  Deletion is not required by <code>RunStore</code>.
  <code>SQLiteRunStore</code> adds <code>delete_task()</code> and
  <code>delete_report()</code> as concrete administrative extensions.
</ApiCallout>

</ApiReference>

### SQLiteRunStore

<ApiReference
  kind="class"
  path="protolink.storage.SQLiteRunStore"
  signature={`class SQLiteRunStore(
    db_path: str | Path = "runs.db",
    *,
    table_prefix: str = "protolink",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L156"
>

Implement `RunStore` with two SQLite tables: one for task snapshots and one for
run reports. JSON payload columns retain complete serialized objects, while
relational columns index common lookup fields.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore constructor parameters">
    <ApiField name="db_path" type="str | Path" defaultValue={'"runs.db"'}>
      SQLite database path, converted to <code>str</code>. The database file and
      schema are created when missing; parent directories are not created.
    </ApiField>
    <ApiField name="table_prefix" type="str" defaultValue={'"protolink"'}>
      Prefix used to create <code>&lt;prefix&gt;_tasks</code> and
      <code>&lt;prefix&gt;_run_reports</code>. It must satisfy
      <code>str.isidentifier()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Attributes">
  <ApiFields ariaLabel="SQLiteRunStore attributes">
    <ApiField name="db_path" type="str">
      Normalized database path.
    </ApiField>
    <ApiField name="table_prefix" type="str">
      Validated table prefix.
    </ApiField>
    <ApiField name="tasks_table" type="str">
      Resolved task table name.
    </ApiField>
    <ApiField name="reports_table" type="str">
      Resolved run-report table name.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteRunStore constructor errors">
    <ApiField name="ValueError">
      Raised for an invalid table-prefix identifier.
    </ApiField>
    <ApiField name="sqlite3.Error">
      Connection, schema creation, index creation, permission, and locking
      errors propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Replacement semantics">
  Tasks are keyed by <code>task_id</code> and reports by <code>run_id</code>.
  Saves use SQLite <code>INSERT OR REPLACE</code>, so a repeated identifier
  replaces the full prior row.
</ApiCallout>

</ApiReference>

### SQLiteRunStore.save_task

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.save_task"
  signature={`save_task(
    task: Task,
    *,
    context: RunContext | None = None,
    agent_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskRecord`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L230"
>

Serialize and upsert one task snapshot together with indexed run correlation.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.save_task parameters">
    <ApiField name="task" type="Task" required>
      Task whose ID, state, creation time, and complete
      <code>to_dict()</code> payload are persisted.
    </ApiField>
    <ApiField name="context" type="RunContext | None" defaultValue="None">
      Explicit run/session/trace source. When omitted,
      <code>RunContext.from_task(task)</code> derives one from task metadata.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Optional indexed agent identity.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional record metadata. A shallow dictionary copy is made before
      serialization.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.save_task return value">
    <ApiField name="record" type="TaskRecord">
      Frozen record matching the row that was committed.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteRunStore.save_task errors">
    <ApiField name="serialization error">
      Errors from task serialization or <code>json.dumps()</code> propagate.
    </ApiField>
    <ApiField name="sqlite3.Error">
      Connection, statement, locking, and commit errors propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.get_task

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.get_task"
  signature={`get_task(
    task_id: str,
) -> Task | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L278"
>

Load a task record and reconstruct its domain model.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.get_task parameters">
    <ApiField name="task_id" type="str" required>
      Primary-key identifier.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.get_task return value">
    <ApiField name="task" type="Task | None">
      <code>Task.from_dict(record.task)</code>, or <code>None</code> when no
      row exists.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteRunStore.get_task errors">
    <ApiField name="deserialization or sqlite error">
      Invalid stored JSON/task payloads and database failures propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.get_task_record

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.get_task_record"
  signature={`get_task_record(
    task_id: str,
) -> TaskRecord | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L283"
>

Load the indexed record without reconstructing a `Task`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.get_task_record parameters">
    <ApiField name="task_id" type="str" required>
      Primary-key identifier.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.get_task_record return value">
    <ApiField name="record" type="TaskRecord | None">
      Parsed task record, or <code>None</code> when absent.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.list_task_records

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.list_task_records"
  signature={`list_task_records(
    *,
    limit: int = 100,
    session_id: str | None = None,
    run_id: str | None = None,
    state: str | TaskState | None = None,
    agent_name: str | None = None,
) -> list[TaskRecord]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L289"
>

Query task records with conjunctive optional filters, ordered by newest
`updated_at` first.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.list_task_records parameters">
    <ApiField name="limit" type="int" defaultValue="100">
      SQLite result limit. Values are not validated; zero returns no rows and
      SQLite treats a negative limit as unbounded.
    </ApiField>
    <ApiField name="session_id" type="str | None" defaultValue="None">
      Match one session exactly.
    </ApiField>
    <ApiField name="run_id" type="str | None" defaultValue="None">
      Match one run exactly.
    </ApiField>
    <ApiField name="state" type="str | TaskState | None" defaultValue="None">
      Match the enum's <code>.value</code> or the string representation of the
      supplied value.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Match one stored agent name exactly.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.list_task_records return value">
    <ApiField name="records" type="list[TaskRecord]">
      Matching records in descending lexicographic ISO timestamp order.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.save_report

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.save_report"
  signature={`save_report(
    report: RunReport,
    *,
    run_id: str | None = None,
    agent_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RunReportRecord`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L323"
>

Serialize and upsert one complete run report.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.save_report parameters">
    <ApiField name="report" type="RunReport" required>
      Report serialized through <code>to_dict()</code>. Its context supplies
      session and trace index fields when present.
    </ApiField>
    <ApiField name="run_id" type="str | None" defaultValue="None">
      Optional primary-key override. When omitted, the report context's run ID
      is used.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Optional indexed agent identity.
    </ApiField>
    <ApiField name="metadata" type="dict[str, Any] | None" defaultValue="None">
      Optional record metadata, shallow-copied before serialization.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.save_report return value">
    <ApiField name="record" type="RunReportRecord">
      Frozen record matching the committed row.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="SQLiteRunStore.save_report errors">
    <ApiField name="ValueError">
      Raised when neither an explicit run ID nor a report-context run ID is
      available.
    </ApiField>
    <ApiField name="serialization or sqlite error">
      Report serialization, JSON encoding, database, and commit errors
      propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Run ID override">
  An explicit <code>run_id</code> changes the record key; it does not rewrite
  the run ID already serialized inside the report payload.
</ApiCallout>

</ApiReference>

### SQLiteRunStore.get_report

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.get_report"
  signature={`get_report(
    run_id: str,
) -> RunReport | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L367"
>

Load a report record and reconstruct the `RunReport`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.get_report parameters">
    <ApiField name="run_id" type="str" required>
      Primary-key identifier.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.get_report return value">
    <ApiField name="report" type="RunReport | None">
      <code>RunReport.from_dict(record.report)</code>, or <code>None</code> when
      absent.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.get_report_record

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.get_report_record"
  signature={`get_report_record(
    run_id: str,
) -> RunReportRecord | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L372"
>

Load the indexed and serialized record without reconstructing a `RunReport`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.get_report_record parameters">
    <ApiField name="run_id" type="str" required>
      Primary-key identifier.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.get_report_record return value">
    <ApiField name="record" type="RunReportRecord | None">
      Parsed record, or <code>None</code> when absent.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.list_report_records

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.list_report_records"
  signature={`list_report_records(
    *,
    limit: int = 100,
    session_id: str | None = None,
    agent_name: str | None = None,
) -> list[RunReportRecord]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L378"
>

Query recent run-report records with optional session and agent filters.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.list_report_records parameters">
    <ApiField name="limit" type="int" defaultValue="100">
      SQLite result limit; it is not range-validated.
    </ApiField>
    <ApiField name="session_id" type="str | None" defaultValue="None">
      Match one session exactly.
    </ApiField>
    <ApiField name="agent_name" type="str | None" defaultValue="None">
      Match one agent name exactly.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.list_report_records return value">
    <ApiField name="records" type="list[RunReportRecord]">
      Matching records ordered by newest <code>created_at</code> first.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.delete_task

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.delete_task"
  signature={`delete_task(
    task_id: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L403"
>

Delete one task snapshot by primary key.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.delete_task parameters">
    <ApiField name="task_id" type="str" required>
      Task identifier to remove.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.delete_task return value">
    <ApiField name="None" type="None">
      The transaction commits even when no matching row existed.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### SQLiteRunStore.delete_report

<ApiReference
  kind="method"
  path="protolink.storage.SQLiteRunStore.delete_report"
  signature={`delete_report(
    run_id: str,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/storage/run_store.py#L409"
>

Delete one run report by primary key.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="SQLiteRunStore.delete_report parameters">
    <ApiField name="run_id" type="str" required>
      Run identifier to remove.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="SQLiteRunStore.delete_report return value">
    <ApiField name="None" type="None">
      The transaction commits even when no matching row existed.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

---

## Usage Examples

### Standalone Usage

You can use the storage module independently of the agent system.

```python
from protolink.storage import SQLiteStorage

# Initialize storage
storage = SQLiteStorage(db_path="data.db", namespace="user_settings")

# Save some data
settings = {"theme": "dark", "notifications": True}
storage.save(settings)

# Load data later
loaded_settings = storage.load()
print(loaded_settings["theme"])  # Output: dark

# Update data
loaded_settings["notifications"] = False
storage.update(loaded_settings)

# Delete data
storage.delete()
```

### In-Memory TTL Usage

`InMemoryStorage` is useful when state should disappear with the process or
after a period of inactivity:

```python
from protolink.storage import InMemoryStorage

cache = InMemoryStorage(namespace="session-42", ttl=300)
cache.save({"messages": 4})

# A successful load refreshes the five-minute idle timeout.
value = cache.load()

# Use the same backing store, heap, and TTL policy when pruning shared entries.
removed = cache.cleanup_expired()
```

### Durable Run Records

Use `SQLiteRunStore` for execution history rather than mutable Agent state:

```python
from protolink import Message, RunContext, Task
from protolink.storage import SQLiteRunStore

run_store = SQLiteRunStore("runs.db")
task = Task.create(
    Message(role="user").add_text("prepare the release notes")
)
context = RunContext(run_id="release-2026-07", session_id="release")

record = run_store.save_task(
    task,
    context=context,
    agent_name="release-writer",
    metadata={"environment": "staging"},
)

recent = run_store.list_task_records(session_id="release", limit=20)
```

### Agent Memory Integration

Agents can use the storage field to persist their state, conversation context, or learned information.

```python
from protolink.agents import Agent
from protolink.storage import SQLiteStorage

class PersistentAgent(Agent):
    async def handle_task(self, task):
        # Load previous state
        state = self.storage.load() or {"count": 0}
        
        # Increment a counter
        state["count"] += 1
        
        # Save updated state
        self.storage.save(state)
        
        return await super().handle_task(task)
```

### State System Integration (v0.5.5+)

Starting with version **v0.5.5**, ProtoLink includes a unified **State** system.
When you provide a `storage` instance and enable `conversation`, the
conversation module automatically performs whole-payload `load()` and `save()`
operations. The `tools`, `task`, and `flow` modules currently expose
storage-backed extension points; applications define their own persistence
conventions on top.

| Module | Storage Usage |
|--------|---------------|
| **conversation** | Stores a serialized map of `session_id` to `ConversationHistory` lists. |
| **tools** | Retains the shared Storage reference but currently exposes no public persistence methods. |
| **task** | Retains the shared Storage reference but currently exposes no public persistence methods. |
| **flow** | `to_dict()` reads the shared storage payload; applications own any write/checkpoint convention. |

This high-level system is the **recommended way** to manage LLM conversation
persistence. Enabled modules currently receive the same `Storage` object rather
than hidden per-module namespaces, so applications combining module-specific
data should partition it explicitly.

## Error Handling

Storage errors are intentionally visible to the caller:

- **Connection and SQL errors**: context managers close short-lived SQLite
  connections, but `sqlite3.Error` subclasses still propagate.
- **Serialization errors**: non-JSON-serializable data raises from
  `json.dumps()` before the write commits.
- **Deserialization errors**: malformed stored JSON raises from `json.loads()`.
- **File permissions and missing parent directories**: both SQLite adapters
  rely on the configured path being writable; neither creates parent
  directories.
- **Concurrent writes**: SQLite locking and busy errors are not retried by the
  storage classes.
