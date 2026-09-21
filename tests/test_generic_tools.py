"""General-purpose tools retain native policy boundaries and bounded structured results."""

import asyncio
import json

import httpx
import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    CapabilityPolicy,
    ResourceConflictError,
    StorageCheckpointStore,
)
from protolink.storage import InMemoryStorage, SQLiteStorage
from protolink.tools import filesystem_tools, http_tool, storage_tools


def agent(*tools, **options):
    value = Agent(AgentCard(name="generic", description="test", url="runtime://generic"), verbosity=0, **options)
    for tool in tools:
        value.add_tool(tool)
    return value


def memory():
    return InMemoryStorage(store={}, ttl_heap=[])


@pytest.mark.asyncio
async def test_file_reads_search_and_optional_writes(tmp_path):
    path = tmp_path / "hello.txt"
    path.write_text("First café\nSecond café\n")
    (tmp_path / "binary").write_bytes(b"\x00binary")
    tools = filesystem_tools(roots=[tmp_path])
    assert {tool.name for tool in tools} == {"read_file", "list_files", "search_files"}
    a = agent(*tools)
    result = await a.call_tool("read_file", path=str(path), max_chars=6)
    assert result["content"] == "First " and result["next_offset"] == 6
    rest = await a.call_tool("read_file", path=str(path), offset=result["next_offset"])
    assert result["content"] + rest["content"] == path.read_text()
    result = await a.call_tool("list_files", path=str(tmp_path), pattern="*.txt")
    assert result["items"] == [{"path": str(path), "type": "file"}]
    result = await a.call_tool("search_files", path=str(tmp_path), query="CAFÉ", max_results=1)
    assert result["items"][0]["line"] == 1 and result["truncated"]
    result = await a.call_tool("search_files", path=str(tmp_path), query="not present")
    assert result["skipped"] == 1 and result["items"] == []
    with pytest.raises(ValueError, match="binary"):
        await a.call_tool("read_file", path=str(tmp_path / "binary"))


