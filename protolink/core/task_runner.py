from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
from protolink.core.task import Task, TaskState

# ----------------------------------------------------------------------
# Task Lifecycle & TaskRunner
# ----------------------------------------------------------------------


class TaskLifecycle:
    """Apply protocol-safe task state transitions.

    This helper is intentionally small: it centralizes lifecycle transitions
    for code that interprets already-produced outputs. It does not execute
    tools, call LLMs, or perform agent dispatch.
    """

    @staticmethod
    def _begin_if_needed(task: Task) -> None:
        """Move a non-terminal task to ``WORKING`` before a final transition."""
        if not task.is_terminal and task.state != TaskState.WORKING:
            task.update_state(TaskState.WORKING)

    def submit(self, task: Task) -> Task:
        """Mark a task as submitted."""
        return task.update_state(TaskState.SUBMITTED)

    def begin(self, task: Task) -> Task:
        """Mark a task as actively being processed."""
        return task.update_state(TaskState.WORKING)

    def require_input(self, task: Task, message: Message | None = None) -> Task:
        """Mark a task as waiting for additional input."""
        self._begin_if_needed(task)
        task.update_state(TaskState.INPUT_REQUIRED)
        if message:
            task.add_message(message)
        return task

    def complete(
        self,
        task: Task,
        message: Message | None = None,
        artifacts: list[Artifact] | None = None,
    ) -> Task:
        """Mark a task as completed and optionally attach outputs."""
        self._begin_if_needed(task)
        task.update_state(TaskState.COMPLETED)
        if message:
            task.add_message(message)
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task

    def fail(
        self,
        task: Task,
        error: str,
        artifacts: list[Artifact] | None = None,
    ) -> Task:
        """Mark a task as failed and record the error message."""
        task.update_state(TaskState.FAILED)
        task.metadata["error"] = error
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task

    def cancel(
        self,
        task: Task,
        reason: str | None = None,
        artifacts: list[Artifact] | None = None,
    ) -> Task:
        """Mark a task as canceled and optionally record a reason."""
        task.update_state(TaskState.CANCELED)
        if reason:
            task.metadata["cancel_reason"] = reason
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task


class TaskRunner:
    """
    Applies protocol-level outputs (Message / Part)
    to a Task and advances its lifecycle.

    The runner never calls the agent.
    It only interprets outputs.
    """

    def __init__(self, lifecycle: TaskLifecycle | None = None):
        self.lifecycle = lifecycle or TaskLifecycle()

    def apply(
        self,
        task: Task,
        outputs: list[Message | Part],
    ) -> Task:
        """
        Apply agent outputs to a task and update state accordingly.
        """

        if task.state not in {
            TaskState.SUBMITTED,
            TaskState.WORKING,
            TaskState.INPUT_REQUIRED,
        }:
            return task

        messages: list[Message] = []
        artifacts: list[Artifact] = []
        requires_input = False
        has_tool_call = False

        for output in outputs:
            if isinstance(output, Message):
                messages.append(output)

            elif isinstance(output, Part):
                artifacts.append(Artifact(parts=[output]))

                if output.type == "tool_call":
                    has_tool_call = True

                if output.type == "status" and output.content.get("state") == "input_required":
                    requires_input = True

                if output.type == "error":
                    return self.lifecycle.fail(
                        task,
                        error=output.content.get("message", "unknown error"),
                        artifacts=artifacts,
                    )

        # ---- lifecycle decisions ----

        for msg in messages:
            task.add_message(msg)

        for art in artifacts:
            task.add_artifact(art)

        if has_tool_call:
            return self.lifecycle.begin(task)

        if requires_input:
            return self.lifecycle.require_input(task)

        if messages or artifacts:
            return self.lifecycle.complete(task)

        return task
