from protolink.core.artifact import Artifact
from protolink.core.message import Message
from protolink.core.part import Part
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

    def require_input(self, task: Task, message: Message | None = None) -> Task:
        if message:
            task.add_message(message)
        return task.update_state(TaskState.INPUT_REQUIRED)

    def complete(
        self,
        task: Task,
        message: Message | None = None,
        artifacts: list[Artifact] | None = None,
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
        artifacts: list[Artifact] | None = None,
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
        artifacts: list[Artifact] | None = None,
    ) -> Task:
        if reason:
            task.metadata["cancel_reason"] = reason
        if artifacts:
            for artifact in artifacts:
                task.add_artifact(artifact)
        return task.update_state(TaskState.CANCELED)


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
                artifacts.append(Artifact.from_part(output))

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
