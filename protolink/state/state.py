"""
Unified state management for ProtoLink agents.
"""

from collections.abc import Callable
from typing import Any

from protolink.storage.base import Storage
from protolink.types import StateMode

from .conversation import ConversationState
from .flow import FlowState
from .task import TaskState
from .tool import ToolState

StateModule = ConversationState | ToolState | TaskState | FlowState

STATE_REGISTRY: dict[StateMode, Callable[[Storage], StateModule]] = {
    "conversation": ConversationState,
    "tools": ToolState,
    "task": TaskState,
    "flow": FlowState,
}


class State:
    """Orchestrates persistent state modules for a ProtoLink agent.

    The State class acts as a container and coordinator for various stateful modules (conversation, tools, tasks, etc.).
    It manages their initialization based on the agent's configuration and ensures they all use the same storage backend
    """

    def __init__(
        self,
        storage: Storage,
        enabled: list[StateMode],
    ):
        """Initialize the State container.

        Args:
            storage: The shared storage backend for all state modules.
            enabled: A list of state module names to enable for this agent.
        """
        self._storage = storage
        self._modules: dict[StateMode, StateModule] = {}

        for name in enabled:
            if name not in STATE_REGISTRY:
                raise ValueError(f"Unknown state module: {name}")

            self._modules[name] = STATE_REGISTRY[name](storage)

    @property
    def conversation(self) -> ConversationState | None:
        """Access the conversation history state module."""
        module = self._modules.get("conversation", None)
        return module if isinstance(module, ConversationState) else None

    @conversation.setter
    def conversation(self, conversation: ConversationState):
        """Set or override the conversation history state module."""
        self._modules["conversation"] = conversation

    @property
    def tools(self) -> ToolState | None:
        """Access the tool-specific state module."""
        module = self._modules.get("tools", None)
        return module if isinstance(module, ToolState) else None

    @tools.setter
    def tools(self, tools: ToolState):
        """Set or override the tool-specific state module."""
        self._modules["tools"] = tools

    @property
    def task(self) -> TaskState | None:
        """Access the task metadata state module."""
        module = self._modules.get("task", None)
        return module if isinstance(module, TaskState) else None

    @task.setter
    def task(self, task: TaskState):
        """Set or override the task metadata state module."""
        self._modules["task"] = task

    @property
    def flow(self) -> FlowState | None:
        """Access the flow-specific state module."""
        module = self._modules.get("flow", None)
        return module if isinstance(module, FlowState) else None

    @flow.setter
    def flow(self, flow: FlowState):
        """Set or override the flow-specific state module."""
        self._modules["flow"] = flow

    @property
    def storage(self) -> Storage:
        """Access the underlying storage backend."""
        return self._storage

    @storage.setter
    def storage(self, storage: Storage):
        """Update the storage backend for the state container."""
        self._storage = storage

    def to_dict(self) -> dict[str, Any]:
        """Convert the entire state container to a nested dictionary representation.

        Returns:
            A dictionary where each key is a module name and the value is its serialized state.
        """
        data = {}
        for name, module in self._modules.items():
            to_dict = getattr(module, "to_dict", None)
            if callable(to_dict):
                data[name] = to_dict()
        return data
