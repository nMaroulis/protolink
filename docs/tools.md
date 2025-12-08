# Tools

Tools extend agent capabilities with additional functions.

## Native Tools

**Native tools** are regular Python callables that you register on an agent. They are exposed over the transport so that other agents (or clients) can invoke them.

To register a native tool, decorate an async function with `@agent.tool`:

```python
from protolink.agents import Agent


@agent.tool(name="add", description="Add two numbers")
async def add_numbers(a: int, b: int) -> int:
    return a + b
```

Native tools are ideal for business logic, data access, or any capability you want your agents to expose.

## MCP Tools

Protolink can also expose tools from an **MCP (Model Context Protocol) server** using the `MCPToolAdapter`.

High‑level flow:

1. Connect to an MCP server using an MCP client (not shown here).
2. Wrap an MCP tool with `MCPToolAdapter`.
3. Register it on the agent.

Example pattern:

```python
from protolink.tools import MCPToolAdapter


mcp_tool = MCPToolAdapter(mcp_client, "multiply")
agent.add_tool(mcp_tool)
```

The MCP adapter lets you reuse existing MCP tools as if they were native tools, keeping a consistent interface on the agent side.

