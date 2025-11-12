"""Logging utilities for Protolink.

This module provides a custom logger with consistent formatting and log levels.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

# Log format constants
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ProtoLinkLogger:
    """Custom logger for Protolink with consistent formatting.

    This logger provides methods for different log levels and supports both
    console and file logging.
    """

    def __init__(
        self,
        name: str = "protolink",
        log_level: int = logging.INFO,
        log_file: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ):
        """Initialize the logger.

        Args:
            name: Logger name
            log_level: Logging level (default: INFO)
            log_file: Optional file path for file logging
            max_bytes: Maximum log file size in bytes before rotation
            backup_count: Number of backup log files to keep
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)

        # Prevent adding multiple handlers
        if not self.logger.handlers:
            formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

            # File handler if log file is specified
            if log_file:
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)

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


# Default logger instance
default_logger = ProtoLinkLogger()


# Convenience functions
def get_logger(name: str = "protolink") -> ProtoLinkLogger:
    """Get a logger instance with the given name.

    Args:
        name: The name of the logger

    Returns:
        A configured ProtoLinkLogger instance
    """
    return ProtoLinkLogger(name)


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
