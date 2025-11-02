"""
Protolink - Agent-to-Agent (A2A) communication protocol implementation.

This module provides the core functionality for creating and managing
intelligent agents that can discover each other and communicate using
the A2A protocol.
"""

from .core.agent import Agent
from .core.message import Message
from .core.task import Task
from .core.artifact import Artifact
from .discovery.registry import Registry

__version__ = "0.1.0"
__all__ = ["Agent", "Message", "Task", "Artifact", "Registry"]
