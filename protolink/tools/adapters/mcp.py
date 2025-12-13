from protolink.tools.base import BaseTool


class MCPToolAdapter(BaseTool):
    def __init__(self, mcp_client, tool_name: str, description: str | None = None):
        self.name = tool_name
        self.description = description or f"MCP tool {tool_name}"
        self.input_schema = None
        self.output_schema = None
        self.tags = None
        self.mcp_client = mcp_client

    async def __call__(self, **kwargs):
        return await self.mcp_client.run_tool(self.name, **kwargs)
