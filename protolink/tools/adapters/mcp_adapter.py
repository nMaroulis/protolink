"""
MCP Tool Adapter for Protolink.

This module provides the MCPToolAdapter class that connects to Model Context Protocol (MCP)
servers and exposes their tools as callable functions compatible with the Protolink BaseTool
protocol.

Supported Transports:
    - **stdio**: Local subprocess communication via stdin/stdout. Use this for MCP servers
      running as local Python scripts or executables.
    - **sse**: Remote server communication via Server-Sent Events (HTTP). Use this for
      legacy MCP servers running as web services.
    - **streamable_http**: Remote MCP servers using Streamable HTTP.

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
import copy
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, ClassVar

try:
    import httpx
    from jsonschema import ValidationError
    from jsonschema.validators import validator_for
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import CallToolResult, PaginatedRequestParams, Tool
    from referencing import Registry
except ImportError as exc:
    raise ImportError(
        "MCP tool support requires the optional 'mcp' dependency. "
        "Install it with: pip install 'protolink[mcp]' or uv add 'protolink[mcp]'."
    ) from exc

from protolink.tools.base import BaseTool
from protolink.tools.tool import Tool as ProtoTool


@asynccontextmanager
async def _session_errors() -> AsyncIterator[None]:
    """Preserve a single failure's type through the SDK's nested task groups."""
    try:
        yield
    except BaseExceptionGroup as group:
        error: BaseException = group
        while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
            error = error.exceptions[0]
        raise error from None


def _validate_mcp_arguments(arguments: dict[str, Any] | None, schema: dict[str, Any] | None) -> dict[str, Any]:
    """Validate MCP JSON Schema without rewriting it or coercing JSON values."""
    result = dict(arguments or {})
    if schema is not None:
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        try:
            validator_type(schema, registry=Registry()).validate(result)
        except ValidationError as exc:
            path = ".".join(str(item) for item in exc.absolute_path)
            raise ValueError(f"MCP tool arguments{'.' + path if path else ''}: {exc.message}") from exc
    return result


class _MCPTool(ProtoTool):
    """Native Tool with the remote server's unmodified JSON Schema contract."""

    def __post_init__(self) -> None:
        # Native normalization inlines references and closes object schemas.
        # MCP schemas may be recursive or allow additional properties by default.
        input_schema, output_schema = self.input_schema, self.output_schema
        self.input_schema, self.output_schema = {"type": "object"}, {}
        super().__post_init__()
        self.input_schema = copy.deepcopy(input_schema)
        self.output_schema = copy.deepcopy(output_schema)

    def validate_args(self, kwargs: dict[str, Any] | None) -> dict[str, Any]:
        return _validate_mcp_arguments(kwargs, self.input_schema)


