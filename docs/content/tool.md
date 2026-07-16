import ApiSurface from '@site/src/components/ApiSurface';

# Tools

Tools extend agent capabilities with additional functions. They enable LLMs and agents to interact with external systems, execute code, access data, and perform specialized tasks that go beyond pure text generation.

## Overview

Protolink provides a flexible tool system with three approaches:

- **Built-in Tools**: Opt-in, dependency-free factories for common read-only and pure operations
- **Native Tools**: Python functions decorated directly on an agent
- **MCP Tools**: Tools from external MCP (Model Context Protocol) servers

All three tool sources use the same interface, making them interchangeable from the agent's perspective.

## Module Structure

The tools module is organized as follows:

```python
# Core interfaces and opt-in built-ins
from protolink.tools import (
    BaseTool,
    Tool,
    calculator,
    current_datetime,
    fetch_url,
    web_search,
)

# Tool adapters for external integrations  
from protolink.tools.adapters import MCPToolAdapter
```

| Module | Description |
|--------|-------------|
| `protolink.tools` | Core interfaces, native implementation, and public built-in factories |
| `protolink.tools.builtins` | Implementations for the dependency-free built-in tools |
| `protolink.tools.adapters` | Adapters for integrating external tool systems |

---

<ApiSurface
  eyebrow="Tool module"
  title="Tools"
  path="protolink.tools"
  description="The callable capability layer for native Python functions, MCP-backed tools, JSON schemas, examples, capability policies, and approval-aware action metadata."
  pills={[
    "Native decorators",
    "MCP adapters",
    "Schema inference",
    "Capability enforcement",
    "AgentSkill advertising",
  ]}
  cards={[
    {
      title: "Built-in tools",
      text: "Explicitly register dependency-free web search, safe URL fetch, calculator, and current-datetime tools.",
      code: "agent.add_tool(web_search())",
    },
    {
      title: "Base contract",
      text: "Tools are async callables with a name, description, input schema, output schema, tags, examples, and capabilities.",
      code: "BaseTool",
    },
    {
      title: "Native tools",
      text: "Register typed Python functions directly on an agent and let Protolink infer schemas.",
      code: "@agent.tool",
    },
    {
      title: "MCP tools",
      text: "Adapt tools from Model Context Protocol servers into the same runtime interface.",
      code: "MCPToolAdapter",
    },
    {
      title: "Policy hooks",
      text: "Attach capabilities and action builders so runtime policy can allow, deny, or request approval.",
      code: "capabilities",
    },
  ]}
/>

## BaseTool Protocol

All tools in Protolink conform to the `BaseTool` protocol, which defines the minimal interface for a tool:

```python
from collections.abc import Collection
from typing import Any, Protocol

class BaseTool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    tags: list[str] | None
    examples: list[Any] | None
    capabilities: Collection[str] | None

    async def __call__(self, **kwargs) -> Any: ...
```

### Protocol Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier for the tool |
| `description` | `str` | Human-readable description of what the tool does |
| `input_schema` | `dict[str, Any] ⎪ None` | JSON Schema object for accepted keyword arguments |
| `output_schema` | `dict[str, Any] ⎪ None` | JSON Schema object for the returned value |
| `tags` | `list[str] ⎪ None` | Categorization tags for filtering and discovery |
| `examples` | `list[Any] ⎪ None` | Example inputs, outputs, or usage scenarios advertised on `AgentSkill` |
| `capabilities` | `Collection[str] ⎪ None` | Permission capabilities evaluated before execution |

### The `__call__` Method

All tools are **async callables** that accept keyword arguments matching their input schema:

```python
# Tools are invoked with keyword arguments
result = await tool(location="Tokyo", units="celsius")
```

---

## Built-in Tools

ProtoLink includes four dependency-free tool factories for common agent tasks:

| Factory | Tool name | Capability | Stable result |
|---------|-----------|------------|---------------|
| `web_search()` | `web_search` | `network.read` | Query, provider, ranked source snippets with sponsored labels, availability hint, and `untrusted_content` marker |
| `fetch_url()` | `fetch_url` | `network.read` | Final URL, status, content type, title, text, truncation state, and `untrusted_content` marker |
| `calculator()` | `calculator` | None | The expression and its finite numeric result |
| `current_datetime()` | `current_datetime` | None | Timezone, ISO-8601 date/time, weekday, UTC offset, and Unix timestamp |

