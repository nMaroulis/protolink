"""
Flow state management for ProtoLink agents.
"""

from protolink.storage import Storage


class FlowState:
    """Manages persistent state for ProtoLink flows.

    This class handles the persistence of flow-specific data, such as progress, checkpoint information, and execution
    context across multiple runs.
    """

    def __init__(self, storage: Storage):
        """Initialize the flow state manager.

        Args:
            storage: The storage backend used for persisting flow-specific data.
        """
        self._storage = storage

    def to_dict(self) -> dict:
        """Convert the flow state to a serializable dictionary.

        Returns:
            A dictionary containing all stored flow states.
        """
        return self._storage.load() or {}
