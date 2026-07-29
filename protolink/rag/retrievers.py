"""Retriever implementations for local stores, callables, and existing indexes."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, cast

from .models import Chunk, Document, SearchHit
from .protocols import Embedder, SearchMode, VectorStore

RetrieverFunction = Callable[..., Sequence[Any] | Awaitable[Sequence[Any]]]


class CallableRetriever:
    """Adapt an application search function to the ProtoLink retriever contract.

    The callable may be synchronous or asynchronous. ProtoLink passes ``query``
    and, when accepted by the signature, ``k`` and ``where``. Results may be
    :class:`SearchHit`, :class:`Document`, :class:`Chunk`, mapping, or string
    values and are normalized immediately.
    """

    def __init__(self, function: RetrieverFunction) -> None:
        if not callable(function):
            raise TypeError("CallableRetriever requires a callable")
        self.function = function
        self._signature = inspect.signature(function)

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Execute the callable and normalize its first ``k`` results."""
        kwargs: dict[str, Any] = {}
        if _accepts_keyword(self._signature, "k"):
            kwargs["k"] = k
        if _accepts_keyword(self._signature, "where"):
            kwargs["where"] = dict(where) if where else None
        result = await _call_maybe_async(self.function, query, **kwargs)
        return normalize_hits(cast(Sequence[Any], result), limit=k)


