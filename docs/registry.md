# Registry

The **Registry** is the discovery and coordination layer of Protolink.  
It allows agents to **register themselves**, **discover other agents**, and **interact autonomously** over a shared transport.

At a high level:

- Agents **announce their existence** to a Registry
- Other agents can **discover agents dynamically**
- The Registry runs as a **server** and exposes a transport-backed API
- Agents can operate **autonomously**, without manual function calls

!!! success "Why a Registry?"
    The Registry enables **dynamic, decentralized agent systems**.  
    Agents don’t need hard-coded references to each other — they discover peers at runtime and coordinate through messages.

!!! info "Inspiration"
    The Registry is inspired by [Google's A2A paper](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/), which introduces a similar concept for agent-to-agent discovery.

## Core Concepts

### Registry

The Registry is a **long-running service** responsible for:

- Tracking active agents
- Storing their `AgentCard` metadata
- Exposing discovery endpoints via a transport
- Acting as the entry point for multi-agent systems

The Registry does **not execute agent logic**.  
It only provides **discovery, metadata, and routing primitives**.

---

### Agent Registration

Each agent registers itself by sending its `AgentCard` to the Registry when it starts.

An `AgentCard` typically includes:

- Agent name
- Description
- Capabilities / skills
- Transport URL
- Optional metadata

Once registered, the agent becomes discoverable by other agents.

!!! note "Dynamic Systems"
    Agents may join or leave at any time.  
    The Registry reflects the current state of the system dynamically.

---

### Agent Discovery

Agents query the Registry to discover other agents.

Discovery supports **optional filtering**, for example:

- By name
- By capability
- By arbitrary metadata

```python
agents = await registry.discover(filters={
    "capability": "search",
    "domain": "finance"
})
```

# Registry

The **Registry** is the discovery and coordination layer of Protolink.  
It allows agents to **register themselves**, **discover other agents**, and **interact autonomously** over a shared transport.

At a high level:

- Agents **announce their existence** to a Registry
- Other agents can **discover agents dynamically**
- The Registry runs as a **server** and exposes a transport-backed API
- Agents can operate **autonomously**, without manual function calls

!!! success "Why a Registry?"
    The Registry enables **dynamic, decentralized agent systems**.  
    Agents don’t need hard-coded references to each other — they discover peers at runtime and coordinate through messages.

---

## Core Concepts

### Registry

The Registry is a **long-running service** responsible for:

- Tracking active agents
- Storing their `AgentCard` metadata
- Exposing discovery endpoints via a transport
- Acting as the entry point for multi-agent systems

The Registry does **not execute agent logic**.  
It only provides **discovery, metadata, and routing primitives**.

---

### Agent Registration

Each agent registers itself by sending its `AgentCard` to the Registry when it starts.

An `AgentCard` typically includes:

- Agent name
- Description
- Capabilities / skills
- Transport URL
- Optional metadata

Once registered, the agent becomes discoverable by other agents.

!!! note "Dynamic Systems"
    Agents may join or leave at any time.  
    The Registry reflects the current state of the system dynamically.

---

### Agent Discovery

Agents query the Registry to discover other agents.

Discovery supports **optional filtering**, for example:

- By name
- By capability
- By arbitrary metadata

```python
agents = await registry.discover(filters={
    "capability": "search",
    "domain": "finance"
})
```

!!! tip "Filters are Optional"
    Calling discover() with no filters returns all registered agents.


### Transport Integration

The Registry is transport-agnostic.
It relies on a Transport implementation to expose its API.

Currently supported:

- HTTPTransport

The transport is responsible for:

- Binding to a host and port
- Exposing registry endpoints
- Handling request/response lifecycle

---

### Starting the Registry

The Registry is started via its transport

```python
from protolink.registry import Registry
from protolink.transport import HTTPTransport

transport = HTTPTransport(host="0.0.0.0", port=8000)
registry = Registry(transport)

await registry.start()
```

This starts a registry server that agents can connect to.
!!! info "Single Source of Truth"
    The Registry’s public URL is derived from the transport and used by agents for registration and discovery.

---

### URL Handling

Both **Agents** and the **Registry** expose a url property.

- The Transport owns host and port
- The url is a derived, canonical representation

To avoid duplication, transports provide helpers to **derive host and port from a URL**.

```python
transport = HTTPTransport.from_url("http://localhost:8000")
```

This ensures consistent configuration across agents and registry instances.