Factories return fresh native `Tool` instances. Nothing is enabled automatically: register only the capabilities an agent needs.

```python
from protolink import Agent, AgentCard, CapabilityPolicy
from protolink.tools import calculator, current_datetime, fetch_url, web_search

agent = Agent(
    card=AgentCard(
        name="researcher",
        description="Finds and summarizes public information",
        url="runtime://researcher",
    ),
    transport="runtime",
    policy=CapabilityPolicy(
        {"network.read": "allow"},
        default_effect="deny",
    ),
)

agent.add_tool(web_search())
agent.add_tool(fetch_url())
agent.add_tool(calculator())
agent.add_tool(current_datetime())
```

Registered tools participate in schema validation, runtime policy, and AgentSkill advertising. When the inference loop invokes one during a task, the task's cancellation, telemetry, and tool-call budget controls apply as well. `network.read` identifies the authority required by `web_search` and `fetch_url`; `calculator` and `current_datetime` declare no protected capability.

:::warning[Default policy and direct calls]

The default `CapabilityPolicy` is allow-by-default for backward compatibility. Declaring `network.read` makes authority visible and configurable, but does not deny it by itself. Pass a restrictive policy when network access should be denied or approval-gated.

Calling a `Tool` object directly, such as `await web_search()(query="...")`, invokes the tool without the Agent and therefore bypasses Agent policy and approval. Use `agent.call_tool(...)` for Agent validation and policy, or let the inference loop invoke a registered tool when the task's full runtime controls should apply.

Agent dict/YAML serialization preserves each built-in's stable identity and the declarative rules, default effect, and name of ProtoLink's first-party `CapabilityPolicy`. Custom policy implementations and approval callbacks are executable application objects and are not embedded; pass them explicitly when restoring, for example `Agent.from_yaml("agent.yaml", policy=custom_policy, approval_handler=approve)`. An explicit policy override takes precedence over serialized first-party policy data.

:::

### Web Search

`web_search()` has one normalized result contract across two explicit engines:

- `engine="brave"` is the default. It uses the [Brave Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get) and reads `BRAVE_SEARCH_API_KEY` from the environment only when invoked. The key is not captured by the Tool, stored in Agent configuration, or required merely to import or register the factory.
- `engine="duckduckgo"` needs no API key or additional dependency. It reads DuckDuckGo's published [non-JavaScript HTML search](https://duckduckgo.com/duckduckgo-help-pages/features/non-javascript) as a best-effort interface.

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
    query="Python structured concurrency",
    engine="duckduckgo",
    freshness="month",
)
```

For a complete Agent-path CLI, see [`examples/builtin_web_search.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_web_search.py). It registers the built-in with an explicit `network.read` policy, supports both engines and every freshness option, and prints the normalized JSON result:

```bash
# Keyless, best-effort DuckDuckGo search
python examples/builtin_web_search.py "Python structured concurrency"

# Documented Brave API
export BRAVE_SEARCH_API_KEY="your-key"
python examples/builtin_web_search.py "Python structured concurrency" --engine brave
```

Running the example without a query only prints its CLI help, so it is safe to inspect without credentials or a network request.

| Argument | Type | Default | Contract |
|----------|------|---------|----------|
| `query` | `str` | Required | 1-400 characters and at most 50 words |
| `max_results` | `int` | `5` | 1-10 normalized results |
| `freshness` | `"any" ⎪ "day" ⎪ "week" ⎪ "month" ⎪ "year"` | `"any"` | Optional age filter sent to the selected engine |
| `engine` | `"brave" ⎪ "duckduckgo"` | `"brave"` | Explicit provider selection; DuckDuckGo is keyless |

