"""Dependency-free vector stores for local ProtoLink knowledge bases.

Both stores use exact scanning. This makes their behavior deterministic and
keeps the base package small; hosted or approximate-nearest-neighbor databases
can be connected through the retriever adapters in :mod:`protolink.rag`.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Chunk, SearchHit, VectorRecord
from .protocols import SearchMode

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(slots=True)
class _StoredRecord:
    chunk: Chunk
    embedding: list[float]


class InMemoryVectorStore:
    """Exact-search vector store held in process memory.

    The implementation supports vector, BM25-style keyword, and weighted
    hybrid ranking, metadata filters, score thresholds, and maximal marginal
    relevance (MMR). It is a strong default for examples, tests, notebooks, and
    small transient indexes.
    """

    def __init__(self) -> None:
        self._records: dict[str, _StoredRecord] = {}
        self._dimensions: int | None = None
        self._lock = asyncio.Lock()

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Insert or replace records by chunk ID."""
        if not records:
            return 0
        dimensions = _record_dimensions(records)
        async with self._lock:
            if self._dimensions is not None and dimensions != self._dimensions:
                raise ValueError(f"Embedding dimension mismatch: store uses {self._dimensions}, received {dimensions}")
            self._dimensions = dimensions
            for record in records:
                self._records[str(record.chunk.id)] = _StoredRecord(
                    chunk=record.chunk,
                    embedding=list(record.embedding),
                )
        return len(records)

    async def replace(
        self,
        records: Sequence[VectorRecord],
        *,
        document_ids: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[int, int]:
        """Atomically remove selected records and insert their replacements."""
        dimensions = _record_dimensions(records) if records else None
        document_set = set(document_ids or ())
        source_set = set(sources or ())
        prepared = {
            str(record.chunk.id): _StoredRecord(
                chunk=record.chunk,
                embedding=list(record.embedding),
            )
            for record in records
        }
        async with self._lock:
            matched = {
                record_id
                for record_id, record in self._records.items()
                if record.chunk.document_id in document_set or record.chunk.source in source_set
            }
            retained = {record_id: record for record_id, record in self._records.items() if record_id not in matched}
            retained_dimensions = {len(record.embedding) for record in retained.values()}
            if dimensions is not None and retained_dimensions and retained_dimensions != {dimensions}:
                raise ValueError(
                    f"Embedding dimension mismatch: store uses {sorted(retained_dimensions)}, received {dimensions}"
                )
            self._records = {**retained, **prepared}
            self._dimensions = dimensions if dimensions is not None else next(iter(retained_dimensions), None)
        return len(matched), len(records)

    async def delete(
        self,
        *,
        ids: Sequence[str] | None = None,
        document_ids: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
        sources: Sequence[str] | None = None,
    ) -> int:
        """Delete records matching any explicit selector and all filters."""
        id_set = set(ids or ())
        document_set = set(document_ids or ())
        source_set = set(sources or ())
        if not (id_set or document_set or source_set or where):
            return 0

        async with self._lock:
            matched = [
                record_id
                for record_id, record in self._records.items()
                if _delete_match(
                    record,
                    ids=id_set,
                    document_ids=document_set,
                    sources=source_set,
                    where=where,
                )
            ]
            for record_id in matched:
                del self._records[record_id]
            if not self._records:
                self._dimensions = None
        return len(matched)

    async def search(
        self,
        *,
        query_vector: Sequence[float] | None,
        query_text: str,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
        mode: SearchMode = "vector",
        score_threshold: float | None = None,
        fetch_k: int | None = None,
        mmr_lambda: float | None = None,
    ) -> list[SearchHit]:
        """Search the in-memory index using exact ranking."""
        async with self._lock:
            records = list(self._records.values())
            dimensions = self._dimensions
        return _search_records(
            records,
            query_vector=query_vector,
            query_text=query_text,
            k=k,
            where=where,
            mode=mode,
            score_threshold=score_threshold,
            fetch_k=fetch_k,
            mmr_lambda=mmr_lambda,
            dimensions=dimensions,
        )

    async def list_sources(self) -> list[str]:
        """Return sorted distinct source identifiers."""
        async with self._lock:
            return sorted({record.chunk.source for record in self._records.values() if record.chunk.source})

    def __len__(self) -> int:
        """Return the current number of indexed chunks."""
        return len(self._records)


class SQLiteVectorStore:
    """Persistent exact-search vector store backed by the Python standard library.

    SQLite stores chunk text, metadata, and vectors durably; ranking is
    intentionally performed in Python so no native vector extension is
    required. This is suitable for local and moderate indexes. Large production
    corpora should use a dedicated vector database through a ProtoLink
    retriever adapter.

    Args:
        path: SQLite database path.
        namespace: Logical partition inside the database.
    """

    def __init__(self, path: str | Path, *, namespace: str = "default") -> None:
        if not namespace.strip():
            raise ValueError("SQLiteVectorStore namespace cannot be empty")
        self.path = Path(path).expanduser()
        self.namespace = namespace
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Insert or replace records in one transaction."""
        if not records:
            return 0
        _record_dimensions(records)
        return await asyncio.to_thread(self._upsert_sync, records)

    async def replace(
        self,
        records: Sequence[VectorRecord],
        *,
        document_ids: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[int, int]:
        """Atomically remove selected rows and insert their replacements."""
        if records:
            _record_dimensions(records)
        return await asyncio.to_thread(
            self._replace_sync,
            records,
            tuple(document_ids or ()),
            tuple(sources or ()),
        )

    async def delete(
        self,
        *,
        ids: Sequence[str] | None = None,
        document_ids: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
        sources: Sequence[str] | None = None,
    ) -> int:
        """Delete matching records and return the affected row count."""
        if not (ids or document_ids or sources or where):
            return 0
        return await asyncio.to_thread(
            self._delete_sync,
            tuple(ids or ()),
            tuple(document_ids or ()),
            dict(where or {}),
            tuple(sources or ()),
        )

    async def search(
        self,
        *,
        query_vector: Sequence[float] | None,
        query_text: str,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
        mode: SearchMode = "vector",
        score_threshold: float | None = None,
        fetch_k: int | None = None,
        mmr_lambda: float | None = None,
    ) -> list[SearchHit]:
        """Load the namespace and rank matching records exactly."""
        records = await asyncio.to_thread(self._read_records_sync)
        dimensions = len(records[0].embedding) if records else None
        return _search_records(
            records,
            query_vector=query_vector,
            query_text=query_text,
            k=k,
            where=where,
            mode=mode,
            score_threshold=score_threshold,
            fetch_k=fetch_k,
            mmr_lambda=mmr_lambda,
            dimensions=dimensions,
        )

    async def list_sources(self) -> list[str]:
        """Return sorted distinct source identifiers in this namespace."""
        return await asyncio.to_thread(self._list_sources_sync)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_vectors (
                    namespace TEXT NOT NULL,
                    id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    source TEXT,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    PRIMARY KEY (namespace, id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_vectors_document
                ON rag_vectors(namespace, document_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_vectors_source
                ON rag_vectors(namespace, source)
                """
            )

    def _upsert_sync(self, records: Sequence[VectorRecord]) -> int:
        dimensions = _record_dimensions(records)
        rows = self._record_rows(records, dimensions)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT DISTINCT dimensions FROM rag_vectors WHERE namespace = ?",
                (self.namespace,),
            ).fetchall()
            known_dimensions = {int(row["dimensions"]) for row in existing}
            if known_dimensions and known_dimensions != {dimensions}:
                raise ValueError(
                    f"Embedding dimension mismatch: store uses {sorted(known_dimensions)}, received {dimensions}"
                )
            connection.executemany(
                """
                INSERT INTO rag_vectors (
                    namespace, id, document_id, chunk_index, source, text,
                    metadata_json, embedding_json, dimensions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, id) DO UPDATE SET
                    document_id = excluded.document_id,
                    chunk_index = excluded.chunk_index,
                    source = excluded.source,
                    text = excluded.text,
                    metadata_json = excluded.metadata_json,
                    embedding_json = excluded.embedding_json,
                    dimensions = excluded.dimensions
                """,
                rows,
            )
        return len(rows)

    def _replace_sync(
        self,
        records: Sequence[VectorRecord],
        document_ids: Sequence[str],
        sources: Sequence[str],
    ) -> tuple[int, int]:
        dimensions = _record_dimensions(records) if records else None
        rows = self._record_rows(records, dimensions) if dimensions is not None else []
        selectors: list[str] = []
        selector_values: list[str] = []
        if document_ids:
            selectors.append(f"document_id IN ({', '.join('?' for _ in document_ids)})")
            selector_values.extend(document_ids)
        if sources:
            selectors.append(f"source IN ({', '.join('?' for _ in sources)})")
            selector_values.extend(sources)
        selector = " OR ".join(selectors) if selectors else "0"

        with self._lock, self._connect() as connection:
            retained_rows = connection.execute(
                f"""
                SELECT DISTINCT dimensions
                FROM rag_vectors
                WHERE namespace = ? AND NOT ({selector})
                """,
                (self.namespace, *selector_values),
            ).fetchall()
            retained_dimensions = {int(row["dimensions"]) for row in retained_rows}
            if dimensions is not None and retained_dimensions and retained_dimensions != {dimensions}:
                raise ValueError(
                    f"Embedding dimension mismatch: store uses {sorted(retained_dimensions)}, received {dimensions}"
                )
            count_row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM rag_vectors
                WHERE namespace = ? AND ({selector})
                """,
                (self.namespace, *selector_values),
            ).fetchone()
            deleted = int(count_row["count"]) if count_row is not None else 0
            connection.execute(
                f"""
                DELETE FROM rag_vectors
                WHERE namespace = ? AND ({selector})
                """,
                (self.namespace, *selector_values),
            )
            if rows:
                connection.executemany(
                    """
                    INSERT INTO rag_vectors (
                        namespace, id, document_id, chunk_index, source, text,
                        metadata_json, embedding_json, dimensions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(namespace, id) DO UPDATE SET
                        document_id = excluded.document_id,
                        chunk_index = excluded.chunk_index,
                        source = excluded.source,
                        text = excluded.text,
                        metadata_json = excluded.metadata_json,
                        embedding_json = excluded.embedding_json,
                        dimensions = excluded.dimensions
                    """,
                    rows,
                )
        return deleted, len(rows)

    def _record_rows(
        self,
        records: Sequence[VectorRecord],
        dimensions: int,
    ) -> list[tuple[Any, ...]]:
        return [
            (
                self.namespace,
                str(record.chunk.id),
                record.chunk.document_id,
                record.chunk.index,
                record.chunk.source,
                record.chunk.text,
                json.dumps(record.chunk.metadata, ensure_ascii=False, sort_keys=True, default=str),
                json.dumps(record.embedding),
                dimensions,
            )
            for record in records
        ]

    def _read_records_sync(self) -> list[_StoredRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, document_id, chunk_index, source, text, metadata_json, embedding_json
                FROM rag_vectors
                WHERE namespace = ?
                ORDER BY id
                """,
                (self.namespace,),
            ).fetchall()
        return [
            _StoredRecord(
                chunk=Chunk(
                    id=str(row["id"]),
                    document_id=str(row["document_id"]),
                    index=int(row["chunk_index"]),
                    source=row["source"],
                    text=str(row["text"]),
                    metadata=json.loads(row["metadata_json"]),
                ),
                embedding=[float(value) for value in json.loads(row["embedding_json"])],
            )
            for row in rows
        ]

    def _delete_sync(
        self,
        ids: Sequence[str],
        document_ids: Sequence[str],
        where: Mapping[str, Any],
        sources: Sequence[str],
    ) -> int:
        # Metadata filtering is evaluated through the same portable matcher as
        # the in-memory store. This also keeps behavior consistent when SQLite
        # JSON1 is unavailable.
        records = self._read_records_sync()
        matched = [
            str(record.chunk.id)
            for record in records
            if _delete_match(
                record,
                ids=set(ids),
                document_ids=set(document_ids),
                sources=set(sources),
                where=where or None,
            )
        ]
        if not matched:
            return 0
        placeholders = ", ".join("?" for _ in matched)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM rag_vectors WHERE namespace = ? AND id IN ({placeholders})",
                (self.namespace, *matched),
            )
            return max(cursor.rowcount, 0)

    def _list_sources_sync(self) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT source
                FROM rag_vectors
                WHERE namespace = ? AND source IS NOT NULL AND source != ''
                ORDER BY source
                """,
                (self.namespace,),
            ).fetchall()
        return [str(row["source"]) for row in rows]


def _record_dimensions(records: Sequence[VectorRecord]) -> int:
    dimensions = len(records[0].embedding)
    if dimensions == 0:
        raise ValueError("Embedding vectors cannot be empty")
    if any(len(record.embedding) != dimensions for record in records):
        raise ValueError("All embedding vectors must have the same dimensions")
    return dimensions


def _search_records(
    records: Sequence[_StoredRecord],
    *,
    query_vector: Sequence[float] | None,
    query_text: str,
    k: int,
    where: Mapping[str, Any] | None,
    mode: SearchMode,
    score_threshold: float | None,
    fetch_k: int | None,
    mmr_lambda: float | None,
    dimensions: int | None,
) -> list[SearchHit]:
    if k <= 0:
        raise ValueError("k must be greater than zero")
    if mode not in {"vector", "keyword", "hybrid"}:
        raise ValueError("mode must be 'vector', 'keyword', or 'hybrid'")
    if mode != "keyword":
        if query_vector is None:
            raise ValueError(f"{mode} search requires a query vector")
        if dimensions is not None and len(query_vector) != dimensions:
            raise ValueError(f"Query dimension mismatch: store uses {dimensions}, received {len(query_vector)}")
    if mmr_lambda is not None and not 0.0 <= mmr_lambda <= 1.0:
        raise ValueError("mmr_lambda must be between 0 and 1")
    if fetch_k is not None and mmr_lambda is None:
        raise ValueError("fetch_k configures the MMR candidate pool and requires mmr_lambda")

    candidates = [record for record in records if _matches_where(record, where)]
    if not candidates:
        return []

    vector_scores = {
        str(record.chunk.id): max(0.0, _cosine(query_vector or (), record.embedding)) for record in candidates
    }
    keyword_scores = _bm25_scores(query_text, candidates)
    scored: list[tuple[_StoredRecord, float]] = []
    for record in candidates:
        record_id = str(record.chunk.id)
        if mode == "vector":
            score = vector_scores[record_id]
        elif mode == "keyword":
            score = keyword_scores[record_id]
        else:
            score = 0.7 * vector_scores[record_id] + 0.3 * keyword_scores[record_id]
        if score_threshold is not None and score < score_threshold:
            continue
        if mode in {"keyword", "hybrid"} and score <= 0.0:
            continue
        scored.append((record, score))

    scored.sort(key=lambda item: (-item[1], str(item[0].chunk.id)))
    candidate_limit = max(k, fetch_k or (k * 4 if mmr_lambda is not None else k))
    scored = scored[:candidate_limit]
    if mmr_lambda is not None:
        scored = _mmr_select(scored, k=k, relevance_weight=mmr_lambda)
    else:
        scored = scored[:k]

    hits: list[SearchHit] = []
    for rank, (record, score) in enumerate(scored, start=1):
        hits.append(
            SearchHit(
                text=record.chunk.text,
                score=round(score, 8),
                source=record.chunk.source,
                metadata={
                    **record.chunk.metadata,
                    "_rag": {
                        "vector_score": round(vector_scores[str(record.chunk.id)], 8),
                        "keyword_score": round(keyword_scores[str(record.chunk.id)], 8),
                        "mode": mode,
                    },
                },
                document_id=record.chunk.document_id,
                chunk_id=str(record.chunk.id),
                rank=rank,
            )
        )
    return hits


def _mmr_select(
    scored: Sequence[tuple[_StoredRecord, float]],
    *,
    k: int,
    relevance_weight: float,
) -> list[tuple[_StoredRecord, float]]:
    remaining = list(scored)
    selected: list[tuple[_StoredRecord, float]] = []
    while remaining and len(selected) < k:
        if not selected:
            selected.append(remaining.pop(0))
            continue
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                relevance_weight * remaining[index][1]
                - (1.0 - relevance_weight)
                * max(_cosine(remaining[index][0].embedding, chosen[0].embedding) for chosen in selected),
                -index,
            ),
        )
        selected.append(remaining.pop(best_index))
    return selected


def _bm25_scores(query: str, records: Sequence[_StoredRecord]) -> dict[str, float]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return {str(record.chunk.id): 0.0 for record in records}

    documents = [_tokens(record.chunk.text) for record in records]
    average_length = sum(len(tokens) for tokens in documents) / max(len(documents), 1)
    frequencies = Counter(token for tokens in documents for token in set(tokens))
    raw_scores: dict[str, float] = {}
    k1 = 1.5
    b = 0.75
    count = len(documents)
    for record, tokens in zip(records, documents, strict=True):
        terms = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = terms[token]
            if not frequency:
                continue
            document_frequency = frequencies[token]
            inverse_frequency = math.log(1.0 + (count - document_frequency + 0.5) / (document_frequency + 0.5))
            length_factor = 1.0 - b + b * len(tokens) / max(average_length, 1.0)
            score += inverse_frequency * (frequency * (k1 + 1.0)) / (frequency + k1 * length_factor)
        raw_scores[str(record.chunk.id)] = score

    maximum = max(raw_scores.values(), default=0.0)
    if maximum <= 0:
        return dict.fromkeys(raw_scores, 0.0)
    return {record_id: score / maximum for record_id, score in raw_scores.items()}


def _tokens(value: str) -> list[str]:
    return [_normalize_token(token) for token in _TOKEN_RE.findall(value.casefold())]


def _normalize_token(token: str) -> str:
    """Apply conservative English plural normalization for keyword ranking."""
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _delete_match(
    record: _StoredRecord,
    *,
    ids: set[str],
    document_ids: set[str],
    sources: set[str],
    where: Mapping[str, Any] | None,
) -> bool:
    selectors = (
        (not ids and not document_ids and not sources)
        or str(record.chunk.id) in ids
        or record.chunk.document_id in document_ids
        or record.chunk.source in sources
    )
    return selectors and _matches_where(record, where)


def _matches_where(record: _StoredRecord, where: Mapping[str, Any] | None) -> bool:
    if not where:
        return True
    searchable = {
        **record.chunk.metadata,
        "id": str(record.chunk.id),
        "chunk_id": str(record.chunk.id),
        "document_id": record.chunk.document_id,
        "source": record.chunk.source,
    }
    return all(_matches_condition(_lookup(searchable, key), condition) for key, condition in where.items())


def _lookup(values: Mapping[str, Any], dotted_key: str) -> Any:
    current: Any = values
    for segment in dotted_key.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def _matches_condition(value: Any, condition: Any) -> bool:
    if not isinstance(condition, Mapping):
        return value == condition
    for operator, expected in condition.items():
        if operator == "$eq" and value != expected:
            return False
        if operator == "$ne" and value == expected:
            return False
        if operator == "$in" and value not in expected:
            return False
        if operator == "$nin" and value in expected:
            return False
        if operator == "$gt" and not (value is not None and value > expected):
            return False
        if operator == "$gte" and not (value is not None and value >= expected):
            return False
        if operator == "$lt" and not (value is not None and value < expected):
            return False
        if operator == "$lte" and not (value is not None and value <= expected):
            return False
        if operator == "$contains" and not (value is not None and expected in value):
            return False
        if operator not in {"$eq", "$ne", "$in", "$nin", "$gt", "$gte", "$lt", "$lte", "$contains"}:
            raise ValueError(f"Unsupported metadata filter operator: {operator}")
    return True
