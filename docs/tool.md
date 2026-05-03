# Tools

Tools extend agent capabilities with additional functions. They enable LLMs and agents to interact with external systems, execute code, access data, and perform specialized tasks that go beyond pure text generation.

## Overview

Protolink provides a flexible tool system with two main approaches:

- **Native Tools**: Python functions decorated directly on an agent
- **MCP Tools**: Tools from external MCP (Model Context Protocol) servers

Both types of tools are exposed through the same interface, making them interchangeable from the agent's perspective.

## Module Structure

The tools module is organized as follows:

```python
# Core tool interfaces
from protolink.tools import BaseTool, Tool

# Tool adapters for external integrations  
from protolink.tools.adapters import MCPToolAdapter
```

| Module | Description |
|--------|-------------|
| `protolink.tools` | Core tool interfaces and native tool implementation |
| `protolink.tools.adapters` | Adapters for integrating external tool systems |

---

## BaseTool Protocol

All tools in Protolink conform to the `BaseTool` protocol, which defines the minimal interface for a tool:

```python
from typing import Any, Protocol

class BaseTool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: str | Any | None
    tags: list[str] | None

    async def __call__(self, **kwargs) -> Any: ...
```

### Protocol Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier for the tool |
| `description` | `str` | Human-readable description of what the tool does |
| `input_schema` | `dict[str, Any] ⎪ None` | Flattened dictionary of parameter definitions (see below) |
| `output_schema` | `str ⎪ Any ⎪ None` | The return type name (e.g., `"dict"`, `"str"`) |
| `tags` | `list[str] ⎪ None` | Categorization tags for filtering and discovery |

### The `__call__` Method

All tools are **async callables** that accept keyword arguments matching their input schema:

```python
# Tools are invoked with keyword arguments
result = await tool(location="Tokyo", units="celsius")
```

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
#     "a": {"type": "number", "required": True},
#     "b": {"type": "number", "required": True}
# }
# output_schema: "float"
```

### Decorator Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | The tool's identifier (used in tool calls) |
| `description` | `str` | Description shown to the LLM for tool selection |
| `tags` | `list[str]` | Optional categorization tags |

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
    # e.g., {'location': {'type': 'string', 'required': True}, ...}
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

!!! note "Sync vs Async"
    `get_callable()` returns a synchronous function that uses `asyncio.run()` internally. This is simple but cannot be used inside an existing async context (it would cause a nested event loop error).

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

!!! tip "Agent Integration"
    `get_tools()` returns `Tool` objects that can be directly registered via `agent.add_tool(tool)`. The agent's async runtime will properly await tool calls.

#### Method 3: wrap_tool() - Single BaseTool Instance

Wrap a specific tool as a `BaseTool`-compatible object:

```python
# Wrap the tool
add_tool = adapter.wrap_tool("add")

# Access metadata
print(add_tool.name)         # "add"
print(add_tool.description)  # "Add two integers."
print(add_tool.input_schema) # {"a": {"type": "integer", "required": True}, ...}

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

!!! warning "Sync Callable Limitation"
    The `callable` in `list_tools()` is synchronous and cannot be used inside an async context. For async usage, use `get_tools()` instead.

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

!!! tip "Native Tool Integration"
    `get_tools()` returns native Protolink `Tool` objects with `tags=["mcp"]`, making them fully compatible with the agent system. No additional wrapping is needed.

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
| `input_schema` | `dict[str, Any]` | Flattened input parameter definitions |
| `output_schema` | `str ⎪ None` | Output type name |
| `tags` | `list[str] ⎪ None` | Tool tags |

---

## Best Practices

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
