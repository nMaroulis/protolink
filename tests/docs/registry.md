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
| `start()` | `background: bool = False` | `None` | Starts the Registry runtime. Can run in the main loop or as an isolated background thread. |
| `stop()` | — | `None` | Stops the Registry runtime and synchronously cleans up resources. |

### Execution Models & Lifecycle

Similar to agents, the Registry's lifecycle management is designed for "minimal boilerplate" and robust background execution across all environments (scripts, async apps, notebooks).

#### The `background` Parameter

- **`background=True`**: Starts the registry in a dedicated background thread with its own isolated `asyncio` event loop and returns immediately. Because it uses a separate thread, it prevents event loop collisions and allows you to easily shut it down later using the synchronous `.stop()` method without any `await` syntax.
- **`background=False` (Default)**: Blocks the main thread's execution until the registry is stopped (e.g., via Ctrl+C). Ideal for standalone registry processes.

#### Common Usage Patterns

**1. Standalone Registry Service**
```python
from protolink.discovery.registry import Registry
registry = Registry(url="http://localhost:9000")

# Blocks and runs the registry server
registry.start()
```

**2. Multi-Agent Orchestration**
```python
registry.start(background=True)
agent.start(background=True)

# ... run your logic ...

# Synchronous, graceful teardown. No async/await boilerplate needed!
agent.stop()
registry.stop()
```

**3. Jupyter Notebooks & Async Contexts**
```python
# Safe to use in an existing async loop
registry.start(background=True) 
```

!!! tip "Graceful Shutdown"
    Always use `registry.stop()` to cleanly shut down the server and release ports. In blocking scripts, `registry.start(background=False)` handles `KeyboardInterrupt` automatically.

---

## Discovery Performance

The Registry is optimized for high-throughput environments where hundreds or thousands of agents may be registered simultaneously.

### Secondary Indexing

To avoid linear scans ($O(N)$) during discovery, the Registry maintains internal **secondary indexes** for common filter fields:

- **Agent Name**: Exact matches are resolved in $O(1)$.
- **Agent Role**: Role-based discovery is resolved in $O(1)$.
- **Tags**: Filtering by tag is resolved in $O(1)$.

When multiple filters are applied (e.g., `role="worker"` AND `tags=["finance"]`), the Registry performs **set intersections** on these indexes, drastically reducing the search space to $O(K)$ candidates where $K$ is the number of agents matching the filters.

### Robust Fallback

While the Registry relies on indexes for speed, it includes a **robust fallback mechanism**. If a discovery query uses non-indexed fields or if the internal indexes are bypassed (e.g., during manual testing), the Registry automatically falls back to a linear scan to ensure no results are missed.

---

### Constructor Parameters

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
