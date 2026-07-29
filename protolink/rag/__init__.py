"""First-party Retrieval-Augmented Generation for ProtoLink agents.

The package offers one high-level :class:`Knowledge` façade while keeping every internal boundary replaceable.
Applications can use the dependency-free local stack, connect an existing vector database, or implement only the small
:class:`Retriever` protocol.
"""

from .embeddings import CallableEmbedder, HashEmbedder, OpenAIEmbedder
from .errors import (
    KnowledgeNotFoundError,
    OptionalRAGDependencyError,
    RAGError,
    UnsupportedKnowledgeOperationError,
)
from .factory import create_knowledge
from .knowledge import Knowledge, SyncKnowledge
from .loaders import AutoLoader
from .models import Chunk, Citation, Document, IndexReport, RAGAnswer, SearchHit, VectorRecord
from .protocols import (
    AtomicVectorStore,
    Embedder,
    Loader,
    Reranker,
    RetrievalMode,
    Retriever,
    SearchMode,
    Splitter,
    VectorStore,
)
from .retrievers import (
    CallableRetriever,
    ChromaRetriever,
    PineconeRetriever,
    QdrantRetriever,
    VectorStoreRetriever,
)
from .splitters import RecursiveCharacterSplitter
from .stores import InMemoryVectorStore, SQLiteVectorStore

__all__ = [
    "AtomicVectorStore",
    "AutoLoader",
    "CallableEmbedder",
    "CallableRetriever",
    "ChromaRetriever",
    "Chunk",
    "Citation",
    "Document",
    "Embedder",
    "HashEmbedder",
    "InMemoryVectorStore",
    "IndexReport",
    "Knowledge",
    "KnowledgeNotFoundError",
    "Loader",
    "OpenAIEmbedder",
    "OptionalRAGDependencyError",
    "PineconeRetriever",
    "QdrantRetriever",
    "RAGAnswer",
    "RAGError",
    "RecursiveCharacterSplitter",
    "Reranker",
    "RetrievalMode",
    "Retriever",
    "SQLiteVectorStore",
    "SearchHit",
    "SearchMode",
    "Splitter",
    "SyncKnowledge",
    "UnsupportedKnowledgeOperationError",
    "VectorRecord",
    "VectorStore",
    "VectorStoreRetriever",
    "create_knowledge",
]
