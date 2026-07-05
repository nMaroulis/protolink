import ApiSurface from '@site/src/components/ApiSurface';

# Storage

Protolink provides a pluggable storage system to act as a persistent memory for agents or to be used as a standalone module.

## Storage Types

Protolink currently supports the following storage implementations:

- **SQLiteStorage** - A local, file-based storage using SQLite. Ideal for persistence across restarts without requiring external database servers.

You can also implement your own storage backend by subclassing the `Storage` base class.

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
  description="The small persistence abstraction used by agents, state modules, registries, and applications that need durable local memory without coupling to one database."
  pills={[
    "CRUD interface",
    "SQLite implementation",
    "Namespaced data",
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
      title: "Agent state",
      text: "Backs conversation, tool, task, and flow state when persistence is enabled.",
      code: "state=[...]",
    },
  ]}
/>

### Base Storage Class

`protolink.storage.base.Storage`

The `Storage` class is an abstract base class (ABC) that defines the interface for all storage implementations.

#### Core Methods

All methods are abstract and must be implemented by subclasses.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `save()` | `data: Any` | `None` | Saves data to the storage. Structure depends on implementation. |
| `load()` | - | `Any` | Loads data from the storage. Returns `None` if no data is found. |
| `update()` | `data: Any` | `None` | Updates existing data in the storage. |
| `delete()` | - | `None` | Deletes the data from the storage. |

### SQLiteStorage

`protolink.storage.sqlite.SQLiteStorage`

A concrete implementation of `Storage` using SQLite. Data is serialized to strings (typically JSON) before being stored in the database.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `db_path` | `str` | `"storage.db"` | Path to the SQLite database file. Created automatically if it doesn't exist. |
| `table_name` | `str` | `"storage"` | Name of the table used for storing data. |
| `namespace` | `str` | `"default"` | Unique identifier (key) for this storage instance's data. |

#### Implementation Details

- **Serialization**: Currently uses `json.dumps()` and `json.loads()` for data persistence.
- **Persistence**: Data is keyed by the `namespace` in a simple Key-Value table.
- **Automatic Setup**: The database file and table are created automatically upon initialization.

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

Starting with version **v0.5.5**, Protolink includes a unified **State** system that automatically manages persistence for various agent modules. When you provide a `storage` instance and enable specific `state` modules, the `State` orchestrator handles the lower-level `load()` and `save()` operations for you.

| Module | Storage Usage |
|--------|---------------|
| **conversation** | Stores a serialized map of `session_id` to `ConversationHistory` lists. |
| **tools** | Provides a storage-backed extension point for tool-specific state. |
| **task** | Provides a storage-backed extension point for task metadata outside the live `Task` object. |
| **flow** | Stores flow context when applications choose to checkpoint structured workflows. |

This high-level system is the **recommended way** to manage LLM conversation persistence. For tool, task, and flow persistence, treat the modules as shared storage foundations and define application-specific conventions on top.

## Error Handling

Implementations of storage should handle common database errors:

- **Connection Errors**: Handled internally by `SQLiteStorage` using context managers.
- **Serialization Errors**: If `data` is not JSON-serializable, `SQLiteStorage.save()` will raise a `TypeError`.
- **File System Permissions**: Ensure the process has write access to the `db_path` directory.
