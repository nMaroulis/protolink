import time
from typing import Any, ClassVar

from protolink.storage.base import Storage


class InMemoryStorage(Storage):
    """In-memory storage implementation.

    A lightweight, dictionary-backed storage that lives entirely in RAM.
    Ideal for development, testing, and short-lived agents that don't need
    disk persistence. Supports optional TTL-based expiration per entry.

    All instances share the same backing store by default (class-level dict),
    isolated by ``namespace``. Pass a custom ``store`` dict to isolate instances.

    Attributes:
        namespace: Unique identifier for this storage instance's data.
        ttl: Optional time-to-live in seconds. Entries older than this are
            automatically evicted on access. ``None`` means no expiration.
    """

    # Class-level shared store — all InMemoryStorage instances see the same data
    # unless a custom store is injected.
    _global_store: ClassVar[dict[str, tuple[Any, float]]] = {}

    def __init__(
        self,
        namespace: str = "default",
        ttl: int | None = None,
        store: dict[str, tuple[Any, float]] | None = None,
    ) -> None:
        """Initialize the in-memory storage.

        Args:
            namespace: Unique identifier for this storage instance's data.
            ttl: Optional time-to-live in seconds for stored entries.
                If ``None``, entries never expire.
            store: Optional custom backing dict. If not provided, the shared
                class-level store is used.
        """
        self.namespace = namespace
        self.ttl = ttl
        self._store = store if store is not None else InMemoryStorage._global_store

    def save(self, data: Any) -> None:
        """Save data to memory.

        Args:
            data: The data to store. Can be any Python object.
        """
        self._store[self.namespace] = (data, time.time())

    def load(self) -> Any:
        """Load data from memory.

        Returns:
            The stored data, or ``None`` if the key doesn't exist or has expired.
        """
        entry = self._store.get(self.namespace)
        if entry is None:
            return None

        data, timestamp = entry

        # Check TTL expiration
        if self.ttl is not None and (time.time() - timestamp) > self.ttl:
            del self._store[self.namespace]
            return None

        # Touch: refresh timestamp on access
        self._store[self.namespace] = (data, time.time())
        return data

    def update(self, data: Any) -> None:
        """Update existing data in memory.

        Functionally equivalent to ``save()`` for in-memory storage.

        Args:
            data: The new data to store.
        """
        self.save(data)

    def delete(self) -> None:
        """Delete data from memory."""
        self._store.pop(self.namespace, None)

    def cleanup_expired(self) -> int:
        """Remove all expired entries from the backing store.

        This is a maintenance method. Expiration is also checked lazily
        on each ``load()`` call, but this method allows proactive cleanup.

        Returns:
            The number of entries removed.
        """
        if self.ttl is None:
            return 0

        now = time.time()
        expired = [key for key, (_, timestamp) in self._store.items() if (now - timestamp) > self.ttl]
        for key in expired:
            del self._store[key]
        return len(expired)
