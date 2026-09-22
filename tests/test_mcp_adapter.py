"""MCP wire results, schemas, and session lifetimes survive the tool boundary."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("mcp")

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ListToolsResult, TextContent
from mcp.types import Tool as MCPTool

from protolink import Agent, AgentCard, Task, TaskState
from protolink.tools.adapters import MCPToolAdapter, MCPToolError, mcp_adapter


def text_result(text="ok"):
    return CallToolResult(content=[TextContent(type="text", text=text)])


@pytest.fixture
def server(monkeypatch):
    session = SimpleNamespace(
        initialize=AsyncMock(),
        list_tools=AsyncMock(
            return_value=ListToolsResult(tools=[MCPTool(name="lookup", inputSchema={"type": "object"})])
        ),
        call_tool=AsyncMock(return_value=text_result()),
    )
    state = SimpleNamespace(session=session, opens=0, closes=0, connections=[])

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield session

    @asynccontextmanager
    async def transport(*args, **kwargs):
        state.opens += 1
        state.connections.append((args, kwargs))
        try:
            if "http_client" in kwargs:
                yield None, None, lambda: "session-id"
            else:
                yield None, None
        finally:
            state.closes += 1

    monkeypatch.setattr(mcp_adapter, "stdio_client", transport)
    monkeypatch.setattr(mcp_adapter, "sse_client", transport)
    monkeypatch.setattr(mcp_adapter, "streamable_http_client", transport)
    monkeypatch.setattr(mcp_adapter, "ClientSession", connection)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable_http"])
@pytest.mark.parametrize("form", ["native", "wrapped", "sync"])
async def test_all_call_paths_preserve_rich_results(server, transport, form):
    expected = {
        "content": [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
            {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
            {"type": "resource_link", "uri": "https://example.com/result", "name": "result"},
        ],
        "structuredContent": {"count": 0, "value": None},
        "isError": False,
        "_meta": {"receipt": "saved", "optional": None},
    }
    server.session.call_tool.return_value = CallToolResult.model_validate(expected)
    adapter = MCPToolAdapter(transport, command="unused", url="https://example.com/mcp")
    native = (await adapter.get_tools_async())[0]
    if form == "native":
        actual = await native()
    elif form == "wrapped":
        actual = await adapter.wrap_tool("lookup")()
    else:
        actual = await asyncio.to_thread(adapter.get_callable("lookup"))
    assert actual == expected
    assert server.session.call_tool.await_count == 1
    assert server.opens == server.closes == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (text_result(""), ""),
        (text_result("ok"), "ok"),
        (CallToolResult(content=[]), None),
        (CallToolResult(content=[], structuredContent={}), {"content": [], "structuredContent": {}, "isError": False}),
        (
            CallToolResult.model_validate({"content": [{"type": "text", "text": "x", "annotations": {"priority": 0}}]}),
            {"content": [{"type": "text", "text": "x", "annotations": {"priority": 0}}], "isError": False},
        ),
    ],
)
async def test_plain_text_compatibility_and_falsey_rich_values(server, result, expected):
    server.session.call_tool.return_value = result
    tool = (await MCPToolAdapter(command="unused").get_tools_async())[0]
    assert await tool() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["native", "wrapped", "sync"])
async def test_tool_errors_raise_with_full_result_without_retry(server, form):
    result = CallToolResult(
        content=[TextContent(type="text", text="denied")], isError=True, structuredContent={"code": 7}
    )
    server.session.call_tool.return_value = result
    adapter = MCPToolAdapter(command="unused")
    native = (await adapter.get_tools_async())[0]
    with pytest.raises(MCPToolError, match="denied") as raised:
        if form == "native":
            await native()
        elif form == "wrapped":
            await adapter.wrap_tool("lookup")()
        else:
            await asyncio.to_thread(adapter.get_callable("lookup"))
    assert raised.value.tool_name == "lookup"
    assert raised.value.result == result.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert server.session.call_tool.await_count == 1
    assert server.opens == server.closes


@pytest.mark.asyncio
async def test_agent_task_records_mcp_failure_instead_of_success(server):
    server.session.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="denied")], isError=True
    )
    agent = Agent(AgentCard(name="mcp", description="MCP test", url="runtime://mcp"), verbosity=0)
    await agent.add_mcp(MCPToolAdapter(command="unused"))
    with pytest.raises(MCPToolError):
        await agent.call_tool("lookup")
    task = await agent.run_task(Task.create_tool_call("lookup"))
    assert task.state is TaskState.FAILED
    assert "denied" in task.get_last_part().as_tool_output().error["message"]


@pytest.mark.asyncio
async def test_discovery_preserves_nullable_and_output_schemas_across_pages(server):
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": ["string", "null"]},
            "choice": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            "anything": True,
        },
    }
    output = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}
    server.session.list_tools.side_effect = [
        ListToolsResult(tools=[MCPTool(name="lookup", inputSchema=schema, outputSchema=output)], nextCursor="page2"),
        ListToolsResult(tools=[MCPTool(name="other", inputSchema={"type": "object"})]),
    ]
    adapter = MCPToolAdapter(command="unused")
    descriptors = await adapter.list_tools_async()
    assert [item["name"] for item in descriptors] == ["lookup", "other"]
    assert descriptors[0]["input_schema"] == schema
    assert descriptors[0]["input_types"] == {"query": Any, "choice": Any, "anything": Any}
    assert descriptors[0]["output_schema"] == descriptors[0]["output"] == output
    tool = (await adapter.get_tools_async())[0]
    assert tool.input_schema["properties"] == schema["properties"]
    assert tool.output_schema["properties"] == output["properties"]
    assert adapter.wrap_tool("lookup").output_schema == output
    await tool(query=None)
    assert server.session.call_tool.call_args.args == ("lookup", {"query": None})
    assert server.session.list_tools.call_args.kwargs["params"].cursor == "page2"
    assert server.session.list_tools.await_count == 2


@pytest.mark.asyncio
async def test_repeated_page_cursor_fails_without_caching_partial_tools(server):
    server.session.list_tools.return_value = ListToolsResult(tools=[], nextCursor="same")
    adapter = MCPToolAdapter(command="unused")
    with pytest.raises(ValueError, match="repeated pagination"):
        await adapter.list_tools_async()
    server.session.list_tools.return_value = ListToolsResult(tools=[])
    assert await adapter.list_tools_async() == []
    assert server.session.list_tools.await_count == 3
    assert server.opens == server.closes == 2


@pytest.mark.asyncio
async def test_mcp_schema_defaults_recursive_refs_and_validation_survive_registration(server):
    schema = {
        "type": "object",
        "$defs": {
            "node": {
                "type": "object",
                "properties": {"value": {"type": "integer"}, "next": {"$ref": "#/$defs/node"}},
                "required": ["value"],
            },
        },
        "properties": {"root": {"$ref": "#/$defs/node"}},
        "required": ["root"],
    }
    server.session.list_tools.return_value = ListToolsResult(tools=[MCPTool(name="lookup", inputSchema=schema)])
    adapter = MCPToolAdapter(command="unused")
    agent = Agent(AgentCard(name="mcp", description="MCP test", url="runtime://mcp"), verbosity=0)
    tool = (await agent.add_mcp(adapter, prefix="remote_"))[0]
    assert tool.input_schema == schema
    assert tool.output_schema is None
    arguments = {"root": {"value": 1, "next": {"value": 2}}, "additional": True}
    await agent.call_tool("remote_lookup", **arguments)
    await adapter.wrap_tool("lookup")(**arguments)
    assert server.session.call_tool.call_args.args == ("lookup", arguments)
    with pytest.raises(ValueError, match="MCP tool arguments"):
        await agent.call_tool("remote_lookup", root={"value": "not an integer"})
    assert server.session.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_session_reuse_wrappers_concurrent_calls_and_cleanup(server):
    adapter = MCPToolAdapter(command="unused")
    async with adapter.session():
        native = (await adapter.get_tools_async())[0]
        wrapped = adapter.wrap_tool("lookup")
        assert await asyncio.gather(native(), wrapped()) == ["ok", "ok"]
        assert server.opens == 1
        with pytest.raises(RuntimeError, match="already has an open"):
            async with adapter.session():
                pass
        with pytest.raises(RuntimeError, match="owning event loop"):
            await asyncio.to_thread(adapter.get_callable("lookup"))
    assert server.opens == server.closes == 1
    assert server.session.initialize.await_count == 1
    assert await native() == "ok"
    assert server.opens == server.closes == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_session_closes_on_error_or_cancellation_and_can_reopen(server, cancel):
    adapter = MCPToolAdapter(command="unused")
    error = asyncio.CancelledError if cancel else ValueError
    with pytest.raises(error):
        async with adapter.session():
            raise error()
    async with adapter.session():
        await adapter.get_tools_async()
    assert server.opens == server.closes == 2


@pytest.mark.asyncio
async def test_session_cleans_up_failed_initialization(server):
    server.session.initialize.side_effect = RuntimeError("cannot initialize")
    adapter = MCPToolAdapter(command="unused")
    with pytest.raises(RuntimeError, match="cannot initialize"):
        async with adapter.session():
            pass
    server.session.initialize.side_effect = None
    async with adapter.session():
        await adapter.get_tools_async()
    assert server.opens == server.closes == 2


@pytest.mark.asyncio
async def test_sync_callable_rejects_active_loop_without_coroutine_warning(server, recwarn):
    with pytest.raises(RuntimeError, match="active event loop"):
        MCPToolAdapter(command="unused").get_callable("lookup")()
    assert server.opens == 0
    assert not recwarn.list


@pytest.mark.parametrize("transport", [None, "streamable_http"])
def test_agent_sync_http_registration_forwards_auth_and_transport(server, transport):
    agent = Agent(AgentCard(name="mcp", description="MCP test", url="runtime://mcp"), verbosity=0)
    agent.sync.add_mcp(url="https://example.com/mcp", transport=transport, headers={"Authorization": "Bearer test"})
    assert agent.sync.call_tool("lookup") == "ok"
    args, options = server.connections[-1]
    assert args == ("https://example.com/mcp",)
    if transport is None:
        assert options["headers"] == {"Authorization": "Bearer test"}
    else:
        client = options["http_client"]
        assert client.headers["Authorization"] == "Bearer test"
        assert client.is_closed


@pytest.mark.asyncio
async def test_real_streamable_http_discovery_call_and_error(monkeypatch):
    """Exercise actual MCP framing and SDK session management against an ASGI server."""
    server = FastMCP("adapter-test", stateless_http=True, json_response=True)

    @server.tool()
    def count(query: str | None = None) -> dict[str, object]:
        return {"count": 7, "query": query}

    @server.tool()
    def fail() -> str:
        raise ValueError("intentional MCP failure")

    app = server.streamable_http_app()
    client_class = httpx.AsyncClient
    requests = []

    async def record(request):
        requests.append(request)

    def local_client(**kwargs):
        return client_class(transport=httpx.ASGITransport(app=app), event_hooks={"request": [record]}, **kwargs)

    monkeypatch.setattr(mcp_adapter.httpx, "AsyncClient", local_client)
    adapter = MCPToolAdapter(
        "streamable_http", url="http://localhost:8000/mcp", headers={"Authorization": "Bearer test"}
    )
    async with server.session_manager.run():
        async with adapter.session():
            tools = {tool.name: tool for tool in await adapter.get_tools_async()}
            result = await tools["count"](query=None)
            assert result["structuredContent"] == {"count": 7, "query": None}
            with pytest.raises(MCPToolError, match="intentional MCP failure"):
                await tools["fail"]()
        # An error escaping the context must retain its type after SDK cleanup.
        with pytest.raises(MCPToolError, match="intentional MCP failure"):
            async with adapter.session():
                await tools["fail"]()
    assert requests
    assert all(request.headers["Authorization"] == "Bearer test" for request in requests)


@pytest.mark.asyncio
async def test_real_stdio_session_reuses_process_and_recovers_after_tool_error(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(
        "from mcp.server.fastmcp import FastMCP\n"
        "server = FastMCP('session-test')\n"
        "calls = 0\n"
        "@server.tool()\n"
        "def count() -> dict[str, int]:\n"
        "    global calls\n"
        "    calls += 1\n"
        "    return {'count': calls}\n"
        "@server.tool()\n"
        "def fail() -> str:\n"
        "    raise ValueError('intentional failure')\n"
        "server.run()\n"
    )
    adapter = MCPToolAdapter(command=sys.executable, args=[str(script)])
    async with asyncio.timeout(20):
        with pytest.raises(MCPToolError, match="intentional failure"):
            async with adapter.session():
                tools = {tool.name: tool for tool in await adapter.get_tools_async()}
                assert (await tools["count"]())["structuredContent"] == {"count": 1}
                assert (await tools["count"]())["structuredContent"] == {"count": 2}
                await tools["fail"]()
        assert (await tools["count"]())["structuredContent"] == {"count": 1}
