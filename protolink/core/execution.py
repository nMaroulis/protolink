"""Shared execution context for optional prepared tools and runtime events.

This module carries live objects only within an invocation. It does not resume
tasks, retain authorizations for reuse, or replace the Agent dispatcher.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from protolink.core.budget import BudgetEnforcer, BudgetExceededError
from protolink.core.cancellation import CancellationToken
from protolink.core.events import EventSink, RunEvent
from protolink.core.policy import ActionAuthorization, ActionPolicyError
from protolink.core.run_context import RunContext
from protolink.core.task import Task
from protolink.utils.serialization import Serializer

if TYPE_CHECKING:
    from protolink.tools.base import BaseTool

_scope: ContextVar[tuple[Task | None, EventSink | None]] = ContextVar("execution_scope", default=(None, None))
_events_suppressed: ContextVar[bool] = ContextVar("runtime_events_suppressed", default=False)
_workflow_budget: ContextVar[BudgetEnforcer | None] = ContextVar("workflow_budget", default=None)


def current_workflow_budget() -> BudgetEnforcer | None:
    """Return the budget shared by nodes in the current structured workflow."""
    return _workflow_budget.get()


@contextmanager
def workflow_budget_scope(context: RunContext) -> Iterator[BudgetEnforcer]:
    """Share native counters across nested workflows without global run state."""
    budget = _workflow_budget.get() or BudgetEnforcer(context)
    token = _workflow_budget.set(budget)
    try:
        yield budget
    finally:
        _workflow_budget.reset(token)


@contextmanager
def suppress_runtime_events() -> Iterator[None]:
    """Let an existing event producer report authorization without duplicate events."""
    token = _events_suppressed.set(True)
    try:
        yield
    finally:
        _events_suppressed.reset(token)


@contextmanager
def execution_scope(task: Task | None = None, sink: EventSink | None = None) -> Iterator[None]:
    """Bind a task and optional event observer for the current async invocation."""
    parent_task, parent_sink = _scope.get()
    token = _scope.set((task if task is not None else parent_task, sink if sink is not None else parent_sink))
    try:
        yield
    finally:
        _scope.reset(token)


def current_task() -> Task | None:
    """Return the task bound to this invocation, if any."""
    return _scope.get()[0]


@contextmanager
def isolate_event_sink() -> Iterator[None]:
    """Keep unary in-process peers from inheriting a caller's live event observer.

    Worker task receipts still persist normally and can be merged from the
    response, just as they are across a network transport boundary.
    """
    token = _scope.set((current_task(), None))
    try:
        yield
    finally:
        _scope.reset(token)


@asynccontextmanager
async def closing_stream(source: AsyncIterator[Any]) -> AsyncIterator[AsyncIterator[Any]]:
    """Close nested generators promptly when a stream consumer leaves."""
    try:
        yield source
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            await close()


async def emit_runtime_event(
    event_type: str, context: RunContext, *, action_id: str | None = None, **payload: Any
) -> RunEvent:
    """Record a native event and notify an optional, non-authoritative observer."""
    task = current_task()
    try:
        serialized = Serializer.serialize_to_dict(payload)
    except (TypeError, ValueError):
        serialized = {"result_omitted": True, "reason": "Result has no JSON representation"}
    event = RunEvent(
        type=event_type,
        run_id=context.run_id,
        task_id=task.id if task else None,
        agent_name=context.agent_chain[-1] if context.agent_chain else None,
        action_id=action_id,
        payload=serialized,
    )
    if _events_suppressed.get():
        return event
    await publish_runtime_event(event)
    return event


async def publish_runtime_event(event: RunEvent) -> None:
    """Retain an existing event's identity when recording it in the active task."""
    task, sink = _scope.get()
    if task is not None:
        task.metadata.setdefault("run_events", []).append(event.to_dict())
    if sink is not None:
        try:
            await sink.emit(event)
        except Exception:
            # An observer failure cannot invalidate an already committed effect.
            pass


