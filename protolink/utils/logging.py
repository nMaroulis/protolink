"""Logging utilities for Protolink.

This module provides a custom logger with consistent formatting and log levels.
"""

import json
import logging
import os
import sys
import warnings
from logging.handlers import RotatingFileHandler
from typing import Any, ClassVar

# Log format constants
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DEBUG_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d:%(funcName)s() | %(message)s"
DEBUG_DATE_FORMAT = "%H:%M:%S.%f"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


_ENV_LOG_LEVEL = "PROTOLINK_LOG_LEVEL"
_ENV_LOG_FILE = "PROTOLINK_LOG_FILE"
_ENV_LOG_FORMAT = "PROTOLINK_LOG_FORMAT"  # "text" or "json"
_ENV_LOG_PRETTY_NAMES = "PROTOLINK_LOG_PRETTY_NAMES"


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


class ColoredFormatter(logging.Formatter):
    """Subtle ANSI-colored formatter for console logs."""

    COLORS: ClassVar[dict[int, str]] = {
        logging.DEBUG: "\033[90m",  # dim gray
        logging.INFO: "\033[34m",  # blue
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",  # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    RESET: ClassVar[str] = "\033[0m"
    LEVEL_WIDTH: ClassVar[int] = 8
    ARROW: ClassVar[str] = " → "

    @staticmethod
    def _use_pretty_names() -> bool:
        return os.getenv(_ENV_LOG_PRETTY_NAMES, "1") == "1"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = record.levelname.center(self.LEVEL_WIDTH)
        if self._use_pretty_names():
            record.name = record.name.replace(".", self.ARROW)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        message = record.getMessage()

        data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
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


def _resolve_log_level(default_level: int) -> int:
    env_level = os.getenv(_ENV_LOG_LEVEL)
    if not env_level:
        return default_level

    level = logging.getLevelName(env_level.upper())
    if isinstance(level, int):
        return level
    return default_level


def _resolve_log_file(explicit_file: str | None) -> str | None:
    if explicit_file is not None:
        return explicit_file
    return os.getenv(_ENV_LOG_FILE)


def _use_json_format() -> bool:
    value = os.getenv(_ENV_LOG_FORMAT)
    if not value:
        return False
    value = value.lower()
    return value in {"json", "structured"}


class ProtoLinkWarning(UserWarning):
    """Base class for Protolink user-facing warnings."""


class ProtoLinkLogger:
    """Custom logger for Protolink with consistent formatting.

    This logger provides methods for different log levels and supports both
    console and file logging.
    """

    _instances: ClassVar[dict[str, "ProtoLinkLogger"]] = {}
    _configured: ClassVar[bool] = False

    def __new__(
        cls,
        name: str = "protolink",
        log_level: int = logging.INFO,
        log_file: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ):
        """Create or return existing logger instance (singleton pattern)."""
        if name not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[name] = instance
        return cls._instances[name]

    def __init__(
        self,
        name: str = "protolink",
        log_level: int = logging.INFO,
        log_file: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ):
        """Initialize logger.

        Args:
            name: Logger name
            log_level: Logging level (default: INFO)
            log_file: Optional file path for file logging
            max_bytes: Maximum log file size in bytes before rotation
            backup_count: Number of backup log files to keep
        """
        # Only initialize once per instance
        if hasattr(self, "_initialized"):
            return

        resolved_level = _resolve_log_level(log_level)
        resolved_file = _resolve_log_file(log_file)

        self.logger = logging.getLogger(name)
        self.logger.setLevel(resolved_level)
        # Don't set propagate to False so module names show up in logs

        # Configure root logger only once
        if not self._configured:
            self._configure_root_logger(resolved_level, resolved_file, max_bytes, backup_count)
            ProtoLinkLogger._configured = True

        self._initialized = True

    def _configure_root_logger(
        self,
        log_level: int,
        log_file: str | None,
        max_bytes: int,
        backup_count: int,
    ) -> None:
        """Configure the root logger with handlers."""
        # Configure the root protolink logger to handle all child loggers
        root_logger = logging.getLogger("protolink")
        root_logger.setLevel(log_level)

        # Clear any existing handlers to prevent duplication
        root_logger.handlers.clear()

        if _use_json_format():
            formatter: logging.Formatter = JsonFormatter(datefmt=DATE_FORMAT)
        else:
            formatter = ColoredFormatter(LOG_FORMAT, DATE_FORMAT)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        if log_file:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

    def debug(self, message: str, extra: dict[str, Any] | None = None) -> None:
        """Log a debug message.

        Args:
            message: The message to log
            extra: Additional context as a dictionary
        """
        self.logger.debug(message, extra=extra or {})

    def info(self, message: str, extra: dict[str, Any] | None = None) -> None:
        """Log an info message.

        Args:
            message: The message to log
            extra: Additional context as a dictionary
        """
        self.logger.info(message, extra=extra or {})

    def warning(self, message: str, extra: dict[str, Any] | None = None) -> None:
        """Log a warning message.

        Args:
            message: The message to log
            extra: Additional context as a dictionary
        """
        self.logger.warning(message, extra=extra or {})

    def error(
        self,
        message: str,
        *,
        exc_info: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log an error message.

        Args:
            message: The message to log
            exc_info: Whether to include exception info
            extra: Additional context as a dictionary
        """
        self.logger.error(message, exc_info=exc_info, extra=extra or {})

    def exception(
        self,
        message: str,
        *,
        exc_info: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log an exception message with traceback.

        Args:
            message: The message to log
            exc_info: Whether to include exception info
            extra: Additional context as a dictionary
        """
        self.logger.exception(message, exc_info=exc_info, extra=extra or {})

    def warn_user(
        self,
        message: str,
        category: type[UserWarning] = ProtoLinkWarning,
    ) -> None:
        """Emit a soft, user-facing warning (not a log).

        This is for optional configuration issues or guidance.
        """
        warnings.warn(message, category=category, stacklevel=3)


def _verbosity_to_log_level(verbose: int) -> int:
    """
    Map verbosity level to logging level.

    0 -> WARNING
    1 -> INFO
    2+ -> DEBUG
    """
    if verbose <= 0:
        return logging.WARNING
    if verbose == 1:
        return logging.INFO
    return logging.DEBUG


# Default logger instance
default_logger = ProtoLinkLogger()


# Convenience functions
def get_logger(name: str = "protolink", verbose: int = 1) -> ProtoLinkLogger:
    """
    Get a logger instance with the given name. Instead of using a logger singleton.

    Args:
        name: The name of the logger
        verbose: verbosity level (0=WARNING, 1=INFO, 2+=DEBUG)

    Returns:
        A configured ProtoLinkLogger instance
    """
    log_level = _verbosity_to_log_level(verbose)
    return ProtoLinkLogger(name, log_level=log_level)


def setup_logging(
    log_level: int = logging.INFO,
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Set up the default logger configuration.

    Args:
        log_level: Logging level (default: INFO)
        log_file: Optional file path for file logging
        max_bytes: Maximum log file size in bytes before rotation
        backup_count: Number of backup log files to keep
    """
    global default_logger
    default_logger = ProtoLinkLogger(
        "protolink",
        log_level=log_level,
        log_file=log_file,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
