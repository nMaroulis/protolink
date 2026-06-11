from abc import ABC, abstractmethod
from typing import Any


class Storage(ABC):
    """Abstract base class for storage implementations.

    This class defines the interface for persistent storage mechanisms used by agents.
    It supports basic CRUD operations: save, load, update, and delete.
    Implementations should handle the underlying storage details (e.g., file system, database).
    """

    @abstractmethod
    def save(self, data: Any) -> None:
        """Saves data to the storage.

        Args:
            data: The data to be saved. Structure depends on implementation.
        """
        pass

    @abstractmethod
    def load(self) -> Any:
        """Loads data from the storage.

        Returns:
            The loaded data, or None if empty/not found.
        """
        pass

    @abstractmethod
    def update(self, data: Any) -> None:
        """Updates existing data in the storage.

        Args:
            data: The new data to update.
        """
        pass

    @abstractmethod
    def delete(self) -> None:
        """Deletes the data from the storage."""
        pass
