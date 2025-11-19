import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from protolink.core.artifact import Artifact
from protolink.core.message import Message


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
    """Unit of work exchanged between agents.

    Attributes:
        id: Unique task identifier
        state: Current task state (check TaskState enum)
        messages: Communication history for this task
        artifacts: Output artifacts produced by task (NEW in v0.2.0)
        metadata: Additional task metadata
        created_at: Task creation time
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: TaskState = TaskState.SUBMITTED
    messages: list[Message] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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
            id=data.get("id", str(uuid.uuid4())),
            state=TaskState(data.get("state", TaskState.SUBMITTED.value)),
            messages=messages,
            artifacts=artifacts,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

    @classmethod
    def create(cls, message: Message) -> "Task":
        """Create a new task with an initial message."""
        return cls(messages=[message])
