"""
Protolink logging package.

Provides a unified interface for logging across the Protolink library.
Includes standard loggers like ConsoleLogger, FileLogger, and QuietLogger.
"""

from .base import BaseLogger
from .config import get_agent_farewell, get_agent_greeting
from .console import ConsoleLogger
from .file import FileLogger
from .quiet import QuietLogger

__all__ = [
    "BaseLogger",
    "ConsoleLogger",
    "FileLogger",
    "QuietLogger",
    "get_agent_farewell",
    "get_agent_greeting",
]
