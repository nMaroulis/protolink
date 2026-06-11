from mcp.server.fastmcp import FastMCP

# -------------------------------------------------
# Create the MCP application
# -------------------------------------------------
mcp = FastMCP(name="example-mcp", instructions="Simple MCP server exposing math and greeting tools")

# -------------------------------------------------
# Tools
# -------------------------------------------------


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def greet(name: str) -> str:
    """Greet a person by name."""
    return f"Hello, {name} 👋"


@mcp.tool()
async def multiply(a: int, b: int = 5.4) -> int:
    """Multiply two numbers (async example)."""
    return a * b


# -------------------------------------------------
# Start MCP server (stdio transport)
# -------------------------------------------------
if __name__ == "__main__":
    print("Starting MCP server...")
    mcp.run()
