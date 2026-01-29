"""
MCP Tool Adapter for Protolink.

This module provides the MCPToolAdapter class that connects to Model Context Protocol (MCP)
servers and exposes their tools as callable functions compatible with the Protolink BaseTool
protocol.

Supported Transports:
    - **stdio**: Local subprocess communication via stdin/stdout. Use this for MCP servers
      running as local Python scripts or executables.
    - **sse**: Remote server communication via Server-Sent Events (HTTP). Use this for
      MCP servers running as web services.

Quick Start:
    >>> from protolink.tools.adapters.mcp_adapter import MCPToolAdapter
    >>>
    >>> # Connect to a local MCP server
    >>> adapter = MCPToolAdapter(
    ...     transport="stdio",
    ...     command="python",
    ...     args=["my_mcp_server.py"]
    ... )
    >>>
    >>> # List available tools
    >>> tools = adapter.list_tools()
    >>> for tool in tools:
    ...     print(f"{tool['name']}: {tool['description']}")
    >>>
    >>> # Call a tool directly
    >>> add = adapter.get_callable("add")
    >>> result = add(a=5, b=7)

See Also:
    - :class:`protolink.tools.base.BaseTool`: The protocol that wrapped tools conform to.
    - MCP Specification: https://modelcontextprotocol.io/
"""

import asyncio
from collections.abc import Callable
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Tool

from protolink.tools.base import BaseTool
from protolink.tools.tool import Tool as ProtoTool


