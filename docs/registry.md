# Registry

The Registry is Protolink's discovery service. Agents register their `AgentCard` with it, and other agents query it to find peers by name, role, tags, capabilities, or other card metadata.

Use a registry when agents should discover each other dynamically instead of hard-coding every peer URL.

## Quick Start

```python
from protolink.discovery import Registry

registry = Registry(url="http://localhost:9000", transport="http")
registry.start(background=True)

# ...start agents that use this registry...

registry.stop()
```

Agents can receive the live `Registry` object directly:

```python
from protolink.agents import Agent

agent = Agent(
    card=card,
    transport="http",
    registry=registry,
)
```

Or they can connect to a registry by transport type and URL:

```python
from protolink.agents import Agent

agent = Agent(
    card=card,
    transport="http",
    registry="http",
    registry_url="http://localhost:9000",
    registry_heartbeat_interval=15,
)
```

!!! tip "Filters are optional"
    Calling `discover()` with no filters returns all registered agents.

## Discovery

```python
cards = await registry.discover({"name": "weather_agent"})
cards = await registry.discover({"role": "worker"})
cards = await registry.discover({"tags": ["weather", "forecast"]})
```

Discovery returns `AgentCard` objects. The same filter shape is available through `Agent.discover_agents()` and `RegistryClient.discover()`.

## Transport Integration

The Registry is transport-agnostic. It relies on a Transport implementation to expose its API.

Currently supported by the default runtime path:

- `HTTPTransport` via `transport="http"`

The transport is responsible for:

- Binding to a host and port
- Exposing registry endpoints
- Handling request/response lifecycle

## Lifecycle Methods

These methods control the registry server component lifecycle.

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `start()` | `background: bool = False` | `None` | Starts the Registry runtime. Can run in the main loop or as an isolated background thread. |
| `stop()` | - | `None` | Stops the Registry runtime and synchronously cleans up resources. |

### Execution Models

- **`background=True`** starts the registry in a dedicated background thread with its own isolated `asyncio` event loop and returns immediately. Use this for examples, notebooks, tests, and multi-agent scripts.
- **`background=False`** blocks the main thread until the registry is stopped. Use this for a standalone registry process.

### Common Usage Patterns

**Standalone registry service**

```python
from protolink.discovery import Registry

registry = Registry(url="http://localhost:9000", transport="http")
registry.start()
```

**Multi-agent orchestration**

```python
registry.start(background=True)
agent.start(background=True)

# ...run your orchestration...

agent.stop()
registry.stop()
```

!!! tip "Graceful shutdown"
    Always use `registry.stop()` to cleanly shut down the server and release ports. In blocking scripts, `registry.start(background=False)` handles `KeyboardInterrupt` automatically.

## Discovery Performance

The Registry is optimized for high-throughput environments where many agents may be registered simultaneously.

### Secondary Indexing

To avoid linear scans during common discovery queries, the Registry maintains secondary indexes for:

- **Agent name**
- **Agent role**
- **Tags**

When multiple indexed filters are applied, the Registry performs set intersections and then refines matches for any non-indexed fields.

### Robust Fallback

If a query uses non-indexed fields, or if the indexed path returns no candidates while agents are still present, the Registry falls back to a full scan to preserve correctness.

## Liveness And Persistence

By default, the registry is an in-memory discovery service. For longer-running systems, two optional knobs make it more robust:

- `entry_ttl_seconds` prunes agents whose `last_seen` timestamp is older than the configured TTL.
- `storage` persists registered entries through the generic `Storage` interface, so a registry can rebuild its in-memory indexes after restart.

Agents can keep their entry fresh by setting `registry_heartbeat_interval` on the Agent. After successful registration, the agent periodically calls `RegistryClient.heartbeat(agent_url)`. Heartbeats update liveness metadata only; they do not mutate the agent card or discovery indexes.

```python
from protolink import Agent, AgentCard
from protolink.discovery import Registry
from protolink.storage import SQLiteStorage

registry = Registry(
    url="http://localhost:9000",
    transport="http",
    entry_ttl_seconds=45,
    storage=SQLiteStorage("registry.db", namespace="registry"),
)

agent = Agent(
    AgentCard(name="worker", description="Worker", url="http://localhost:9010"),
    transport="http",
    registry="http",
    registry_url="http://localhost:9000",
    registry_heartbeat_interval=15,
)
```

The public registry API now includes:

| Method | Purpose |
|------|-------------|
| `register(card)` | Add or replace an agent card and update secondary indexes. |
| `heartbeat(agent_url)` | Refresh `last_seen` for a registered agent. |
| `unregister(agent_url)` | Remove an agent and its indexes. |
| `discover(filter_by=None)` | Return live agent cards, pruning expired entries first. |

## Constructor

```python
Registry(
    transport: TransportType | Transport = "http",
    url: str | None = None,
    verbosity: Literal[0, 1, 2] = 1,
    *,
    entry_ttl_seconds: float | None = None,
    storage: Storage | None = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `transport` | `TransportType | Transport` | `"http"` | Transport instance or registered transport string. |
| `url` | `str | None` | `None` | Registry URL. Required when `transport` is a string. |
| `verbosity` | `Literal[0, 1, 2]` | `1` | Logging verbosity: `0` = warning, `1` = info, `2` = debug. |
| `entry_ttl_seconds` | `float | None` | `None` | Optional liveness TTL. Expired entries are pruned before discovery, status, and count/list operations. |
| `storage` | `Storage | None` | `None` | Optional persistence for serialized registry entries. |

!!! info "Single source of truth"
    The Registry's public URL is derived from its transport and used by agents for registration and discovery.

## URL Handling

Both Agents and the Registry expose a `url` property through their transport.

```python
from protolink.transport import HTTPTransport

transport = HTTPTransport(url="http://localhost:9000")
registry = Registry(transport=transport)
```

This keeps host, port, transport, and discovery metadata consistent across agent and registry instances.
