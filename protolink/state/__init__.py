"""
State management module for ProtoLink.

This module provides a unified interface for managing persistent state across different components of a ProtoLink agent,
including conversation history, tool state, task metadata, and flow context.
"""

from .conversation import ConversationState
from .flow import FlowState
from .operations import StateOperationRequest, StateOperationResult, StateStoreReport
from .state import State
from .task import TaskState
from .tool import ToolState

__all__ = [
    "ConversationState",
    "FlowState",
    "State",
    "StateOperationRequest",
    "StateOperationResult",
    "StateStoreReport",
    "TaskState",
    "ToolState",
]