class MCPToolError(RuntimeError):
    """An MCP tool reported failure; ``result`` retains its complete JSON response."""

    def __init__(self, tool_name: str, result: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.result = result
        text = "\n".join(item["text"] for item in result["content"] if item.get("type") == "text")
        super().__init__(f"MCP tool '{tool_name}' failed" + (f": {text}" if text else ""))


def _normalize_result(tool_name: str, result: CallToolResult) -> Any:
    """Keep plain-text compatibility and preserve rich MCP results as JSON data."""
    # exclude_unset preserves nulls inside structuredContent and extension data.
    payload = result.model_dump(mode="json", by_alias=True, exclude_unset=True)
    payload["content"] = payload.get("content", [])
    payload["isError"] = result.isError
    if result.isError:
        raise MCPToolError(tool_name, payload)
    if payload.keys() <= {"content", "isError"}:
        content = payload["content"]
        if not content:
            return None
        if len(content) == 1 and content[0].get("type") == "text" and content[0].keys() <= {"type", "text"}:
            return content[0]["text"]
    return payload


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
        Union, nullable, referenced, and unsupported schemas use ``typing.Any``.
        This shallow mapping is for inspection only; the original schema is retained.
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
        typ_str = prop.get("type") if isinstance(prop, dict) else None
        args[name] = type_map.get(typ_str, Any) if isinstance(typ_str, str) else Any

    return args


class MCPToolAdapter(BaseTool):
    """
    Adapter that connects to MCP servers and exposes their tools as callables.

    This class provides a bridge between the Model Context Protocol (MCP) and Protolink's
    tool system. It can discover tools from an MCP server, retrieve their schemas, and
    create callable wrappers that invoke the tools.

    The adapter supports three transport mechanisms:

    - **stdio**: For local MCP servers running as subprocesses. The adapter communicates
      via stdin/stdout pipes.
    - **sse**: For remote MCP servers exposing an SSE (Server-Sent Events) endpoint.
    - **streamable_http**: For remote MCP servers exposing a Streamable HTTP endpoint.

    Attributes:
        transport (str): The transport type ("stdio", "sse", or "streamable_http").
        command (str | None): Command to run for stdio transport.
        args (list[str]): Arguments for the stdio command.
        url (str | None): URL for an HTTP transport.
        headers (dict[str, str]): Headers for an HTTP transport.
        name (str): Tool name (set when wrapping a specific tool).
        description (str): Tool description (set when wrapping a specific tool).
        input_schema (dict[str, Any] | None): JSON Schema input object from the MCP server.
        output_schema (dict[str, Any] | None): MCP schema for structuredContent.
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
        >>> print(add_tool.input_schema) # {"type": "object", "properties": {"a": {"type": "integer"}}}
        >>> # Use async call
        >>> import asyncio
        >>> result = asyncio.run(add_tool(a=5, b=7))
    """

    _protolink_validates_args: ClassVar[bool] = True

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
                - ``"streamable_http"``: Remote server via Streamable HTTP.
            command: Command to run for stdio transport (e.g., ``"python"`` or ``"node"``).
                Required when ``transport="stdio"``.
            args: Arguments for the command (e.g., ``["mcp_server.py"]``).
                Used with stdio transport.
            url: Endpoint required for either HTTP transport.
            headers: Optional HTTP headers (e.g., for authentication).

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
        self.input_schema: dict[str, Any] | None = None
        self.output_schema: dict[str, Any] | None = None
        self.tags: list[str] | None = None

        self._tools_cache: list[dict] | None = None
        self._session: ClientSession | None = None
        self._session_loop: asyncio.AbstractEventLoop | None = None
        self._session_open = False
        self._session_adapter: MCPToolAdapter | None = None

    def _validate_transport(self) -> None:
        """
        Validate that the transport configuration is complete.

        Raises:
            ValueError: If required transport arguments are missing or transport type is unknown.
        """
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("Provide 'command' for stdio transport.")
        elif self.transport in {"sse", "streamable_http"}:
            if not self.url:
                raise ValueError(f"Provide 'url' for {self.transport} transport.")
        else:
            raise ValueError(f"Unknown transport: {self.transport}. Use 'stdio', 'sse', or 'streamable_http'.")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[ClientSession]:
        """Own transport/session cleanup in the task that opened them."""
        self._validate_transport()
        async with _session_errors(), AsyncExitStack() as stack:
            if self.transport == "stdio":
                assert self.command is not None
                streams = await stack.enter_async_context(
                    stdio_client(StdioServerParameters(command=self.command, args=self.args))
                )
                read, write = streams
            elif self.transport == "sse":
                assert self.url is not None
                read, write = await stack.enter_async_context(sse_client(self.url, headers=self.headers))
            else:
                assert self.url is not None
                client = await stack.enter_async_context(
                    httpx.AsyncClient(headers=self.headers, timeout=httpx.Timeout(30, read=300), follow_redirects=False)
                )
                read, write, _ = await stack.enter_async_context(streamable_http_client(self.url, http_client=client))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            yield session

    @asynccontextmanager
    async def session(self) -> AsyncIterator["MCPToolAdapter"]:
        """Reuse one initialized session within ``async with adapter.session()``.

        Registered wrappers share this session. Await all calls before leaving;
        opening and closing must happen in the same task. Nested contexts and
        use from another event loop are rejected. Outside the context each
        operation owns its session. No tool call is automatically retried.
        """
        if self._session_adapter is not None:
            async with self._session_adapter.session():
                yield self
            return
        if self._session_open:
            raise RuntimeError("This MCP adapter already has an open session context")
        self._session_open = True
        try:
            async with self._connect() as session:
                self._session = session
                self._session_loop = asyncio.get_running_loop()
                try:
                    yield self
                finally:
                    self._session = None
                    self._session_loop = None
        finally:
            self._session_open = False

    async def _run_with_session(self, callback: Callable[[ClientSession], Awaitable[Any]]) -> Any:
        """Use the managed session or open one for this operation."""
        if self._session_adapter is not None:
            return await self._session_adapter._run_with_session(callback)
        if self._session is not None:
            if self._session_loop is not asyncio.get_running_loop():
                raise RuntimeError("An open MCP session must be used from its owning event loop")
            return await callback(self._session)
        if self._session_open:
            raise RuntimeError("The MCP session context is opening or closing")
        async with self._connect() as session:
            return await callback(session)

    async def _call_tool(self, tool_name: str, kwargs: dict[str, Any]) -> Any:
        async def invoke(session: ClientSession) -> CallToolResult:
            return await session.call_tool(tool_name, kwargs)

        # Normalize after session cleanup so MCP tool errors retain their own type.
        result = await self._run_with_session(invoke)
        return _normalize_result(tool_name, result)

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
                - ``output_schema`` (dict | None): Schema for MCP structuredContent.
                - ``output`` (dict | None): Alias for output_schema.
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

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.list_tools_async(refresh=refresh))
        raise RuntimeError("Use await adapter.list_tools_async() inside an active event loop")

    async def list_tools_async(self, *, refresh: bool = False) -> list[dict]:
        """Discover MCP descriptors without starting a nested event loop.

        Uses the same cache as list_tools and follows pagination in one session.
        Discovery performs no tool invocation. Set refresh to reload metadata.
        """
        if self._tools_cache is not None and not refresh:
            return self._tools_cache

        async def _fetch_tools(session: ClientSession) -> list[dict]:
            tools = []
            cursor = None
            seen_cursors: set[str] = set()
            while True:
                result = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
                for tool in result.tools:
                    tools.append(
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema,
                            "input_types": _parse_tool_arguments(tool),
                            "output_schema": tool.outputSchema,
                            "output": tool.outputSchema,
                            "callable": self._make_callable(tool.name),
                        }
                    )
                cursor = result.nextCursor
                if not cursor:
                    break
                if cursor in seen_cursors:
                    raise ValueError("MCP tools/list returned a repeated pagination cursor")
                seen_cursors.add(cursor)
            return tools

        self._tools_cache = await self._run_with_session(_fetch_tools)
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
        return self._wrap_tools(self.list_tools())

    async def get_tools_async(self) -> list[ProtoTool]:
        """Discover native Tool wrappers in async applications and notebooks.

        Wrappers call the original server tool names and retain their schemas.
        Register them with Agent.add_tools, or use await Agent.add_mcp directly.
        """
        return self._wrap_tools(await self.list_tools_async())

    def _wrap_tools(self, tool_dicts: list[dict]) -> list[ProtoTool]:
        """Build native wrappers from discovered descriptors."""
        wrapped_tools: list[ProtoTool] = []

        for tool_dict in tool_dicts:
            wrapped = _MCPTool(
                name=tool_dict["name"],
                description=tool_dict["description"],
                input_schema=tool_dict["input_schema"],
                output_schema=tool_dict["output_schema"],
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

        async def async_call_tool(**kwargs) -> Any:
            return await self._call_tool(tool_name, kwargs)

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
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self._call_tool(tool_name, kwargs))
            raise RuntimeError("Use an async MCP tool inside an active event loop")

        return call_tool

    async def __call__(self, **kwargs) -> Any:
        """
        Call this adapter as an async tool.

        When the adapter is wrapping a specific tool (via :meth:`wrap_tool` or
        :meth:`get_tools`), this method invokes that tool with the provided arguments.

        Args:
            **kwargs: Keyword arguments matching the tool's input schema.

        Returns:
            A plain text string, None for empty content, or a complete MCP result
            dictionary for structured, annotated, or multiple content blocks.

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

        return await self._call_tool(self.name, self.validate_args(kwargs))

    def validate_args(self, kwargs: dict[str, Any] | None) -> dict[str, Any]:
        """Validate a wrapped tool using its original MCP schema."""
        return _validate_mcp_arguments(kwargs, self.input_schema)

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
                - ``input_schema``: Set to the original MCP JSON Schema.
                - ``__call__``: Configured to invoke the specific tool.

        Raises:
            ValueError: If no tool with the given name exists on the MCP server.

        Example:
            >>> add_tool = adapter.wrap_tool("add")
            >>> print(add_tool.name)         # "add"
            >>> print(add_tool.description)  # "Add two integers."
            >>> print(add_tool.input_schema) # {"type": "object", "properties": {"a": {"type": "integer"}}}
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
        wrapped.input_schema = tool_info["input_schema"]
        wrapped.output_schema = tool_info["output_schema"]
        wrapped.tags = None
        wrapped._tools_cache = self._tools_cache
        wrapped._session_adapter = self

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