@dataclass(frozen=True)
class ToolExecution:
    """Live context supplied to a tool's optional ``execute_authorized`` hook.

    ``authorization.action`` is the exact prepared operation. Hooks must execute
    that operation, checking resource preconditions immediately before effects.
    """

    authorization: ActionAuthorization
    context: RunContext
    budget: BudgetEnforcer
    cancellation: CancellationToken | None = None

    @property
    def task_id(self) -> str | None:
        """Identifier of the active task, absent for standalone tool calls."""
        task = current_task()
        return task.id if task else None

    def check(self) -> None:
        """Reject cancellation or exhausted budgets before a side effect."""
        if self.context.canceled:
            raise asyncio.CancelledError(self.context.cancel_reason)
        if self.cancellation is not None:
            self.cancellation.raise_if_cancelled()
        decision = self.budget.evaluate()
        if not decision.allowed:
            raise BudgetExceededError(decision)

    @property
    def remaining_seconds(self) -> float | None:
        """Remaining native runtime budget, or ``None`` for an unlimited run."""
        limit = self.budget.budget.max_runtime_seconds
        if limit is None:
            return None
        usage = self.budget.evaluate().usage
        return max(0.0, limit - (usage.runtime_seconds if usage else 0.0))

    async def emit(self, event_type: str, **payload: Any) -> RunEvent:
        """Emit output or resource evidence correlated with this action."""
        payload.pop("action_id", None)
        return await emit_runtime_event(
            event_type, self.context, action_id=self.authorization.action.action_id, **payload
        )


async def execute_authorized_tool(tool: BaseTool, execution: ToolExecution) -> Any:
    """Dispatch an authorized prepared tool or the existing callable contract.

    Budget counters are charged by the caller once, before this hook. Results
    are recorded before returning to optional telemetry or model-history code.
    """
    execution.check()
    action = execution.authorization.action
    await execution.emit("action.started", action=action.to_dict())
    execution.check()
    try:
        hook = getattr(tool, "execute_authorized", None)
        result = await hook(execution) if callable(hook) else await tool(**action.payload["arguments"])
    except asyncio.CancelledError:
        await execution.emit("action.canceled", action=action.to_dict())
        raise
    except Exception as exc:
        await execution.emit(
            "action.failed", action=action.to_dict(), error={"code": type(exc).__name__, "message": str(exc)}
        )
        raise
    await execution.emit("action.completed", action=action.to_dict(), result=result)
    return result


async def record_task_blocker(task: Task, error: Exception) -> None:
    """Retain machine-readable policy/budget failures on native task results."""
    if isinstance(error, BudgetExceededError):
        blocker = {"code": "budget_exceeded", "decision": error.decision.to_dict()}
        event_type = "budget.exceeded"
    elif isinstance(error, ActionPolicyError):
        blocker = {
            "code": type(error).__name__,
            "action_id": error.action.action_id,
            "decision": error.decision.to_dict(),
        }
        event_type = "task.blocked"
    else:
        return
    blockers = task.metadata.setdefault("blockers", [])
    if blocker not in blockers:
        blockers.append(blocker)
        with execution_scope(task):
            await emit_runtime_event(event_type, RunContext.from_task(task), blocker=blocker)


async def stream_runtime_events(source: AsyncIterator[Any], task: Task) -> AsyncIterator[Any]:
    """Merge native events into an existing task stream without buffering output indefinitely."""
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
    done = object()
    consumer_closed = False

    class Sink:
        async def emit(self, event: RunEvent) -> None:
            if not consumer_closed:
                await queue.put(event)

    async def produce() -> None:
        with execution_scope(task, Sink()):
            try:
                async for event in source:
                    if not consumer_closed:
                        await queue.put(event)
            except BaseException as exc:
                if not consumer_closed:
                    await queue.put(exc)
            finally:
                close = getattr(source, "aclose", None)
                if close is not None:
                    await close()
                if not consumer_closed:
                    await queue.put(done)

    producer = asyncio.create_task(produce())
    try:
        while True:
            item = await queue.get()
            if item is done:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        consumer_closed = True
        producer.cancel()
        # A closed consumer must not leave a producer blocked on its full queue.
        while not queue.empty():
            queue.get_nowait()
        await asyncio.gather(producer, return_exceptions=True)
