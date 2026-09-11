"""SQLite operations must release handles without relying on garbage collection."""

import sqlite3
from contextlib import closing

import pytest

from protolink import SQLiteRunStore
from protolink.devtools.server import _validate_run_store_path
from protolink.rag import Chunk, SQLiteVectorStore, VectorRecord


@pytest.fixture
def connections(monkeypatch):
    """Retain connections so tests observe explicit closure, with reliable teardown."""
    opened = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        # Store operations run on worker threads. Allow assertions and teardown
        # on the test thread without changing where the operations execute.
        kwargs["check_same_thread"] = False
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    yield opened
    for connection in opened:
        connection.close()


def assert_closed(connections):
    """Closed handles reject SQL even when a strong reference still exists."""
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def record(name):
    return VectorRecord(Chunk(text=name, document_id=name, index=0, source=f"{name}.md", id=name), [1.0, 0.0])


@pytest.mark.asyncio
async def test_vector_store_closes_connections_and_commits_each_operation(tmp_path, connections):
    path = tmp_path / "knowledge.db"
    store = SQLiteVectorStore(path)
    assert_closed(connections)
    assert await store.upsert([record("original")]) == 1
    assert_closed(connections)

    reopened = SQLiteVectorStore(path)
    assert await reopened.list_sources() == ["original.md"]
    assert_closed(connections)
    hits = await reopened.search(query_vector=[1.0, 0.0], query_text="original")
    assert [hit.chunk_id for hit in hits] == ["original"]
    assert_closed(connections)

    assert await store.replace([record("replacement")], sources=["original.md"]) == (1, 1)
    assert_closed(connections)
    assert await reopened.list_sources() == ["replacement.md"]
    assert await store.delete(ids=["replacement"]) == 1
    assert_closed(connections)
    assert await reopened.list_sources() == []
    assert_closed(connections)


@pytest.mark.asyncio
async def test_failed_vector_replace_rolls_back_and_closes_connection(tmp_path, connections):
    path = tmp_path / "knowledge.db"
    store = SQLiteVectorStore(path)
    await store.upsert([record("original")])
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """CREATE TRIGGER reject_bad BEFORE INSERT ON rag_vectors
               WHEN NEW.id = 'bad' BEGIN SELECT RAISE(ABORT, 'rejected record'); END"""
        )

    # Fail after deleting the preimage and inserting the first replacement.
    with pytest.raises(sqlite3.IntegrityError, match="rejected record"):
        await store.replace([record("good"), record("bad")], sources=["original.md"])
    assert_closed(connections)
    assert await SQLiteVectorStore(path).list_sources() == ["original.md"]
    assert_closed(connections)


def test_failed_vector_store_initialization_closes_connection(tmp_path, connections):
    path = tmp_path / "invalid.db"
    path.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        SQLiteVectorStore(path)
    assert_closed(connections)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["search", "list_sources"])
async def test_failed_vector_reads_close_connection(tmp_path, connections, operation):
    path = tmp_path / "knowledge.db"
    store = SQLiteVectorStore(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TABLE rag_vectors")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        if operation == "search":
            await store.search(query_vector=[1.0, 0.0], query_text="missing")
        else:
            await store.list_sources()
    assert_closed(connections)


@pytest.mark.parametrize("valid_schema", [True, False])
def test_dashboard_store_inspection_closes_connection(tmp_path, connections, valid_schema):
    path = tmp_path / "runs.db"
    SQLiteRunStore(path)
    if valid_schema:
        assert _validate_run_store_path(str(path)) == path.resolve()
    else:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("DROP TABLE protolink_tasks")
        with pytest.raises(ValueError, match="expected protolink_tasks schema"):
            _validate_run_store_path(str(path))
    assert_closed(connections)
