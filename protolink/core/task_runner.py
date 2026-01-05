from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.task import Task, TaskState

# ----------------------------------------------------------------------
# Task Lifecycle & TaskRunner
# ----------------------------------------------------------------------


class TaskLifecycle:
    """Handles transitions of Task states and optional artifacts."""

    def submit(self, task: Task) -> Task:
        return task.update_state(TaskState.SUBMITTED)

    def begin(self, task: Task) -> Task:
        return task.update_state(TaskState.WORKING)

    def require_input(self, task: Task, message: "Message" | None = None) -> Task:
        if message:
            task.add_message(message)
        return task.update_state(TaskState.INPUT_REQUIRED)

    def complete(
        self,
        task: Task,
        message: "Message" | None = None,
        artifacts: list["Artifact"] | None = None,
    ) -> Task:
        if message:
            task.add_message(message)
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task.update_state(TaskState.COMPLETED)

    def fail(
        self,
        task: Task,
        error: str,
        artifacts: list["Artifact"] | None = None,
    ) -> Task:
        task.metadata["error"] = error
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task.update_state(TaskState.FAILED)

    def cancel(
        self,
        task: Task,
        reason: str | None = None,
        artifacts: list["Artifact"] | None = None,
    ) -> Task:
        if reason:
            task.metadata["cancel_reason"] = reason
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task.update_state(TaskState.CANCELED)


class TaskRunner:
    """
    Runs a task by applying direct agent output.
    Fully decoupled from the agent.
    """

    def __init__(self, lifecycle: TaskLifecycle | None = None):
        self.lifecycle = lifecycle or TaskLifecycle()

    def run(
        self,
        task: Task,
        state: TaskState,
        message: "Message" | None = None,
        error: str | None = None,
        reason: str | None = None,
        artifacts: list["Artifact"] | None = None,
    ) -> Task:
        """
        Update task state directly based on agent output.
        One-way: runner never calls agent.
        """
        if task.state not in {TaskState.SUBMITTED, TaskState.WORKING, TaskState.INPUT_REQUIRED}:
            return task

        if state == TaskState.COMPLETED:
            return self.lifecycle.complete(task, message, artifacts)

        if state == TaskState.INPUT_REQUIRED:
            return self.lifecycle.require_input(task, message)

        if state == TaskState.FAILED:
            return self.lifecycle.fail(task, error or "unknown error", artifacts)

        if state == TaskState.CANCELED:
            return self.lifecycle.cancel(task, reason, artifacts)

        # fallback
        return self.lifecycle.fail(task, "unknown state", artifacts)
