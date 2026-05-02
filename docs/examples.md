# Examples

This section links to example projects and code snippets in the repository.

!!! tip "New here?"
    Start with the **Jupyter Notebooks** in `examples/notebooks/basic_example`! They provide the easiest and best interactive introduction to running the Registry and Agents.

## Jupyter Notebooks (Recommended)

The best way to get started is by running the interactive notebooks in [`examples/notebooks/basic_example`](https://github.com/nMaroulis/protolink/tree/main/examples/notebooks/basic_example). These notebooks teach you the core concepts of Protolink through a complete multi-agent system:

### 🎯 What You'll Learn

- **Registry Setup**: How to run a central discovery service for agents
- **Agent Creation**: Building agents with tools and task handling
- **Agent Communication**: How agents discover and communicate with each other
- **Transport Configuration**: Using HTTP transport for agent-to-agent messaging
- **Tool Integration**: Adding native tools to agents using decorators

### 📚 Notebook Sequence

Run these notebooks in order to build a complete weather monitoring system:

#### 1. **[`registry.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/registry.ipynb)** - Start the Registry
- Sets up the central discovery service on `localhost:9010`
- Exposes REST API endpoints for agent registration and discovery
- Provides a web interface at `/status` to view registered agents

#### 2. **[`weather_agent.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/weather_agent.ipynb)** - Create a Data Provider
- Builds an agent that provides mock weather data
- Demonstrates tool creation with the `@tool` decorator
- Shows agent registration and task handling patterns
- Runs on `localhost:8010`

#### 3. **[`alert_agent.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/alert_agent.ipynb)** - Create a Consumer Agent
- Builds an agent that processes weather data and sends alerts
- Demonstrates agent-to-agent communication via the registry
- Shows different transport configuration patterns
- Runs on `localhost:8020`

### 🏗️ System Architecture

```
┌─────────────────┐    HTTP REST API   ┌─────────────────┐
│   Registry      │◄──────────────────►│  Alert Agent    │
│  (localhost:    │                    │  (localhost:    │
│   9010)         │                    │   8020)         │
└─────────────────┘                    └─────────────────┘
         ▲                                   ▲
         │                                   │
         │ HTTP REST API                     │ HTTP REST API
         │                                   │
┌─────────────────┐                    ┌─────────────────┐
│ Weather Agent   │◄──────────────────►│  Alert Agent    │
│ (localhost:     │                    │                 │
│  8010)          │                    │                 │
└─────────────────┘                    └─────────────────┘
```

### 🚀 Quick Start

1. **Start the Registry** (run `registry.ipynb` first)
2. **Start the Weather Agent** (run `weather_agent.ipynb`)
3. **Start the Alert Agent** (run `alert_agent.ipynb`)
4. **Test the System**: Visit `http://localhost:9010/status` to see all registered agents

### 💡 Key Concepts Demonstrated

- **Transport Flexibility**: Use transport strings (`"http"`) or `HTTPTransport` instances
- **Registry Patterns**: Pass registry as URL string or `Registry` object
- **Tool Creation**: Native tools with automatic schema inference
- **Task Handling**: Implement `handle_task` for processing incoming tasks
- **Agent Discovery**: Find and communicate with other agents via the registry



## Example Scripts

The repository includes several **standalone example scripts** that demonstrate specific Protolink capabilities:

### 📝 [`basic_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/basic_agent.py)
**Purpose**: Minimal agent setup focused on core concepts

- Demonstrates simplified agent creation using dictionary-based `AgentCard`
- Shows how to add native tools using the `@agent.tool` decorator with automatic schema inference
- Demonstrates direct agent invocation using convenience methods: `invoke()` and `invoke_sync()`
- Includes optional LLM integration for reasoning and inference
- Uses `runtime` transport for in-memory execution (no network dependencies)

### 🌐 [`http_agents.py`](https://github.com/nMaroulis/protolink/blob/main/examples/http_agents.py)
**Purpose**: HTTP transport and agent-to-agent communication

- Demonstrates two agents communicating over HTTP
- Tests client functions: `get_agent_card`, `send_message_to`, `call_agent`
- Shows how to set up multiple agents on different ports
- Includes comprehensive error handling and cleanup

### 🤖 [`llms.py`](https://github.com/nMaroulis/protolink/blob/main/examples/llms.py)
**Purpose**: LLM backend integration and testing
- Tests OpenAI and Anthropic LLM implementations
- Demonstrates both streaming and non-streaming responses
- Safe import pattern for optional dependencies
- Command-line interface for testing specific backends

### 📋 [`registry.py`](https://github.com/nMaroulis/protolink/blob/main/examples/registry.py)
**Purpose**: Registry discovery and autonomous agent behaviour

- Creates autonomous agents that discover peers and send tasks
- Demonstrates registry-based agent discovery
- Shows background task management and cleanup
- Multi-agent orchestration with automatic peer communication

### ⚡ [`runtime_agents.py`](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_agents.py)
**Purpose**: In-memory agent communication interoperability

- Uses explicitly mapped URL `RuntimeTransport` instances for agent-to-agent communication without HTTP configuration
- Demonstrates safe registry discovery enabling native message parsing safely inside isolated testing contexts
- Shows how to build reliable agent networks safely running within a single process retaining production semantics
- Useful for test pipelines scaling native workflow isolation

### 📡 [`streaming_agent.py`](https://github.com/nMaroulis/protolink/blob/main/examples/streaming_agent.py)
**Purpose**: Real-time streaming with progress updates (v0.2.0+)

- Demonstrates streaming task handlers with progress events
- Shows artifact production and streaming
- Context management for multi-turn conversations
- Event-driven architecture with task status updates

### 🔌 [`websocket_basic_example.py`](https://github.com/nMaroulis/protolink/blob/main/examples/websocket_basic_example.py)
**Purpose**: WebSocket transport with streaming support

- Mirrors the basic notebook example but uses WebSocket transport
- Demonstrates both request/response and streaming task patterns
- Shows registry discovery over WebSockets
- Real-time progress updates via WebSocket events
