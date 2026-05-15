from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator


class TaskState(Enum):
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


@dataclass
class Task:
    """Shared Unit of work exchanged between agents.

    Tasks act as the state container for agentic workflows, tracking communication
    history and produced artifacts. This implementation uses internal caching
    to optimize retrieval of the most recent task updates.

    Attributes:
        id: Unique task identifier
        state: Current task state (check TaskState enum)
        messages: Communication history for this task
        artifacts: Output artifacts produced by task
        metadata: Additional task metadata
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
    created_at: str = field(default_factory=lambda: utc_now())

    _last_item: Message | Artifact | None = field(default=None, init=False, repr=False)

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

    def update_state(self, state: TaskState) -> "Task":
        """Update task state.

        Time: O(1)
        """
        self.state = state
        return self

    def complete(self, response_text: str) -> "Task":
        """Mark task as completed with a response.

        Time: O(1)
        """
        self.add_message(Message.agent(response_text))
        self.state = TaskState.COMPLETED
        return self

    def fail(self, error_message: str) -> "Task":
        """Mark task as failed.

        Time: O(1)
        """
        self.metadata["error"] = error_message
        self.state = TaskState.FAILED
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
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create a Task instance from a dictionary.

        This method also reconstructs the `_last_item` cache by comparing
        the timestamps of the last message and artifact.

        Time: O(M + A)
        """
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        artifacts = [Artifact.from_dict(a) for a in data.get("artifacts", [])]
        task = cls(
            id=data.get("id", IDGenerator.generate_task_id()),
            state=TaskState(data.get("state", TaskState.SUBMITTED.value)),
            messages=messages,
            artifacts=artifacts,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", utc_now()),
        )

        # Reconstruct last item cache from existing data
        candidates = []
        if messages:
            candidates.append(messages[-1])
        if artifacts:
            candidates.append(artifacts[-1])

        if candidates:
            task._last_item = max(candidates, key=lambda x: x.timestamp)

        return task

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
