"""Bounded workflow traversal using native budgets and cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from protolink.core.budget import BudgetExceededError
from protolink.core.execution import emit_runtime_event, execution_scope, workflow_budget_scope
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState


def merge_node_result(parent: Task, result: Task) -> None:
    """Retain node outputs without prematurely completing the enclosing task."""
    context = RunContext.from_task(parent)
    history = parent.metadata.get("state_history", [])
    events = {event["event_id"]: event for event in parent.metadata.get("run_events", [])}
    events.update({event["event_id"]: event for event in result.metadata.get("run_events", [])})
    message_ids = {message.id for message in parent.messages}
    artifact_ids = {artifact.id for artifact in parent.artifacts}
    for message in result.messages:
        if message.id not in message_ids:
            parent.add_message(message)
    for artifact in result.artifacts:
        if artifact.id not in artifact_ids:
            parent.add_artifact(artifact)
    parent.metadata.update(result.metadata)
    parent.metadata["state_history"] = history
    parent.metadata["run_events"] = list(events.values())
    context.attach_to_task(parent)


class WorkflowLimitError(RuntimeError):
    """A node-visit or iteration boundary stopped traversal before another effect."""

    def __init__(self, *, limit: int, observed: int, node: str | None = None) -> None:
        """Retain machine-readable limit information for blockers and reports."""
        self.limit, self.observed, self.node = limit, observed, node
        super().__init__(
            f"Workflow safety threshold exceeded: {observed} visits > {limit}" + (f" at {node}" if node else "")
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bounded traversal failure."""
        return {"code": "workflow_limit", "limit": self.limit, "observed": self.observed, "node": self.node}


def workflow_execution(method: Callable[..., Awaitable[Task]]) -> Callable[..., Awaitable[Task]]:
    """Wrap existing flow execution with shared native budgets and reporting."""

    @wraps(method)
    async def execute(self: Any, task: Task) -> Task:
        context = RunContext.ensure_task_context(task)
        with workflow_budget_scope(context) as budget, execution_scope(task):
            try:
                if context.canceled:
                    raise asyncio.CancelledError(context.cancel_reason)
                if task.is_terminal:
                    return task
                task.begin()
                decision = budget.evaluate()
                if not decision.allowed:
                    raise BudgetExceededError(decision)
                limit = budget.budget.max_runtime_seconds
                remaining = (
                    max(0.0, limit - (decision.usage.runtime_seconds if decision.usage else 0.0))
                    if limit is not None
                    else None
                )
                async with asyncio.timeout(remaining):
                    result = await method(self, task)
                merge_node_result(task, result)
                state = (
                    result.state
                    if result.is_terminal or result.state is TaskState.INPUT_REQUIRED
                    else TaskState.COMPLETED
                )
                if not task.is_terminal:
                    task.update_state(state)
                return task
            except (WorkflowLimitError, BudgetExceededError, TimeoutError) as exc:
                if isinstance(exc, WorkflowLimitError):
                    blocker = exc.to_dict()
                elif isinstance(exc, BudgetExceededError):
                    blocker = {"code": "budget_exceeded", "decision": exc.decision.to_dict()}
                else:
                    blocker = {"code": "budget_exceeded", "limit": "max_runtime_seconds"}
                task.metadata.setdefault("blockers", []).append(blocker)
                await emit_runtime_event("workflow.blocked", context, blocker=blocker)
                if not task.is_terminal:
                    task.fail(str(exc))
                raise
            except asyncio.CancelledError:
                await emit_runtime_event("workflow.canceled", context)
                if not task.is_terminal:
                    task.cancel("Workflow canceled")
                raise
            except Exception as exc:
                if not task.is_terminal:
                    task.fail(str(exc))
                raise

    return execute
