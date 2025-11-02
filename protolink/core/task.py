"""Task management for the A2A protocol.

This module defines the Task class and related components for managing
tasks that can be executed by agents in the Protolink system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator


class TaskStatus(str, Enum):
    """Possible status values for a task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    """Priority levels for tasks."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class TaskResult(BaseModel):
    """Result of a task execution."""
    task_id: str = Field(
        ...,
        description="ID of the task this result is for"
    )
    status: TaskStatus = Field(
        default=TaskStatus.COMPLETED,
        description="Final status of the task"
    )
    output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Task output data"
    )
    error: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Error details if the task failed"
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Performance metrics and statistics"
    )
    artifacts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="References to any artifacts produced by the task"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="When the task completed"
    )

    @classmethod
    def from_exception(
        cls,
        task_id: str,
        exception: Exception,
        status: TaskStatus = TaskStatus.FAILED,
    ) -> TaskResult:
        """Create a task result from an exception.
        
        Args:
            task_id: ID of the task that failed
            exception: The exception that was raised
            status: Status to set (defaults to FAILED)
            
        Returns:
            A TaskResult indicating failure
        """
        return cls(
            task_id=task_id,
            status=status,
            error={
                "type": exception.__class__.__name__,
                "message": str(exception),
                "details": str(exception.__dict__) if hasattr(exception, "__dict__") else None,
            }
        )


class Task(BaseModel):
    """A unit of work that can be executed by an agent.
    
    Tasks represent work that can be performed by agents. They include
    all the necessary information to execute the task, including parameters,
    priority, and any dependencies.
    """
    
    # Core fields
    id: str = Field(
        default_factory=lambda: f"task_{__import__('uuid').uuid4().hex}",
        description="Unique task identifier"
    )
    type: str = Field(
        ...,
        description="Type of task, determines which handler will process it"
    )
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Current status of the task"
    )
    
    # Task definition
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters for the task"
    )
    priority: TaskPriority = Field(
        default=TaskPriority.NORMAL,
        description="Task priority"
    )
    
    # Metadata
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="When the task was created"
    )
    started_at: Optional[str] = Field(
        default=None,
        description="When the task started executing"
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="When the task completed"
    )
    
    # Relationships
    parent_id: Optional[str] = Field(
        default=None,
        description="ID of the parent task, if this is a subtask"
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="IDs of tasks that must complete before this one can start"
    )
    
    # Execution context
    assigned_agent: Optional[str] = Field(
        default=None,
        description="ID of the agent this task is assigned to"
    )
    timeout_seconds: Optional[float] = Field(
        default=None,
        description="Maximum time in seconds the task is allowed to run"
    )
    
    # Results
    result: Optional[TaskResult] = Field(
        default=None,
        description="Result of the task execution, if completed"
    )
    
    # Validation
    @validator('status')
    def validate_status(cls, v, values):
        """Validate status transitions."""
        if 'status' in values:
            current_status = values['status']
            if current_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                raise ValueError(f"Cannot change status from {current_status}")
        return v
    
    # Helper methods
    def start(self) -> None:
        """Mark the task as started."""
        if self.status != TaskStatus.PENDING:
            raise ValueError(f"Cannot start task with status {self.status}")
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.utcnow().isoformat()
    
    def complete(self, result: Optional[Dict[str, Any]] = None) -> TaskResult:
        """Mark the task as completed with the given result.
        
        Args:
            result: Optional result data
            
        Returns:
            The created TaskResult
        """
        if self.status != TaskStatus.RUNNING:
            raise ValueError(f"Cannot complete task with status {self.status}")
        
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow().isoformat()
        self.result = TaskResult(
            task_id=self.id,
            status=TaskStatus.COMPLETED,
            output=result or {},
            timestamp=self.completed_at,
        )
        return self.result
    
    def fail(self, error: Union[str, Exception]) -> TaskResult:
        """Mark the task as failed with the given error.
        
        Args:
            error: Error message or exception
            
        Returns:
            The created TaskResult
        """
        if self.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ValueError(f"Cannot fail task with status {self.status}")
        
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.utcnow().isoformat()
        
        if isinstance(error, Exception):
            self.result = TaskResult.from_exception(self.id, error, TaskStatus.FAILED)
        else:
            self.result = TaskResult(
                task_id=self.id,
                status=TaskStatus.FAILED,
                error={"message": str(error)},
                timestamp=self.completed_at,
            )
        
        return self.result
    
    def cancel(self) -> TaskResult:
        """Mark the task as cancelled."""
        if self.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ValueError(f"Cannot cancel task with status {self.status}")
        
        self.status = TaskStatus.CANCELLED
        self.completed_at = datetime.utcnow().isoformat()
        self.result = TaskResult(
            task_id=self.id,
            status=TaskStatus.CANCELLED,
            timestamp=self.completed_at,
        )
        return self.result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the task to a dictionary."""
        return self.dict()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        """Create a task from a dictionary."""
        return cls(**data)