def _parse_tool_arguments(tool: Tool) -> dict[str, type]:
    """
    Convert an MCP Tool's inputSchema into a Python dictionary mapping argument names to Python types.

    This helper function translates JSON Schema type definitions from MCP tools into
    native Python types for easier introspection and validation.

    Args:
        tool: An MCP Tool object containing an inputSchema.

    Returns:
        A dictionary mapping argument names to their corresponding Python types.
        For example: ``{"a": int, "b": str}``

    Note:
        Unsupported JSON Schema types default to ``typing.Any``.
    """
    if not tool.inputSchema:
        return {}

    args: dict[str, type] = {}
    properties = tool.inputSchema.get("properties", {})

    type_map = {
        "integer": int,
        "number": float,
        "string": str,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    for name, prop in properties.items():
        typ_str = prop.get("type", "string")
        args[name] = type_map.get(typ_str, Any)

    return args


class MCPToolAdapter(BaseTool):
    """
    Adapter that connects to MCP servers and exposes their tools as callables.

    This class provides a bridge between the Model Context Protocol (MCP) and Protolink's
    tool system. It can discover tools from an MCP server, retrieve their schemas, and
    create callable wrappers that invoke the tools.

    The adapter supports two transport mechanisms:

    - **stdio**: For local MCP servers running as subprocesses. The adapter communicates
      via stdin/stdout pipes.
    - **sse**: For remote MCP servers exposing an SSE (Server-Sent Events) endpoint.

    Attributes:
        transport (str): The transport type ("stdio" or "sse").
        command (str | None): Command to run for stdio transport.
        args (list[str]): Arguments for the stdio command.
        url (str | None): URL for SSE transport.
        headers (dict[str, str]): Headers for SSE transport.
        name (str): Tool name (set when wrapping a specific tool).
        description (str): Tool description (set when wrapping a specific tool).
        input_schema (dict[str, type] | None): Input parameter types.
        output_schema (dict[str, type] | None): Output types (currently unused by MCP).
        tags (list[str] | None): Optional tags for tool categorization.

    Example:
        **Connecting to a local MCP server (stdio):**

        >>> adapter = MCPToolAdapter(
        ...     transport="stdio",
        ...     command="python",
        ...     args=["mcp_server.py"]
        ... )
        >>> adapter.print_tools()
        🛠 Available MCP Tools:
        🔹 Name       : add
           Description: Add two integers.
           ...

        **Connecting to a remote MCP server (SSE):**

        >>> adapter = MCPToolAdapter(
        ...     transport="sse",
        ...     url="http://localhost:8080/sse",
        ...     headers={"Authorization": "Bearer token123"}
        ... )

        **Listing tools as dictionaries:**

        >>> tools = adapter.list_tools()
        >>> for t in tools:
        ...     print(f"{t['name']}: {t['description']}")
        ...     print(f"  Schema: {t['input_schema']}")
        ...     print(f"  Callable: {t['callable']}")

        **Listing tools as BaseTool objects:**

        >>> base_tools = adapter.get_tools()
        >>> for tool in base_tools:
        ...     print(f"{tool.name}: {tool.description}")
        ...     print(f"  Input Schema: {tool.input_schema}")

        **Calling a tool directly:**

        >>> add_fn = adapter.get_callable("add")
        >>> result = add_fn(a=5, b=7)
        >>> print(result)  # "12"

        **Wrapping a tool as a BaseTool-compatible object:**

        >>> add_tool = adapter.wrap_tool("add")
        >>> print(add_tool.name)         # "add"
        >>> print(add_tool.description)  # "Add two integers."
        >>> print(add_tool.input_schema) # {"a": int, "b": int}
        >>> # Use async call
        >>> import asyncio
        >>> result = asyncio.run(add_tool(a=5, b=7))
    """

    def __init__(
        self,
        transport: str = "stdio",
        *,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        """
        Initialize the MCP Tool Adapter.

        Args:
            transport: Transport type for MCP communication.
                - ``"stdio"``: Local subprocess via stdin/stdout (default).
                - ``"sse"``: Remote server via Server-Sent Events.
            command: Command to run for stdio transport (e.g., ``"python"`` or ``"node"``).
                Required when ``transport="stdio"``.
            args: Arguments for the command (e.g., ``["mcp_server.py"]``).
                Used with stdio transport.
            url: URL for SSE transport (e.g., ``"http://localhost:8080/sse"``).
                Required when ``transport="sse"``.
            headers: Optional HTTP headers for SSE transport (e.g., for authentication).

        Raises:
            ValueError: If required arguments for the chosen transport are not provided.

        Example:
            >>> # Local MCP server
            >>> adapter = MCPToolAdapter(
            ...     transport="stdio",
            ...     command="python",
            ...     args=["my_server.py"]
            ... )

            >>> # Remote MCP server with auth
            >>> adapter = MCPToolAdapter(
            ...     transport="sse",
            ...     url="https://api.example.com/mcp/sse",
            ...     headers={"Authorization": "Bearer my-token"}
            ... )
        """
        self.transport = transport
        self.command = command
        self.args = args or []
        self.url = url
        self.headers = headers or {}

        # BaseTool protocol attributes (set when wrapping a specific tool)
        self.name: str = ""
        self.description: str = ""
        self.input_schema: dict[str, type] | None = None
        self.output_schema: dict[str, type] | None = None
        self.tags: list[str] | None = None

        self._tools_cache: list[dict] | None = None

    def _validate_transport(self) -> None:
        """
        Validate that the transport configuration is complete.

        Raises:
            ValueError: If required transport arguments are missing or transport type is unknown.
        """
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("Provide 'command' for stdio transport.")
        elif self.transport == "sse":
            if not self.url:
                raise ValueError("Provide 'url' for SSE transport.")
        else:
            raise ValueError(f"Unknown transport: {self.transport}. Use 'stdio' or 'sse'.")

    async def _run_with_session(self, callback: Callable[[ClientSession], Any]) -> Any:
        """
        Execute a callback with an active MCP session.

        This internal method handles the complexity of establishing connections to
        MCP servers using the configured transport and provides a session to the callback.

        Args:
            callback: An async function that receives a ``ClientSession`` and returns a result.
                The session is fully initialized before the callback is invoked.

        Returns:
            The result from the callback function.

        Raises:
            ValueError: If transport configuration is invalid.
        """
        self._validate_transport()

        if self.transport == "stdio":
            assert self.command is not None  # Validated in _validate_transport
            server_params = StdioServerParameters(command=self.command, args=self.args)
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await callback(session)

        elif self.transport == "sse":
            assert self.url is not None  # Validated in _validate_transport
            async with sse_client(self.url, headers=self.headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await callback(session)

    def list_tools(self, *, refresh: bool = False) -> list[dict]:
        """
        List all available tools from the MCP server.

        Retrieves tool metadata from the connected MCP server and returns it as a list
        of dictionaries. Results are cached after the first call for performance.

        Args:
            refresh: If ``True``, bypass the cache and fetch fresh tool data from the server.
                Defaults to ``False``.

        Returns:
            A list of dictionaries, each containing:
                - ``name`` (str): The tool's identifier.
                - ``description`` (str): Human-readable description of what the tool does.
                - ``input_schema`` (dict): The original JSON Schema for input parameters.
                - ``input_types`` (dict[str, type]): Parsed Python types for inputs.
                - ``output`` (None): Reserved for future use (MCP doesn't provide output schemas).
                - ``callable`` (Callable): A synchronous function to invoke the tool.

        Example:
            >>> adapter = MCPToolAdapter(transport="stdio", command="python", args=["server.py"])
            >>> tools = adapter.list_tools()
            >>> for tool in tools:
            ...     print(f"Tool: {tool['name']}")
            ...     print(f"  Description: {tool['description']}")
            ...     print(f"  Input Types: {tool['input_types']}")
            ...     # Call the tool
            ...     result = tool['callable'](a=1, b=2)
        """
        if self._tools_cache is not None and not refresh:
            return self._tools_cache

        async def _fetch_tools(session: ClientSession) -> list[dict]:
            result = await session.list_tools()
            tools = []

            for tool in result.tools:
                tool_dict = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema or {},
                    "input_types": _parse_tool_arguments(tool),
                    "output": None,  # MCP doesn't provide output schema
                    "callable": self._make_callable(tool.name),
                }
                tools.append(tool_dict)

            return tools

        self._tools_cache = asyncio.run(self._run_with_session(_fetch_tools))
        return self._tools_cache

    def get_tool(self, tool_name: str) -> dict | None:
        """
        Get a specific tool's metadata by name.

        Args:
            tool_name: The name of the tool to retrieve.

        Returns:
            A dictionary containing the tool's metadata (same structure as ``list_tools``),
            or ``None`` if no tool with that name exists.

        Example:
            >>> tool = adapter.get_tool("add")
            >>> if tool:
            ...     print(f"Found: {tool['name']} - {tool['description']}")
            ...     result = tool['callable'](a=5, b=3)
        """
        tools = self.list_tools()
        for tool in tools:
            if tool["name"] == tool_name:
                return tool
        return None

    def get_tools(self) -> list[ProtoTool]:
        """
        Get all tools as native Protolink Tool objects.

        Returns a list of ``Tool`` instances, each wrapping a specific MCP tool.
        These instances are native Protolink tools with ``name``, ``description``,
        ``input_schema``, ``tags``, and ``__call__`` properly set.

        Returns:
            A list of ``Tool`` instances, each representing one tool from the
            MCP server. Each instance can be called directly (async) or registered
            on a Protolink agent.

        Example:
            >>> tools = adapter.get_tools()
            >>> for tool in tools:
            ...     print(f"{tool.name}: {tool.description}")
            ...     print(f"  Input Schema: {tool.input_schema}")
            >>>
            >>> # Register all tools on an agent
            >>> for tool in tools:
            ...     agent.add_tool(tool)
            >>>
            >>> # Find and use a specific tool
            >>> add_tool = next(t for t in tools if t.name == "add")
            >>> import asyncio
            >>> result = asyncio.run(add_tool(a=5, b=7))

        See Also:
            :meth:`wrap_tool`: Wrap a single tool by name.
            :meth:`list_tools`: Get tools as dictionaries with callables.
        """
        tool_dicts = self.list_tools()
        wrapped_tools: list[ProtoTool] = []

        for tool_dict in tool_dicts:
            wrapped = ProtoTool(
                name=tool_dict["name"],
                description=tool_dict["description"],
                input_schema=tool_dict["input_types"],
                output_schema=None,
                tags=["mcp"],
                func=self._make_async_callable(tool_dict["name"]),
            )
            wrapped_tools.append(wrapped)

        return wrapped_tools

    def _make_async_callable(self, tool_name: str) -> Callable[..., Any]:
        """
        Create an async-compatible callable wrapper for an MCP tool.

        This method creates a closure that can be awaited safely within an async context.
        Unlike _make_callable, this doesn't use asyncio.run(), making it compatible
        with Tool.__call__ which is async.

        Args:
            tool_name: The name of the tool to wrap.

        Returns:
            An async callable that invokes the MCP tool and returns its result.
        """
        # Store references to avoid closure issues
        transport = self.transport
        command = self.command
        args = self.args
        url = self.url
        headers = self.headers

        async def async_call_tool(**kwargs) -> Any:
            # Create session inline since we can't reuse the adapter's _run_with_session
            # (it would cause nested event loop issues)
            if transport == "stdio":
                assert command is not None
                server_params = StdioServerParameters(command=command, args=args)
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, kwargs)
                        if result.content and hasattr(result.content[0], "text"):
                            return result.content[0].text
                        return None
            elif transport == "sse":
                assert url is not None
                async with sse_client(url, headers=headers) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, kwargs)
                        if result.content and hasattr(result.content[0], "text"):
                            return result.content[0].text
                        return None
            else:
                raise ValueError(f"Unknown transport: {transport}")

        return async_call_tool

    def get_callable(self, tool_name: str) -> Callable[..., Any]:
        """
        Get a synchronous callable for a specific tool.

        Creates a wrapper function that invokes the named tool on the MCP server.
        The callable accepts keyword arguments matching the tool's input schema.

        Args:
            tool_name: The name of the tool to create a callable for.

        Returns:
            A synchronous callable that accepts keyword arguments and returns the tool's
            result (typically a string).

        Example:
            >>> add = adapter.get_callable("add")
            >>> result = add(a=5, b=7)
            >>> print(result)  # "12"
            >>>
            >>> greet = adapter.get_callable("greet")
            >>> message = greet(name="Alice")
            >>> print(message)  # "Hello, Alice!"

        Note:
            The returned callable is synchronous and uses ``asyncio.run()`` internally.
            For async usage, use :meth:`get_tools` which returns ``Tool`` objects
            with async ``__call__`` methods.
        """
        return self._make_callable(tool_name)

    def _make_callable(self, tool_name: str) -> Callable[..., Any]:
        """
        Create a synchronous callable wrapper for an MCP tool.

        This internal method creates a closure that captures the tool name and adapter
        configuration, returning a function that can be called with keyword arguments.

        Args:
            tool_name: The name of the tool to wrap.

        Returns:
            A synchronous callable that invokes the MCP tool and returns its result.
        """

        def call_tool(**kwargs) -> Any:
            async def _invoke(session: ClientSession):
                result = await session.call_tool(tool_name, kwargs)
                if result.content and hasattr(result.content[0], "text"):
                    return result.content[0].text
                return None

            return asyncio.run(self._run_with_session(_invoke))

        return call_tool

    async def __call__(self, **kwargs) -> Any:
        """
        Call this adapter as an async tool.

        When the adapter is wrapping a specific tool (via :meth:`wrap_tool` or
        :meth:`get_tools`), this method invokes that tool with the provided arguments.

        Args:
            **kwargs: Keyword arguments matching the tool's input schema.

        Returns:
            The tool's result (typically a string).

        Raises:
            ValueError: If the adapter is not wrapping a specific tool (``name`` is empty).

        Example:
            >>> add_tool = adapter.wrap_tool("add")
            >>> import asyncio
            >>> result = asyncio.run(add_tool(a=5, b=7))
            >>> print(result)  # "12"
        """
        if not self.name:
            raise ValueError("Tool name not set. Use get_callable() or set self.name first.")

        async def _invoke(session: ClientSession):
            result = await session.call_tool(self.name, kwargs)
            if result.content and hasattr(result.content[0], "text"):
                return result.content[0].text
            return None

        return await self._run_with_session(_invoke)

    def wrap_tool(self, tool_name: str) -> "MCPToolAdapter":
        """
        Create a new adapter instance wrapping a specific tool.

        Returns a new ``MCPToolAdapter`` configured to act as a single tool, with all
        ``BaseTool`` protocol attributes populated. The wrapped adapter shares the same
        connection configuration and tool cache as the parent.

        Args:
            tool_name: The name of the tool to wrap.

        Returns:
            A new ``MCPToolAdapter`` instance with:
                - ``name``: Set to the tool's name.
                - ``description``: Set to the tool's description.
                - ``input_schema``: Set to the parsed Python types.
                - ``__call__``: Configured to invoke the specific tool.

        Raises:
            ValueError: If no tool with the given name exists on the MCP server.

        Example:
            >>> add_tool = adapter.wrap_tool("add")
            >>> print(add_tool.name)         # "add"
            >>> print(add_tool.description)  # "Add two integers."
            >>> print(add_tool.input_schema) # {"a": int, "b": int}
            >>>
            >>> # Call the tool asynchronously
            >>> import asyncio
            >>> result = asyncio.run(add_tool(a=10, b=20))
            >>> print(result)  # "30"

        See Also:
            :meth:`get_tools`: Wrap all tools at once.
        """
        tool_info = self.get_tool(tool_name)
        if not tool_info:
            raise ValueError(f"Tool '{tool_name}' not found on MCP server.")

        # Create a new adapter with the same transport config
        wrapped = MCPToolAdapter(
            transport=self.transport,
            command=self.command,
            args=self.args,
            url=self.url,
            headers=self.headers,
        )
        wrapped.name = tool_info["name"]
        wrapped.description = tool_info["description"]
        wrapped.input_schema = tool_info["input_types"]
        wrapped.output_schema = None
        wrapped.tags = None
        wrapped._tools_cache = self._tools_cache

        return wrapped

    def print_tools(self) -> None:
        """
        Print all available tools in a human-readable format.

        Displays tool information including name, description, JSON schema, and
        parsed Python types. Useful for debugging and exploration.

        Example:
            >>> adapter.print_tools()
            🛠 Available MCP Tools:

            🔹 Name       : add
               Description: Add two integers.
               Input Schema: {'properties': {'a': {'type': 'integer'}, ...}}
               Input Types : {'a': <class 'int'>, 'b': <class 'int'>}

            🔹 Name       : greet
               Description: Greet a person by name.
               ...
        """
        tools = self.list_tools()
        print("\n🛠 Available MCP Tools:\n")
        for t in tools:
            print(f"🔹 Name       : {t['name']}")
            print(f"   Description: {t['description']}")
            print(f"   Input Schema: {t['input_schema']}")
            print(f"   Input Types : {t['input_types']}")
            print()