@pytest.mark.asyncio
async def test_file_read_boundaries_and_policy(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    private = tmp_path / "outside"
    private.write_text("secret")
    (root / "link").symlink_to(private)
    (root / "dirlink").symlink_to(tmp_path, target_is_directory=True)
    a = agent(*filesystem_tools(roots=[root]))
    for target in (root / "link", private, root / ".." / "outside"):
        with pytest.raises((OSError, ValueError)):
            await a.call_tool("read_file", path=str(target))
    result = await a.call_tool("search_files", path=str(root), query="secret")
    assert result["items"] == []
    with pytest.raises(OSError):
        await a.call_tool("list_files", path=str(root / "dirlink"))
    a.action_authorizer.policy = CapabilityPolicy({"filesystem.read": "deny"})
    with pytest.raises(ActionDeniedError):
        await a.call_tool("read_file", path=str(root / "missing"))


@pytest.mark.asyncio
async def test_exact_edits_preview_ambiguity_and_recovery(tmp_path):
    path = tmp_path / "code.py"
    path.write_text("value = 1\nother = 1\n")
    previews = []

    async def approve(request, context):
        previews.append(request.action.artifacts[0].parts[0].content)
        return True

    a = agent(
        *filesystem_tools(roots=[tmp_path], checkpoints=StorageCheckpointStore(memory())),
        policy=CapabilityPolicy({"filesystem.write": "require_approval"}),
        approval_handler=approve,
    )
    with pytest.raises(ValueError, match="exactly once"):
        await a.call_tool("edit_file", path=str(path), old_text="1", new_text="2")
    assert previews == []
    change = await a.call_tool("edit_file", path=str(path), old_text="1", new_text="2", replace_all=True)
    assert path.read_text() == "value = 2\nother = 2\n" and "+value = 2" in previews[0]
    await a.call_tool("restore_change", change_id=change["change_id"])
    assert path.read_text() == "value = 1\nother = 1\n"

    async def modify_before_approval(request, context):
        path.write_text("external change")
        return True

    a.action_authorizer.approval_handler = modify_before_approval
    with pytest.raises(ResourceConflictError):
        await a.call_tool("edit_file", path=str(path), old_text="value = 1", new_text="value = 3")
    assert path.read_text() == "external change"


@pytest.mark.asyncio
async def test_size_and_recursive_file_limits(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    (child / "large.txt").write_text("x" * 100)
    (child / "small.txt").write_text("yes")
    a = agent(*filesystem_tools(roots=[tmp_path], max_file_bytes=10))
    result = await a.call_tool("list_files", path=str(tmp_path), recursive=True, max_results=1)
    assert len(result["items"]) == 1 and result["truncated"]
    result = await a.call_tool("search_files", path=str(tmp_path), query="yes")
    assert result["items"][0]["path"].endswith("small.txt") and result["skipped"] == 1
    with pytest.raises(ValueError, match="size limit"):
        await a.call_tool("read_file", path=str(child / "large.txt"))


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_storage_crud_detached_values_and_namespace_isolation(tmp_path, persistent):
    store = SQLiteStorage(str(tmp_path / "data.db"), namespace="tools") if persistent else memory()
    a = agent(*storage_tools(store, allow_write=True))
    assert await a.call_tool("get_value", key="missing") == {"key": "missing", "found": False, "value": None}
    assert (await a.call_tool("set_value", key="a", value={"nested": [1]}))["created"]
    assert not (await a.call_tool("set_value", key="a", value=None))["created"]
    assert (await a.call_tool("get_value", key="a"))["found"]
    await a.call_tool("set_value", key="b", value={"nested": [1]})
    value = await a.call_tool("get_value", key="b")
    value["value"]["nested"].append(2)
    assert (await a.call_tool("get_value", key="b"))["value"] == {"nested": [1]}
    assert await a.call_tool("list_keys", limit=1) == {"keys": ["a"], "next_offset": 1}
    assert (await a.call_tool("list_keys", prefix="b"))["keys"] == ["b"]
    assert (await a.call_tool("delete_value", key="a"))["deleted"]
    assert not (await a.call_tool("delete_value", key="a"))["deleted"]
    assert store.load() == {"b": {"nested": [1]}}
    if persistent:
        assert SQLiteStorage(str(tmp_path / "data.db"), namespace="other").load() is None
        assert SQLiteStorage(str(tmp_path / "data.db"), namespace="tools").load() == store.load()


@pytest.mark.asyncio
async def test_storage_limits_and_policy_prevent_mutation():
    store = memory()
    assert len(storage_tools(store)) == 2
    a = agent(*storage_tools(store, allow_write=True, max_value_bytes=10, max_keys=1))
    for value in ("x" * 20, float("nan")):
        with pytest.raises(ValueError):
            await a.call_tool("set_value", key="a", value=value)
    assert store.load() is None
    await a.call_tool("set_value", key="a", value=1)
    with pytest.raises(ValueError, match="max_keys"):
        await a.call_tool("set_value", key="b", value=2)
    a.action_authorizer.policy = CapabilityPolicy({"storage.write": "deny"})
    with pytest.raises(ActionDeniedError):
        await a.call_tool("delete_value", key="a")
    assert store.load() == {"a": 1}
    store.save(["not a map"])
    with pytest.raises(ValueError, match="JSON object"):
        await a.call_tool("list_keys")


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    requests, responses, clients = [], [], []

    async def respond(request):
        requests.append(request)
        response = responses.pop(0)
        return await response(request) if callable(response) else response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        value = original(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(value)
        return value

    monkeypatch.setattr(httpx, "AsyncClient", client)
    yield requests, responses
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_http_contract_refresh_and_dynamic_policy(transport):
    requests, responses = transport
    tokens = iter(["first-secret", "second-secret"])
    previews = []

    async def headers():
        return {"Authorization": f"Bearer {next(tokens)}"}

    async def approve(request, context):
        previews.append(request.action)
        return True

    a = agent(
        http_tool("https://api.example.com/v1/", headers=headers, allowed_methods=["GET", "POST"], name="api"),
        policy=CapabilityPolicy({"network.read": "allow", "network.write": "require_approval"}, default_effect="deny"),
        approval_handler=approve,
    )
    responses.extend(
        [
            httpx.Response(200, json={"items": []}, headers={"Set-Cookie": "private-cookie"}),
            httpx.Response(201, json={"id": 1}),
        ]
    )
    first = await a.call_tool("api", path="/items", query={"q": "a&b"})
    assert first["body"] == {"items": []} and first["body_encoding"] == "json" and previews == []
    assert "set-cookie" not in first["headers"]
    await a.call_tool("api", method="post", path="items", body={"label": "café"})
    assert len(previews) == 1 and previews[0].capabilities == frozenset({"network.write"})
    assert requests[0].url.path == "/v1/items" and requests[0].url.params["q"] == "a&b"
    assert [r.headers["Authorization"] for r in requests] == ["Bearer first-secret", "Bearer second-secret"]
    assert json.loads(requests[1].content) == {"label": "café"}
    assert "secret" not in str(previews) + json.dumps(a.to_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "../private",
        "%2e%2e/private",
        "a/%252e%252e/private",
        "//evil.example/a",
        "https://evil.example/a",
        "a\\..\\b",
        "x?token=a",
        "x#fragment",
        "x\nHost:evil",
        "%2f%2fevil",
    ],
)
async def test_http_path_cannot_escape_prefix_or_origin(transport, path):
    requests, _ = transport
    a = agent(http_tool("https://api.example.com/v1"))
    with pytest.raises(ValueError):
        await a.call_tool("http_request", path=path)
    assert requests == []


@pytest.mark.asyncio
async def test_http_method_body_and_byte_limits(transport):
    requests, responses = transport
    a = agent(http_tool("https://api.example.com/", max_request_bytes=10, max_response_bytes=10))
    with pytest.raises(ValueError, match="not enabled"):
        await a.call_tool("http_request", method="POST", body={"x": 1})
    with pytest.raises(ValueError, match="GET/HEAD"):
        await a.call_tool("http_request", body={"x": 1})
    assert requests == []
    responses.append(httpx.Response(200, content=b"x" * 11))
    with pytest.raises(ValueError, match="max_response_bytes"):
        await a.call_tool("http_request")
    a = agent(http_tool("https://api.example.com", allowed_methods=["POST"], max_request_bytes=4))
    with pytest.raises(ValueError, match="max_request_bytes"):
        await a.call_tool("http_request", method="POST", body={"long": "body"})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_statuses_binary_and_no_redirect_or_retry(transport):
    requests, responses = transport
    responses.extend(
        [
            httpx.Response(302, headers={"Location": "https://evil.example"}),
            httpx.Response(429, json={"error": "quota"}),
            httpx.Response(200, content=b"\x00\xff"),
        ]
    )
    a = agent(http_tool("https://api.example.com"))
    assert (await a.call_tool("http_request"))["status_code"] == 302
    assert (await a.call_tool("http_request"))["body"] == {"error": "quota"}
    result = await a.call_tool("http_request")
    assert result["body_encoding"] == "base64" and result["body"] == "AP8="
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_http_cancellation_and_denial_close_without_credentials(transport):
    requests, responses = transport
    started = asyncio.Event()

    async def pending(request):
        started.set()
        await asyncio.Event().wait()

    responses.append(pending)
    a = agent(http_tool("https://api.example.com"))
    task = asyncio.create_task(a.call_tool("http_request"))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    def never_resolve():
        pytest.fail("Denied requests must not resolve credentials")

    a = agent(
        http_tool("https://api.example.com", headers=never_resolve), policy=CapabilityPolicy(default_effect="deny")
    )
    with pytest.raises(ActionDeniedError):
        await a.call_tool("http_request")
    assert len(requests) == 1


def test_http_developer_configuration_and_copied_headers():
    with pytest.raises(ValueError):
        http_tool("http://localhost")
    http_tool("http://localhost", allow_http=True)
    with pytest.raises(ValueError):
        http_tool("https://user:password@example.com")
    with pytest.raises(ValueError):
        http_tool("https://example.com", allowed_methods=["CONNECT"])


@pytest.mark.asyncio
async def test_prepared_tools_reject_direct_calls(tmp_path):
    for tool in [*filesystem_tools(roots=[tmp_path]), *storage_tools(memory()), http_tool("https://api.example.com")]:
        with pytest.raises(RuntimeError, match="authorization"):
            await tool()
