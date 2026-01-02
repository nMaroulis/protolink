"""
ProtoLink - Events

Event classes for task streaming and real-time updates.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from protolink.utils import utc_now


@dataclass
class TaskStatusUpdateEvent:
    """Task state transition event for streaming updates.

    Emitted when a task changes state (e.g., submitted → working → completed).
    Can be streamed to clients via SSE for real-time progress visibility.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task being updated
        previous_state: State before transition (or None for initial)
        new_state: Current task state
        timestamp: When event occurred
        final: Whether this ends the stream
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    previous_state: str | None = None
    new_state: str = ""
    timestamp: str = field(default_factory=lambda: utc_now())
    final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_status_update",
            "task_id": self.task_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "timestamp": self.timestamp,
            "final": self.final,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskStatusUpdateEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state", ""),
            timestamp=data.get("timestamp", utc_now()),
            final=data.get("final", False),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskArtifactUpdateEvent:
    """New artifact available event.

    Emitted when a task produces an output artifact (file, result, etc.).
    Allows progressive delivery of results in streaming scenarios.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task
        artifact: The artifact that was produced
        timestamp: When event occurred
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    artifact: Any = None  # Artifact object
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        artifact_dict = None
        if self.artifact and hasattr(self.artifact, "to_dict"):
            artifact_dict = self.artifact.to_dict()

        return {
            "event_id": self.event_id,
            "type": "task_artifact_update",
            "task_id": self.task_id,
            "artifact": artifact_dict,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskArtifactUpdateEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            artifact=data.get("artifact"),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskProgressEvent:
    """Task progress update event.

    Emitted to report incremental progress (e.g., 50% complete).
    Useful for long-running tasks that want to signal advancement.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task
        progress: Completion percentage (0-100)
        message: Optional progress message
        timestamp: When event occurred
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    progress: int = 0  # 0-100
    message: str | None = None
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_progress",
            "task_id": self.task_id,
            "progress": self.progress,
            "message": self.message,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskProgressEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            progress=data.get("progress", 0),
            message=data.get("message"),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskErrorEvent:
    """Task error event.

    Emitted when a task encounters an error.
    Allows streaming of error details without closing connection.

    Attributes:
        event_id: Unique event identifier
        task_id: ID of the task
        error_code: Error code/type
        error_message: Human-readable error description
        recoverable: Whether error is recoverable
        timestamp: When event occurred
        metadata: Additional event data
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    error_code: str = ""
    error_message: str = ""
    recoverable: bool = False
    timestamp: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert event to dictionary for transmission."""
        return {
            "event_id": self.event_id,
            "type": "task_error",
            "task_id": self.task_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "recoverable": self.recoverable,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskErrorEvent":
        """Create event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            error_code=data.get("error_code", ""),
            error_message=data.get("error_message", ""),
            recoverable=data.get("recoverable", False),
            timestamp=data.get("timestamp", utc_now()),
            metadata=data.get("metadata", {}),
        )
