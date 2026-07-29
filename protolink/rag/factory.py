"""Factory for opinionated ProtoLink knowledge backends."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .embeddings import HashEmbedder
from .knowledge import Knowledge
from .loaders import AutoLoader
from .protocols import Embedder, Loader, Reranker, SearchMode, Splitter, VectorStore
from .retrievers import ChromaRetriever, PineconeRetriever, QdrantRetriever, VectorStoreRetriever
from .splitters import RecursiveCharacterSplitter
from .stores import InMemoryVectorStore, SQLiteVectorStore


def create_knowledge(
    backend: str | Any = "memory",
    *,
    name: str = "knowledge",
    description: str | None = None,
    sources: Any | Sequence[Any] | None = None,
    default_k: int = 5,
    context_max_chars: int = 12_000,
    loader: Loader | None = None,
    splitter: Splitter | None = None,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    reranker: Reranker | None = None,
    mode: SearchMode | None = None,
    score_threshold: float | None = None,
    fetch_k: int | None = None,
    mmr_lambda: float | None = None,
    where: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Knowledge:
    """Create managed local knowledge or adapt an existing external index.

    Built-in backend aliases:

    - ``"memory"``: dependency-free, process-local exact search.
    - ``"sqlite"``: dependency-free persistent exact search.
    - ``"vector"``: caller-supplied ``store`` and ``embedder``.
    - ``"chroma"``: existing Chroma ``collection``.
    - ``"pinecone"``: existing Pinecone ``index`` and matching ``embedder``.
    - ``"qdrant"``: existing Qdrant ``client``, ``collection_name``, and matching ``embedder``.

    A retriever object or callable may be passed directly instead of an alias.
    Staged ``sources`` are indexed lazily on the first search or explicitly via
    ``knowledge.ready()`` / ``knowledge.sync.ready()``.
    """
    if not isinstance(backend, str):
        if sources is not None:
            raise ValueError("A custom retriever cannot ingest sources; provide managed Knowledge components")
        if any(component is not None for component in (loader, splitter, embedder, store)):
            raise TypeError("Custom retrievers cannot use loader, splitter, embedder, or store factory arguments")
        if mode is not None or fetch_k is not None or mmr_lambda is not None:
            raise TypeError("Custom retrievers control their own search mode, fetch size, and diversity")
        _reject_kwargs("custom", kwargs)
        return Knowledge(
            backend,
            name=name,
            description=description,
            default_k=default_k,
            reranker=reranker,
            where=where,
            score_threshold=score_threshold,
            context_max_chars=context_max_chars,
        )

    backend_key = backend.strip().casefold()
    if backend_key in {"memory", "sqlite", "vector"}:
        active_embedder = embedder or HashEmbedder()
        active_loader = loader or AutoLoader()
        active_splitter = splitter or RecursiveCharacterSplitter()
        if backend_key == "memory":
            active_store = store or InMemoryVectorStore()
        elif backend_key == "sqlite":
            path = kwargs.pop("path", None)
            if store is not None:
                active_store = store
            elif path is None:
                raise ValueError("create_knowledge('sqlite') requires path='knowledge.db'")
            else:
                active_store = SQLiteVectorStore(
                    Path(path),
                    namespace=str(kwargs.pop("namespace", name)),
                )
        else:
            if store is None:
                raise ValueError("create_knowledge('vector') requires store=...")
            active_store = store
        _reject_kwargs(backend_key, kwargs)
        retriever = VectorStoreRetriever(
            active_store,
            active_embedder,
            mode=mode or "hybrid",
            default_k=default_k,
            score_threshold=score_threshold,
            fetch_k=fetch_k,
            mmr_lambda=mmr_lambda,
        )
        return Knowledge(
            retriever,
            name=name,
            description=description,
            default_k=default_k,
            reranker=reranker,
            where=where,
            score_threshold=score_threshold,
            loader=active_loader,
            splitter=active_splitter,
            embedder=active_embedder,
            store=active_store,
            context_max_chars=context_max_chars,
            pending_sources=sources,
        )

    if sources:
        raise ValueError(
            f"Backend '{backend_key}' adapts an existing index and cannot ingest sources. "
            "Index them through that database or pass a managed VectorStore."
        )
    if any(component is not None for component in (loader, splitter, store)):
        raise TypeError(f"Backend '{backend_key}' is retrieval-only and does not accept loader, splitter, or store")
    if mode not in {None, "vector"}:
        raise ValueError(f"Backend '{backend_key}' supports vector retrieval only")
    if fetch_k is not None or mmr_lambda is not None:
        raise TypeError(f"Backend '{backend_key}' does not implement fetch_k or MMR; configure those in the database")
    if backend_key == "chroma":
        collection = kwargs.pop("collection", None)
        retriever = ChromaRetriever(
            collection,
            embedder=embedder,
            source_key=str(kwargs.pop("source_key", "source")),
        )
    elif backend_key == "pinecone":
        if embedder is None:
            raise ValueError("Pinecone retrieval requires the embedder used to build the index")
        retriever = PineconeRetriever(
            kwargs.pop("index", None),
            embedder,
            namespace=kwargs.pop("namespace", None),
            text_key=str(kwargs.pop("text_key", "text")),
            source_key=str(kwargs.pop("source_key", "source")),
        )
    elif backend_key == "qdrant":
        if embedder is None:
            raise ValueError("Qdrant retrieval requires the embedder used to build the collection")
        retriever = QdrantRetriever(
            kwargs.pop("client", None),
            str(kwargs.pop("collection_name", "")),
            embedder,
            text_key=str(kwargs.pop("text_key", "text")),
            source_key=str(kwargs.pop("source_key", "source")),
            vector_name=kwargs.pop("vector_name", None),
            filter_converter=kwargs.pop("filter_converter", None),
        )
    else:
        raise ValueError(
            f"Unknown knowledge backend '{backend}'. "
            "Available backends: chroma, memory, pinecone, qdrant, sqlite, vector"
        )
    _reject_kwargs(backend_key, kwargs)
    return Knowledge(
        retriever,
        name=name,
        description=description,
        default_k=default_k,
        reranker=reranker,
        where=where,
        score_threshold=score_threshold,
        context_max_chars=context_max_chars,
    )


def _reject_kwargs(backend: str, kwargs: Mapping[str, Any]) -> None:
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected {backend} knowledge arguments: {names}")
