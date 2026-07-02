"""File logger implementation for Protolink."""

import json
import logging as std_logging
from pathlib import Path
from typing import Any, Literal

from protolink.logging.base import BaseLogger

_STANDARD_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}


class JsonFormatter(std_logging.Formatter):
    """JSON formatter for structured file logging."""

    def format(self, record: std_logging.LogRecord) -> str:
        message = record.getMessage()

        data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt or "%Y-%m-%d %H:%M:%S"),
            "name": record.name,
            "level": record.levelname,
            "message": message,
        }

        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_KEYS or key.startswith("_"):
                continue
            extra[key] = value

        if extra:
            data["extra"] = extra

        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(data, ensure_ascii=False)


class FileLogger(BaseLogger):
    """
    File logger that appends formatted logs to a file.
    Supports standard text formatting and structured JSON logging.
    """

    def __init__(
        self,
        filepath: str | Path,
        name: str = "protolink",
        level: int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = std_logging.INFO,
        fmt: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt: str = "%Y-%m-%d %H:%M:%S",
        extension: str | None = None,
    ):
        """
        Initialize the file logger.

        Args:
            filepath: Path to the log file. If the path's parent directory does not exist, it will be created.
            name: The name of the logger instance.
            level: The logging level. Defaults to INFO.
            fmt: The format string for the log message (used when not in JSON mode).
            datefmt: The format string for the timestamp.
            extension: Override the file extension or format logic. If 'json', it writes structured JSON logs.
                       If None, it deduces the format from the filepath.
        """
        self._name = name
        self._logger = std_logging.getLogger(f"file.{name}.{filepath}")

        # Resolve level string to int if necessary
        if isinstance(level, str):
            level = getattr(std_logging, level.upper(), std_logging.INFO)

        self._logger.setLevel(level)

        # Clear existing handlers to avoid duplicate logs in case of re-initialization
        self._logger.handlers.clear()

        # Prevent propagation to avoid double logging from root logger
        self._logger.propagate = False

        path = Path(filepath)

        # Determine format type
        file_ext = extension or path.suffix.lstrip(".")

        # Ensure parent directories exist
        path.parent.mkdir(parents=True, exist_ok=True)

        handler = std_logging.FileHandler(path, mode="a", encoding="utf-8")

        if file_ext.lower() == "json":
            formatter = JsonFormatter(datefmt=datefmt)
        else:
            formatter = std_logging.Formatter(fmt, datefmt=datefmt)

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
