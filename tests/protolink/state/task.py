"""
Task state management for ProtoLink agents.
"""

from protolink.storage import Storage


class TaskState:
    """Manages persistent task state and metadata.

    This class provides an interface for persisting and retrieving task-related information using a shared
    storage backend.
    """

    def __init__(self, storage: Storage):
        """Initialize the task state manager.

        Args:
            storage: The storage backend used for persisting task data.
        """
        self._storage = storage
