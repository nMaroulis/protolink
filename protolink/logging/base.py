"""Base logger definition for Protolink."""

from abc import ABC, abstractmethod
from typing import Any


class BaseLogger(ABC):
    """
    Abstract base class for all Protolink loggers.

    Any custom logger provided to the Agent or other Protolink components should implement this interface to
    ensure compatibility.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the logger's name."""
        pass

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug level message.

        Args:
            message: The message to log.
            **kwargs: Additional contextual information (e.g., extra).
        """
        pass

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info level message.

        Args:
            message: The message to log.
            **kwargs: Additional contextual information.
        """
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning level message.

        Args:
            message: The message to log.
            **kwargs: Additional contextual information.
        """
        pass

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error level message.

        Args:
            message: The message to log.
            **kwargs: Additional contextual information (e.g., exc_info).
        """
        pass

    @abstractmethod
    def exception(self, message: str, **kwargs: Any) -> None:
        """Log an exception message, usually capturing the stack trace.

        Args:
            message: The message to log.
            **kwargs: Additional contextual information.
        """
        pass
