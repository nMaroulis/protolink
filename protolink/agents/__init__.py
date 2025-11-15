"""Agent module for Protolink framework.

This module provides the core agent functionality including the base Agent class,
agent lifecycle management, and task execution.
"""

from .base import Agent
from .builtins.echo_agent import EchoAgent

__all__ = [
    "Agent",
    "EchoAgent",
]
