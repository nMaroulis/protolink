"""Small deterministic steps and bounded acceptance loops over ordinary Tasks."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from protolink.client import AgentClient, RegistryClient
from protolink.core.report import RunReport
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState
from protolink.core.validation import CompletionCheck, CompletionValidator
from protolink.discovery import Registry
from protolink.models import Message
from protolink.types import FlowTarget

from .base import Flow
from .limits import WorkflowLimitError, merge_node_result, workflow_execution


class Step(Flow):
    """Adapt a synchronous or async ``Task -> Task`` function into a Flow.

    The callback can be used in Pipeline, Parallel, Router, Graph, or RepeatUntil.
    It receives the current task and must return a Task. Workflow budgets, events,
    and cancellation surround the callback; synchronous Python work remains
    cooperative. Tool execution should go through Agent's public methods.
    """

    def __init__(self, handler: Callable[[Task], Task | Awaitable[Task]]) -> None:
        super().__init__()
        self.handler = handler

    @workflow_execution
    async def execute(self, task: Task) -> Task:
        """Call the handler once; reject results outside the Task contract."""
        result = self.handler(task)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Task):
            raise TypeError("Step handlers must return a Task")
        return result


class ToolStep(Flow):
    """Execute one known tool through a local or remote agent's task lifecycle.

    Args:
        agent: Agent instance or remote name/URL, resolved like other flow targets.
        tool_name: Registered tool to invoke.
        args: Fixed arguments or a synchronous function computing them from the task.
        client: Client for a remote target; unnecessary for a local Agent.
        registry: Registry for a remote name, as on Pipeline.

    Results remain typed tool-output parts. Validation, approvals, execution
    receipts, and cancellation are supplied by the receiving Agent.
    """

    def __init__(
        self,
        agent: FlowTarget,
        tool_name: str,
        args: Mapping[str, Any] | Callable[[Task], Mapping[str, Any]] | None = None,
        *,
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        super().__init__(client=client, registry=registry)
        self.agent, self.tool_name, self.args = agent, tool_name, args

    @workflow_execution
    async def execute(self, task: Task) -> Task:
        """Append a tool instruction and dispatch once using normal flow execution."""
        args = self.args(task) if callable(self.args) else self.args
        if args is not None and not isinstance(args, Mapping):
            raise TypeError("ToolStep args must be a mapping or return one")
        task.add_message(Message.tool_call(tool_name=self.tool_name, args=dict(args or {})))
        return await self._execute_target(self.agent, task)


class RepeatUntil(Flow):
    """Repeat a step until named completion checks pass, within an explicit bound.

    Args:
        step: Agent, remote target, or Flow to execute on each attempt.
        checks: One CompletionCheck or a sequence; at least one is required.
        max_attempts: Positive total attempt count, including the first.
        client: Optional remote client, as on Pipeline.
        registry: Optional registry, as on Pipeline.

    Only failed acceptance triggers another attempt; exceptions and failed,
    canceled, or input-required tasks stop immediately. Repetition is explicit
    and can repeat side effects. Checks see the current attempt's receipts;
    accumulated task history and all validation events remain in the final task.
    Exhaustion raises WorkflowLimitError and records a workflow blocker.
    """

    def __init__(
        self,
        step: FlowTarget,
        checks: CompletionCheck | Sequence[CompletionCheck],
        *,
        max_attempts: int,
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        super().__init__(client=client, registry=registry)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.step, self.max_attempts = step, max_attempts
        items = [checks] if isinstance(checks, CompletionCheck) else list(checks)
        if not items:
            raise ValueError("RepeatUntil requires at least one completion check")
        self.validator = CompletionValidator(items)

    @workflow_execution
    async def execute(self, task: Task) -> Task:
        """Evaluate fresh execution evidence after each successful step."""
        current = task
        for _ in range(self.max_attempts):
            previous = {event["event_id"] for event in current.metadata.get("run_events", [])}
            current = await self._execute_target(self.step, current)
            if current.state in {TaskState.FAILED, TaskState.CANCELED, TaskState.INPUT_REQUIRED}:
                return current
            report = RunReport.from_events(
                [event for event in current.metadata.get("run_events", []) if event["event_id"] not in previous],
                context=RunContext.from_task(current),
                final_task=current.to_dict(),
            )
            results = await self.validator.validate(current, report=report)
            merge_node_result(task, current)
            if all(result.passed for result in results):
                return current
        raise WorkflowLimitError(limit=self.max_attempts, observed=self.max_attempts + 1, node="repeat")
