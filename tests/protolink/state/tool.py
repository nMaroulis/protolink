"""
Tool state management for ProtoLink agents.
"""

from protolink.storage import Storage


class ToolState:
    """Manages persistent tool-specific state.

    This class allows tools to persist their own internal state across different task executions or sessions using a
    shared storage backend.
    """

    def __init__(self, storage: Storage):
        """Initialize the tool state manager.

        Args:
            storage: The storage backend used for persisting tool-specific data.
        """
        self._storage = storage