class VectorStoreRetriever:
    """Combine an embedder with a managed ProtoLink vector store."""

    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        *,
        mode: SearchMode = "hybrid",
        default_k: int = 5,
        score_threshold: float | None = None,
        fetch_k: int | None = None,
        mmr_lambda: float | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> None:
        if default_k <= 0:
            raise ValueError("default_k must be greater than zero")
        if mode not in {"vector", "keyword", "hybrid"}:
            raise ValueError("mode must be 'vector', 'keyword', or 'hybrid'")
        if fetch_k is not None and fetch_k <= 0:
            raise ValueError("fetch_k must be greater than zero")
        if fetch_k is not None and mmr_lambda is None:
            raise ValueError("fetch_k configures the MMR candidate pool and requires mmr_lambda")
        if mmr_lambda is not None and not 0.0 <= mmr_lambda <= 1.0:
            raise ValueError("mmr_lambda must be between 0 and 1")
        self.store = store
        self.embedder = embedder
        self.mode = mode
        self.default_k = default_k
        self.score_threshold = score_threshold
        self.fetch_k = fetch_k
        self.mmr_lambda = mmr_lambda
        self.where = dict(where or {})

    async def retrieve(
        self,
        query: str,
        *,
        k: int | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Embed the query and delegate normalized ranking to the store.

        Omit ``k`` to use the retriever's configured ``default_k``.
        """
        effective_k = self.default_k if k is None else k
        # Constructor filters are an application-owned scope (for example a
        # tenant boundary), so model- or request-provided filters may refine but
        # never replace them.
        effective_where = {**dict(where or {}), **self.where}
        query_vector = None if self.mode == "keyword" else await self.embedder.embed_query(query)
        return await self.store.search(
            query_vector=query_vector,
            query_text=query,
            k=effective_k,
            where=effective_where or None,
            mode=self.mode,
            score_threshold=self.score_threshold,
            fetch_k=self.fetch_k,
            mmr_lambda=self.mmr_lambda,
        )


class ChromaRetriever:
    """Search an existing Chroma collection.

    Args:
        collection: User-created Chroma collection.
        embedder: Optional query embedder. Omit it when the collection has its
            own embedding function and accepts ``query_texts``.
        source_key: Metadata field containing a displayable source.
    """

    def __init__(
        self,
        collection: Any,
        *,
        embedder: Embedder | None = None,
        source_key: str = "source",
    ) -> None:
        if collection is None:
            raise ValueError("ChromaRetriever requires a collection")
        self.collection = collection
        self.embedder = embedder
        self.source_key = source_key

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Query Chroma and normalize documents, distances, and metadata."""
        kwargs: dict[str, Any] = {
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = dict(where)
        if self.embedder is None:
            kwargs["query_texts"] = [query]
        else:
            kwargs["query_embeddings"] = [await self.embedder.embed_query(query)]
        response = await _call_maybe_async(self.collection.query, **kwargs)

        documents = _first_batch(_field(response, "documents", []))
        metadatas = _first_batch(_field(response, "metadatas", []))
        distances = _first_batch(_field(response, "distances", []))
        ids = _first_batch(_field(response, "ids", []))
        hits: list[SearchHit] = []
        for index, text in enumerate(documents[:k]):
            if text is None or not str(text).strip():
                continue
            metadata = dict(_at(metadatas, index, {}) or {})
            distance = _optional_float(_at(distances, index))
            hits.append(
                SearchHit(
                    text=str(text),
                    score=None if distance is None else 1.0 / (1.0 + max(distance, 0.0)),
                    source=_optional_str(metadata.get(self.source_key)),
                    metadata={**metadata, "_rag": {"distance": distance, "backend": "chroma"}},
                    chunk_id=_optional_str(_at(ids, index)),
                    rank=index + 1,
                )
            )
        return hits


class PineconeRetriever:
    """Search an existing Pinecone index with the index's matching embedder."""

    def __init__(
        self,
        index: Any,
        embedder: Embedder,
        *,
        namespace: str | None = None,
        text_key: str = "text",
        source_key: str = "source",
    ) -> None:
        if index is None:
            raise ValueError("PineconeRetriever requires an index")
        self.index = index
        self.embedder = embedder
        self.namespace = namespace
        self.text_key = text_key
        self.source_key = source_key

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Embed and query Pinecone, preserving match metadata."""
        kwargs: dict[str, Any] = {
            "vector": await self.embedder.embed_query(query),
            "top_k": k,
            "include_metadata": True,
        }
        if self.namespace is not None:
            kwargs["namespace"] = self.namespace
        if where:
            kwargs["filter"] = dict(where)
        response = await _call_maybe_async(self.index.query, **kwargs)

        matches = _field(response, "matches", []) or []
        hits: list[SearchHit] = []
        for index, match in enumerate(matches[:k]):
            metadata = dict(_field(match, "metadata", {}) or {})
            text = metadata.get(self.text_key, "")
            if not text:
                continue
            metadata.pop(self.text_key, None)
            hits.append(
                SearchHit(
                    text=str(text),
                    score=_optional_float(_field(match, "score")),
                    source=_optional_str(metadata.get(self.source_key)),
                    metadata={**metadata, "_rag": {"backend": "pinecone"}},
                    chunk_id=_optional_str(_field(match, "id")),
                    rank=index + 1,
                )
            )
        return hits


class QdrantRetriever:
    """Search an existing Qdrant collection using a user-owned client."""

    def __init__(
        self,
        client: Any,
        collection_name: str,
        embedder: Embedder,
        *,
        text_key: str = "text",
        source_key: str = "source",
        vector_name: str | None = None,
        filter_converter: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> None:
        if client is None:
            raise ValueError("QdrantRetriever requires a client")
        if not collection_name.strip():
            raise ValueError("Qdrant collection_name cannot be empty")
        self.client = client
        self.collection_name = collection_name
        self.embedder = embedder
        self.text_key = text_key
        self.source_key = source_key
        self.vector_name = vector_name
        self.filter_converter = filter_converter

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Query current or legacy Qdrant client surfaces and normalize points."""
        vector = await self.embedder.embed_query(query)
        if hasattr(self.client, "query_points"):
            kwargs: dict[str, Any] = {
                "collection_name": self.collection_name,
                "query": vector,
                "limit": k,
                "with_payload": True,
            }
            if self.vector_name is not None:
                kwargs["using"] = self.vector_name
            if where:
                kwargs["query_filter"] = self._convert_filter(where)
            response = await _call_maybe_async(self.client.query_points, **kwargs)
            points = _field(response, "points", response) or []
        elif hasattr(self.client, "search"):
            vector_query: Any = (self.vector_name, vector) if self.vector_name is not None else vector
            kwargs = {
                "collection_name": self.collection_name,
                "query_vector": vector_query,
                "limit": k,
                "with_payload": True,
            }
            if where:
                kwargs["query_filter"] = self._convert_filter(where)
            points = await _call_maybe_async(self.client.search, **kwargs)
        else:
            raise TypeError("Qdrant client must expose query_points() or search()")

        hits: list[SearchHit] = []
        for index, point in enumerate(list(points)[:k]):
            payload = dict(_field(point, "payload", {}) or {})
            text = payload.get(self.text_key, "")
            if not text:
                continue
            payload.pop(self.text_key, None)
            hits.append(
                SearchHit(
                    text=str(text),
                    score=_optional_float(_field(point, "score")),
                    source=_optional_str(payload.get(self.source_key)),
                    metadata={**payload, "_rag": {"backend": "qdrant"}},
                    chunk_id=_optional_str(_field(point, "id")),
                    rank=index + 1,
                )
            )
        return hits

    def _convert_filter(self, where: Mapping[str, Any]) -> Any:
        """Convert portable filters to an installed Qdrant client's model."""
        values = dict(where)
        if self.filter_converter is not None:
            return self.filter_converter(values)
        try:
            from qdrant_client import models
        except ImportError:
            # Keeps dependency-free stubs and remote wrappers usable. A real
            # qdrant-client installation is converted below for QdrantLocal and
            # strict SDK validation.
            return values
        return _qdrant_filter(models, values)


def normalize_hits(values: Sequence[Any] | None, *, limit: int | None = None) -> list[SearchHit]:
    """Normalize common custom-retriever result values."""
    if values is None:
        return []
    if isinstance(values, (str, bytes, Mapping)):
        raise TypeError("Retriever results must be a sequence, not one scalar value")
    hits: list[SearchHit] = []
    for rank, value in enumerate(values, start=1):
        if limit is not None and len(hits) >= limit:
            break
        hit = _normalize_hit(value)
        hit.rank = hit.rank or rank
        hits.append(hit)
    return hits


def _normalize_hit(value: Any) -> SearchHit:
    if isinstance(value, SearchHit):
        return SearchHit(**value.to_dict())
    if isinstance(value, Chunk):
        return SearchHit(
            text=value.text,
            source=value.source,
            metadata=dict(value.metadata),
            document_id=value.document_id,
            chunk_id=str(value.id),
        )
    if isinstance(value, Document):
        return SearchHit(
            text=value.text,
            source=value.source,
            metadata=dict(value.metadata),
            document_id=str(value.id),
        )
    if isinstance(value, str):
        return SearchHit(text=value)
    if isinstance(value, Mapping):
        text = value.get("text", value.get("content", value.get("page_content")))
        if text is None:
            raise ValueError("Retriever result mappings must contain 'text', 'content', or 'page_content'")
        known = {
            "text",
            "content",
            "page_content",
            "score",
            "source",
            "metadata",
            "document_id",
            "chunk_id",
            "id",
            "rank",
        }
        extra = {str(key): item for key, item in value.items() if key not in known}
        metadata = {**dict(value.get("metadata") or {}), **extra}
        return SearchHit(
            text=str(text),
            score=_optional_float(value.get("score")),
            source=_optional_str(value.get("source") or metadata.get("source")),
            metadata=metadata,
            document_id=_optional_str(value.get("document_id")),
            chunk_id=_optional_str(value.get("chunk_id", value.get("id"))),
            rank=int(value["rank"]) if value.get("rank") is not None else None,
        )
    raise TypeError(
        "Retriever results must contain SearchHit, Document, Chunk, mapping, or string values; "
        f"received {type(value).__name__}"
    )


def _accepts_keyword(signature: inspect.Signature, name: str) -> bool:
    parameter = signature.parameters.get(name)
    if parameter is not None and parameter.kind is not inspect.Parameter.POSITIONAL_ONLY:
        return True
    return any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_batch(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        first = value[0]
        if isinstance(first, Sequence) and not isinstance(first, (str, bytes)):
            return list(first)
        return list(value)
    return []


def _at(values: Sequence[Any], index: int, default: Any = None) -> Any:
    return values[index] if index < len(values) else default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


async def _call_maybe_async(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call async functions directly and offload synchronous SDK methods."""
    call = vars(type(function)).get("__call__")
    is_async = inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(call)
    result = function(*args, **kwargs) if is_async else await asyncio.to_thread(function, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _qdrant_filter(models: Any, where: Mapping[str, Any]) -> Any:
    """Build a Qdrant ``Filter`` from native or portable filter mappings."""
    if any(key in where for key in ("must", "must_not", "should", "min_should")):
        return models.Filter(**dict(where))

    must: list[Any] = []
    must_not: list[Any] = []
    for key, raw_condition in where.items():
        conditions = raw_condition if isinstance(raw_condition, Mapping) else {"$eq": raw_condition}
        range_values: dict[str, Any] = {}
        for operator, expected in conditions.items():
            if operator == "$eq":
                must.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=expected),
                    )
                )
            elif operator == "$ne":
                must_not.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=expected),
                    )
                )
            elif operator in {"$in", "$nin"}:
                condition = models.FieldCondition(
                    key=key,
                    match=models.MatchAny(any=list(expected)),
                )
                (must if operator == "$in" else must_not).append(condition)
            elif operator in {"$gt", "$gte", "$lt", "$lte"}:
                range_values[operator[1:]] = expected
            elif operator == "$contains":
                must.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchText(text=str(expected)),
                    )
                )
            else:
                raise ValueError(f"Unsupported Qdrant metadata filter operator: {operator}")
        if range_values:
            must.append(
                models.FieldCondition(
                    key=key,
                    range=models.Range(**range_values),
                )
            )
    return models.Filter(must=must or None, must_not=must_not or None)
