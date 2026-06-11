"""
Protolink logging package.

Provides a unified interface for logging across the Protolink library.
Includes standard loggers like ConsoleLogger and FileLogger.
"""

from .base import BaseLogger
from .config import get_agent_farewell, get_agent_greeting
from .console import ConsoleLogger
from .file import FileLogger

__all__ = ["BaseLogger", "ConsoleLogger", "FileLogger", "get_agent_farewell", "get_agent_greeting"]