The tool normalizes both engines into provider-neutral JSON-compatible data and bounds the result count and text placed into model context. Every result includes `sponsored`; Brave web results use `False`, while recognized DuckDuckGo advertisements stay in provider order with `sponsored=True`. Both engines use fixed HTTPS endpoints with DNS validation, a 2,000,000-byte response limit, a 10-second transport deadline, and no redirects. DuckDuckGo organic redirect links are decoded locally and validated; sponsored click URLs remain intact. Results also include the selected `provider`, `more_results_available`, and the explicit marker `untrusted_content=True`.

DuckDuckGo's HTML page is a human-facing interface rather than a versioned developer API. It can change markup, rate-limit automated requests, or return a human-verification challenge. ProtoLink does not spoof a browser, suppress or discard recognized advertising, retry a challenge, or attempt to bypass one; it raises a clear error. Applications distributing a DuckDuckGo-backed integration should review DuckDuckGo's [URL-parameter and partnership guidance](https://duckduckgo.com/duckduckgo-help-pages/settings/params). Use Brave when a documented, production-oriented provider contract is required. With either engine, search queries leave the process, and titles, URLs, snippets, and page content are untrusted external data. Do not treat search output as instructions, executable content, or proof that a claim is correct.

### URL Fetch

`fetch_url()` retrieves bounded textual content from a public HTTP or HTTPS URL. It rejects credentials in URLs, non-HTTP schemes, and private, loopback, link-local, reserved, or otherwise non-public targets. Redirect destinations are resolved and validated again before they are followed. Responses are subject to redirect, timeout, byte, character, and supported-text-content limits; the result reports when extracted text was truncated.

```python
page = await agent.call_tool("fetch_url", url="https://example.com/")
```

| Argument | Type | Default | Contract |
|----------|------|---------|----------|
| `url` | `str` | Required | Public HTTP(S) URL, at most 2,048 characters, using its standard port |
| `max_chars` | `int` | `12000` | 1-50,000 returned text characters |

After each destination is DNS-validated, the transfer is limited to 1,000,000 bytes, four validated redirects, and a 10-second transport deadline for each request or redirect before the `max_chars` return bound is applied. DNS lookup uses the host operating system's resolver and is not included in that transport deadline. These restrictions reduce accidental server-side request forgery and context exhaustion; they do not make remote content trustworthy. Treat returned text as untrusted input and keep application-specific authorization at the Agent policy boundary.

### Calculator and Current Datetime

`calculator()` evaluates a deliberately small arithmetic grammar rather than Python code. It never uses `eval`, rejects names and function calls, and enforces expression-complexity, exponent, magnitude, and finite-result limits.

`current_datetime()` returns structured current-time data for the requested timezone. UTC works without a host timezone database; other IANA zones use the system database, or the `tzdata` package when a host does not provide one. Invalid or unavailable timezone identifiers raise a clear tool error rather than silently falling back to local machine time.

```python
calculation = await calculator()(expression="(18 + 6) / 3")
now = await current_datetime()(timezone="Europe/Zurich")
```

| Tool | Argument contract |
|------|-------------------|
| `calculator` | Required `expression`: 1-256 characters using numbers, parentheses, and `+`, `-`, `*`, `/`, `//`, `%`, or `**` |
| `current_datetime` | Optional `timezone`: IANA timezone name up to 100 characters; defaults to `"UTC"` |

---

## Native Tools

**Native tools** are regular Python callables that you register on an agent. They are exposed over the transport so that other agents (or clients) can invoke them.

### Registering Native Tools

To register a native tool, **decorate** an async function with `@agent.tool`:

```python
from protolink.agents import Agent
from protolink.models import AgentCard

agent_card = AgentCard(
    url="http://localhost:8020",
    name="calculator_agent", 
    description="Agent with math tools"
)
agent = Agent(card=agent_card, transport="http")

@agent.tool(name="add", description="Add two numbers together")
async def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


@agent.tool(name="multiply", description="Multiply two numbers")
async def multiply_numbers(a: float, b: float) -> float:
    """Multiply two numbers and return the result."""
    return a * b

# Inferred Schemas:
# input_schema: {
#     "type": "object",
#     "properties": {
#         "a": {"type": "integer"},
#         "b": {"type": "integer"}
#     },
#     "required": ["a", "b"],
#     "additionalProperties": False
# }
# output_schema: {"type": "integer"}
```

### Decorator Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | The tool's identifier (used in tool calls) |
| `description` | `str` | Description shown to the LLM for tool selection |
| `input_schema` | `dict[str, Any] ⎪ None` | Optional explicit JSON Schema. If omitted, Protolink infers it from type hints. Legacy `{name: type}` maps are still accepted and normalized. |
| `output_schema` | `dict[str, Any] ⎪ None` | Optional explicit JSON Schema. If omitted, Protolink infers it from the return type hint. |
| `tags` | `list[str]` | Optional categorization tags |
| `examples` | `list[Any]` | Optional examples copied to the advertised `AgentSkill` |
| `capabilities` | `Collection[str]` | Optional capability names enforced before execution |
| `action_builder` | `Callable` | Optional action factory for metadata and approval preview artifacts |

### JSON Schema and Runtime Validation

Tool schemas are first-class JSON Schema objects. Native tools infer nested schemas from Python type hints, dataclasses, enums, typed dictionaries, and Pydantic models. Before execution, Protolink validates and lightly coerces tool arguments against the schema, then applies Python annotation validation where available.

```python
from pydantic import BaseModel, Field

class BookingRequest(BaseModel):
    location: str
    guests: int = Field(gt=0)

@agent.tool(
    name="book_hotel",
    description="Book a hotel",
    examples=[{"booking": {"location": "Athens", "guests": 2}}],
)
async def book_hotel(booking: BookingRequest) -> dict[str, str]:
    return {"location": booking.location, "status": "confirmed"}
```

The inferred input schema is a JSON Schema object with a nested `booking` property. Runtime calls such as `{"booking": {"location": "Athens", "guests": "2"}}` are coerced before the function receives a `BookingRequest` instance. Missing required fields, unexpected fields, invalid enums, and incompatible scalar values return a structured tool error instead of reaching user code.

### Capabilities And Approval

Declare capabilities for operations that should participate in runtime policy. Capability names are extensible strings rather than a fixed coding or filesystem taxonomy.

```python
from protolink import Agent, ApprovalDecision, CapabilityPolicy

async def approve(request, context):
    return ApprovalDecision(approved=True, request_id=request.request_id)

agent = Agent(
    card,
    policy=CapabilityPolicy({"records.write": "require_approval"}),
    approval_handler=approve,
)

@agent.tool(
    name="publish_record",
    description="Publish one record",
    capabilities=["records.write"],
)
async def publish_record(record_id: str) -> dict[str, str]:
    return {"record_id": record_id, "status": "published"}
```

Policy is evaluated after argument validation and immediately before the callable runs. See [Runtime](runtime.md#capability-policy) for wildcard rules, `RunContext.permissions`, approval handlers, and preview artifacts.

Use `agent.call_tool_in_context(name, context, **arguments)` when a deterministic application path invokes a tool directly and needs the same per-run permissions, cancellation, and approval behavior as task execution.

### Tool Cancellation

Tools invoked by a running task participate in that task's live cancellation automatically. Protolink checks the token before authorization, before calling the tool, and after the awaited result returns. It also cancels the owning task, so an async tool normally receives `asyncio.CancelledError` at its current `await` point.

```python
@agent.tool(name="build_report", description="Build a report in stages")
async def build_report() -> str:
    data = await load_data()
    report = await render_report(data)
    await commit_report(report)
    return "committed"
```

Cancellation can interrupt the first two awaits, but it cannot undo a commit that an external system already accepted. Side-effecting tools should therefore delay irreversible commits, use transactional APIs, or forward cancellation to a subprocess or remote service that supports it.

Synchronous Python tools cannot be forcibly stopped safely. If they run on the event-loop thread, the cancellation request is processed only after they return. If an application moves them to a worker thread, the event loop remains responsive but the thread itself may continue. These limits are why Protolink defines cancellation as best-effort rather than a rollback guarantee.

### When to Use Native Tools

Native tools are ideal for:

- **Business logic**: Domain-specific operations like order processing, data validation
- **Data access**: Database queries, API calls, file operations
- **Computation**: Complex calculations, data transformations
- **System integration**: Interacting with internal services

---

## Tool Tags

Tools can be categorized using tags for better organization and discovery:

```python
@agent.tool(
    name="calculate", 
    description="Performs arithmetic calculations", 
    tags=["math", "utility"]
)
async def calculate(operation: str, a: float, b: float) -> float:
    """Perform basic arithmetic operations."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    else:
        raise ValueError(f"Unsupported operation: {operation}")


@agent.tool(
    name="search_documents", 
    description="Search internal documents", 
    tags=["search", "documents", "rag"]
)
async def search_documents(query: str, limit: int = 10) -> list[dict]:
    """Search the document database."""
    # Implementation here
    pass
```

Tags are automatically propagated to the agent's skills and can be used for:

- **Filtering**: Find tools by category
- **Discovery**: Help users understand available capabilities
- **Organization**: Group related tools together

---

## MCP Tools

Protolink integrates seamlessly with **MCP (Model Context Protocol)** servers, allowing you to use tools from external MCP-compatible services as if they were native tools.

### What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard for connecting AI assistants to external tools and data sources. MCP servers can be:

- Local Python scripts running as subprocesses
- Remote web services exposing SSE endpoints
- Third-party tool providers

### MCPToolAdapter

The `MCPToolAdapter` class connects to MCP servers and exposes their tools as callables compatible with Protolink's `BaseTool` protocol.

#### Supported Transports

| Transport | Description | Use Case |
|-----------|-------------|----------|
| `stdio` | Local subprocess via stdin/stdout | Local Python/Node.js MCP servers |
| `sse` | Server-Sent Events over HTTP | Remote MCP web services |

#### Constructor

```python
from protolink.tools.adapters import MCPToolAdapter

adapter = MCPToolAdapter(
    transport: str = "stdio",      # "stdio" or "sse"
    command: str | None = None,    # Command for stdio (e.g., "python")
    args: list[str] | None = None, # Args for command (e.g., ["server.py"])
    url: str | None = None,        # URL for SSE transport
    headers: dict[str, str] | None = None,  # Headers for SSE
)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `transport` | `str` | `"stdio"` | Transport type: `"stdio"` or `"sse"` |
| `command` | `str ⎪ None` | `None` | Command to run for stdio transport |
| `args` | `list[str] ⎪ None` | `None` | Arguments for the stdio command |
| `url` | `str ⎪ None` | `None` | URL for SSE transport |
| `headers` | `dict[str, str] ⎪ None` | `None` | HTTP headers for SSE (e.g., auth) |

---

### Connecting to MCP Servers

#### Local MCP Server (stdio)

Connect to a local MCP server running as a Python script:

```python
from protolink.tools.adapters import MCPToolAdapter

# Connect to a local MCP server
adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["path/to/mcp_server.py"]
)

# Or with a Node.js server
adapter = MCPToolAdapter(
    transport="stdio",
    command="node",
    args=["path/to/mcp_server.js"]
)
```

#### Remote MCP Server (SSE)

Connect to a remote MCP server over HTTP:

```python
from protolink.tools.adapters import MCPToolAdapter

# Connect to a remote MCP server
adapter = MCPToolAdapter(
    transport="sse",
    url="http://localhost:8080/sse"
)

# With authentication
adapter = MCPToolAdapter(
    transport="sse",
    url="https://api.example.com/mcp/sse",
    headers={"Authorization": "Bearer your-api-token"}
)
```

---

### Discovering Tools

#### list_tools()

Retrieve all available tools from the MCP server as dictionaries:

```python
tools = adapter.list_tools()

for tool in tools:
    print(f"Tool: {tool['name']}")
    print(f"  Description: {tool['description']}")
    print(f"  Input Schema: {tool['input_schema']}")
    print(f"  Input Types: {tool['input_types']}")
    print(f"  Callable: {tool['callable']}")
```

**Returns** a list of dictionaries with:

| Key | Type | Description |
|-----|------|-------------|
| `name` | `str` | Tool identifier |
| `description` | `str` | Human-readable description |
| `input_schema` | `dict` | Original JSON Schema for inputs |
| `input_types` | `dict[str, type]` | Parsed Python types |
| `output` | `None` | Reserved (MCP doesn't provide output schemas) |
| `callable` | `Callable` | Synchronous function to invoke the tool |

#### get_tools()

Retrieve all tools as `BaseTool`-compatible objects:

```python
base_tools = adapter.get_tools()

for tool in base_tools:
    print(f"{tool.name}: {tool.description}")
    print(f"  Input Schema: {tool.input_schema}")
    # e.g., {"type": "object", "properties": {"location": {"type": "string"}}}
```

**Returns** a list of native Protolink `Tool` instances. Each tool:

- Has `name`, `description`, `input_schema` populated from the MCP server
- Has `tags=["mcp"]` to identify it as an MCP-sourced tool
- Can be directly registered on a Protolink agent via `agent.add_tool()`

#### print_tools()

Display all available tools in a human-readable format:

```python
adapter.print_tools()
```

**Output:**
```
🛠 Available MCP Tools:

🔹 Name       : add
   Description: Add two integers.
   Input Schema: {'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}}, ...}
   Input Types : {'a': <class 'int'>, 'b': <class 'int'>}

🔹 Name       : greet
   Description: Greet a person by name.
   Input Schema: {'properties': {'name': {'type': 'string'}}, ...}
   Input Types : {'name': <class 'str'>}
```

---

### Invoking Tools

There are multiple ways to invoke MCP tools, depending on whether you need synchronous or asynchronous execution:

#### Method 1: get_callable() - Synchronous Callable

Get a **synchronous** callable for a specific tool. Best for quick scripts and non-async contexts:

```python
# Get the synchronous callable
add = adapter.get_callable("add")

# Invoke with keyword arguments (no await needed)
result = add(a=5, b=7)
print(result)  # "12"
```

:::note[Sync vs Async]

`get_callable()` returns a synchronous function that uses `asyncio.run()` internally. This is simple but cannot be used inside an existing async context (it would cause a nested event loop error).

:::
#### Method 2: get_tools() - Native Protolink Tools (Async)

Get all tools as native Protolink `Tool` objects with **async** `__call__` methods:

```python
import asyncio

# Get all tools as native Tool objects
tools = adapter.get_tools()

# Find a specific tool
multiply = next(t for t in tools if t.name == "multiply")

# Invoke asynchronously
result = asyncio.run(multiply(a=5, b=7))
print(result)  # "35"
```

This is the **recommended approach** for:
- Registering tools on Protolink agents
- Using tools in async contexts
- Avoiding nested event loop issues

:::tip[Agent Integration]

`get_tools()` returns `Tool` objects that can be directly registered via `agent.add_tool(tool)`. The agent's async runtime will properly await tool calls.

:::
#### Method 3: wrap_tool() - Single BaseTool Instance

Wrap a specific tool as a `BaseTool`-compatible object:

```python
# Wrap the tool
add_tool = adapter.wrap_tool("add")

# Access metadata
print(add_tool.name)         # "add"
print(add_tool.description)  # "Add two integers."
print(add_tool.input_schema) # {"type": "object", "properties": {"a": {"type": "integer"}}, ...}

# Invoke asynchronously
import asyncio
result = asyncio.run(add_tool(a=5, b=7))
print(result)  # "12"
```

#### Method 4: Via list_tools() Callable

Use the **synchronous** callable directly from the tool dictionary:

```python
tools = adapter.list_tools()

# Find the tool you want
add_tool = next(t for t in tools if t['name'] == 'add')

# Invoke it (synchronous)
result = add_tool['callable'](a=5, b=7)
print(result)  # "12"
```

:::warning[Sync Callable Limitation]

The `callable` in `list_tools()` is synchronous and cannot be used inside an async context. For async usage, use `get_tools()` instead.

:::
---

### Registering MCP Tools on Agents

Once you have MCP tools, you can register them on a Protolink agent:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.tools.adapters import MCPToolAdapter

# Create the agent
agent_card = AgentCard(
    url="http://localhost:8020",
    name="mcp_agent", 
    description="Agent with MCP tools"
)
agent = Agent(card=agent_card, transport="http")

# Connect to MCP server
adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["mcp_server.py"]
)

# Get all tools as native Protolink Tool objects
mcp_tools = adapter.get_tools()

# Register each tool with the agent
for tool in mcp_tools:
    agent.add_tool(tool)
```

:::tip[Native Tool Integration]

`get_tools()` returns native Protolink `Tool` objects with `tags=["mcp"]`, making them fully compatible with the agent system. No additional wrapping is needed.

:::
---

### Complete Example

Here's a complete example showing how to create an MCP server and use it with Protolink:

#### MCP Server (mcp_server.py)

```python
from mcp.server.fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP(
    name="math-tools",
    instructions="Simple MCP server with math tools"
)

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b

@mcp.tool()
def greet(name: str) -> str:
    """Greet a person by name."""
    return f"Hello, {name}! 👋"

if __name__ == "__main__":
    mcp.run()
```

#### Protolink Client

```python
from protolink.tools.adapters import MCPToolAdapter

# Connect to the MCP server
adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["mcp_server.py"]
)

# Discover available tools
print("Available tools:")
adapter.print_tools()

# Get tools as BaseTool objects
tools = adapter.get_tools()
print(f"\nFound {len(tools)} tools")

# Use the add tool
add = adapter.get_callable("add")
result = add(a=10, b=20)
print(f"\n10 + 20 = {result}")

# Use the greet tool
greet = adapter.get_callable("greet")
message = greet(name="World")
print(f"\n{message}")
```

**Output:**
```
Available tools:

🛠 Available MCP Tools:

🔹 Name       : add
   Description: Add two integers.
   ...

🔹 Name       : multiply
   Description: Multiply two integers.
   ...

🔹 Name       : greet
   Description: Greet a person by name.
   ...

Found 3 tools

10 + 20 = 30

Hello, World! 👋
```

---

## MCPToolAdapter API Reference

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `list_tools(refresh=False)` | `list[dict]` | List all tools as dictionaries with metadata and callables |
| `get_tools()` | `list[Tool]` | Get all tools as native Protolink `Tool` objects (tagged with `"mcp"`) |
| `get_tool(name)` | `dict ⎪ None` | Get a specific tool's metadata by name |
| `get_callable(name)` | `Callable` | Get a synchronous callable for a tool |
| `wrap_tool(name)` | `MCPToolAdapter` | Wrap a tool as a BaseTool instance |
| `print_tools()` | `None` | Print all tools in human-readable format |

### Attributes (when wrapping a tool)

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Tool name |
| `description` | `str` | Tool description |
| `input_schema` | `dict[str, Any]` | JSON Schema input object |
| `output_schema` | `dict[str, Any] ⎪ None` | Output JSON Schema when available |
| `tags` | `list[str] ⎪ None` | Tool tags |

---

## Best Practices

### Built-in Tools

1. **Register selectively**: Built-ins are opt-in; add only the tools an agent needs.
2. **Configure policy**: Use `CapabilityPolicy` to allow, deny, or approval-gate `network.read` explicitly.
3. **Treat external data as untrusted**: Search results and fetched pages can contain incorrect or adversarial text.
4. **Use the Agent execution path**: Direct Tool calls are convenient for low-level tests but bypass Agent runtime controls.

### Tool Design

1. **Clear descriptions**: Write descriptions that help the LLM understand when to use each tool
2. **Typed parameters**: Use type hints for all parameters
3. **Error handling**: Raise clear exceptions for invalid inputs
4. **Single responsibility**: Each tool should do one thing well

### MCP Integration

1. **Connection reuse**: Create one `MCPToolAdapter` and reuse it for multiple tool calls
2. **Caching**: Use `list_tools()` without `refresh=True` to leverage caching
3. **Error handling**: Wrap tool calls in try/except for network failures
4. **Transport choice**: Use `stdio` for local servers, `sse` for remote services

### Agent Registration

1. **Selective registration**: Only register tools the agent actually needs
2. **Descriptive names**: Use clear, action-oriented names like `search_documents` not `do_search`
3. **Tag organization**: Use consistent tagging for related tools

---

## See Also

- [Agent Documentation](agent.md) - How agents use tools
- [LLM Documentation](llm.md) - How LLMs invoke tools via `infer()`
- [MCP Specification](https://modelcontextprotocol.io/) - Model Context Protocol details
