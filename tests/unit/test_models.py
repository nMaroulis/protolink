"""Unit tests for the core models in the Protolink A2A library."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from protolink import Message, Task, TaskPriority, TaskStatus


class TestMessage:
    """Tests for the Message model."""
    
    def test_create_message_with_required_fields(self):
        """Test creating a message with required fields only."""
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
        )
        
        assert message.message_id == "msg-123"
        assert message.message_type == "test_message"
        assert message.sender_id == "sender-1"
        assert message.recipient_id == "recipient-1"
        assert message.payload == {"key": "value"}
        assert message.timestamp is not None
        assert message.correlation_id is None
        assert message.metadata == {}
    
    def test_create_message_with_all_fields(self):
        """Test creating a message with all fields."""
        timestamp = datetime.now(timezone.utc)
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
            correlation_id="corr-456",
            timestamp=timestamp,
            metadata={"priority": "high"},
        )
        
        assert message.message_id == "msg-123"
        assert message.correlation_id == "corr-456"
        assert message.timestamp == timestamp
        assert message.metadata == {"priority": "high"}
    
    def test_message_serialization(self):
        """Test serializing and deserializing a message."""
        message = Message(
            message_id="msg-123",
            message_type="test_message",
            sender_id="sender-1",
            recipient_id="recipient-1",
            payload={"key": "value"},
        )
        
        # Serialize to JSON
        json_str = message.model_dump_json()
        data = json.loads(json_str)
        
        # Check serialized fields
        assert data["message_id"] == "msg-123"
        assert data["message_type"] == "test_message"
        assert data["sender_id"] == "sender-1"
        assert data["recipient_id"] == "recipient-1"
        assert data["payload"] == {"key": "value"}
        
        # Deserialize back to Message
        new_message = Message.model_validate(data)
        assert new_message == message
    
    def test_create_response_message(self):
        """Test creating a response message."""
        original = Message(
            message_id="msg-123",
            message_type="request",
            sender_id="client-1",
            recipient_id="agent-1",
            payload={"action": "get_status"},
        )
        
        response = original.create_response(
            message_type="response",
            payload={"status": "ok"},
            metadata={"processed": True},
        )
        
        assert response.message_type == "response"
        assert response.sender_id == "agent-1"
        assert response.recipient_id == "client-1"
        assert response.correlation_id == "msg-123"
        assert response.payload == {"status": "ok"}
        assert response.metadata == {"processed": True}
        assert response.timestamp > original.timestamp


class TestTask:
    """Tests for the Task model."""
    
    def test_create_task_with_required_fields(self):
        """Test creating a task with required fields only."""
        task = Task(
            task_id="task-123",
            task_type="process_data",
            parameters={"input": "test"},
            created_by="user-1",
        )
        
        assert task.task_id == "task-123"
        assert task.task_type == "process_data"
        assert task.parameters == {"input": "test"}
        assert task.created_by == "user-1"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.MEDIUM
        assert task.progress == 0.0
        assert task.result is None
        assert task.error is None
        assert task.metadata == {}
        assert task.created_at is not None
        assert task.updated_at is not None
        assert task.completed_at is None
    
    def test_create_task_with_all_fields(self):
        """Test creating a task with all fields."""
        created_at = datetime.now(timezone.utc)
        updated_at = created_at
        completed_at = created_at
        
        task = Task(
            task_id="task-123",
            task_type="process_data",
            parameters={"input": "test"},
            created_by="user-1",
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.HIGH,
            progress=1.0,
            result={"output": "result"},
            error=None,
            metadata={"retry_count": 3},
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
        )
        
        assert task.status == TaskStatus.COMPLETED
        assert task.priority == TaskPriority.HIGH
        assert task.progress == 1.0
        assert task.result == {"output": "result"}
        assert task.metadata == {"retry_count": 3}
        assert task.completed_at == completed_at
    
    def test_task_serialization(self):
        """Test serializing and deserializing a task."""
        task = Task(
            task_id="task-123",
            task_type="process_data",
            parameters={"input": "test"},
            created_by="user-1",
            status=TaskStatus.RUNNING,
            priority=TaskPriority.HIGH,
            progress=0.5,
        )
        
        # Serialize to JSON
        json_str = task.model_dump_json()
        data = json.loads(json_str)
        
        # Check serialized fields
        assert data["task_id"] == "task-123"
        assert data["task_type"] == "process_data"
        assert data["parameters"] == {"input": "test"}
        assert data["status"] == "running"
        assert data["priority"] == "high"
        assert data["progress"] == 0.5
        
        # Deserialize back to Task
        new_task = Task.model_validate(data)
        assert new_task.task_id == task.task_id
        assert new_task.status == task.status
        assert new_task.progress == task.progress
    
    def test_task_status_transitions(self):
        """Test valid and invalid task status transitions."""
        task = Task(
            task_id="task-123",
            task_type="test",
            parameters={},
            created_by="user-1",
        )
        
        # Valid transitions
        task.status = TaskStatus.PENDING
        task.status = TaskStatus.RUNNING
        task.status = TaskStatus.COMPLETED
        
        # Reset
        task.status = TaskStatus.PENDING
        task.status = TaskStatus.RUNNING
        task.status = TaskStatus.FAILED
        
        # Reset and test cancellation
        task.status = TaskStatus.PENDING
        task.status = TaskStatus.CANCELLED
        
        # Test invalid transition from COMPLETED to RUNNING
        with pytest.raises(ValueError):
            task.status = TaskStatus.RUNNING
        
        # Test invalid transition from FAILED to RUNNING
        task.status = TaskStatus.FAILED
        with pytest.raises(ValueError):
            task.status = TaskStatus.RUNNING
    
    def test_task_priority_validation(self):
        """Test task priority validation."""
        # Valid priorities
        for priority in ["low", "medium", "high"]:
            task = Task(
                task_id=f"task-{priority}",
                task_type="test",
                parameters={},
                created_by="user-1",
                priority=priority,
            )
            assert task.priority == TaskPriority(priority)
        
        # Invalid priority
        with pytest.raises(ValueError):
            Task(
                task_id="task-invalid",
                task_type="test",
                parameters={},
                created_by="user-1",
                priority="invalid",
            )
    
    def test_task_progress_validation(self):
        """Test task progress validation."""
        # Valid progress values
        for progress in [0.0, 0.5, 1.0]:
            task = Task(
                task_id=f"task-{progress}",
                task_type="test",
                parameters={},
                created_by="user-1",
                progress=progress,
            )
            assert task.progress == progress
        
        # Progress out of range
        with pytest.raises(ValueError):
            Task(
                task_id="task-invalid-progress",
                task_type="test",
                parameters={},
                created_by="user-1",
                progress=1.5,  # Invalid
            )
        
        with pytest.raises(ValueError):
            Task(
                task_id="task-negative-progress",
                task_type="test",
                parameters={},
                created_by="user-1",
                progress=-0.1,  # Invalid
            )
