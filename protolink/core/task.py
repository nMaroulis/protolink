from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator


class TaskState(Enum):
    """Lifecycle states for a task as it moves through agent execution.

    The default lifecycle is:
    ``submitted`` -> ``working`` -> one of ``completed``, ``input-required``, ``failed``, or ``canceled``.
    Terminal states cannot transition further.
    """

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


# Allowed transition graph (Not used yet)
_ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED},
    TaskState.WORKING: {TaskState.COMPLETED, TaskState.INPUT_REQUIRED, TaskState.FAILED, TaskState.CANCELED},
    TaskState.INPUT_REQUIRED: {TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.CANCELED: set(),
    TaskState.FAILED: set(),
    TaskState.UNKNOWN: set(TaskState),
}

_TERMINAL_STATES: set[TaskState] = {TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED}


class TaskExecutionError(RuntimeError):
    """A returned task failed or was canceled.

    Attributes:
        task: The original task, including its state, error metadata, and any
            partial outputs. Raised by :meth:`Task.raise_for_status`; exceptions
            raised directly by a handler retain their original types.
    """

    def __init__(self, task: "Task") -> None:
        self.task = task
        key = "cancel_reason" if task.state is TaskState.CANCELED else "error"
        reason = task.metadata.get(key)
        message = f"Task '{task.id}' {task.state.value}"
        super().__init__(f"{message}: {reason}" if reason else message)


def _coerce_task_state(state: TaskState | str) -> TaskState:
    """Normalize a state value to ``TaskState``.

    Serialized tasks carry states as strings, while in-memory tasks store the enum. Accepting both keeps deserialization
    and direct construction ergonomic while preserving a single internal representation.
    """
    if isinstance(state, TaskState):
        return state
    if isinstance(state, str):
        return TaskState(state)
    raise TypeError(f"Task state must be a TaskState or str, got {type(state).__name__}")


def _task_item_timestamp(item: Message | Artifact) -> str:
    """Return the timestamp used to order task messages and artifacts."""
    return item.timestamp


