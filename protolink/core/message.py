"""Message handling for the A2A protocol.

This module defines the message format and types used for communication
between agents in the Protolink system.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, validator


class MessageType(str, Enum):
    """Types of messages that can be exchanged between agents."""
    # Basic message types
    PING = "ping"
    PONG = "pong"
    
    # Task-related messages
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    TASK_UPDATE = "task_update"
    
    # Artifact exchange
    ARTIFACT_UPLOAD = "artifact_upload"
    ARTIFACT_DOWNLOAD = "artifact_download"
    
    # Discovery and registration
    REGISTER = "register"
    DISCOVER = "discover"
    HEARTBEAT = "heartbeat"
    
    # Error handling
    ERROR = "error"


class Message(BaseModel):
    """Base message format for all A2A communications.
    
    Messages are the primary means of communication between agents.
    They follow a consistent JSON-based format with a type, sender/receiver IDs,
    and a flexible payload structure.
    """
    
    # Core fields
    id: str = Field(
        default_factory=lambda: f"msg_{__import__('uuid').uuid4().hex}",
        description="Unique message identifier"
    )
    type: Union[str, MessageType] = Field(
        ...,
        description="Message type, determines how the payload should be interpreted"
    )
    sender: str = Field(
        ...,
        description="ID of the sending agent"
    )
    receiver: str = Field(
        ...,
        description="ID of the intended recipient agent"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO 8601 timestamp of when the message was created"
    )
    
    # Payload and metadata
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Message payload, structure depends on message type"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the message"
    )
    
    # Validation
    @validator('type')
    def validate_message_type(cls, v):
        """Ensure message type is valid."""
        if isinstance(v, str):
            try:
                return MessageType(v.lower())
            except ValueError:
                # Allow custom message types that aren't in the enum
                return v
        return v
    
    @validator('timestamp')
    def validate_timestamp(cls, v):
        """Ensure timestamp is in ISO 8601 format."""
        if isinstance(v, str):
            try:
                datetime.fromisoformat(v.replace('Z', '+00:00'))
                return v
            except ValueError:
                pass
        return datetime.utcnow().isoformat()
    
    # Serialization
    def to_json(self) -> str:
        """Serialize the message to a JSON string."""
        return self.json()
    
    @classmethod
    def from_json(cls, json_str: str) -> Message:
        """Deserialize a message from a JSON string."""
        return cls.parse_raw(json_str)
    
    # Helper methods
    def create_reply(
        self,
        message_type: Union[str, MessageType],
        payload: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Message:
        """Create a reply to this message.
        
        Args:
            message_type: Type of the reply message
            payload: Optional payload for the reply
            **kwargs: Additional fields to include in the reply
            
        Returns:
            A new Message instance with sender/receiver swapped
        """
        return Message(
            type=message_type,
            sender=self.receiver,
            receiver=self.sender,
            payload=payload or {},
            **kwargs
        )
    
    def is_error(self) -> bool:
        """Check if this message represents an error."""
        return self.type == MessageType.ERROR or "error" in self.payload
    
    def get_error(self) -> Optional[Dict[str, Any]]:
        """Get error details if this is an error message."""
        if self.type == MessageType.ERROR:
            return self.payload
        return self.payload.get("error")
