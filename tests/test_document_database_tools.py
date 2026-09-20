"""Real document formats and SQLite enforce bounded reads through ordinary Agents."""

import asyncio
import sqlite3
import zipfile

import pytest

from protolink import ActionDeniedError, Agent, AgentCard, CapabilityPolicy
from protolink.tools import SQLiteDatabase, database_tools, document_tools


def agent(*tools, **options):
    a = Agent(AgentCard(name="data", description="test", url="runtime://data"), verbosity=0, **options)
    for tool in tools:
        a.add_tool(tool)
    return a


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "db #&?.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL); "
            "INSERT INTO items VALUES (1, 'café'), (2, 'second'), (3, 'third'); "
            "CREATE VIEW names AS SELECT name FROM items;"
        )
    return path


@pytest.mark.asyncio
async def test_database_schema_parameters_rows_and_blobs(database):
    backend = SQLiteDatabase(database)
    a = agent(*database_tools(backend))
    schema = await a.call_tool("database_schema")
    assert [item["name"] for item in schema["tables"]] == ["items", "names"]
    assert schema["tables"][0]["columns"][1] == {
        "name": "name",
        "type": "TEXT",
        "nullable": False,
        "primary_key": False,
    }
    result = await a.call_tool(
        "query_database", sql="SELECT name, name FROM items WHERE id > ? ORDER BY id", parameters=[0], max_rows=2
    )
    assert result == {"columns": ["name", "name"], "rows": [["café", "café"], ["second", "second"]], "truncated": True}
    assert (await a.call_tool("query_database", sql="SELECT name FROM items WHERE id = :id", parameters={"id": 1}))[
        "rows"
    ] == [["café"]]
    assert (await backend.query(sql="SELECT X'00FF', NULL"))["rows"] == [[{"base64": "AP8="}, None]]
    result = await backend.query(sql="SELECT name FROM items WHERE name = ?", parameters=["' OR 1=1 --"])
    assert result["rows"] == []
    result = await backend.query(sql="WITH values_cte(x) AS (SELECT 42) SELECT x FROM values_cte")
    assert result["rows"] == [[42]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM items",
        "UPDATE items SET name='bad'",
        "DROP TABLE items",
        "CREATE TABLE bad (x)",
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA user_version=42",
        "PRAGMA journal_mode=WAL",
        "BEGIN",
        "VACUUM",
        "SELECT load_extension('malicious')",
        "SELECT 1; DELETE FROM items",
        "WITH all_items AS (SELECT * FROM items) DELETE FROM items WHERE id IN (SELECT id FROM all_items)",
    ],
)
async def test_sqlite_authorizer_denies_writes_and_escape_statements(database, sql):
    backend = SQLiteDatabase(database)
    with pytest.raises(sqlite3.Error):
        await backend.query(sql=sql)
    assert (await backend.query(sql="SELECT count(*) FROM items"))["rows"] == [[3]]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_database_byte_limits_and_schema_truncation(database):
    backend = SQLiteDatabase(database, max_tables=1)
    schema = await backend.describe_schema()
    assert len(schema["tables"]) == 1 and schema["truncated"]
    backend = SQLiteDatabase(database, max_result_bytes=1000)
    result = await backend.query(sql="SELECT replace(hex(zeroblob(200)), '0', 'a') AS body FROM items")
    assert len(result["rows"]) == 2 and result["truncated"]
    with pytest.raises(sqlite3.DataError):
        await backend.query(sql="SELECT zeroblob(1001)")


@pytest.mark.asyncio
async def test_database_timeout_and_cancellation_keep_loop_responsive(database):
    sql = "WITH RECURSIVE counter(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM counter) SELECT sum(x) FROM counter"
    with pytest.raises(TimeoutError):
        await SQLiteDatabase(database, timeout_seconds=0.02).query(sql=sql)
    task = asyncio.create_task(SQLiteDatabase(database).query(sql=sql))
    await asyncio.sleep(0.02)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Cleanup cannot leave a connection locking out the next operation.
    result = await SQLiteDatabase(database).query(sql="SELECT 1")
    assert result["rows"] == [[1]]


@pytest.mark.asyncio
async def test_database_policy_validation_and_no_implicit_creation(tmp_path):
    path = tmp_path / "missing.sqlite"
    backend = SQLiteDatabase(path)
    assert not path.exists()
    a = agent(*database_tools(backend), policy=CapabilityPolicy({"database.read": "deny"}))
    with pytest.raises(ActionDeniedError):
        await a.call_tool("database_schema")
    with pytest.raises(ValueError):
        await backend.query(sql="SELECT ?", parameters=[{"not": "scalar"}])
    with pytest.raises(sqlite3.OperationalError):
        await backend.query(sql="SELECT 1")
    assert not path.exists()


