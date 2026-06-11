import asyncio
import os

from protolink.tools.adapters import MCPToolAdapter

# -----------------------------
# Example usage
# -----------------------------

if __name__ == "__main__":
    # Connect to a local MCP server via stdio
    adapter = MCPToolAdapter(
        transport="stdio",
        command="python",
        args=[f"{os.path.dirname(__file__)}/mcp_server.py"],
    )

    # List all tools
    adapter.print_tools()

    # Get tools as list of dicts
    tools = adapter.list_tools()
    for tool in tools:
        print(f"Tool: {tool['name']}")
        print(f"  Callable: {tool['callable']}")
        print(f"  Input Schema: {tool['input_schema']}")
        print(f"  Input Types : {tool['input_types']}")
        print()

    # Use a specific tool via get_callable() - returns synchronous callable
    add_callable = adapter.get_callable("add")
    result = add_callable(a=5, b=7)
    print(f"\nadd(5, 7) = {result}")

    # Or wrap a tool as a BaseTool-compatible object
    add_tool = adapter.wrap_tool("add")
    print(f"\nWrapped tool name: {add_tool.name}")
    print(f"Wrapped tool description: {add_tool.description}")
    print(f"Wrapped tool input_schema: {add_tool.input_schema}")

    # Get all tools as native Protolink Tool objects
    print("\n--- All Tools as Protolink Tool objects ---")
    base_tools = adapter.get_tools()
    for t in base_tools:
        print(f"  {t.name}: {t.description} | schema: {t.input_schema}")

    # Tool.__call__ is async, so we need to use asyncio.run()
    multiply_tool = next(t for t in base_tools if t.name == "multiply")
    result = asyncio.run(multiply_tool(a=5, b=7))
    print(f"\nmultiply(5, 7) = {result}")
