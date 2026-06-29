"""Core task execution engine for :class:`protolink.agents.Agent`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from protolink.core.actions import RunAction
from protolink.core.cancellation import ActiveTaskExecution, CancellationToken, mark_task_canceled
from protolink.core.policy import ActionAuthorization, ActionPolicyError
from protolink.core.run_context import RunContext
from protolink.core.task import TaskState
from protolink.llms.history import ConversationHistory
from protolink.models import Artifact, Message, Part, Task

from ._typing import _AgentMixinBase


class AgentExecutionMixin(_AgentMixinBase):
    """Implements task execution, streaming, LLM calls, and delegation."""

    async def run_task(self, task: Task) -> Task:
        """Run the configured task handler under live cancellation control.

        ``AgentServer`` uses this wrapper rather than calling ``handle_task``
        directly, so subclasses that override the handler still participate in
        active-task registration and protocol cancellation. Direct callers of a
        custom handler can use this method for the same guarantee.
        """
        if task.is_terminal:
            return task

        execution, owner = self._task_executions.register(task)
        try:
            execution.token.raise_if_cancelled()
            result = await self.handle_task(task)
            self._persist_task_snapshot(result)
            return result
        except asyncio.CancelledError:
            mark_task_canceled(task, execution.token.reason)
            self._persist_task_snapshot(task)
            return task
        finally:
            if owner:
                self._task_executions.unregister(task.id, execution.execution_task)

    async def run_task_streaming(self, task: Task) -> AsyncIterator[Any]:
        """Stream a task handler under live cancellation control.

        A successfully canceled stream ends with one final
        ``TaskStatusUpdateEvent`` whose state is ``canceled``. This keeps SSE,
        WebSocket, runtime, and direct consumers aligned on the same lifecycle.
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
        try:
            execution.token.raise_if_cancelled()
            async for event in self.handle_task_streaming(task):
                yield event
        except asyncio.CancelledError:
            mark_task_canceled(task, execution.token.reason)
            yield self._canceled_status_event(task, execution)
        finally:
            self._persist_task_snapshot(task)
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
        Default task handler for A2A-compatible agents.

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
        RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        if self.telemetry:
            await self.telemetry.on_task_start(task, self.card.name)
            RunContext.ensure_task_context(
                task,
                default_session_id=task.metadata.get("session_id", task.id),
                agent_name=self.card.name,
            )

        try:
            result = await self.execute_task(task)
            if self.telemetry:
                await self.telemetry.on_task_end(task, result, self.card.name)
            return result
        except Exception:
            if self.telemetry:
                await self.telemetry.on_task_end(task, task, self.card.name)
            raise

    async def handle_task_streaming(self, task: Task) -> AsyncIterator:
        """Process a task while streaming under live cancellation control."""
        if task.is_terminal:
            async for event in self._handle_task_streaming_impl(task, CancellationToken()):
                yield event
            return

        execution, owner = self._task_executions.register(task)
        try:
            execution.token.raise_if_cancelled()
            async for event in self._handle_task_streaming_impl(task, execution.token):
                yield event
        except asyncio.CancelledError:
            mark_task_canceled(task, execution.token.reason)
            yield self._canceled_status_event(task, execution)
        finally:
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

            async with self._llm_history_scope(task, context):
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
                        outputs.append(
                            await self.execute_tool(
                                part,
                                task=task,
                                cancellation_token=cancellation_token,
                            )
                        )
                    elif part.type == "infer":
                        async for event in self.call_llm_stream(
                            part,
                            task=task,
                            cancellation_token=cancellation_token,
                        ):
                            if isinstance(event, dict) and "__protolink_part__" in event:
                                outputs.append(Part.from_dict(event["__protolink_part__"]))
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

                cancellation_token.raise_if_cancelled()
                for out in outputs:
                    if isinstance(out, Message):
                        task.add_message(out)
                    else:
                        task.add_artifact(Artifact(parts=[out]))

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

        Errors win over all other outputs, an explicit status part can request
        more input, and otherwise successful execution completes the task.
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

    async def execute_task(self, task: Task) -> Task:
        """
        Execute the next step of a Task by inspecting the most recently
        appended Message or Artifact and performing the explicitly
        requested action.

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
        try:
            execution.token.raise_if_cancelled()
            result = await self._execute_task_impl(task, execution.token)
            self._persist_task_snapshot(result)
            return result
        except asyncio.CancelledError:
            mark_task_canceled(task, execution.token.reason)
            self._persist_task_snapshot(task)
            return task
        finally:
            if owner:
                self._task_executions.unregister(task.id, execution.execution_task)

    async def _execute_task_impl(self, task: Task, cancellation_token: CancellationToken) -> Task:
        """Execute one task step using an already registered cancellation token."""
        context = RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        self._begin_task_if_needed(task)

        try:
            last_item = task.get_last_item()
            if last_item is None:
                task.update_state(TaskState.COMPLETED)
                return task

            outputs: list[Part | Message] = []

            async with self._llm_history_scope(task, context):
                # ---- Inspect Parts in the last item only ----
                for part in last_item.parts:
                    cancellation_token.raise_if_cancelled()
                    if part.type == "tool_call":
                        outputs.append(
                            await self.execute_tool(
                                part,
                                task=task,
                                cancellation_token=cancellation_token,
                            )
                        )
                    elif part.type == "infer":
                        outputs.append(
                            await self.call_llm(
                                part,
                                task=task,
                                cancellation_token=cancellation_token,
                            )
                        )
                    else:
                        self._logger.debug(f"Unknown part type '{part.type}'. Ignoring.")
                cancellation_token.raise_if_cancelled()
                # ---- Attach outputs to the Task ----
                for out in outputs:
                    if isinstance(out, Message):
                        task.add_message(out)
                    else:
                        task.add_artifact(Artifact(parts=[out]))

            self._finalize_task_state(task, outputs)
        except Exception as exc:
            if not task.is_terminal:
                task.fail(str(exc))
            raise

        return task

    @asynccontextmanager
    async def _llm_history_scope(self, task: Task, context: RunContext):
        """Bind task-local LLM history and serialize same-session updates.

        Stateless runs receive a fresh isolated history object. Persistent
        conversation runs load the requested session under a per-session lock,
        execute against a task-local history, then save that same history back
        after successful execution. The lock prevents concurrent tasks for the
        same session from overwriting each other's conversation turns.
        """
        if self.llm is None:
            yield
            return

        session_id = context.session_id or task.id
        if self._state.conversation:
            lock = self._session_locks.setdefault(session_id, asyncio.Lock())
            async with lock:
                history = self._state.conversation.get_history(
                    session_id,
                    default_system_prompt=self.llm.system_prompt,
                )
                with self.llm.use_history(history):
                    yield
                    completed_history = self.llm.history
                self._state.conversation.save_history(session_id, completed_history)
                self.llm.history = completed_history.copy()
            return

        with self.llm.use_history(ConversationHistory()) as history:
            yield
        self.llm.history = history.copy()

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
            cancellation_token: Optional live token for cooperative checks
                before authorization and after the tool returns.

        Returns:
            A Part of type "tool_output" containing:
            - call_id: The original tool call identifier
            - result: The tool output (on success)
            - error: Error information (on failure)
        """

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
            await self.telemetry.on_tool_start(tool_name, args)

        try:
            active_token = cancellation_token
            if active_token is None and task is not None:
                active_token = self.get_cancellation_token(task.id)
            if active_token is not None:
                active_token.raise_if_cancelled()

            context = (
                RunContext.ensure_task_context(task, agent_name=self.card.name)
                if task is not None
                else RunContext(agent_chain=[self.card.name])
            )
            _, call_args = await self._authorize_tool_action(tool, args, context)
            if active_token is not None:
                active_token.raise_if_cancelled()
            result = await tool(**call_args)
            if active_token is not None:
                active_token.raise_if_cancelled()
            if self.telemetry:
                await self.telemetry.on_tool_end(tool_name, result)
            return Part.tool_output(call_id=call_id, result=result)
        except ActionPolicyError as e:
            if self.telemetry:
                await self.telemetry.on_tool_end(tool_name, None, error=str(e))
            raise
        except Exception as e:
            if self.telemetry:
                await self.telemetry.on_tool_end(tool_name, None, error=str(e))
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
            streaming: Whether to call the underlying LLM with its streaming
                interface and collect streamed chunks before action parsing.
            event_callback: Optional async callback receiving provider-agnostic
                inference events while the LLM loop runs. Used by
                ``call_llm_stream()`` and task streaming transports.
            cancellation_token: Optional live token checked throughout the
                inference loop and before side-effect dispatch.

        Returns:
            Part: A Part of type ``infer_output`` containing the LLM's final response,
                or an ``error`` Part if no LLM is configured.

        Notes:
            The inference loop continues until the LLM produces a ``final`` action.
            Tool calls and agent delegations are executed automatically and their
            results are injected back into the conversation for the LLM to process.
        """

        if not self.llm:
            return Part.error(
                code="no_llm",
                message="Agent has no LLM but received a infer instruction",
            )

        active_token = cancellation_token
        if active_token is None and task is not None:
            active_token = self.get_cancellation_token(task.id)
        if active_token is not None:
            active_token.raise_if_cancelled()

        # Get Available Agents (Guardrail: excluding ourselves to prevent self-delegation loops)
        discovered = []
        if self.card.capabilities.delegation:  # If the agent supports delegation
            discovered = await self.discover_agents()
            discovered = [agent for agent in discovered if agent.url != self.card.url]
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
            await self.telemetry.on_llm_start(
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

        async def emit_inference_event(event: dict[str, Any]) -> None:
            if self.telemetry:
                await self.telemetry.on_llm_event(event)
            if event_callback:
                await event_callback(event)

        active_context = (
            RunContext.ensure_task_context(task, agent_name=self.card.name)
            if task is not None
            else RunContext(agent_chain=[self.card.name])
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

        response: Part = await self.llm.infer(
            query=query,
            tools=self.tools,
            agent_callback=handle_inference_agent_call if self.card.capabilities.delegation else None,
            agent_cards=discovered if self.card.capabilities.delegation else None,
            streaming=streaming,
            event_callback=emit_inference_event if self.telemetry or event_callback else None,
            action_authorizer=authorize_inference_action,
            cancellation_token=active_token,
            run_context=active_context,
        )

        if self.telemetry:
            await self.telemetry.on_llm_end(response)

        return response

    async def call_llm_stream(
        self,
        infer_part: Part,
        task: Task | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterator[Any]:
        """Invoke the agent LLM in streaming mode and yield task events.

        The returned iterator yields ``TaskLLMStreamEvent`` objects for
        provider activity such as chunks, tool calls, delegated agent calls,
        and final inference content. A private final payload is used internally
        by ``handle_task_streaming()`` to attach the completed ``Part`` to the
        task before the final status event is emitted.
        """
        from protolink.core.events import TaskErrorEvent, TaskLLMStreamEvent

        queue: asyncio.Queue[Any] = asyncio.Queue()
        sentinel = object()
        task_id = task.id if task else ""

        async def emit(payload: dict[str, Any]) -> None:
            metadata = {key: value for key, value in payload.items() if key not in {"type", "step", "content", "final"}}
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
            try:
                part = await self.call_llm(
                    infer_part,
                    task=task,
                    streaming=True,
                    event_callback=emit,
                    cancellation_token=cancellation_token,
                )
                await queue.put({"__protolink_part__": part.to_dict()})
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
                await queue.put(sentinel)

        runner = asyncio.create_task(run_inference())
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
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
            agent_name: Name or URL of the agent to delegate to.
            action: The action type - either "tool_call" (execute a tool on the remote agent) or "infer" (ask the
                remote agent to generate a response).
            payload: The full agent_call payload from the LLM, containing tool/args or prompt.
            parent_context: Optional active context used to create a correlated
                child run for delegated work.

        Returns:
            The result from the delegated agent (typically the last part content from the response task).

        Raises:
            ValueError: If the action type is unknown.
            RuntimeError: If the delegation fails (propagated from call_agent).
        """
        # Resolve agent name to URL
        agent_url = await self._resolve_agent_url(agent_name)

        # Guardrail Check for self-delegation
        if agent_url == self.card.url:
            self._logger.debug("Self-delegation detected.")
            raise ValueError(
                f"Self-delegation is not allowed. You are '{self.card.name}' ({self.card.url}) and cannot delegate tasks to yourself."  # noqa: E501
            )

        async def call_delegated_task(task: Task) -> Task:
            if parent_context is not None:
                parent_context.child().attach_to_task(task)
            try:
                return await self.call_agent(agent_url, task)
            except asyncio.CancelledError:
                self._schedule_delegated_cancellation(
                    agent_url,
                    task.id,
                    "Parent task was canceled",
                )
                raise

        if action == "tool_call":
            tool_name = payload.get("tool")
            args = payload.get("args", {})
            if not tool_name:
                raise ValueError(f"tool_call agent_call must specify 'tool' field. Received payload: {payload}")
            # Create task with tool_call part for the remote agent to execute
            task = Task.create(Message(role="agent", parts=[Part.tool_call(tool_name=tool_name, args=args)]))
            result_task = await call_delegated_task(task)
            return result_task.get_last_part_content()

        elif action == "infer":
            prompt = payload.get("prompt", "")
            # Create task with infer message for the remote agent to process
            task = Task.create(Message.infer(prompt=prompt))
            result_task = await call_delegated_task(task)
            return result_task.get_last_part_content()

        raise ValueError(f"Unknown agent_call action: {action}")

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
