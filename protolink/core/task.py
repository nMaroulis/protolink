from dataclasses import dataclass, field
from typing import Any
from datetime import datetime
import uuid
from protolink.core.message import Message


@dataclass
class Task:
    """Unit of work exchanged between agents.
    
    Attributes:
        id: Unique task identifier
        state: Current task state (submitted, working, completed, failed)
        messages: Communication history for this task
        metadata: Additional task metadata
        created_at: Task creation time
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "submitted"
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def add_message(self, message: Message) -> 'Task':
        """Add a message to the task."""
        self.messages.append(message)
        return self
    
    def update_state(self, state: str) -> 'Task':
        """Update task state."""
        self.state = state
        return self
    
    def complete(self, response_text: str) -> 'Task':
        """Mark task as completed with a response."""
        self.add_message(Message.agent(response_text))
        self.state = "completed"
        return self
    
    def fail(self, error_message: str) -> 'Task':
        """Mark task as failed."""
        self.metadata["error"] = error_message
        self.state = "failed"
        return self
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "state": self.state,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Task':
        """Create from dictionary."""
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            state=data.get("state", "submitted"),
            messages=messages,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.now().isoformat())
        )
    
    @classmethod
    def create(cls, message: Message) -> 'Task':
        """Create a new task with an initial message."""
        return cls(messages=[message])