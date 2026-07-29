"""Typed data models shared by ProtoLink retrieval components.

The RAG module keeps its values deliberately provider-neutral. Loaders,
splitters, vector databases, custom retrievers, agent tools, and citations all
exchange these small dataclasses instead of leaking a vendor SDK's response
types through the public API.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any


def stable_id(prefix: str, *values: object) -> str:
    """Return a compact deterministic identifier for the supplied values."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(str(value).encode("utf-8", errors="replace"))
        digest.update(b"\x00")
    return f"{prefix}_{digest.hexdigest()[:24]}"


@dataclass(slots=True)
class Document:
    """One source document before it is divided into retrievable chunks.

    Args:
        text: Plain-text document content.
        source: Optional path, URL, database key, or human-readable origin.
        metadata: Application metadata retained through chunking and search.
        id: Stable document identifier. When omitted, ProtoLink derives one
            from ``source`` and ``text``.
        media_type: MIME type describing the original source.
    """

    text: str
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        """Validate content and create a deterministic identifier."""
        if not isinstance(self.text, str):
            raise TypeError("Document text must be a string")
        if not self.text.strip():
            raise ValueError("Document text cannot be empty")
        self.metadata = dict(self.metadata)
        self.id = self.id or stable_id("doc", self.source or "", self.text)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        """Reconstruct a document from serialized data."""
        return cls(
            text=str(data["text"]),
            source=data.get("source"),
            metadata=dict(data.get("metadata") or {}),
            id=data.get("id"),
            media_type=str(data.get("media_type") or "text/plain"),
        )


@dataclass(slots=True)
class Chunk:
    """A bounded document passage stored and returned by retrieval.

    Args:
        text: Passage content.
        document_id: Identifier of the parent :class:`Document`.
        index: Zero-based position inside the parent document.
        source: Original document origin.
        metadata: Metadata inherited from the document and splitter.
        id: Stable chunk identifier. When omitted, ProtoLink derives one.
    """

    text: str
    document_id: str
    index: int
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str | None = None

    def __post_init__(self) -> None:
        """Validate content and create a deterministic identifier."""
        if not isinstance(self.text, str):
            raise TypeError("Chunk text must be a string")
        if not self.text.strip():
            raise ValueError("Chunk text cannot be empty")
        if self.index < 0:
            raise ValueError("Chunk index cannot be negative")
        self.metadata = dict(self.metadata)
        self.id = self.id or stable_id("chunk", self.document_id, self.index, self.text)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chunk:
        """Reconstruct a chunk from serialized data."""
        return cls(
            text=str(data["text"]),
            document_id=str(data["document_id"]),
            index=int(data["index"]),
            source=data.get("source"),
            metadata=dict(data.get("metadata") or {}),
            id=data.get("id"),
        )


@dataclass(slots=True)
class VectorRecord:
    """A chunk paired with its vector representation for storage adapters."""

    chunk: Chunk
    embedding: list[float]

    def __post_init__(self) -> None:
        """Normalize numeric vectors and reject empty embeddings."""
        if not self.embedding:
            raise ValueError("VectorRecord embedding cannot be empty")
        self.embedding = [float(value) for value in self.embedding]


@dataclass(slots=True)
class SearchHit:
    """One normalized retrieval result.

    ``SearchHit`` is the only result shape the Agent integration needs. A
    custom store may therefore participate in ProtoLink RAG by returning these
    values without implementing ingestion, embeddings, or vector persistence.
    """

    text: str
    score: float | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    document_id: str | None = None
    chunk_id: str | None = None
    rank: int | None = None

    def __post_init__(self) -> None:
        """Copy mutable metadata and normalize optional scalars."""
        if not isinstance(self.text, str):
            raise TypeError("SearchHit text must be a string")
        if not self.text.strip():
            raise ValueError("SearchHit text cannot be empty")
        self.metadata = dict(self.metadata)
        if self.score is not None:
            self.score = float(self.score)
            if not math.isfinite(self.score):
                self.score = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchHit:
        """Reconstruct a search result from serialized data."""
        return cls(
            text=str(data["text"]),
            score=data.get("score"),
            source=data.get("source"),
            metadata=dict(data.get("metadata") or {}),
            document_id=data.get("document_id"),
            chunk_id=data.get("chunk_id"),
            rank=data.get("rank"),
        )


@dataclass(slots=True)
class Citation:
    """A source reference associated with a grounded answer."""

    number: int
    source: str | None
    excerpt: str
    score: float | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Return the compact label models are instructed to emit."""
        return f"[{self.number}]"

    @classmethod
    def from_hit(cls, hit: SearchHit, number: int) -> Citation:
        """Create a citation from a ranked search result."""
        return cls(
            number=number,
            source=hit.source,
            excerpt=hit.text,
            score=hit.score,
            document_id=hit.document_id,
            chunk_id=hit.chunk_id,
            metadata=dict(hit.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary representation."""
        data = asdict(self)
        data["label"] = self.label
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Citation:
        """Reconstruct a citation from serialized data."""
        return cls(
            number=int(data["number"]),
            source=data.get("source"),
            excerpt=str(data["excerpt"]),
            score=data.get("score"),
            document_id=data.get("document_id"),
            chunk_id=data.get("chunk_id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class RAGAnswer:
    """A deterministic retrieve-then-answer result returned by ``Agent.ask``."""

    text: str
    citations: list[Citation] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    query: str | None = None

    def __str__(self) -> str:
        """Return only the user-facing answer text."""
        return self.text

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary representation."""
        return {
            "text": self.text,
            "query": self.query,
            "citations": [citation.to_dict() for citation in self.citations],
            "hits": [hit.to_dict() for hit in self.hits],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RAGAnswer:
        """Reconstruct a grounded answer from serialized data."""
        return cls(
            text=str(data["text"]),
            citations=[Citation.from_dict(item) for item in data.get("citations", [])],
            hits=[SearchHit.from_dict(item) for item in data.get("hits", [])],
            query=data.get("query"),
        )


@dataclass(slots=True)
class IndexReport:
    """Summary of a completed ingestion or synchronization operation."""

    documents: int = 0
    chunks: int = 0
    added: int = 0
    deleted: int = 0
    skipped: int = 0
    sources: list[str] = field(default_factory=list)

    def merge(self, other: IndexReport) -> IndexReport:
        """Return a report containing the totals from both operations."""
        return IndexReport(
            documents=self.documents + other.documents,
            chunks=self.chunks + other.chunks,
            added=self.added + other.added,
            deleted=self.deleted + other.deleted,
            skipped=self.skipped + other.skipped,
            sources=list(dict.fromkeys([*self.sources, *other.sources])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary representation."""
        return asdict(self)
