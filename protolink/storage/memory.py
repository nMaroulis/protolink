import heapq
import time
from typing import Any, ClassVar

from protolink.storage.base import Storage


class InMemoryStorage(Storage):
    """In-memory storage implementation.

    A lightweight, dictionary-backed storage that lives entirely in RAM.
    Ideal for development, testing, and short-lived agents that don't need
    disk persistence. Supports optional TTL-based expiration per entry.

    This implementation uses a min-heap to optimize proactive cleanup of expired entries.

    Attributes:
        namespace: Unique identifier for this storage instance's data.
        ttl: Optional time-to-live in seconds. Entries older than this are
            automatically evicted on access or during proactive cleanup.
            ``None`` means no expiration.

    Time Complexity:
        - save: O(log N) due to heap push
        - load: O(log N) due to heap push (touch)
        - delete: O(1)
        - cleanup_expired: O(M log N) where M is the number of expired items

    Space Complexity:
        - O(N) where N is the number of entries in the store.
    """

    # Class-level shared store — all InMemoryStorage instances see the same data
    # unless a custom store is injected.
    _global_store: ClassVar[dict[str, tuple[Any, float]]] = {}
    _global_ttl_heap: ClassVar[list[tuple[float, str]]] = []

    def __init__(
        self,
        namespace: str = "default",
        ttl: int | None = None,
        store: dict[str, tuple[Any, float]] | None = None,
        ttl_heap: list[tuple[float, str]] | None = None,
    ) -> None:
        """Initialize the in-memory storage.

        Args:
            namespace: Unique identifier for this storage instance's data.
            ttl: Optional time-to-live in seconds for stored entries.
                If ``None``, entries never expire.
            store: Optional custom backing dict. If not provided, the shared
                class-level store is used.
            ttl_heap: Optional custom TTL heap.
        """
        self.namespace = namespace
        self.ttl = ttl
        self._store = store if store is not None else InMemoryStorage._global_store
        self._ttl_heap = ttl_heap if ttl_heap is not None else InMemoryStorage._global_ttl_heap

    def save(self, data: Any) -> None:
        """Save data to memory.

        Args:
            data: The data to store. Can be any Python object.

        Time: O(log N) due to heap insertion for TTL tracking.
        """
        now = time.time()
        self._store[self.namespace] = (data, now)
        if self.ttl is not None:
            heapq.heappush(self._ttl_heap, (now + self.ttl, self.namespace))

    def load(self) -> Any:
        """Load data from memory.

        Returns:
            The stored data, or ``None`` if the key doesn't exist or has expired.

        Time: O(log N) if TTL is enabled, as access "touches" the entry and
              updates its expiration time in the heap.
        """
        entry = self._store.get(self.namespace)
        if entry is None:
            return None

        data, timestamp = entry

        # Check TTL expiration (lazy)
        if self.ttl is not None and (time.time() - timestamp) > self.ttl:
            del self._store[self.namespace]
            return None

        # Touch: refresh timestamp on access and push new expiration to heap
        now = time.time()
        self._store[self.namespace] = (data, now)
        if self.ttl is not None:
            heapq.heappush(self._ttl_heap, (now + self.ttl, self.namespace))

        return data

    def update(self, data: Any) -> None:
        """Update existing data in memory.

        Functionally equivalent to ``save()`` for in-memory storage.

        Args:
            data: The new data to store.

        Time: O(log N)
        """
        self.save(data)

    def delete(self) -> None:
        """Delete data from memory.

        Time: O(1)
        """
        self._store.pop(self.namespace, None)

    def cleanup_expired(self) -> int:
        """Remove all expired entries from the backing store using a min-heap.

        This method proactively evicts all entries whose TTL has passed by inspecting
        the top of the min-heap. This is significantly more efficient than a linear
        scan of the entire dictionary.

        Returns:
            The number of entries removed.

        Time: O(M log N) where M is the number of expired items.
        (Improved from O(N) linear scan).
        """
        if not self._ttl_heap:
            return 0

        now = time.time()
        count = 0

        while self._ttl_heap and self._ttl_heap[0][0] < now:
            _, namespace = heapq.heappop(self._ttl_heap)
            # Verify it's still in the store and actually expired (handles re-pushed entries)
            entry = self._store.get(namespace)
            if entry:
                _, timestamp = entry
                # If we have multiple entries in heap for the same namespace (due to touch/update),
                # we only delete if the latest stored timestamp also indicates expiration.
                effective_ttl = self.ttl
                if effective_ttl is not None and (now - timestamp) > effective_ttl:
                    del self._store[namespace]
                    count += 1

        return count
