"""Dependency-light embedding implementations and callable adapters."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from itertools import pairwise
from typing import Any, cast

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)


class HashEmbedder:
    """Create deterministic lexical vectors without a model dependency.

    This embedder is intended for local development, examples, tests, and modest knowledge bases. It hashes normalized
    word and adjacent-word features into a fixed-size vector and L2-normalizes the result. It is not a neural semantic
    embedding model. Production applications can replace it with any object implementing
    :class:`~protolink.rag.Embedder`.

    Args:
        dimensions: Number of output vector dimensions.
        include_bigrams: Whether adjacent token pairs contribute features.
    """

    def __init__(self, dimensions: int = 384, *, include_bigrams: bool = True) -> None:
        if dimensions < 8:
            raise ValueError("HashEmbedder dimensions must be at least 8")
        self.dimensions = dimensions
        self.include_bigrams = include_bigrams

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed multiple passages in their input order."""
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query in the same lexical vector space."""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        tokens = [_normalize_token(token) for token in _TOKEN_RE.findall(text.casefold())]
        features = list(tokens)
        if self.include_bigrams:
            features.extend(f"{left}\x1f{right}" for left, right in pairwise(tokens))

        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            return [value / norm for value in vector]
        return vector


EmbeddingBatchFunction = Callable[
    [Sequence[str]],
    Sequence[Sequence[float]] | Awaitable[Sequence[Sequence[float]]],
]
EmbeddingQueryFunction = Callable[[str], Sequence[float] | Awaitable[Sequence[float]]]


class CallableEmbedder:
    """Adapt synchronous or asynchronous application embedding functions.

    Args:
        embed_documents: Batch function accepting a sequence of strings.
        embed_query: Optional query-specific function. When omitted, the batch function is called with a single-item
            sequence.
    """

    def __init__(
        self,
        embed_documents: EmbeddingBatchFunction,
        *,
        embed_query: EmbeddingQueryFunction | None = None,
    ) -> None:
        self._document_function = embed_documents
        self._query_function = embed_query

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed and validate a document batch."""
        values = await _call_maybe_async(self._document_function, texts)
        batch = cast(Sequence[Sequence[float]], values)
        vectors = [[float(item) for item in vector] for vector in batch]
        if len(vectors) != len(texts):
            raise ValueError(f"Embedding function returned {len(vectors)} vectors for {len(texts)} texts")
        _validate_dimensions(vectors)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        """Embed a query with the configured query or batch function."""
        if self._query_function is None:
            return (await self.embed_documents([text]))[0]
        value = await _call_maybe_async(self._query_function, text)
        vector = [float(item) for item in cast(Sequence[float], value)]
        if not vector:
            raise ValueError("Embedding function returned an empty query vector")
        return vector


class OpenAIEmbedder:
    """Use an OpenAI-compatible embeddings client through a small adapter.

    The adapter accepts an already configured client, keeping authentication and lifecycle ownership in the application.
    Both synchronous and asynchronous clients are supported as long as they expose
    ``client.embeddings.create(model=..., input=...)``.

    Args:
        client: Configured OpenAI or OpenAI-compatible client.
        model: Embedding model identifier.
        dimensions: Optional provider-supported output dimension.
    """

    def __init__(
        self,
        client: Any,
        *,
        model: str,
        dimensions: int | None = None,
    ) -> None:
        if client is None:
            raise ValueError("OpenAIEmbedder requires a configured client")
        if not model.strip():
            raise ValueError("OpenAIEmbedder model cannot be empty")
        self.client = client
        self.model = model
        self.dimensions = dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch using the configured client."""
        kwargs: dict[str, Any] = {"model": self.model, "input": list(texts)}
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        response = await _call_maybe_async(self.client.embeddings.create, **kwargs)
        data = _field(response, "data", [])
        ordered = sorted(data, key=lambda item: int(_field(item, "index", 0)))
        vectors = [[float(value) for value in _field(item, "embedding", [])] for item in ordered]
        if len(vectors) != len(texts):
            raise ValueError(f"Embedding provider returned {len(vectors)} vectors for {len(texts)} texts")
        _validate_dimensions(vectors)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query with the same model and dimensions."""
        return (await self.embed_documents([text]))[0]


def _validate_dimensions(vectors: Sequence[Sequence[float]]) -> None:
    """Reject empty or inconsistent embedding batches."""
    if not vectors:
        return
    dimensions = len(vectors[0])
    if dimensions == 0:
        raise ValueError("Embedding vectors cannot be empty")
    if any(len(vector) != dimensions for vector in vectors):
        raise ValueError("Embedding vectors must have consistent dimensions")


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read a response field from mapping- or attribute-style SDK objects."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize_token(token: str) -> str:
    """Apply conservative English plural normalization for local retrieval."""
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


async def _call_maybe_async(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call async functions directly and offload synchronous work."""
    call = vars(type(function)).get("__call__")
    is_async = inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(call)
    result = function(*args, **kwargs) if is_async else await asyncio.to_thread(function, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result
