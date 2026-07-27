"""Core task execution engine for :class:`protolink.agents.Agent`."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any

from protolink.core.actions import RunAction
from protolink.core.budget import BudgetDecision, BudgetEnforcer, BudgetExceededError
from protolink.core.cancellation import ActiveTaskExecution, CancellationToken, mark_task_canceled
from protolink.core.policy import ActionAuthorization, ActionPolicyError
from protolink.core.run_context import RunContext
from protolink.core.task import TaskState
from protolink.llms.history import ConversationHistory
from protolink.models import Artifact, Message, Part, Task

from ._typing import _AgentMixinBase

_TaskBudgetScope = tuple[str, BudgetEnforcer]
_active_task_budget: ContextVar[_TaskBudgetScope | None] = ContextVar(
    "protolink_active_task_budget",
    default=None,
)
_active_inference_action_receipts: ContextVar[set[str] | None] = ContextVar(
    "protolink_active_inference_action_receipts",
    default=None,
)


def _activate_task_budget(task: Task, context: RunContext) -> Token[_TaskBudgetScope | None] | None:
    """Install one enforcer per task id without resetting same-task nesting."""
    current = _active_task_budget.get()
    if current is not None and current[0] == task.id:
        return None
    return _active_task_budget.set((task.id, BudgetEnforcer(context)))


def _deactivate_task_budget(token: Token[_TaskBudgetScope | None] | None) -> None:
    """Restore the previous task budget context when this scope installed it."""
    if token is not None:
        _active_task_budget.reset(token)


def _current_task_budget(task: Task | None) -> BudgetEnforcer | None:
    """Return the scoped enforcer only for the matching task."""
    current = _active_task_budget.get()
    if current is None:
        return None
    task_id, enforcer = current
    if task is None or task.id == task_id:
        return enforcer
    return None


def _accepts_keyword_argument(callback: Any, name: str) -> bool:
    """Return whether a callable accepts one named keyword or arbitrary kwargs."""
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


class AgentExecutionMixin(_AgentMixinBase):
    """Implements task execution, streaming, LLM calls, and delegation."""

    async def run_task(self, task: Task) -> Task:
        """Run the configured task handler under live cancellation control.

        ``AgentServer`` uses this wrapper rather than calling ``handle_task`` directly, so subclasses that override the
        handler still participate in active-task registration and protocol cancellation. Direct callers of a custom
        handler can use this method for the same guarantee.
        """
        if task.is_terminal:
            return task

        execution, owner = self._task_executions.register(task)
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        budget_token = _activate_task_budget(task, context)
        try:
            self._raise_if_execution_canceled(task, execution.token)
            result = await self.handle_task(task)
            self._persist_task_snapshot(result)
            return result
        except asyncio.CancelledError as exc:
            protocol_cancellation = execution.token.is_cancelled
            mark_task_canceled(task, self._cancellation_reason(exc, execution.token))
            self._persist_task_snapshot(task)
            if not protocol_cancellation:
                raise
            return task
        except Exception as exc:
            if not task.is_terminal:
                task.fail(str(exc))
            self._persist_task_snapshot(task)
            raise
        finally:
            _deactivate_task_budget(budget_token)
            if owner:
                self._task_executions.unregister(task.id, execution.execution_task)

    async def run_task_streaming(self, task: Task) -> AsyncIterator[Any]:
        """Stream a task handler under live cancellation control.

        A successfully canceled stream ends with one final ``TaskStatusUpdateEvent`` whose state is ``canceled``. This
        keeps SSE, WebSocket, runtime, and direct consumers aligned on the same lifecycle.
        """
        from protolink.core.events import TaskStatusUpdateEvent

        if task.is_terminal:
            yield TaskStatusUpdateEvent(
                task_id=task.id,
                previous_state=None,
                new_state=self._state_value(task.state),
                final=True,
                metadata={"task": task.to_dict()},
            )
            return

        execution, owner = self._task_executions.register(task)
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        budget_token = _activate_task_budget(task, context)
        try:
            self._raise_if_execution_canceled(task, execution.token)
            async for event in self.handle_task_streaming(task):
                yield event
        except asyncio.CancelledError as exc:
            protocol_cancellation = execution.token.is_cancelled
            mark_task_canceled(task, self._cancellation_reason(exc, execution.token))
            self._persist_task_snapshot(task)
            if not protocol_cancellation:
                raise
            yield self._canceled_status_event(task, execution)
        finally:
            if not task.is_terminal:
                mark_task_canceled(task, "Streaming consumer closed before task completion")
            self._persist_task_snapshot(task)
            _deactivate_task_budget(budget_token)
            if owner:
                self._task_executions.unregister(task.id, execution.execution_task)

    def _canceled_status_event(self, task: Task, execution: ActiveTaskExecution) -> Any:
        """Build the final status event shared by cancellation wrappers."""
        from protolink.core.events import TaskStatusUpdateEvent

        return TaskStatusUpdateEvent(
            task_id=task.id,
            previous_state=execution.previous_state or TaskState.WORKING.value,
            new_state=TaskState.CANCELED.value,
            final=True,
            metadata={
                "task": task.to_dict(),
                "cancel_reason": execution.token.reason,
            },
        )

    async def handle_task(self, task: Task) -> Task:
        """
        Default task handler for ProtoLink agents.

        This method provides the standard execution behavior for an agent.
        Users typically DO NOT need to override this method.

        Default behavior:
        - Interprets the Task's Parts as explicit execution instructions
        - Executes all `tool_call` Parts via registered tools
        - Executes all `infer` Parts via the agent's LLM (if available)
        - Attaches produced outputs (messages and artifacts) back to the Task

        This method is deterministic and non-heuristic:
        - No implicit reasoning is performed
        - The LLM is only invoked when a `infer` Part is present
        - If no executable Parts are found, the Task is returned unchanged

        When to override:
        Override this method ONLY if you need custom orchestration logic, such as:
        - Conditional execution or filtering of Parts
        - Enforcing execution policies or limits
        - Custom routing between tools, LLMs, or sub-agents
        - Short-circuiting execution for specific Task types

        When overriding, users are encouraged to:
        - Call `super().handle_task(task)` when possible
        - Preserve explicit execution semantics (avoid hidden heuristics)
        - Avoid mutating Task state directly; return an updated Task instead

        Args:
            task: The Task to be processed.

        Returns:
            The updated Task after applying all explicitly requested executions.
        """
        self._logger.debug(f"Received task: {task.to_dict()}")
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        if context.canceled:
            mark_task_canceled(task, context.cancel_reason)
            self._persist_task_snapshot(task)
            return task
        if self.telemetry:
            await self._emit_telemetry("on_task_start", task, self.card.name)
            RunContext.ensure_task_context(
                task,
                default_session_id=task.metadata.get("session_id", task.id),
                agent_name=self.card.name,
            )

        result = task
        try:
            result = await self.execute_task(task)
            return result
        finally:
            if self.telemetry:
                await self._emit_telemetry("on_task_end", task, result, self.card.name)

    async def handle_task_streaming(self, task: Task) -> AsyncIterator:
        """Process a task while streaming under live cancellation control."""
        if task.is_terminal:
            async for event in self._handle_task_streaming_impl(task, CancellationToken()):
                yield event
            return

        execution, owner = self._task_executions.register(task)
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        budget_token = _activate_task_budget(task, context)
        try:
            self._raise_if_execution_canceled(task, execution.token)
            if self.telemetry:
                await self._emit_telemetry("on_task_start", task, self.card.name)
            async for event in self._handle_task_streaming_impl(task, execution.token):
                yield event
        except asyncio.CancelledError as exc:
            protocol_cancellation = execution.token.is_cancelled
            mark_task_canceled(task, self._cancellation_reason(exc, execution.token))
            self._persist_task_snapshot(task)
            if not protocol_cancellation:
                raise
            yield self._canceled_status_event(task, execution)
        finally:
            if not task.is_terminal:
                mark_task_canceled(task, "Streaming consumer closed before task completion")
                self._persist_task_snapshot(task)
            if self.telemetry:
                await self._emit_telemetry("on_task_end", task, task, self.card.name)
            _deactivate_task_budget(budget_token)
            if owner:
                self._task_executions.unregister(task.id, execution.execution_task)

    async def _handle_task_streaming_impl(
        self,
        task: Task,
        cancellation_token: CancellationToken,
    ) -> AsyncIterator[Any]:
        """Produce task events using an already registered cancellation token."""
        from protolink.core.events import (
            TaskArtifactUpdateEvent,
            TaskErrorEvent,
            TaskProgressEvent,
            TaskStatusUpdateEvent,
        )

        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        self._raise_if_execution_canceled(task, cancellation_token, context=context)
        previous_state = self._begin_task_if_needed(task)
        if previous_state is None:
            yield TaskStatusUpdateEvent(
                task_id=task.id,
                previous_state=None,
                new_state=self._state_value(task.state),
                final=True,
                metadata={"task": task.to_dict()},
            )
            return

        yield TaskStatusUpdateEvent(
            task_id=task.id,
            previous_state=previous_state,
            new_state=self._state_value(task.state),
        )
        cancellation_token.raise_if_cancelled()

        try:
            last_item = task.get_last_item()
            if last_item is None:
                previous_state = self._state_value(task.state)
                task.update_state(TaskState.COMPLETED)
                self._persist_task_snapshot(task)
                yield TaskStatusUpdateEvent(
                    task_id=task.id,
                    previous_state=previous_state,
                    new_state=self._state_value(task.state),
                    final=True,
                    metadata={"task": task.to_dict()},
                )
                return

            outputs: list[Part | Message] = []

            async with self._llm_history_scope(task, context, outputs=outputs):
                for part in last_item.parts:
                    cancellation_token.raise_if_cancelled()
                    if part.type == "tool_call":
                        tool_name = getattr(part.content, "tool_name", None)
                        if tool_name is None and isinstance(part.content, dict):
                            tool_name = part.content.get("tool_name")
                        yield TaskProgressEvent(
                            task_id=task.id,
                            message=f"Executing tool: {tool_name or 'unknown'}",
                            metadata={"agent": self.card.name, "part_type": part.type},
                        )
                        output = await self.execute_tool(
                            part,
                            task=task,
                            cancellation_token=cancellation_token,
                        )
                        outputs.append(output)
                        self._attach_task_output(task, output)
                        self._persist_task_snapshot(task)
                    elif part.type == "infer":
                        async for event in self.call_llm_stream(
                            part,
                            task=task,
                            cancellation_token=cancellation_token,
                        ):
                            if isinstance(event, dict) and "__protolink_part__" in event:
                                output = Part.from_dict(event["__protolink_part__"])
                                outputs.append(output)
                                self._attach_task_output(task, output)
                                self._persist_task_snapshot(task)
                                continue
                            if isinstance(event, TaskErrorEvent):
                                previous_state = self._state_value(task.state)
                                if not task.is_terminal:
                                    task.fail(event.error_message)
                                yield event
                                self._persist_task_snapshot(task)
                                yield TaskStatusUpdateEvent(
                                    task_id=task.id,
                                    previous_state=previous_state,
                                    new_state=self._state_value(task.state),
                                    final=True,
                                    metadata={"task": task.to_dict()},
                                )
                                return
                            yield event
                    else:
                        self._logger.debug(f"Unknown part type '{part.type}'. Ignoring.")

            previous_state = self._state_value(task.state)
            self._finalize_task_state(task, outputs)
            self._persist_task_snapshot(task)

            for artifact in task.artifacts:
                yield TaskArtifactUpdateEvent(task_id=task.id, artifact=artifact)

            yield TaskStatusUpdateEvent(
                task_id=task.id,
                previous_state=previous_state,
                new_state=self._state_value(task.state),
                final=True,
                metadata={"task": task.to_dict()},
            )
        except Exception as e:
            previous_state = self._state_value(task.state)
            if not task.is_terminal:
                task.fail(str(e))
            self._persist_task_snapshot(task)
            yield TaskErrorEvent(
                task_id=task.id,
                error_code="task_failed",
                error_message=str(e),
                recoverable=False,
            )
            yield TaskStatusUpdateEvent(
                task_id=task.id,
                previous_state=previous_state,
                new_state=self._state_value(task.state),
                final=True,
                metadata={"task": task.to_dict()},
            )

    @staticmethod
    def _state_value(state: TaskState | str) -> str:
        """Return a serialized task state value for events and metadata."""
        return state.value if isinstance(state, TaskState) else str(state)

    def _enforce_budget_decision(self, decision: BudgetDecision) -> None:
        """Apply an explicit runtime-part budget decision."""
        if decision.effect == "warn":
            self._logger.warning(decision.message or "Run budget is approaching a configured limit")
        if not decision.allowed:
            raise BudgetExceededError(decision)

    async def _emit_telemetry(self, hook_name: str, *args: Any, **kwargs: Any) -> Any:
        """Invoke one telemetry hook without making observability authoritative."""
        telemetry = self.telemetry
        if telemetry is None:
            return None
        hook = getattr(telemetry, hook_name, None)
        if not callable(hook):
            return None
        try:
            return await hook(*args, **kwargs)
        except Exception as exc:
            if hook_name not in self._telemetry_error_hooks:
                self._telemetry_error_hooks.add(hook_name)
                self._logger.warning(f"Telemetry hook {hook_name} failed; continuing without it: {exc}")
            return None

    def _record_inference_action_result(self, task: Task | None, event: dict[str, Any]) -> None:
        """Attach one durable receipt for a side effect completed inside inference.

        Model-driven tools and delegations execute inside ``LLM.infer`` rather
        than as top-level task parts. Recording metadata-only completion
        receipts on the task makes partial progress visible if a later model
        call, cancellation, or budget boundary ends inference before a final
        response, without exposing the private result observation.
        """
        if task is None or event.get("type") not in {"tool_result", "agent_call_result"}:
            return

        action_id_value = event.get("action_id")
        action_id = str(action_id_value) if action_id_value else None
        receipt_tracker = _active_inference_action_receipts.get()
        if action_id and any(
            artifact.kind == "action_result" and artifact.action_id == action_id for artifact in task.artifacts
        ):
            if receipt_tracker is not None:
                receipt_tracker.add(action_id)
            return

        if event["type"] == "tool_result":
            name = str(event.get("tool") or "tool")
            action_kind = "tool.call"
            delegated_action = None
        else:
            name = str(event.get("agent") or "agent")
            action_kind = "agent.call"
            delegated_action = event.get("action")

        # Internal observations can contain credentials, private records, or
        # other data intended only for model context. The durable/client-visible
        # task receipt proves completion without copying that raw result across
        # the task boundary.
        receipt: dict[str, Any] = {
            "status": "completed",
            "action_id": action_id,
            "action_kind": action_kind,
            "name": name,
            "result_omitted": True,
        }
        if delegated_action is not None:
            receipt["action"] = delegated_action
        part = Part.json(receipt)

        artifact = Artifact(
            parts=[part],
            kind="action_result",
            name=name,
            action_id=action_id,
            metadata={
                "source": "inference",
                "action_kind": action_kind,
                "step": event.get("step"),
                "result_omitted": True,
            },
        )
        task.add_artifact(artifact)
        if receipt_tracker is not None:
            receipt_tracker.add(action_id or artifact.id)
        # Minimize the crash window between an external side effect and its
        # durable receipt. RunStore persistence is intentionally best effort.
        self._persist_task_snapshot(task)

    def _raise_if_execution_canceled(
        self,
        task: Task,
        cancellation_token: CancellationToken | None = None,
        *,
        context: RunContext | None = None,
    ) -> None:
        """Honor serialized and live cancellation before execution starts."""
        active_context = context or RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        if active_context.canceled:
            if cancellation_token is not None:
                cancellation_token.cancel(active_context.cancel_reason)
            mark_task_canceled(task, active_context.cancel_reason)
            raise asyncio.CancelledError(active_context.cancel_reason or "Task was canceled before execution")
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

    @staticmethod
    def _cancellation_reason(exc: asyncio.CancelledError, cancellation_token: CancellationToken) -> str | None:
        """Return the protocol reason or preserve an external cancel message."""
        if cancellation_token.is_cancelled:
            return cancellation_token.reason
        if exc.args and exc.args[0]:
            return str(exc.args[0])
        return "Execution coroutine was canceled"

    @staticmethod
    def _part_requires_input(part: Part) -> bool:
        """Return whether an output part explicitly asks for more input."""
        if part.type != "status" or not isinstance(part.content, dict):
            return False
        return part.content.get("state") in {"input-required", "input_required"}

    @staticmethod
    def _part_error_message(part: Part) -> str | None:
        """Extract a user-facing error message from an output part, if any."""
        if part.type == "error" and isinstance(part.content, dict):
            return str(part.content.get("message", "unknown error"))

        if part.type == "tool_output":
            try:
                error = part.as_tool_output().error
            except (TypeError, ValueError):
                error = part.content.get("error") if isinstance(part.content, dict) else None
            if error:
                if isinstance(error, dict):
                    return str(error.get("message", error))
                return str(error)

        return None

    def _begin_task_if_needed(self, task: Task) -> str | None:
        """Move a non-terminal task to ``WORKING`` and return its prior state."""
        if task.is_terminal:
            return None
        previous_state = self._state_value(task.state)
        if task.state != TaskState.WORKING:
            task.begin()
        return previous_state

    def _finalize_task_state(self, task: Task, outputs: list[Part | Message]) -> None:
        """Set the terminal or waiting state implied by agent outputs.

        Errors win over all other outputs, an explicit status part can request more input, and otherwise successful
        execution completes the task.
        """
        if task.is_terminal:
            return

        for output in outputs:
            if isinstance(output, Part):
                error_message = self._part_error_message(output)
                if error_message:
                    task.fail(error_message)
                    return

        if any(isinstance(output, Part) and self._part_requires_input(output) for output in outputs):
            task.require_input()
            return

        task.update_state(TaskState.COMPLETED)

    @staticmethod
    def _attach_task_output(task: Task, output: Part | Message) -> None:
        """Attach a completed output immediately so later failures cannot erase it."""
        if any(output is existing_part for item in (*task.messages, *task.artifacts) for existing_part in item.parts):
            return
        if isinstance(output, Message):
            task.add_message(output)
        else:
            task.add_artifact(Artifact(parts=[output]))

    async def execute_task(self, task: Task) -> Task:
        """
        Execute the next step of a Task by inspecting the most recently appended Message or Artifact and performing the
        explicitly requested action.

        Execution model:
        - The agent processes ONE step at a time
        - Only the most recent Message or Artifact is inspected
        - No historical scanning or inference is performed

        Supported semantics:
        - `tool_call` Parts are executed via registered tools
        - `infer` Parts trigger model inference via the agent's LLM (if available)

        Task lifecycle:
        - A non-terminal task is moved to ``WORKING`` before execution
        - Successful outputs move the task to ``COMPLETED``
        - Error outputs or raised exceptions move the task to ``FAILED``
        - Status outputs requesting input move the task to ``INPUT_REQUIRED``

        Determinism guarantees:
        - No intent inference
        - No fallback behavior
        - No automatic execution unless explicitly declared
        - If nothing executable is found, this method is a no-op

        Args:
            task: The Task to execute.

        Returns:
            The same Task instance, augmented with new Messages or Artifacts.
        """

        if task.is_terminal:
            return task

        execution, owner = self._task_executions.register(task)
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        budget_token = _activate_task_budget(task, context)
        try:
            self._raise_if_execution_canceled(task, execution.token)
            result = await self._execute_task_impl(task, execution.token)
            self._persist_task_snapshot(result)
            return result
        except asyncio.CancelledError as exc:
            protocol_cancellation = execution.token.is_cancelled
            mark_task_canceled(task, self._cancellation_reason(exc, execution.token))
            self._persist_task_snapshot(task)
            if not protocol_cancellation:
                raise
            return task
        except Exception:
            self._persist_task_snapshot(task)
            raise
        finally:
            _deactivate_task_budget(budget_token)
            if owner:
                self._task_executions.unregister(task.id, execution.execution_task)

    async def _execute_task_impl(self, task: Task, cancellation_token: CancellationToken) -> Task:
        """Execute one task step using an already registered cancellation token."""
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        self._raise_if_execution_canceled(task, cancellation_token, context=context)
        self._begin_task_if_needed(task)

        try:
            last_item = task.get_last_item()
            if last_item is None:
                task.update_state(TaskState.COMPLETED)
                return task

            outputs: list[Part | Message] = []

            async with self._llm_history_scope(task, context, outputs=outputs):
                # ---- Inspect Parts in the last item only ----
                for part in last_item.parts:
                    cancellation_token.raise_if_cancelled()
                    output: Part | Message | None = None
                    if part.type == "tool_call":
                        output = await self.execute_tool(
                            part,
                            task=task,
                            cancellation_token=cancellation_token,
                        )
                    elif part.type == "infer":
                        output = await self.call_llm(
                            part,
                            task=task,
                            cancellation_token=cancellation_token,
                        )
                    elif part.type == "text" and task.metadata.get("a2a_inbound") is True and self.llm is not None:
                        # Keep the canonical A2A text -> ProtoLink text mapping
                        # visible to custom handlers. Only the default engine
                        # treats authenticated adapter input as an inference
                        # instruction; ordinary local text remains inert.
                        output = await self.call_llm(
                            Part.infer(prompt=str(part.content)),
                            task=task,
                            cancellation_token=cancellation_token,
                        )
                    else:
                        self._logger.debug(f"Unknown part type '{part.type}'. Ignoring.")

                    if output is not None:
                        outputs.append(output)
                        self._attach_task_output(task, output)
                        # Persist each completed boundary. If a later part
                        # fails, callers still see which operations succeeded.
                        self._persist_task_snapshot(task)

            self._finalize_task_state(task, outputs)
        except Exception as exc:
            if not task.is_terminal:
                task.fail(str(exc))
            raise

        return task

    @asynccontextmanager
    async def _llm_history_scope(
        self,
        task: Task,
        context: RunContext,
        *,
        outputs: list[Part | Message] | None = None,
    ):
        """Bind task-local LLM history and serialize same-session updates.

        Stateless runs receive a fresh isolated history object. Persistent conversation runs load the requested session
        under a per-session lock, execute against a task-local history, then save that same history back after
        successful execution. The lock prevents concurrent tasks for the same session from overwriting each other's
        conversation turns.
        """
        if self.llm is None:
            yield
            return

        receipt_tracker: set[str] = set()
        receipt_token = _active_inference_action_receipts.set(receipt_tracker)

        def completed_without_failure(*, completed_normally: bool) -> bool:
            output_failed = any(
                isinstance(output, Part) and self._part_error_message(output) for output in outputs or ()
            )
            return completed_normally and not output_failed and task.state not in {TaskState.FAILED, TaskState.CANCELED}

        def should_commit_history(*, completed_normally: bool) -> bool:
            if receipt_tracker:
                return True
            return completed_without_failure(completed_normally=completed_normally)

        try:
            session_id = context.session_id or task.id
            if self._state.conversation:
                lock = self._session_locks.setdefault(session_id, asyncio.Lock())
                async with lock:
                    history = self._state.conversation.get_history(
                        session_id,
                        default_system_prompt=self.llm.system_prompt,
                    )
                    completed_history: ConversationHistory | None = None
                    completed_normally = False
                    try:
                        with self.llm.use_history(history):
                            try:
                                yield
                                completed_normally = True
                            finally:
                                completed_history = self.llm.history.copy()
                    finally:
                        # Normally failed turns remain isolated. A runtime-owned
                        # receipt is the authoritative signal that an external
                        # side effect completed and its observation must survive.
                        if completed_history is not None and should_commit_history(
                            completed_normally=completed_normally
                        ):
                            try:
                                self._state.conversation.save_history(session_id, completed_history)
                                self.llm.history = completed_history.copy()
                            except Exception as exc:
                                if completed_without_failure(completed_normally=completed_normally):
                                    raise
                                # An execution/cancellation exception is already
                                # active. Preserve its semantics instead of
                                # replacing it with secondary persistence loss.
                                self._logger.warning(
                                    "Could not persist completed-action history "
                                    f"for session '{session_id}'; preserving the original execution error: {exc}"
                                )
                return

            history = ConversationHistory()
            completed_history = None
            completed_normally = False
            try:
                with self.llm.use_history(history):
                    try:
                        yield
                        completed_normally = True
                    finally:
                        completed_history = self.llm.history.copy()
            finally:
                if completed_history is not None and should_commit_history(completed_normally=completed_normally):
                    self.llm.history = completed_history.copy()
        finally:
            _active_inference_action_receipts.reset(receipt_token)

    def _persist_task_snapshot(self, task: Task) -> None:
        """Persist a task snapshot when this agent has a run store."""
        run_store = getattr(self, "run_store", None)
        if run_store is None:
            return
        try:
            run_store.save_task(
                task,
                context=RunContext.from_task(task),
                agent_name=self.card.name,
            )
        except Exception as exc:
            self._logger.debug(f"Failed to persist task snapshot {task.id}: {exc}")

    async def execute_tool(
        self,
        part: Part,
        *,
        task: Task | None = None,
        cancellation_token: CancellationToken | None = None,
        budget_enforcer: BudgetEnforcer | None = None,
    ) -> Part:
        """
        Execute a single tool call described by a `tool_call` Part.

        This method:
        - Resolves the tool from the agent's tool registry
        - Executes it with the provided arguments
        - Captures success or failure
        - Returns a corresponding `tool_output` Part

        The agent runtime is responsible for calling this method.
        The protocol / lifecycle layers never execute tools directly.

        Args:
            part: A Part of type "tool_call" containing:
                - tool_name (str)
                - args (dict)
                - call_id (str)
            task: Optional active task supplying the propagated ``RunContext``.
            cancellation_token: Optional live token checked before authorization
                and dispatch. A result that has already completed is returned
                rather than discarded by a late cancellation request.
            budget_enforcer: Optional task-scoped enforcer shared with other infer and tool parts in the same task.

        Returns:
            A Part of type "tool_output" containing:
            - call_id: The original tool call identifier
            - result: The tool output (on success)
            - error: Error information (on failure)
        """

        active_token = cancellation_token
        if active_token is None and task is not None:
            active_token = self.get_cancellation_token(task.id)
        context = (
            RunContext.ensure_task_context(task, agent_name=self.card.name)
            if task is not None
            else RunContext(agent_chain=[self.card.name])
        )
        if task is not None:
            self._raise_if_execution_canceled(task, active_token, context=context)
        elif active_token is not None:
            active_token.raise_if_cancelled()

        active_budget_enforcer = budget_enforcer or _current_task_budget(task) or BudgetEnforcer(context)
        self._enforce_budget_decision(active_budget_enforcer.check_next_step())

        tc = part.as_tool_call()
        tool_name, args, call_id = tc.tool_name, tc.args, tc.call_id
        self._logger.debug(f"Executing tool: {tool_name}")
        tool = self.tools.get(tool_name)
        if not tool:
            return Part.tool_output(
                call_id=call_id,
                error={"message": f"Tool '{tool_name}' not found"},
            )

        if self.telemetry:
            await self._emit_telemetry("on_tool_start", tool_name, args)

        try:
            _, call_args = await self._authorize_tool_action(tool, args, context)
            if active_token is not None:
                active_token.raise_if_cancelled()
            self._enforce_budget_decision(active_budget_enforcer.evaluate())
            self._enforce_budget_decision(active_budget_enforcer.check_tool_call())
            result = await tool(**call_args)
            post_action_decision = active_budget_enforcer.evaluate()
            if not post_action_decision.allowed:
                # Runtime is a dispatch boundary, not a retroactive verdict on
                # an operation that may already have committed a side effect.
                # Preserve the result and stop any subsequent part at its
                # normal preflight check.
                self._logger.warning(
                    f"Tool '{tool_name}' completed after a run-budget boundary: {post_action_decision.message}"
                )
                if task is not None:
                    overruns = task.metadata.setdefault("completed_action_budget_overruns", [])
                    if isinstance(overruns, list):
                        overruns.append(
                            {
                                "action_kind": "tool.call",
                                "action_name": tool_name,
                                "call_id": call_id,
                                "decision": post_action_decision.to_dict(),
                            }
                        )
            elif post_action_decision.effect == "warn":
                self._logger.warning(post_action_decision.message or "Run budget is near a configured limit")

            if active_token is not None and active_token.is_cancelled and task is not None:
                task.metadata.setdefault(
                    "completed_after_cancellation",
                    {
                        "action_kind": "tool.call",
                        "action_name": tool_name,
                        "call_id": call_id,
                        "reason": active_token.reason,
                    },
                )
            output = Part.tool_output(call_id=call_id, result=result)
            if task is not None:
                # The tool may already have committed an external side effect.
                # Attach and snapshot its result before any nonessential
                # post-action await (for example a slow telemetry exporter).
                self._attach_task_output(task, output)
                self._persist_task_snapshot(task)
            try:
                if self.telemetry:
                    await self._emit_telemetry("on_tool_end", tool_name, result)
            except asyncio.CancelledError as exc:
                if task is not None:
                    reason = (
                        active_token.reason
                        if active_token is not None and active_token.is_cancelled
                        else str(exc.args[0])
                        if exc.args and exc.args[0]
                        else "Execution canceled after tool completion"
                    )
                    task.metadata.setdefault(
                        "completed_after_cancellation",
                        {
                            "action_kind": "tool.call",
                            "action_name": tool_name,
                            "call_id": call_id,
                            "reason": reason,
                        },
                    )
                    self._persist_task_snapshot(task)
                raise
            return output
        except ActionPolicyError as e:
            if self.telemetry:
                await self._emit_telemetry("on_tool_end", tool_name, None, error=str(e))
            raise
        except BudgetExceededError as e:
            if self.telemetry:
                await self._emit_telemetry("on_tool_end", tool_name, None, error=str(e))
            raise
        except Exception as e:
            if self.telemetry:
                await self._emit_telemetry("on_tool_end", tool_name, None, error=str(e))
            return Part.tool_output(
                call_id=call_id,
                error={"message": str(e)},
            )

    async def call_llm(
        self,
        infer_part: Part,
        task: Task | None = None,
        *,
        streaming: bool = False,
        event_callback=None,
        cancellation_token: CancellationToken | None = None,
        budget_enforcer: BudgetEnforcer | None = None,
    ) -> Part:
        """
        Invoke the agent's LLM to process an inference request.

        This method orchestrates a complete LLM inference cycle by:
        1. Discovering available agents from the registry
        2. Building a system prompt with tools, agent cards, and user instructions (Semantic Context Injection)
        3. Invoking the LLM's inference loop with tool and agent delegation support

        The LLM may respond with:
        - A final text response (returned as ``infer_output`` Part)
        - Tool calls (handled internally via ``_inject_tool_call``)
        - Agent delegation (handled via ``_handle_agent_call`` callback)

        Args:
            infer_part: A Part of type ``infer`` containing:
                - prompt (str): The user query or instruction to process
            task: Optional Task object to retrieve topological/flow context.
            streaming: Whether to call the underlying LLM with its streaming interface and collect streamed chunks
                before action parsing.
            event_callback: Optional async callback receiving provider-agnostic inference events while the LLM loop
                runs. Used by ``call_llm_stream()`` and task streaming transports.
            cancellation_token: Optional live token checked throughout the inference loop and before side-effect
                dispatch.
            budget_enforcer: Optional task-scoped enforcer shared with other infer and tool parts in the same task.

        Returns:
            Part: A Part of type ``infer_output`` containing the LLM's final response,
                or an ``error`` Part if no LLM is configured.

        Notes:
            The inference loop continues until the LLM produces a ``final`` action. Tool calls and agent delegations are
            executed automatically and their results are injected back into the conversation for the LLM to process.
        """

        active_token = cancellation_token
        if active_token is None and task is not None:
            active_token = self.get_cancellation_token(task.id)
        active_context = (
            RunContext.ensure_task_context(task, agent_name=self.card.name)
            if task is not None
            else RunContext(agent_chain=[self.card.name])
        )
        if task is not None:
            self._raise_if_execution_canceled(task, active_token, context=active_context)
        elif active_token is not None:
            active_token.raise_if_cancelled()

        if not self.llm:
            return Part.error(
                code="no_llm",
                message="Agent has no LLM but received a infer instruction",
            )

        # Discovery is an optional prompt affordance. An unavailable registry
        # must not take down otherwise-local inference.
        discovered = []
        if self.card.capabilities.delegation:
            try:
                discovered = await self.discover_agents()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.warning(f"Agent discovery failed; continuing inference without delegation targets: {exc}")
                discovered = []

            ancestor_names = {name.strip().casefold() for name in active_context.agent_chain}
            discovered = [
                agent
                for agent in discovered
                if agent.url != self.card.url and agent.name.strip().casefold() not in ancestor_names
            ]
            agent_cards_list = [
                f"Agent {i}:\n{agent.get_prompt_format()}" for i, agent in enumerate(discovered, start=1)
            ]
            agent_cards = "\n".join(agent_cards_list)
        else:
            agent_cards = ""

        # Extract flow instructions injected by orchestrators
        flow_instructions = task.flow_state.get("prompt", "") if task and task.flow_state else ""

        # Build the System Prompt
        # Streaming uses JSON action text unless the provider can stream native
        # tool-call events and normalize them through call_action_stream().
        action_mode = "native" if streaming and self.llm.supports_native_action_stream else None
        if streaming and action_mode is None:
            action_mode = "json"
        _ = self.llm.build_system_prompt(
            user_instructions=self._system_prompt,
            agent_cards=agent_cards,
            tools=self._build_tools_prompt(),
            action_mode=action_mode,
            flow_instructions=flow_instructions,
            override_system_prompt=self.override_system_prompt,
            persist=self._state.conversation is not None,
            agent_name=self.card.name,
        )

        query = (
            infer_part.content.get("prompt", "")
            if isinstance(infer_part.content, dict)
            else getattr(infer_part.content, "prompt", "")
        )

        model_name = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", None)
        if self.telemetry:
            await self._emit_telemetry(
                "on_llm_start",
                query,
                model_name,
                {
                    "agent_name": self.card.name,
                    "task_id": task.id if task else None,
                    "trace_id": task.metadata.get("trace_id") if task else None,
                    "provider": getattr(self.llm, "provider", None),
                    "model_type": getattr(self.llm, "model_type", None),
                },
            )

        external_observer_disabled = False

        async def emit_inference_event(event: dict[str, Any]) -> None:
            nonlocal external_observer_disabled
            self._record_inference_action_result(task, event)
            if self.telemetry:
                await self._emit_telemetry("on_llm_event", event)
            if event_callback and not external_observer_disabled:
                try:
                    await event_callback(event)
                except Exception as exc:
                    external_observer_disabled = True
                    self._logger.warning(
                        f"Inference event observer failed; continuing with runtime receipts enabled: {exc}"
                    )

        async def authorize_inference_action(action: RunAction) -> ActionAuthorization:
            """Prepare tool actions and enforce this agent's runtime policy."""
            if action.kind == "tool.call":
                tool = self.tools.get(action.name)
                if tool is None:
                    raise ValueError(f"Tool {action.name} not found")
                arguments = action.payload.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise TypeError("Tool action payload.arguments must be a dictionary")
                authorization, _ = await self._authorize_tool_action(tool, arguments, active_context)
                return authorization
            return await self.authorize_action(action, active_context)

        async def handle_inference_agent_call(
            agent_name: str,
            action: str,
            payload: dict[str, Any],
        ) -> Any:
            """Delegate work with child context and cancellation propagation."""
            return await self._handle_agent_call(
                agent_name,
                action,
                payload,
                parent_context=active_context,
            )

        infer_kwargs: dict[str, Any] = {
            "query": query,
            "tools": self.tools,
            "agent_callback": handle_inference_agent_call if discovered else None,
            "agent_cards": discovered or None,
            "streaming": streaming,
            "event_callback": (emit_inference_event if task is not None or self.telemetry or event_callback else None),
            "action_authorizer": authorize_inference_action,
            "cancellation_token": active_token,
            "run_context": active_context,
        }
        if _accepts_keyword_argument(self.llm.infer, "event_metrics"):
            infer_kwargs["event_metrics"] = bool(self.telemetry or event_callback)
        active_budget_enforcer = budget_enforcer or _current_task_budget(task)
        # ``LLM.infer`` is a documented extension point. Existing adapters may
        # override its pre-0.6.7 signature, so only pass the new shared-budget
        # argument when the override explicitly accepts it (or ``**kwargs``).
        if active_budget_enforcer is not None and _accepts_keyword_argument(
            self.llm.infer,
            "budget_enforcer",
        ):
            infer_kwargs["budget_enforcer"] = active_budget_enforcer

        response: Part = await self.llm.infer(**infer_kwargs)

        if self.telemetry:
            await self._emit_telemetry("on_llm_end", response)

        return response

    async def call_llm_stream(
        self,
        infer_part: Part,
        task: Task | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
        budget_enforcer: BudgetEnforcer | None = None,
    ) -> AsyncIterator[Any]:
        """Invoke the agent LLM in streaming mode and yield task events.

        The returned iterator yields ``TaskLLMStreamEvent`` objects for provider activity such as chunks, tool calls,
        delegated agent calls, and final inference content. A private final payload is used internally by
        ``handle_task_streaming()`` to attach the completed ``Part`` to the task before the final status event is
        emitted.
        """
        from protolink.core.events import TaskErrorEvent, TaskLLMStreamEvent

        queue: asyncio.Queue[Any] = asyncio.Queue()
        sentinel = object()
        task_id = task.id if task else ""

        async def emit(payload: dict[str, Any]) -> None:
            metadata = {key: value for key, value in payload.items() if key not in {"type", "step", "content", "final"}}
            if payload.get("type") in {"tool_result", "agent_call_result"}:
                # Internal observations may contain credentials or private
                # records intended only for LLM history and privileged
                # telemetry. Client streams receive correlation, not content.
                metadata.pop("result", None)
                metadata["result_omitted"] = True
            await queue.put(
                TaskLLMStreamEvent(
                    task_id=task_id,
                    agent_name=self.card.name,
                    llm_event_type=str(payload.get("type", "")),
                    step=payload.get("step"),
                    content=payload.get("content"),
                    final=bool(payload.get("final", False)),
                    metadata=metadata,
                )
            )

        async def run_inference() -> None:
            explicit_budget_token = (
                _active_task_budget.set((task.id if task is not None else "", budget_enforcer))
                if budget_enforcer is not None
                else None
            )
            try:
                part = await self.call_llm(
                    infer_part,
                    task=task,
                    streaming=True,
                    event_callback=emit,
                    cancellation_token=cancellation_token,
                )
                await queue.put({"__protolink_part__": part.to_dict()})
            except asyncio.CancelledError as exc:
                await queue.put(exc)
            except Exception as exc:
                await queue.put(
                    TaskErrorEvent(
                        task_id=task_id,
                        error_code="llm_stream_failed",
                        error_message=str(exc),
                        recoverable=False,
                    )
                )
            finally:
                if explicit_budget_token is not None:
                    _active_task_budget.reset(explicit_budget_token)
                await queue.put(sentinel)

        runner = asyncio.create_task(run_inference())
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                if isinstance(item, asyncio.CancelledError):
                    raise item
                yield item
        finally:
            if not runner.done():
                runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass

    async def _handle_agent_call(
        self,
        agent_name: str,
        action: str,
        payload: dict[str, Any],
        *,
        parent_context: RunContext | None = None,
    ) -> Any:
        """
        Handle agent delegation from the LLM inference loop.

        This callback is invoked when the LLM produces an agent_call action. It translates the LLM's delegation request
        into a Task and sends it to the target agent using the transport layer.

        Args:
            agent_name: Registry-advertised name of the agent to delegate to.
                Model-originated direct URLs are rejected.
            action: The action type - either "tool_call" (execute a tool on the remote agent) or "infer" (ask the
                remote agent to generate a response).
            payload: The full agent_call payload from the LLM, containing tool/args or prompt.
            parent_context: Optional active context used to create a correlated child run for delegated work.

        Returns:
            The result from the delegated agent (typically the last part content from the response task).

        Raises:
            ValueError: If the target is a direct URL, would create a delegation cycle, or the action type is unknown.
            RuntimeError: If the delegation fails (propagated from call_agent).
        """
        if "://" in agent_name:
            raise ValueError(
                "Direct URL delegation is not allowed for model-originated agent calls; "
                "use the name of an agent advertised by the registry."
            )

        if parent_context is not None:
            target_name = agent_name.strip().casefold()
            ancestor_names = {name.strip().casefold() for name in parent_context.agent_chain}
            if target_name in ancestor_names:
                chain = " -> ".join(parent_context.agent_chain)
                raise ValueError(
                    f"Delegation cycle detected: agent '{agent_name}' already appears in the ancestor chain ({chain})."
                )

        # Resolve the registry-advertised agent name to its transport URL.
        agent_url = await self._resolve_agent_url(agent_name)

        # Guardrail Check for self-delegation
        if agent_url == self.card.url:
            self._logger.debug("Self-delegation detected.")
            raise ValueError(
                f"Self-delegation is not allowed. You are '{self.card.name}' ({self.card.url}) and cannot delegate tasks to yourself."  # noqa: E501
            )

        async def call_delegated_task(task: Task) -> Any:
            request_item_ids = frozenset(item.id for item in (*task.messages, *task.artifacts))
            if parent_context is not None:
                parent_context.child(agent_name=agent_name).attach_to_task(task)
            try:
                result_task = await self.call_agent(agent_url, task)
            except asyncio.CancelledError:
                self._schedule_delegated_cancellation(
                    agent_url,
                    task.id,
                    "Parent task was canceled",
                )
                raise
            return self._require_completed_delegation(
                result_task,
                agent_name,
                request_item_ids=request_item_ids,
            )

        if action == "tool_call":
            tool_name = payload.get("tool")
            args = payload.get("args", {})
            if not tool_name:
                raise ValueError(f"tool_call agent_call must specify 'tool' field. Received payload: {payload}")
            # Create task with tool_call part for the remote agent to execute
            task = Task.create(Message(role="agent", parts=[Part.tool_call(tool_name=tool_name, args=args)]))
            return await call_delegated_task(task)

        elif action == "infer":
            prompt = payload.get("prompt", "")
            # Create task with infer message for the remote agent to process
            task = Task.create(Message.infer(prompt=prompt))
            return await call_delegated_task(task)

        raise ValueError(f"Unknown agent_call action: {action}")

    @staticmethod
    def _require_completed_delegation(
        result_task: Task,
        agent_name: str,
        *,
        request_item_ids: frozenset[str],
    ) -> Any:
        """Return a delegated result only when the remote task truly completed."""
        state = result_task.state
        if not isinstance(state, TaskState):
            try:
                state = TaskState(str(state))
            except ValueError as exc:
                raise RuntimeError(f"Delegated agent '{agent_name}' returned an unknown task state: {state}") from exc

        if state is TaskState.INPUT_REQUIRED:
            raise ValueError(
                f"Delegated agent '{agent_name}' requires additional input before it can complete the task"
            )
        if state is TaskState.FAILED:
            reason = result_task.metadata.get("error") or "remote task failed without an error message"
            raise RuntimeError(f"Delegated agent '{agent_name}' failed: {reason}")
        if state is TaskState.CANCELED:
            reason = result_task.metadata.get("cancel_reason") or "remote task was canceled"
            raise RuntimeError(f"Delegated agent '{agent_name}' was canceled: {reason}")
        if state is not TaskState.COMPLETED:
            raise RuntimeError(f"Delegated agent '{agent_name}' returned non-terminal task state '{state.value}'")

        # Some transports return the full task while others return a response-
        # only task. Item identity distinguishes either valid shape from an
        # unchanged request that was merely marked completed.
        last_item = result_task.get_last_item()
        if last_item is None or last_item.id in request_item_ids:
            raise RuntimeError(f"Delegated agent '{agent_name}' completed without returning an output")
        result = last_item.parts[-1].content if last_item.parts else None
        if result is None:
            raise RuntimeError(f"Delegated agent '{agent_name}' completed with an empty output")
        return result

    def _schedule_delegated_cancellation(self, agent_url: str, task_id: str, reason: str) -> None:
        """Schedule best-effort cancellation of a delegated child task."""
        client = self._client
        if client is None:
            return

        async def cancel_child() -> None:
            try:
                await client.cancel_task(agent_url, task_id, reason=reason)
            except Exception as exc:
                self._logger.debug(f"Could not cancel delegated task '{task_id}': {exc}")

        control_task = asyncio.create_task(cancel_child())
        self._control_tasks.add(control_task)
        control_task.add_done_callback(self._control_tasks.discard)

    async def _resolve_agent_url(self, agent_name: str) -> str:
        """
        Resolve an agent name to its URL by looking up the registry.

        Args:
            agent_name: The agent name to resolve (can also be a URL).

        Returns:
            The agent's URL.

        Raises:
            ValueError: If the agent is not found in the registry.
        """
        # If it already looks like a URL, return as-is
        if (
            agent_name.startswith("http://")
            or agent_name.startswith("https://")
            or agent_name.startswith("ws://")
            or agent_name.startswith("wss://")
        ):
            return agent_name

        # Look up in registry using filtered discovery (O(1) with optimized Registry)
        discovered = await self.discover_agents(filter_by={"name": agent_name})
        if discovered:
            return discovered[0].url

        raise ValueError(f"Agent '{agent_name}' not found in registry.")
