!!! tip "Filters are Optional"
    Calling discover() with no filters returns all registered agents.

### Transport Integration

The Registry is transport-agnostic. It relies on a Transport implementation to expose its API.

Currently supported:
- `HTTPTransport` (via `protolink.transport.HTTPTransport`)

The transport is responsible for:
- Binding to a host and port
- Exposing registry endpoints
- Handling request/response lifecycle

---

## Lifecycle Methods

These methods control the registry server component lifecycle.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `start()` | `background: bool = False` | `asyncio.Task ⎪ None` | Starts the Registry runtime. Automatically detects environment and event loops. |
| `stop()` | — | `None` | Stops the Registry runtime and cleans up resources. |

### Execution Models: Adaptive `start()`

Similar to agents, the Registry's `start()` method is **environment-aware**. It detects whether it is running in a script, an async app, or a notebook.

#### The `background` Parameter

- **`background=False` (Default)**: Blocks execution until the registry is stopped (e.g., via Ctrl+C). Ideal for standalone registry processes.
- **`background=True`**: Starts the registry in the background and returns immediately. Ideal for orchestrating a system in a single script.

#### Common Usage Patterns

**1. Standalone Registry Service**
```python
from protolink.discovery.registry import Registry
registry = Registry(url="http://localhost:9000")

# Blocks and runs the registry server
registry.start()
```

**2. Multi-Agent Orchestration (Sync Script)**
```python
registry.start(background=True)
agent_a.start(background=True)
agent_b.start(background=False) # Blocks here to keep the process alive
```

**3. Jupyter Notebooks**
```python
# In a Jupyter cell
registry.start() # Returns an asyncio.Task immediately and runs in background
```

!!! tip "Graceful Shutdown"
    Use `registry.stop()` to cleanly shut down the server. In blocking scripts, `registry.start()` handles `KeyboardInterrupt` automatically.

---


#### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `transport` | `TransportType ⎪ Transport` | `"http"` | Transport instance or type string. |
| `url` | `str ⎪ None` | `None` | Registry URL (used when transport is a string type). |
| `verbosity` | `Literal[0, 1, 2]` | `1` | Logging verbosity: `0` = silent (WARNING), `1` = normal (INFO), `2` = verbose (DEBUG). |

!!! info "Single Source of Truth"
    The Registry’s public URL is derived from the transport and used by agents for registration and discovery.

---

### URL Handling

Both **Agents** and the **Registry** expose a url property.

- The Transport owns host and port
- The url is a derived, canonical representation

To avoid duplication, transports provide helpers to **derive host and port from a URL**.

```python
transport = HTTPTransport(url="http://localhost:8000")
```

This ensures consistent configuration across agents and registry instances.
