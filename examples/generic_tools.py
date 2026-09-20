"""Exercise filesystem, storage, HTTP, documents, and database tools on one Agent.

Run: python examples/generic_tools.py
Install: pip install 'protolink[integrations]'

No account, model, or socket is used. Files/databases live in a temporary directory,
and HTTP uses MockTransport. The automatic approval callback is specific to this
offline demonstration. PDF/DOCX/XLSX extraction is covered by the format tests;
this example uses CSV so the documents extra is not required.
"""

import asyncio
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from protolink import Agent, AgentCard, CapabilityPolicy, StorageCheckpointStore
from protolink.storage import InMemoryStorage
from protolink.tools import SQLiteDatabase, database_tools, document_tools, filesystem_tools, http_tool, storage_tools


async def main() -> None:
    """Compose independent capabilities without choosing a domain-specific agent."""
    approvals = []

    async def approve(request, context):
        approvals.append(request.action.name)
        return True  # Only for the temporary resources and mock service below.

    def isolated_storage():
        return InMemoryStorage(store={}, ttl_heap=[])

    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        database = root / "data.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO items VALUES (1, 'example')")

        agent = Agent(
            AgentCard(name="generic", description="General capabilities", url="runtime://generic"),
            policy=CapabilityPolicy(
                {
                    "filesystem.read": "allow",
                    "filesystem.write": "require_approval",
                    "filesystem.restore": "require_approval",
                    "storage.read": "allow",
                    "storage.write": "require_approval",
                    "network.read": "allow",
                    "network.write": "require_approval",
                    "database.read": "allow",
                },
                default_effect="deny",
            ),
            approval_handler=approve,
            verbosity=0,
        )
        for tool in (
            *filesystem_tools(roots=[root], checkpoints=StorageCheckpointStore(isolated_storage())),
            *storage_tools(isolated_storage(), allow_write=True),
            http_tool("https://api.example.com/v1", allowed_methods=["GET", "POST"]),
            *document_tools(roots=[root]),
            *database_tools(SQLiteDatabase(database)),
        ):
            agent.add_tool(tool)

        path = str(root / "notes.txt")
        await agent.call_tool("create_file", path=path, content="hello world\n")
        assert (await agent.call_tool("read_file", path=path))["content"] == "hello world\n"
        assert (await agent.call_tool("list_files", path=str(root), pattern="*.txt"))["items"][0]["path"] == path
        assert (await agent.call_tool("search_files", path=str(root), query="world", pattern="*.txt"))["items"][0][
            "line"
        ] == 1
        edited = await agent.call_tool("edit_file", path=path, old_text="world", new_text="tools")
        assert not (await agent.call_tool("preview_change", change_id=edited["change_id"]))["conflict"]
        await agent.call_tool("restore_change", change_id=edited["change_id"])
        await agent.call_tool("replace_file", path=path, content="replacement\n")
        assert Path(path).read_text() == "replacement\n"

        await agent.call_tool("set_value", key="example", value={"count": 1})
        assert (await agent.call_tool("get_value", key="example"))["value"] == {"count": 1}
        assert (await agent.call_tool("list_keys"))["keys"] == ["example"]
        assert (await agent.call_tool("delete_value", key="example"))["deleted"]

        original_client = httpx.AsyncClient

        def respond(request):
            assert request.url.host == "api.example.com" and request.url.path == "/v1/items"
            if request.method == "POST":
                assert json.loads(request.content) == {"name": "example"}
                return httpx.Response(201, json={"id": 1})
            return httpx.Response(200, json={"items": []})

        with patch.object(
            httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs)
        ):
            assert (await agent.call_tool("http_request", path="items"))["body"] == {"items": []}
            assert (await agent.call_tool("http_request", method="POST", path="items", body={"name": "example"}))[
                "status_code"
            ] == 201

        csv = root / "table.csv"
        csv.write_text("name,value\nexample,42\n")
        document = await agent.call_tool("read_document", path=str(csv))
        assert document["sections"][1]["cells"] == ["example", "42"]
        assert (await agent.call_tool("search_document", path=str(csv), query="EXAMPLE"))["matches"][0]["location"][
            "row"
        ] == 2

        assert (await agent.call_tool("database_schema"))["tables"][0]["name"] == "items"
        result = await agent.call_tool("query_database", sql="SELECT name FROM items WHERE id = ?", parameters=[1])
        assert result == {"columns": ["name"], "rows": [["example"]], "truncated": False}
        assert set(approvals) == {
            "create_file",
            "edit_file",
            "restore_change",
            "replace_file",
            "set_value",
            "delete_value",
            "http_request",
        }
        print("All five generic tool families passed, including approvals and file recovery.")


if __name__ == "__main__":
    asyncio.run(main())
