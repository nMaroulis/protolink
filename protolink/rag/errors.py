"""Retrieval-specific exceptions exposed by :mod:`protolink.rag`."""


class RAGError(RuntimeError):
    """Base exception for ProtoLink retrieval operations."""


class UnsupportedKnowledgeOperationError(RAGError):
    """Raised when a retrieval-only knowledge source is asked to index data."""


class KnowledgeNotFoundError(RAGError):
    """Raised when required retrieval produces no usable context."""


class OptionalRAGDependencyError(RAGError, ImportError):
    """Raised when a selected loader or adapter needs an uninstalled extra."""
