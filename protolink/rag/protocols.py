"""Structural extension contracts for ProtoLink retrieval.

Applications do not need to inherit from framework base classes. Any object that implements the relevant protocol can be
supplied to :class:`Knowledge`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from .models import Chunk, Document, SearchHit, VectorRecord

SearchMode = Literal["vector", "keyword", "hybrid"]
RetrievalMode = Literal["auto", "always", "required"]


@runtime_checkable
class Loader(Protocol):
    """Load one application source into normalized documents."""

    async def load(
        self,
        source: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[Document]:
        """Load ``source`` and preserve the supplied metadata."""
        ...


@runtime_checkable
class Splitter(Protocol):
    """Divide documents into bounded retrievable chunks."""

    def split(self, documents: Iterable[Document]) -> list[Chunk]:
        """Split documents while retaining source and metadata."""
        ...


@runtime_checkable
class Embedder(Protocol):
    """Create compatible vector representations for documents and queries."""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of document passages."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed one search query using the same vector space."""
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Persist vector records and perform normalized local-style search."""

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Insert or replace records and return the number written."""
        ...

    async def delete(
        self,
        *,
        ids: Sequence[str] | None = None,
        document_ids: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
        sources: Sequence[str] | None = None,
    ) -> int:
        """Delete matching records and return the number removed."""
        ...

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
        """Search records and return provider-neutral hits."""
        ...

    async def list_sources(self) -> list[str]:
        """Return distinct non-empty source identifiers in the store."""
        ...


@runtime_checkable
class AtomicVectorStore(VectorStore, Protocol):
    """Optional store extension for failure-safe source replacement."""

    async def replace(
        self,
        records: Sequence[VectorRecord],
        *,
        document_ids: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
    ) -> tuple[int, int]:
        """Atomically replace selected records and return ``(deleted, added)``."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """Return relevant passages for an unstructured query."""

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Return at most ``k`` normalized results."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Reorder retrieved candidates using query-aware relevance."""

    async def rerank(
        self,
        query: str,
        hits: Sequence[SearchHit],
        *,
        k: int,
    ) -> list[SearchHit]:
        """Return the best ``k`` candidates in descending relevance order."""
        ...
