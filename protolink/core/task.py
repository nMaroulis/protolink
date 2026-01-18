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

    Attributes:
        id: Unique task identifier
        state: Current task state (check TaskState enum)
        messages: Communication history for this task
        artifacts: Output artifacts produced by task (NEW in v0.2.0)
        metadata: Additional task metadata
        created_at: Task creation time
    """

    id: str = field(default_factory=lambda: IDGenerator.generate_task_id())
    state: TaskState = TaskState.SUBMITTED
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())

    def add_message(self, message: Message) -> "Task":
        """Add a message to the task."""
        self.messages.append(message)
        return self

    def add_artifact(self, artifact: Artifact) -> "Task":
        """Add an artifact to the task (NEW in v0.2.0)."""
        self.artifacts.append(artifact)
        return self

    def update_state(self, state: TaskState) -> "Task":
        """Update task state."""
        self.state = state
        return self

    def complete(self, response_text: str) -> "Task":
        """Mark task as completed with a response."""
        self.add_message(Message.agent(response_text))
        self.state = TaskState.COMPLETED
        return self

    def fail(self, error_message: str) -> "Task":
        """Mark task as failed."""
        self.metadata["error"] = error_message
        self.state = TaskState.FAILED
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
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
        """Create from dictionary."""
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        artifacts = [Artifact.from_dict(a) for a in data.get("artifacts", [])]
        return cls(
            id=data.get("id", IDGenerator.generate_task_id()),
            state=TaskState(data.get("state", TaskState.SUBMITTED.value)),
            messages=messages,
            artifacts=artifacts,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", utc_now()),
        )

    @classmethod
    def create(cls, message: Message) -> "Task":
        """Create a new task with an initial message."""
        return cls(messages=[message])

    def get_last_item(self) -> Message | Artifact | None:
        """
        Return the most recently appended Message or Artifact in this Task.

        Since messages and artifacts are appended in order, the last item in each list is always the most recent.
        We compare timestamps of the last Message and last Artifact to determine which is more recent.
        """
        if not self.messages and not self.artifacts:
            return None

        # Get candidates (last items from each collection)
        candidates = []
        if self.messages:
            candidates.append(self.messages[-1])
        if self.artifacts:
            candidates.append(self.artifacts[-1])

        # Return single candidate or compare timestamps
        if len(candidates) == 1:
            return candidates[0]

        # Sort by timestamp (descending) and return first
        return max(candidates, key=lambda x: x.timestamp)

    @staticmethod
    def tool_call(
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> Part:
        """
        Create a tool_call Part to be executed by an agent.

        This represents an explicit request to invoke a tool.
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

        An infer explicitly instructs the agent to invoke its LLM.
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
        """
        last_item = self.get_last_item()
        if last_item is None:
            return None

        # Get the last part from the last item
        if last_item.parts:
            last_part = last_item.parts[-1]
            return last_part.content
        return None