@pytest.mark.asyncio
async def test_custom_database_backend_uses_same_contract():
    class Backend:
        async def describe_schema(self):
            return {"tables": [], "truncated": False}

        async def query(self, **kwargs):
            assert kwargs == {"sql": "SELECT ?", "parameters": [7], "max_rows": 5}
            return {"columns": ["value"], "rows": [[7]], "truncated": False}

    a = agent(*database_tools(Backend()))
    assert (await a.call_tool("query_database", sql="SELECT ?", parameters=[7], max_rows=5))["rows"] == [[7]]


@pytest.mark.asyncio
async def test_text_csv_search_and_source_locations(tmp_path):
    text = tmp_path / "notes.md"
    text.write_text("Heading\nCafé notes\nMore notes\n")
    csv = tmp_path / "data.csv"
    csv.write_text('name,note\n"Café","comma, included"\n')
    a = agent(*document_tools(roots=[tmp_path]))
    result = await a.call_tool("read_document", path=str(csv))
    assert result["sections"][1]["cells"] == ["Café", "comma, included"]
    assert result["sections"][1]["location"] == {"row": 2}
    assert result["metadata"]["format"] == "csv" and not result["truncated"]
    result = await a.call_tool("search_document", path=str(text), query="NOTES", max_results=1)
    assert result["matches"][0]["location"] == {"section": 1, "line": 2}
    assert result["matches"][0]["text"] == "Café notes" and result["truncated"]


@pytest.mark.asyncio
async def test_real_docx_paragraph_and_table_order(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Before the table")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Name", "Value"
    document.add_paragraph("After the table")
    path = tmp_path / "document.docx"
    document.save(path)
    result = await agent(*document_tools(roots=[tmp_path])).call_tool("read_document", path=str(path))
    assert [part["kind"] for part in result["sections"]] == ["text", "table_row", "text"]
    assert result["sections"][1]["cells"] == ["Name", "Value"]
    assert result["sections"][2]["text"] == "After the table"


@pytest.mark.asyncio
async def test_real_spreadsheet_cached_values_and_locations(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Name", "Amount"])
    sheet.append(["Café", 42])
    sheet.append(["Formula", "=B2*2"])
    path = tmp_path / "data.xlsx"
    workbook.save(path)
    workbook.close()
    result = await agent(*document_tools(roots=[tmp_path])).call_tool("read_document", path=str(path))
    assert result["sections"][1]["location"] == {"sheet": "Sales", "row": 2}
    assert result["sections"][1]["cells"] == ["Café", "42"]
    assert result["sections"][2]["cells"] == ["Formula", ""]  # No formula execution.


@pytest.mark.asyncio
async def test_real_pdf_text_and_page_locations(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 250 Td (Hello PDF) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "document.pdf"
    writer.write(path)
    writer.close()
    result = await agent(*document_tools(roots=[tmp_path])).call_tool("read_document", path=str(path))
    assert result["sections"][0]["text"] == "Hello PDF" and result["sections"][0]["location"] == {"page": 1}


@pytest.mark.asyncio
async def test_document_limits_archive_bounds_and_scoped_access(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "notes.txt"
    path.write_text("a" * 100 + "needle")
    a = agent(*document_tools(roots=[root], max_output_chars=10))
    result = await a.call_tool("read_document", path=str(path))
    assert result["sections"][0]["text"] == "a" * 10 and result["truncated"]
    result = await a.call_tool("search_document", path=str(path), query="needle")
    assert result["matches"] == [] and result["truncated"]
    csv = root / "rows.csv"
    csv.write_text("a,b\nc,d\n")
    result = await agent(*document_tools(roots=[root], max_sections=1)).call_tool("read_document", path=str(csv))
    assert len(result["sections"]) == 1 and result["truncated"]
    with pytest.raises(ValueError, match="size limit"):
        await agent(*document_tools(roots=[root], max_file_bytes=1)).call_tool("read_document", path=str(path))
    (root / "link.txt").symlink_to(path)
    with pytest.raises(OSError):
        await a.call_tool("read_document", path=str(root / "link.txt"))
    with pytest.raises(ValueError, match="outside"):
        await a.call_tool("read_document", path=str(tmp_path / "secret.txt"))
    archive = root / "bomb.docx"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("large.xml", "x" * 1000)
    with pytest.raises(ValueError, match="expansion limit"):
        await agent(*document_tools(roots=[root], max_archive_bytes=10)).call_tool("read_document", path=str(archive))


@pytest.mark.asyncio
async def test_document_policy_and_invalid_format(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"arbitrary")
    a = agent(*document_tools(roots=[tmp_path]))
    with pytest.raises(ValueError, match="Unsupported"):
        await a.call_tool("read_document", path=str(path))
    a.action_authorizer.policy = CapabilityPolicy({"filesystem.read": "deny"})
    with pytest.raises(ActionDeniedError):
        await a.call_tool("read_document", path=str(path))
    for tool in (*document_tools(roots=[tmp_path]), *database_tools(SQLiteDatabase(tmp_path / "missing"))):
        with pytest.raises(RuntimeError, match="authorization"):
            await tool()
