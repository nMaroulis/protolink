"""Core components of the Protolink A2A protocol implementation.

This module contains the fundamental building blocks for agent communication,
including the base Agent class, message handling, and protocol implementation.
"""

from .agent import Agent
from .message import Message, MessageType
from .task import Task, TaskStatus, TaskResult
from .artifact import Artifact, ArtifactType
from .protocol import Protocol, ProtocolError

__all__ = [
    "Agent",
    "Message",
    "MessageType",
    "Task",
    "TaskStatus",
    "TaskResult",
    "Artifact",
    "ArtifactType",
    "Protocol",
    "ProtocolError",
]
