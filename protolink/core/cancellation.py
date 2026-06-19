"""Cooperative cancellation primitives for active Protolink task runs.

Task lifecycle state and live execution control are deliberately separate.
``Task.cancel()`` and ``RunContext.canceled`` are serializable facts about a
run, while ``CancellationToken`` and ``TaskExecutionRegistry`` are process-local
runtime objects used to interrupt work that is currently executing.

Cancellation is best-effort. Async model calls, tools, and agent delegation can
usually be interrupted at an await point. Synchronous functions and remote
systems may not be immediately stoppable and must provide their own cooperative
or process-level cancellation when stronger guarantees are required.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from protolink.core.run_context import RunContext
from protolink.utils import utc_now

if TYPE_CHECKING:
    from protolink.core.task import Task


class TaskCancellationError(RuntimeError):
    """Base exception for task cancellation control-plane failures."""


class TaskNotFoundError(TaskCancellationError):
    """Raised when cancellation targets a task that is not currently active."""


class TaskNotCancelableError(TaskCancellationError):
    """Raised when a known task has already reached a terminal state."""


class TaskAlreadyRunningError(TaskCancellationError):
    """Raised when the same task ID is concurrently submitted more than once."""


@dataclass(frozen=True)
class TaskCancellationRequest:
    """Serializable request to cancel one active task.

    The wire shape follows the A2A ``TaskIdParams`` convention by using ``id``
    and an extensible metadata object. ``reason`` is exposed as a convenience
    field and is also mirrored into metadata during serialization.

    Attributes:
        id: Identifier of the task to cancel.
        reason: Optional human-readable reason for the cancellation request.
        metadata: Additional control-plane metadata supplied by the caller.
    """

    id: str
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the task ID and defensively copy request metadata."""
        if not self.id.strip():
            raise ValueError("TaskCancellationRequest.id must not be empty")
        metadata = dict(self.metadata)
        if self.reason is not None:
            metadata.setdefault("reason", self.reason)
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the request using an A2A-compatible task-ID payload."""
        metadata = dict(self.metadata)
        if self.reason is not None:
            metadata.setdefault("reason", self.reason)
        return {"id": self.id, "metadata": metadata}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskCancellationRequest:
        """Create a cancellation request from serialized task-ID parameters."""
        metadata = dict(data.get("metadata") or {})
        reason = data.get("reason", metadata.get("reason"))
        return cls(
            id=str(data.get("id") or data.get("task_id") or ""),
            reason=str(reason) if reason is not None else None,
            metadata=metadata,
        )


class CancellationToken:
    """Thread-safe, process-local signal for cooperative task cancellation.

    The token uses ``threading.Event`` rather than ``asyncio.Event`` because an
    Agent may serve work on a background event-loop thread while a direct caller
    requests cancellation from another thread. Consumers normally call
    ``raise_if_cancelled()`` at safe execution boundaries; the active-task
    registry also cancels the owning ``asyncio.Task`` for prompt interruption at
    await points.
    """

    def __init__(self) -> None:
        """Initialize an uncanceled token."""
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._reason: str | None = None
        self._canceled_at: str | None = None

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        """Return the first cancellation reason supplied to the token."""
        with self._lock:
            return self._reason

    @property
    def canceled_at(self) -> str | None:
        """Return the timestamp of the first cancellation request."""
        with self._lock:
            return self._canceled_at

    def cancel(self, reason: str | None = None) -> bool:
        """Signal cancellation and return whether this was the first request.

        Repeated calls are idempotent and preserve the first reason so traces
        and final task metadata remain deterministic.
        """
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason
            self._canceled_at = utc_now()
            self._event.set()
            return True

    def raise_if_cancelled(self) -> None:
        """Raise ``asyncio.CancelledError`` when cancellation was requested."""
        if self.is_cancelled:
            raise asyncio.CancelledError(self.reason or "Task cancellation requested")


@dataclass
class ActiveTaskExecution:
    """Process-local record connecting a protocol task to its coroutine."""

    task: Task
    token: CancellationToken
    execution_task: asyncio.Task[Any]
    loop: asyncio.AbstractEventLoop
    started_at: str = field(default_factory=lambda: utc_now())
    previous_state: str | None = None

    def request_cancel(self, reason: str | None = None) -> Task:
        """Mark task state and request interruption of the owning coroutine."""
        if self.task.is_terminal:
            raise TaskNotCancelableError(
                f"Task '{self.task.id}' cannot be canceled from terminal state '{self.task.state.value}'"
            )

        self.previous_state = self.task.state.value
        self.token.cancel(reason)
        mark_task_canceled(self.task, reason)

        current = asyncio.current_task()
        if current is self.execution_task:
            return self.task

        if self.execution_task.done() or self.loop.is_closed():
            return self.task

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self.loop:
            self.execution_task.cancel(reason or "Task cancellation requested")
        else:
            try:
                self.loop.call_soon_threadsafe(
                    self.execution_task.cancel,
                    reason or "Task cancellation requested",
                )
            except RuntimeError:
                # The loop may close between ``is_closed()`` and scheduling.
                # Serialized task state is already canceled, so no additional
                # process-local interruption is possible or required here.
                pass
        return self.task


class TaskExecutionRegistry:
    """Thread-safe registry of tasks currently executing on one Agent.

    The registry is intentionally in-memory and bounded by active execution.
    Durable task history remains the responsibility of Protolink storage and
    application state; this object only provides the live control plane needed
    to locate a coroutine for cancellation.
    """

    def __init__(self) -> None:
        """Initialize an empty active-task registry."""
        self._entries: dict[str, ActiveTaskExecution] = {}
        self._lock = threading.RLock()

    @property
    def task_ids(self) -> tuple[str, ...]:
        """Return a stable snapshot of active task IDs."""
        with self._lock:
            return tuple(self._entries)

    def register(self, task: Task) -> tuple[ActiveTaskExecution, bool]:
        """Register the current coroutine as owner of ``task`` execution.

        Nested default runtime layers may register the same task from the same
        coroutine; those registrations reuse the existing entry and return
        ``owner=False``. A second coroutine using the same task ID is rejected.

        Returns:
            ``(entry, owner)`` where ``owner`` controls cleanup responsibility.
        """
        execution_task = asyncio.current_task()
        if execution_task is None:
            raise RuntimeError("Task execution registration requires an active asyncio task")
        loop = asyncio.get_running_loop()

        with self._lock:
            existing = self._entries.get(task.id)
            if existing is not None:
                if existing.execution_task is execution_task:
                    return existing, False
                raise TaskAlreadyRunningError(f"Task '{task.id}' is already running")

            entry = ActiveTaskExecution(
                task=task,
                token=CancellationToken(),
                execution_task=execution_task,
                loop=loop,
            )
            self._entries[task.id] = entry
            return entry, True

    def unregister(self, task_id: str, execution_task: asyncio.Task[Any]) -> None:
        """Remove an entry only when the supplied coroutine still owns it."""
        with self._lock:
            existing = self._entries.get(task_id)
            if existing is not None and existing.execution_task is execution_task:
                self._entries.pop(task_id, None)

    def get(self, task_id: str) -> ActiveTaskExecution | None:
        """Return the active execution for ``task_id`` if present."""
        with self._lock:
            return self._entries.get(task_id)

    def get_token(self, task_id: str) -> CancellationToken | None:
        """Return the live cancellation token for an active task."""
        entry = self.get(task_id)
        return entry.token if entry is not None else None

    def cancel(self, task_id: str, reason: str | None = None) -> Task:
        """Request cancellation of one active task and return its updated model."""
        entry = self.get(task_id)
        if entry is None:
            raise TaskNotFoundError(f"Active task '{task_id}' was not found")
        return entry.request_cancel(reason)


def mark_task_canceled(task: Task, reason: str | None = None) -> None:
    """Synchronize cancellation state across ``Task`` and ``RunContext``.

    The helper is idempotent for an already canceled task and intentionally does
    not overwrite other terminal states.
    """
    from protolink.core.task import TaskState

    context = RunContext.from_task(task).cancel(reason)
    context.attach_to_task(task)

    if task.state is TaskState.CANCELED:
        if reason and not task.metadata.get("cancel_reason"):
            task.metadata["cancel_reason"] = reason
        return
    if task.is_terminal:
        return
    task.cancel(reason)
