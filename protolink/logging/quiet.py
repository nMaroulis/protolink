"""No-op logger implementation for Protolink."""

from typing import Any

from protolink.logging.base import BaseLogger


class QuietLogger(BaseLogger):
    """
    Logger implementation that intentionally drops every log message.

    Use this logger when an Agent or integration needs a ``BaseLogger``
    instance but the application should not emit console output, file logs, or
    structured log records.
    """

    def __init__(self, name: str = "protolink") -> None:
        """
        Initialize the quiet logger.

        Args:
            name: The logical logger name returned by the ``name`` property.
        """
        self._name = name

    @property
    def name(self) -> str:
        """Get the logger's name."""
        return self._name

    def debug(self, message: str, **kwargs: Any) -> None:
        """Ignore a debug level message."""
        return None

    def info(self, message: str, **kwargs: Any) -> None:
        """Ignore an info level message."""
        return None

    def warning(self, message: str, **kwargs: Any) -> None:
        """Ignore a warning level message."""
        return None

    def error(self, message: str, **kwargs: Any) -> None:
        """Ignore an error level message."""
        return None

    def exception(self, message: str, **kwargs: Any) -> None:
        """Ignore an exception message."""
        return None
