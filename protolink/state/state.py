"""
Unified state management for ProtoLink agents.
"""

from collections.abc import Callable
from typing import Any, cast

from protolink.storage.base import Storage
from protolink.types import StateMode

from .conversation import ConversationState
from .flow import FlowState
from .operations import StateOperationRequest, StateOperationResult, StateStoreReport
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

    @property
    def enabled_modes(self) -> tuple[StateMode, ...]:
        """Return enabled state stores in deterministic order."""
        return tuple(name for name in STATE_REGISTRY if name in self._modules)

    def describe(
        self,
        request: StateOperationRequest | None = None,
    ) -> StateOperationResult:
        """Describe enabled state stores and optional session contents.

        Args:
            request: Optional state operation request. When ``session_id`` is
                provided, conversation state is reported for that session while
                other stores are still described as store-level data.

        Returns:
            A structured report for every requested store.
        """
        active_request = request or StateOperationRequest()
        reports: list[StateStoreReport] = []
        missing: list[str] = []

        for name in self._selected_store_names(active_request):
            if name not in self._modules:
                missing.append(name)
                reports.append(StateStoreReport(name=name, enabled=False, error="state store is not enabled"))
                continue
            reports.append(
                self._describe_store(
                    name,
                    session_id=active_request.session_id,
                    include_data=active_request.include_data,
                )
            )

        return StateOperationResult(
            operation="describe",
            session_id=active_request.session_id,
            stores=tuple(reports),
            missing=tuple(missing),
        )

    def reset(
        self,
        request: StateOperationRequest | None = None,
    ) -> StateOperationResult:
        """Reset state and return a structured report.

        Session-scoped reset is precise for conversation state. Full reset
        without ``session_id`` clears the shared storage namespace for all
        enabled stores. Because the current storage abstraction is namespace
        based, partial non-session resets are rejected rather than clearing more
        than the caller requested.
        """
        active_request = request or StateOperationRequest()
        selected = self._selected_store_names(
            active_request,
            default=("conversation",) if active_request.session_id else None,
        )
        reports: list[StateStoreReport] = []
        cleared: list[str] = []
        missing: list[str] = []
        errors: list[dict[str, str]] = []

        if active_request.session_id:
            for name in selected:
                if name not in self._modules:
                    missing.append(name)
                    reports.append(StateStoreReport(name=name, enabled=False, error="state store is not enabled"))
                    continue
                if name != "conversation":
                    message = "session-scoped reset is only supported for conversation state"
                    errors.append({"store": name, "message": message})
                    reports.append(StateStoreReport(name=name, enabled=True, error=message))
                    continue
                before = self._describe_store(name, session_id=active_request.session_id, include_data=False)
                conversation = self.conversation
                if conversation is not None:
                    conversation.clear_session(active_request.session_id)
                after = self._describe_store(name, session_id=active_request.session_id, include_data=False)
                cleared.append(name)
                reports.append(
                    StateStoreReport(
                        name=name,
                        enabled=True,
                        exists=after.exists,
                        item_count=after.item_count,
                        message_count=after.message_count,
                        cleared=True,
                        metadata={"before": before.to_dict(), "after": after.to_dict()},
                    )
                )
            return StateOperationResult(
                operation="reset",
                session_id=active_request.session_id,
                stores=tuple(reports),
                cleared=tuple(cleared),
                missing=tuple(missing),
                errors=tuple(errors),
            )

        enabled = set(self.enabled_modes)
        selected_set = set(selected)
        if selected_set and selected_set != enabled:
            for name in selected:
                if name not in self._modules:
                    missing.append(name)
                    reports.append(StateStoreReport(name=name, enabled=False, error="state store is not enabled"))
                else:
                    message = "partial full-state reset is not supported by namespace storage"
                    errors.append({"store": name, "message": message})
                    reports.append(StateStoreReport(name=name, enabled=True, error=message))
            return StateOperationResult(
                operation="reset",
                stores=tuple(reports),
                missing=tuple(missing),
                errors=tuple(errors),
            )

        before_reports = {name: self._describe_store(name, session_id=None, include_data=False) for name in selected}
        self._storage.delete()
        for name in selected:
            if name not in self._modules:
                missing.append(name)
                reports.append(StateStoreReport(name=name, enabled=False, error="state store is not enabled"))
                continue
            after = self._describe_store(name, session_id=None, include_data=False)
            cleared.append(name)
            reports.append(
                StateStoreReport(
                    name=name,
                    enabled=True,
                    exists=after.exists,
                    item_count=after.item_count,
                    message_count=after.message_count,
                    cleared=True,
                    metadata={"before": before_reports[name].to_dict(), "after": after.to_dict()},
                )
            )

        return StateOperationResult(
            operation="reset",
            stores=tuple(reports),
            cleared=tuple(cleared),
            missing=tuple(missing),
        )

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

    def _selected_store_names(
        self,
        request: StateOperationRequest,
        *,
        default: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        if request.stores:
            return request.stores
        if default is not None:
            return default
        return tuple(str(name) for name in self.enabled_modes)

    def _describe_store(
        self,
        name: str,
        *,
        session_id: str | None,
        include_data: bool,
    ) -> StateStoreReport:
        module = self._modules[cast(StateMode, name)]  # caller already checked membership
        to_dict = getattr(module, "to_dict", None)
        data = to_dict() if callable(to_dict) else self._storage.load()
        exists = data is not None
        item_count = _item_count(data)
        message_count: int | None = None
        report_data = data if include_data else None
        metadata: dict[str, Any] = {}

        if name == "conversation" and session_id:
            session_data = data.get(session_id) if isinstance(data, dict) else None
            exists = session_data is not None
            item_count = _item_count(session_data)
            message_count = item_count if isinstance(session_data, list) else None
            report_data = session_data if include_data else None
            metadata["session_scoped"] = True
        elif session_id:
            metadata["session_scoped"] = False

        return StateStoreReport(
            name=name,
            enabled=True,
            exists=exists,
            item_count=item_count,
            message_count=message_count,
            data=report_data,
            metadata=metadata,
        )


def _item_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict | list | tuple | set):
        return len(value)
    return None
