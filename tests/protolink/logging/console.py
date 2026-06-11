"""Console logger implementation for Protolink."""

import logging as std_logging
import sys
from typing import Any, ClassVar, Literal

from protolink.logging.base import BaseLogger


class ConsoleFormatter(std_logging.Formatter):
    """Subtle ANSI-colored formatter for console logs."""

    COLORS: ClassVar[dict[int, str]] = {
        std_logging.DEBUG: "\033[90m",  # dim gray
        std_logging.INFO: "\033[34m",  # blue
        std_logging.WARNING: "\033[33m",  # yellow
        std_logging.ERROR: "\033[31m",  # red
        std_logging.CRITICAL: "\033[1;31m",  # bold red
    }
    RESET: ClassVar[str] = "\033[0m"
    LEVEL_WIDTH: ClassVar[int] = 8

    def format(self, record: std_logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = record.levelname.center(self.LEVEL_WIDTH)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


class ConsoleLogger(BaseLogger):
    """
    Console logger that writes formatted and colored logs to standard output.
    """

    def __init__(
        self,
        name: str = "protolink",
        level: int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = std_logging.INFO,
        fmt: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt: str = "%Y-%m-%d %H:%M:%S",
    ):
        """
        Initialize the console logger.

        Args:
            name: The name of the logger instance.
            level: The logging level. Defaults to INFO.
            fmt: The format string for the log message.
            datefmt: The format string for the timestamp.
        """
        self._name = name
        self._logger = std_logging.getLogger(f"console.{name}")

        # Resolve level string to int if necessary
        if isinstance(level, str):
            level = getattr(std_logging, level.upper(), std_logging.INFO)

        self._logger.setLevel(level)

        # Clear existing handlers to avoid duplicate logs in case of re-initialization
        self._logger.handlers.clear()

        # Prevent propagation to avoid double logging from root logger
        self._logger.propagate = False

        handler = std_logging.StreamHandler(sys.stdout)
        formatter = ConsoleFormatter(fmt, datefmt=datefmt)
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    @property
    def name(self) -> str:
        """Get the logger's name."""
        return self._name

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug level message."""
        self._logger.debug(message, extra=kwargs.get("extra", {}))

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info level message."""
        self._logger.info(message, extra=kwargs.get("extra", {}))

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning level message."""
        self._logger.warning(message, extra=kwargs.get("extra", {}))

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error level message."""
        self._logger.error(
            message,
            exc_info=kwargs.get("exc_info", False),
            extra=kwargs.get("extra", {}),
        )

    def exception(self, message: str, **kwargs: Any) -> None:
        """Log an exception level message."""
        self._logger.exception(
            message,
            exc_info=kwargs.get("exc_info", True),
            extra=kwargs.get("extra", {}),
        )