@dataclass
class Task:
    """Shared Unit of work exchanged between agents.

    Tasks act as the state container for agentic workflows, tracking communication history and produced artifacts.
    This implementation uses internal caching to optimize retrieval of the most recent task updates.

    Attributes:
        id: Unique task identifier
        state: Current task state (check TaskState enum)
        messages: Communication history for this task
        artifacts: Output artifacts produced by task
        metadata: Additional task metadata
        flow_state: Optional flow state for structured flows
        created_at: Task creation time

    Time Complexity:
        - add_message / add_artifact: O(1)
        - get_last_item: O(1) (Improved from O(N) by caching _last_item)
        - to_dict: O(M + A) where M is messages and A is artifacts

    Space Complexity:
        - O(M + A) where M is messages and A is artifacts.
    """

    id: str = field(default_factory=lambda: IDGenerator.generate_task_id())
    state: TaskState = TaskState.SUBMITTED
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    flow_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())

    _last_item: Message | Artifact | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Normalize state and rebuild the last-item cache after dataclass init."""
        self.state = _coerce_task_state(self.state)
        if self._last_item is None:
            self._last_item = self._compute_last_item()

    def _compute_last_item(self) -> Message | Artifact | None:
        """Return the most recent message or artifact based on timestamps."""
        candidates: list[Message | Artifact] = []
        if self.messages:
            candidates.append(self.messages[-1])
        if self.artifacts:
            candidates.append(self.artifacts[-1])
        if not candidates:
            return None
        return max(candidates, key=_task_item_timestamp)

    def _record_state_transition(self, previous_state: TaskState, new_state: TaskState) -> None:
        """Append a serialized state transition to ``metadata['state_history']``."""
        history = self.metadata.setdefault("state_history", [])
        if not isinstance(history, list):
            return
        history.append(
            {
                "previous_state": previous_state.value,
                "new_state": new_state.value,
                "timestamp": utc_now(),
            }
        )

    @property
    def is_terminal(self) -> bool:
        """Return whether the task is in a terminal lifecycle state."""
        return self.state in _TERMINAL_STATES

    def raise_for_status(self) -> "Task":
        """Raise for a failed or canceled task; otherwise return this task.

        This check does not wait for completion. Submitted, working, and
        input-required tasks remain valid protocol responses; inspect ``state``
        when your application requires a completed result.

        Raises:
            TaskExecutionError: The task failed or was canceled. The exception's
                ``task`` attribute retains the original task and partial outputs.
        """
        if self.state in {TaskState.FAILED, TaskState.CANCELED}:
            raise TaskExecutionError(self)
        return self

    def add_message(self, message: Message) -> "Task":
        """Add a message to the task and update the last item cache.

        Time: O(1)
        """
        self.messages.append(message)
        self._last_item = message
        return self

    def add_artifact(self, artifact: Artifact) -> "Task":
        """Add an artifact to the task and update the last item cache.

        Time: O(1)
        """
        self.artifacts.append(artifact)
        self._last_item = artifact
        return self

    def update_state(self, state: TaskState | str) -> "Task":
        """Transition the task to a new state.

        The transition must be allowed by the task lifecycle graph. Repeating the current state is treated as a no-op.
        Successful transitions are recorded in ``metadata['state_history']``.

        Time: O(1)
        """
        current_state = _coerce_task_state(self.state)
        new_state = _coerce_task_state(state)
        if current_state == new_state:
            self.state = new_state
            return self

        if new_state not in _ALLOWED_TRANSITIONS[current_state]:
            raise ValueError(f"Invalid task state transition: {current_state.value} -> {new_state.value}")

        self.state = new_state
        self._record_state_transition(current_state, new_state)
        return self

    def begin(self) -> "Task":
        """Mark the task as actively being processed."""
        return self.update_state(TaskState.WORKING)

    def require_input(self, message: Message | None = None) -> "Task":
        """Mark the task as waiting for additional input.

        If the task has not started yet, it is first moved through ``WORKING`` so the lifecycle history remains valid.
        """
        if self.state in {TaskState.SUBMITTED, TaskState.INPUT_REQUIRED}:
            self.begin()
        self.update_state(TaskState.INPUT_REQUIRED)
        if message:
            self.add_message(message)
        return self

    def complete(self, response_text: str) -> "Task":
        """Mark the task as completed and append a final agent message.

        If the task is still ``SUBMITTED`` or ``INPUT_REQUIRED``, it is first moved through ``WORKING`` so callers can
        use this convenience method directly without manually managing intermediate states.

        Time: O(1)
        """
        if self.state in {TaskState.SUBMITTED, TaskState.INPUT_REQUIRED}:
            self.begin()
        self.update_state(TaskState.COMPLETED)
        self.add_message(Message.agent(response_text))
        return self

    def fail(self, error_message: str) -> "Task":
        """Mark the task as failed and store the error message in metadata.

        Time: O(1)
        """
        self.update_state(TaskState.FAILED)
        self.metadata["error"] = error_message
        return self

    def cancel(self, reason: str | None = None) -> "Task":
        """Mark the task as canceled and optionally store a cancel reason."""
        self.update_state(TaskState.CANCELED)
        if reason:
            self.metadata["cancel_reason"] = reason
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert task to a JSON-serializable dictionary.

        Time: O(M + A) where M is messages and A is artifacts.
        """
        return {
            "id": self.id,
            "state": self.state.value,
            "messages": [m.to_dict() for m in self.messages],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "metadata": self.metadata,
            "flow_state": self.flow_state,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create a Task instance from a dictionary.

        This method also reconstructs the `_last_item` cache by comparing the timestamps of the last message and
        artifact.

        Time: O(M + A)
        """
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        artifacts = [Artifact.from_dict(a) for a in data.get("artifacts", [])]
        return cls(
            id=data.get("id", IDGenerator.generate_task_id()),
            state=TaskState(data.get("state", TaskState.SUBMITTED.value)),
            messages=messages,
            artifacts=artifacts,
            metadata=data.get("metadata", {}),
            flow_state=data.get("flow_state", {}),
            created_at=data.get("created_at", utc_now()),
        )

    @classmethod
    def create(cls, message: Message) -> "Task":
        """Create a new task with an initial message.

        Time: O(1)
        """
        task = cls(messages=[message])
        task._last_item = message
        return task

    @classmethod
    def create_infer(
        cls,
        *,
        prompt: str | None = None,
        user: str | None = None,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Task":
        """
        Create a new task initialized with an infer message.

        Time: O(1)
        """
        message = Message.infer(
            prompt=prompt,
            user=user,
            output_schema=output_schema,
            metadata=metadata,
        )
        return cls.create(message)

    @classmethod
    def create_tool_call(
        cls,
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> "Task":
        """
        Create a new task initialized with a tool_call message.

        Time: O(1)
        """
        message = Message.tool_call(
            tool_name=tool_name,
            args=args or {},
            call_id=call_id,
        )
        return cls.create(message)

    def get_last_item(self) -> Message | Artifact | None:
        """
        Return the most recently appended Message or Artifact in this Task.

        Time: O(1) (Using cached _last_item)
        """
        return self._last_item

    @staticmethod
    def tool_call(
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> Part:
        """
        Create a tool_call Part to be executed by an agent.

        Time: O(1)
        """
        return Part.tool_call(
            tool_name=tool_name,
            args=args or {},
            call_id=call_id,
        )

    @staticmethod
    def infer(
        *,
        prompt: str | None = None,
        user: str | None = None,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Part:
        """
        Create a infer Part to be executed by the agent's LLM.

        Time: O(1)
        """

        return Part.infer(
            prompt=prompt,
            user=user,
            output_schema=output_schema,
            metadata=metadata,
        )

    # ----------------------------------------------------------------------
    # Helper funcs
    # ----------------------------------------------------------------------

    def get_last_part_content(self) -> Any | None:
        """
        Get the content of the last part in the most recent Message or Artifact.

        Time: O(1)
        """
        last_item = self.get_last_item()
        if last_item is None:
            return None

        # Get the last part from the last item
        if last_item.parts:
            last_part = last_item.parts[-1]
            return last_part.content
        return None
