"""Reusable behavior mixins for the public Agent class.

These mixins keep the public :class:`protolink.agents.Agent` API stable while
separating independent responsibilities such as lifecycle, control-plane
operations, tools, registry communication, configuration, and serialization.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any, Literal, TypeVar

from protolink.client import AgentClient, RegistryClient
from protolink.core.actions import RunAction
from protolink.core.cancellation import CancellationToken, TaskCancellationRequest
from protolink.core.policy import ActionAuthorization
from protolink.core.run_context import RunContext
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.llms.compaction import HistoryCompactionRequest, HistoryCompactionResult, HistoryCompactionStrategy
from protolink.logging import get_agent_farewell, get_agent_greeting
from protolink.models import AgentCard, AgentSkill, Message, Task
from protolink.server import AgentServer
from protolink.state.operations import StateOperationRequest, StateOperationResult, StateStoreReport
from protolink.storage import Storage
from protolink.telemetry.base import Telemetry
from protolink.tools import ActionBuilder, BaseTool, Tool
from protolink.tools.schema import validate_tool_args
from protolink.transport import Transport, get_transport
from protolink.types import TransportType
from protolink.utils.renderers.chat import to_chat_html
from protolink.utils.renderers.status import to_status_html

from ._typing import _AgentMixinBase
from .helpers import _coerce_state_operation_request

AgentSerializationT = TypeVar("AgentSerializationT", bound="AgentSerializationMixin")


class AgentLifecycleMixin(_AgentMixinBase):
    """Starts, stops, and tears down the embedded server runtime."""

    async def _serve(self, *, register: bool = True) -> None:
        """Initialize and start the agent runtime.

        This method performs agent startup operations such as:
        - starting the transport/server
        - registering the agent to the registry
        - initializing runtime state

        This method does NOT:
        - block indefinitely
        - manage event loops
        - handle threading
        - detect execution environments

        It is the internal async startup primitive used by the public `start()` API.

        Args:
            register: If True, registers the agent with the configured registry.

        Raises:
            Exception: Propagates unexpected startup or registration errors.
        """

        # Start server
        if self._server:
            try:
                await self._server.start()
            except Exception as e:
                self._logger.exception(f"Unexpected error during server start: {e}")
                raise

        # Register agent
        if register and self.registry_client:
            try:
                await self.registry_client.register(self.card)
                self._logger.info(f"Registered to registry at {self.registry_client.url}")
            except ConnectionError as e:
                self._logger.exception(
                    f"Failed to register to registry: {e}. Agent will continue running but won't be discoverable."
                )
            except Exception as e:
                self._logger.exception(f"Unexpected error during registry registration: {e}")

        self.start_time = time.time()

    async def _serve_forever(self) -> None:
        """Keep the agent runtime alive until cancellation.

        This method blocks indefinitely and gracefully shuts down the
        agent when cancellation occurs.
        """

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self._logger.info(f"Agent '{self.card.name}' shutting down...")
            await self._stop()
            self._logger.info(get_agent_farewell(self.card.name))

    async def _stop(self) -> None:
        """Internal async shutdown primitive."""

        # Guard against double stop
        if getattr(self, "_stopped", False):
            return
        self._stopped = True

        # 1. Unregister from registry first (while transport is still alive)
        if self.registry_client:
            try:
                # We use a short timeout for unregistration during shutdown
                await asyncio.wait_for(self.registry_client.unregister(self.card.url), timeout=2.0)
            except Exception as e:
                self._logger.debug(f"Failed to unregister from registry during shutdown: {e}")

        # 2. Stop server and transport
        if self._server:
            await self._server.stop()

    def start(
        self,
        *,
        register: bool = True,
        background: bool = False,
    ) -> None:
        """Start the agent runtime and initialize outbound/inbound communications.

        This is the primary public entrypoint for running the agent. It is designed to be
        environment-agnostic, working seamlessly in:
        - standard scripts
        - async applications
        - background threads
        - Jupyter notebooks (interactive environments)


        **Technical Note on Lifecycle Orchestration:**
        Protolink handles the transition between synchronous and asynchronous contexts using
        a dual-mode execution strategy:

        1. **Deterministic Background Mode (``background=True``):** Starts a dedicated thread
           with its own ``asyncio`` event loop. To prevent race conditions, this method
           utilizes a ``threading.Event`` to block the caller until the background agent is
           fully initialized, registered, and ready to receive traffic. Any startup
           failures (e.g., port collisions) are captured and re-raised in the caller thread.

        2. **Blocking Mode (``background=False``):** Utilizes ``asyncio.run()`` to take over
            the main thread's execution. This is the recommended pattern for standalone
           agent scripts.

        Args:
            register: If True, registers the agent with the configured registry upon startup.
            background: Controls execution mode. If True, returns immediately after startup.

        Notes:
            - Safe to call in any environment.
            - Re-raises background startup exceptions in the main thread.
        """

        async def _lifecycle():
            try:
                self._logger.info(get_agent_greeting(self.card.name))
                await self._serve()
                # Signal that startup completed successfully if in background mode
                if hasattr(self, "_ready_event"):
                    self._ready_event.set()
                await self._serve_forever()
            except Exception as e:
                # Store startup failure so the main thread can re-raise it
                self._startup_exception = e
                # Unblock waiting thread even on failure if in background mode
                if hasattr(self, "_ready_event"):
                    self._ready_event.set()
                raise

        if background:
            self._ready_event = threading.Event()
            self._startup_exception = None

            def _thread_target():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

                self._background_task = self._loop.create_task(_lifecycle())

                try:
                    self._loop.run_until_complete(self._background_task)
                finally:
                    # Cancel pending tasks cleanly
                    pending = asyncio.all_tasks(self._loop)

                    for task in pending:
                        task.cancel()

                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

                    self._loop.close()

            self._thread = threading.Thread(
                target=_thread_target,
                daemon=False,
            )
            self._thread.start()
            # Wait until Agent startup completes
            ready = self._ready_event.wait(timeout=10)

            if not ready:
                self._logger.warning(f"Agent '{self.card.name}' background thread took more than 10s to start.")

            # Re-raise startup exceptions in caller thread
            if self._startup_exception is not None:
                raise self._startup_exception

            return
        # Blocking mode
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                self._logger.error(
                    "Agent.start() called in blocking mode from within an active event loop. "
                    "This will block the loop. Use \033[1mbackground=True\033[22m instead."
                )
        except RuntimeError:
            pass

        asyncio.run(_lifecycle())
        return

    def stop(self) -> None:
        """Stop the agent runtime and orchestrate a graceful teardown.

        This method automatically handles shutdown across across all supported execution environments:
        - scripts
        - async environments
        - background threads
        - Jupyter notebooks

        It is specifically designed to safely terminate agents started with ``background=True``.

        **Technical Note on Thread-Safe Teardown:**
        When an agent is running in a background thread, its lifecycle is managed by a private event loop.
        To stop it from the main thread, we utilize ``call_soon_threadsafe`` to inject a cancellation request into
        the background loop. This triggers a ``CancelledError`` within the ``_lifecycle()`` coroutine, allowing
        it to execute its ``finally`` blocks which perform critical cleanup like closing the transport and stopping
        the ASGI server.

        The subsequent ``join(timeout=10)`` synchronizes the main thread with the background thread's exit.
        This ensures that the caller doesn't proceed (or the process doesn't exit) while the background server
        is still in the middle of a graceful port release or connection drain.

        Notes:
            - Safe to call multiple times.
            - Blocks the main thread briefly to ensure deterministic cleanup.
        """

        # Background thread mode
        if self._loop and self._loop.is_running():
            if self._background_task and not self._background_task.done():
                self._loop.call_soon_threadsafe(self._background_task.cancel)

        # Wait for the thread to fully exit before returning,
        # so the process doesn't die while uvicorn is still cleaning up
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)


class AgentControlPlaneMixin(_AgentMixinBase):
    """Exposes cancellation, history compaction, and persistent-state controls."""

    @property
    def active_task_ids(self) -> tuple[str, ...]:
        """Return task IDs currently executing on this Agent.

        This is a process-local runtime view intended for diagnostics and
        control planes. Completed tasks are removed immediately and should be
        retrieved from application storage rather than this active registry.
        """
        return self._task_executions.task_ids

    def get_cancellation_token(self, task_id: str) -> CancellationToken | None:
        """Return the live cooperative token for an active task.

        Custom handlers may use this token to add cancellation checkpoints
        inside long-running loops. The token is never serialized into ``Task``
        or ``RunContext``.
        """
        return self._task_executions.get_token(task_id)

    async def cancel_task(
        self,
        request: str | TaskCancellationRequest,
        reason: str | None = None,
    ) -> Task:
        """Request best-effort cancellation of an active task.

        Cancellation updates both the protocol ``Task`` state and serialized
        ``RunContext``, then interrupts the owning ``asyncio.Task`` at its next
        await point. Synchronous functions and already-issued external side
        effects may not be immediately stoppable.

        Args:
            request: Active task ID or a typed A2A-style cancellation request.
            reason: Optional reason used when ``request`` is a task ID. When a
                typed request is supplied, an explicit argument takes precedence.

        Returns:
            The active task after its state changes to ``canceled``.

        Raises:
            TaskNotFoundError: The task is not active on this Agent.
            TaskNotCancelableError: The task already reached a terminal state.
        """
        if isinstance(request, TaskCancellationRequest):
            task_id = request.id
            cancel_reason = reason if reason is not None else request.reason
        else:
            task_id = request
            cancel_reason = reason
        return self._task_executions.cancel(task_id, cancel_reason)

    async def compact_history(
        self,
        request: HistoryCompactionRequest | dict[str, Any] | None = None,
    ) -> HistoryCompactionResult:
        """Compact this agent's LLM history through a control-plane request.

        This method backs the ``/llm/history/compact`` endpoint and the
        matching ``AgentClient`` request spec. It is intentionally outside
        ``Task`` execution and outside ``LLM.infer()``, so compaction is never
        advertised to the model as a tool and never consumes prompt budget.

        When ``request.session_id`` is provided and conversation state is
        enabled, the session history is loaded before compaction and saved
        afterward. The operation is authorized through the
        ``llm.history.compact`` runtime capability before any history mutation.
        """
        if self.llm is None:
            raise RuntimeError("Agent has no LLM but received a history compaction request")

        if request is None:
            active_request = HistoryCompactionRequest()
        elif isinstance(request, HistoryCompactionRequest):
            active_request = request
        elif isinstance(request, dict):
            active_request = HistoryCompactionRequest.from_dict(request)
        else:
            raise TypeError("history compaction request must be a HistoryCompactionRequest or dictionary")
        context = RunContext(
            session_id=active_request.session_id,
            agent_chain=[self.card.name],
        )
        action = RunAction(
            kind="llm.history.compact",
            name="compact_history",
            payload={"arguments": active_request.to_dict()},
            capabilities=frozenset({"llm.history.compact"}),
            description="Compact this agent's LLM conversation history.",
        )
        authorization = await self.authorize_action(action, context)
        arguments = authorization.action.payload.get("arguments", active_request.to_dict())
        if not isinstance(arguments, dict):
            raise TypeError("History compaction action payload.arguments must be a dictionary")
        authorized_request = HistoryCompactionRequest.from_dict(arguments)

        session_id = authorized_request.session_id
        if session_id and self._state.conversation:
            self.llm.history = self._state.conversation.get_history(
                session_id,
                default_system_prompt=self.llm.system_prompt,
            )

        result = self.llm.compact_history(
            authorized_request.strategy,
            max_messages=authorized_request.max_messages,
            max_tokens=authorized_request.max_tokens,
            preserve_recent=authorized_request.preserve_recent,
            summary_max_tokens=authorized_request.summary_max_tokens,
        )

        if session_id and self._state.conversation:
            self._state.conversation.save_history(session_id, self.llm.history)

        return result

    async def describe_state(
        self,
        request: str | StateOperationRequest | dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        stores: tuple[str, ...] | list[str] | None = None,
        include_data: bool | None = None,
    ) -> StateOperationResult:
        """Describe enabled state stores through the control plane.

        This method reports what state stores are enabled and, for conversation
        state, whether a specific session exists. It does not expose a model
        tool and does not mutate state.
        """
        active_request = _coerce_state_operation_request(
            request,
            session_id=session_id,
            stores=stores,
            include_data=include_data,
        )
        authorized_request = await self._authorize_state_operation(
            "describe",
            "describe_state",
            active_request,
            capabilities=frozenset({"state.describe"}),
            description="Describe this agent's persistent state.",
        )
        return self._state.describe(authorized_request)

    async def reset_state(
        self,
        request: str | StateOperationRequest | dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        stores: tuple[str, ...] | list[str] | None = None,
    ) -> StateOperationResult:
        """Reset persistent state and return a structured report.

        Passing a ``session_id`` precisely clears conversation state for that
        session. Omitting ``session_id`` performs a full agent-state reset for
        all enabled stores. Partial full resets are rejected because the current
        storage abstraction is namespace-based.
        """
        active_request = _coerce_state_operation_request(
            request,
            session_id=session_id,
            stores=stores,
        )
        authorized_request = await self._authorize_state_operation(
            "reset",
            "reset_state",
            active_request,
            capabilities=frozenset({"state.reset"}),
            description="Reset this agent's persistent state.",
        )
        return self._state.reset(authorized_request)

    async def compact_state(
        self,
        request: str | StateOperationRequest | dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        strategy: HistoryCompactionStrategy | None = None,
        max_messages: int | None = None,
        max_tokens: int | None = None,
        preserve_recent: int | None = None,
        summary_max_tokens: int | None = None,
    ) -> StateOperationResult:
        """Compact persistent conversation state and return a state report.

        Conversation state is currently the built-in compactable store. The
        operation loads the selected session, runs the LLM-owned
        ``HistoryCompactor``, saves the compacted session, and reports the
        before/after counts. Explicit keyword arguments override fields on
        ``request``; omitted keywords preserve request-spec values delivered by
        remote clients.
        """
        active_request = _coerce_state_operation_request(
            request,
            session_id=session_id,
            stores=("conversation",),
            strategy=strategy,
            max_messages=max_messages,
            max_tokens=max_tokens,
            preserve_recent=preserve_recent,
            summary_max_tokens=summary_max_tokens,
        )
        authorized_request = await self._authorize_state_operation(
            "compact",
            "compact_state",
            active_request,
            capabilities=frozenset({"state.compact", "llm.history.compact"}),
            description="Compact this agent's persistent conversation state.",
        )
        return self._compact_state_conversation(authorized_request)

    async def _authorize_state_operation(
        self,
        kind: str,
        name: str,
        request: StateOperationRequest,
        *,
        capabilities: frozenset[str],
        description: str,
    ) -> StateOperationRequest:
        """Authorize a state control-plane operation and return authorized args."""
        context = RunContext(
            session_id=request.session_id,
            agent_chain=[self.card.name],
        )
        action = RunAction(
            kind=f"state.{kind}",
            name=name,
            payload={"arguments": request.to_dict()},
            capabilities=capabilities,
            description=description,
        )
        authorization = await self.authorize_action(action, context)
        arguments = authorization.action.payload.get("arguments", request.to_dict())
        if not isinstance(arguments, dict):
            raise TypeError("State operation action payload.arguments must be a dictionary")
        return StateOperationRequest.from_dict(arguments)

    def _compact_state_conversation(self, request: StateOperationRequest) -> StateOperationResult:
        """Compact one persisted conversation session and build a result."""
        if not request.session_id:
            message = "compact_state requires session_id"
            return StateOperationResult(
                operation="compact",
                stores=(
                    StateStoreReport(
                        name="conversation",
                        enabled=self._state.conversation is not None,
                        error=message,
                    ),
                ),
                errors=({"store": "conversation", "message": message},),
            )

        if self.llm is None:
            message = "Agent has no LLM but received a state compaction request"
            return StateOperationResult(
                operation="compact",
                session_id=request.session_id,
                stores=(
                    StateStoreReport(
                        name="conversation",
                        enabled=self._state.conversation is not None,
                        error=message,
                    ),
                ),
                errors=({"store": "conversation", "message": message},),
            )

        conversation = self._state.conversation
        if conversation is None:
            return StateOperationResult(
                operation="compact",
                session_id=request.session_id,
                stores=(StateStoreReport(name="conversation", enabled=False, error="state store is not enabled"),),
                missing=("conversation",),
            )

        before = self._state.describe(StateOperationRequest(session_id=request.session_id, stores=("conversation",)))
        before_store = before.stores[0] if before.stores else None
        if before_store is None or not before_store.exists:
            return StateOperationResult(
                operation="compact",
                session_id=request.session_id,
                stores=(
                    StateStoreReport(
                        name="conversation",
                        enabled=True,
                        exists=False,
                        error="conversation session not found",
                    ),
                ),
                missing=("conversation",),
            )

        self.llm.history = conversation.get_history(
            request.session_id,
            default_system_prompt=self.llm.system_prompt,
        )
        compaction = self.llm.compact_history(
            request.strategy,
            max_messages=request.max_messages,
            max_tokens=request.max_tokens,
            preserve_recent=request.preserve_recent,
            summary_max_tokens=request.summary_max_tokens,
        )
        conversation.save_history(request.session_id, self.llm.history)
        after = self._state.describe(StateOperationRequest(session_id=request.session_id, stores=("conversation",)))
        after_store = after.stores[0] if after.stores else None

        report = StateStoreReport(
            name="conversation",
            enabled=True,
            exists=after_store.exists if after_store else True,
            item_count=after_store.item_count if after_store else None,
            message_count=after_store.message_count if after_store else None,
            compacted=True,
            metadata={
                "before": before_store.to_dict(),
                "after": after_store.to_dict() if after_store else None,
                "compaction": compaction.to_dict(),
            },
        )
        return StateOperationResult(
            operation="compact",
            session_id=request.session_id,
            stores=(report,),
            compacted=("conversation",),
        )


class AgentCommunicationMixin(_AgentMixinBase):
    """Handles direct invocation, registry discovery, and agent-to-agent calls."""

    async def call_agent(self, agent_url: str, task: Task) -> Task:
        """Send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send

        Returns:
            Task with updated state and response messages

        Raises:
            RuntimeError: If agent has no transport configured
        """
        if not self._client:
            raise RuntimeError("Agent has no transport configured, cannot send tasks.")
        RunContext.ensure_task_context(
            task,
            default_session_id=task.metadata.get("session_id", task.id),
            agent_name=self.card.name,
        )
        self._logger.debug(f"Sending to agent {agent_url} the task: {task.to_dict()}")
        result: Task = await self._client.send_task(agent_url, task)
        self._logger.debug(f"Received response Task from agent {agent_url}: {result.to_dict()}")
        return result

    async def send_message_to(self, agent_url: str, message: Message) -> Message:
        """Send a message to another agent.

        Args:
            agent_url: URL of the target agent
            message: Message to send

        Returns:
            Response message

        Raises:
            RuntimeError: If agent has no transport configured
        """
        if not self._client:
            raise RuntimeError("Agent has no transport configured, cannot send messages.")
        return await self._client.send_message(agent_url, message)

    async def invoke(
        self,
        message: str,
        part_type: Literal["tool_call", "infer"] = "infer",
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        session_id: str = "invocation_session_id",
    ) -> str:
        """Simple synchronous processing (convenience method).

        Args:
            message: User message text
            part_type: Type of part to create
            tool_name: Name of tool (if part_type is "tool_call")
            tool_args: Arguments for tool (if part_type is "tool_call")
            session_id: Session ID to use for the task

        Returns:
            Agent response text
        """
        # Create a task with the user message
        if part_type == "infer":
            task = Task.create_infer(prompt=message)
        elif part_type == "tool_call":
            task = Task.create_tool_call(tool_name=tool_name if tool_name else "", args=tool_args)
        else:
            raise ValueError(f"Unsupported part type: {part_type}")

        task.metadata["session_id"] = session_id

        # Process the task
        result_task = await self.handle_task(task)
        last_part = result_task.get_last_part_content()
        return last_part if last_part else "No response generated"

    async def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover agents in the registry.

        Args:
            filter_by: Optional filter criteria (e.g., {"capabilities.streaming": True})

        Returns:
            List of matching AgentCard objects
        """
        if not self.registry_client:
            return []

        # Simple TTL caching
        cache_key = str(filter_by)
        if self._discovery_ttl > 0:
            cached = self._discovery_cache.get(cache_key)
            if cached:
                timestamp, cards = cached
                if time.time() - timestamp < self._discovery_ttl:
                    return cards

        cards = await self.registry_client.discover(filter_by=filter_by)

        if self._discovery_ttl > 0:
            self._discovery_cache[cache_key] = (time.time(), cards)

        return cards

    async def register(self) -> None:
        """Register this agent in the global registry.

        Raises:
            ValueError: If agent with same URL or name already exists
        """
        if not self.registry_client:
            return
        await self.registry_client.register(self.card)

    async def unregister(self) -> None:
        """Unregister this agent from the global registry."""
        if not self.registry_client:
            return
        await self.registry_client.unregister(self.card.url)


class AgentToolMixin(_AgentMixinBase):
    """Manages tools, skills, and runtime action authorization."""

    def add_tool(self, tool: BaseTool) -> None:
        """Register a Tool instance with the agent."""
        self.tools[tool.name] = tool
        skill = AgentSkill(
            id=tool.name,
            description=tool.description or f"Tool: {tool.name}",
            input_schema=tool.input_schema or {},
            output_schema=tool.output_schema or {},
            tags=tool.tags or [],
            examples=getattr(tool, "examples", None) or [],
        )
        self._add_skill_to_agent_card(skill)

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        examples: list[Any] | None = None,
        capabilities: list[str] | tuple[str, ...] | set[str] | None = None,
        action_builder: ActionBuilder | None = None,
    ):
        """Decorate a function as a tool with optional policy metadata.

        Args:
            name: Stable tool name exposed to agents and models.
            description: Human-readable tool purpose.
            input_schema: Optional JSON Schema for keyword arguments.
            output_schema: Optional JSON Schema for the return value.
            tags: Optional discovery and presentation tags.
            examples: Optional usage examples.
            capabilities: Permission capabilities required before execution.
            action_builder: Optional callable that enriches the prepared
                ``RunAction`` with metadata or preview artifacts.

        Returns:
            A decorator that registers the wrapped callable on this agent.
        """

        # decorator for Native functions
        def decorator(func):
            self.add_tool(
                Tool(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    tags=tags,
                    func=func,
                    examples=examples,
                    capabilities=capabilities,
                    action_builder=action_builder,
                )
            )
            return func

        return decorator

    async def call_tool(self, tool_name: str, **kwargs):
        """Invoke a registered tool after runtime policy authorization.

        Direct calls use a fresh run context. Task-based execution uses the
        context propagated on the task, allowing per-run permissions and
        cancellation state to participate in the decision.
        """
        tool = self.tools.get(tool_name, None)
        if not tool:
            raise ValueError(f"Tool {tool_name} not found")
        context = RunContext(agent_chain=[self.card.name])
        return await self.call_tool_in_context(tool_name, context, **kwargs)

    async def call_tool_in_context(
        self,
        tool_name: str,
        context: RunContext,
        **kwargs: Any,
    ) -> Any:
        """Invoke a registered tool using an explicit run context.

        This variant is intended for application runtimes and deterministic
        flows that call tools directly while preserving per-run permissions,
        cancellation, trace correlation, and approval behavior.

        Args:
            tool_name: Name of the registered tool to invoke.
            context: Active typed runtime context.
            **kwargs: Tool keyword arguments validated before authorization.

        Returns:
            The raw tool result.
        """
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool {tool_name} not found")
        _, call_args = await self._authorize_tool_action(tool, kwargs, context)
        return await tool(**call_args)

    async def authorize_action(
        self,
        action: RunAction,
        context: RunContext | None = None,
    ) -> ActionAuthorization:
        """Authorize an arbitrary runtime action without executing it.

        This public primitive supports deterministic flows and application
        runtimes that prepare side effects outside the built-in tool dispatcher.
        Tool execution paths call the same authorizer internally after enriching
        actions with tool-declared capabilities and preview artifacts.

        Args:
            action: Concrete operation to evaluate.
            context: Optional active run context. A fresh context associated
                with this agent is created when omitted.

        Returns:
            A successful authorization record.

        Raises:
            ActionDeniedError: Policy or an approver denied the operation.
            ApprovalRequiredError: Approval is required but no handler exists.
        """
        active_context = context or RunContext(agent_chain=[self.card.name])
        return await self.action_authorizer.authorize(action, active_context)

    async def _prepare_tool_action(
        self,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: RunContext,
    ) -> tuple[RunAction, dict[str, Any]]:
        """Validate tool arguments and prepare their concrete runtime action."""
        validate_args = getattr(tool, "validate_args", None)
        if getattr(tool, "_protolink_validates_args", False) and callable(validate_args):
            call_args = validate_args(arguments)
        else:
            call_args = validate_tool_args(arguments, getattr(tool, "input_schema", None))

        declared_capabilities = tuple(getattr(tool, "capabilities", None) or ())
        prepare = getattr(tool, "prepare_action", None)
        if callable(prepare):
            prepared = prepare(call_args, context)
            if inspect.isawaitable(prepared):
                prepared = await prepared
            if not isinstance(prepared, RunAction):
                raise TypeError(f"Tool '{tool.name}' prepare_action() must return RunAction")
            action = prepared.with_capabilities(declared_capabilities)
            action = action.with_artifacts(action.artifacts)
        else:
            action = RunAction(
                kind="tool.call",
                name=tool.name,
                payload={"arguments": call_args},
                capabilities=frozenset(declared_capabilities),
                description=tool.description or None,
            )

        prepared_arguments = action.payload.get("arguments", call_args)
        if not isinstance(prepared_arguments, dict):
            raise TypeError(f"Tool action '{action.name}' payload.arguments must be a dictionary")

        if getattr(tool, "_protolink_validates_args", False) and callable(validate_args):
            prepared_arguments = validate_args(prepared_arguments)
        else:
            prepared_arguments = validate_tool_args(prepared_arguments, getattr(tool, "input_schema", None))
        action_payload = dict(action.payload)
        action_payload["arguments"] = prepared_arguments
        return action.with_payload(action_payload), prepared_arguments

    async def _authorize_tool_action(
        self,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: RunContext,
    ) -> tuple[ActionAuthorization, dict[str, Any]]:
        """Prepare and authorize a tool operation immediately before execution."""
        action, call_args = await self._prepare_tool_action(tool, arguments, context)
        authorization = await self.authorize_action(action, context)
        return authorization, call_args

    def _resolve_skills(self, skills_mode: Literal["auto", "fixed"]) -> None:
        """Resolve skills parameter based on mode and update agent card.

        Args:
            skills_mode: "auto" to detect and add skills, "fixed" to use only AgentCard skills
        """
        if skills_mode == "auto":
            # Add auto-detected skills to agent card
            auto_skills = self._auto_detect_skills()
            for skill in auto_skills:
                self._add_skill_to_agent_card(skill)

    def _add_skill_to_agent_card(self, skill: AgentSkill) -> None:
        """Add a skill to the agent card, avoiding duplicates.

        Args:
            skill: AgentSkill to add to the card
        """
        # Check if skill with same ID already exists
        existing_ids = {existing_skill.id for existing_skill in self.card.skills}
        if skill.id not in existing_ids:
            self.card.skills.append(skill)

    def _auto_detect_skills(self, *, include_public_methods: bool = False) -> list[AgentSkill]:
        """Automatically detect skills from available tools and methods.

        Args:
            include_public_methods: Whether to automatically detect skills from public methods of the agent.
                When True, scans all public methods (those not starting with '_') and creates
                AgentSkill objects from them. When False, only detects skills from registered tools.
                Defaults to False to avoid unintended exposure of all public methods as skills.

        Returns:
            List of AgentSkill objects detected from the agent
        """
        detected_skills = []
        # TODO(): Get LLM's skills. e.g. reasoning etc.
        # Detect skills from tools
        for tool_name, tool in self.tools.items():
            skill = AgentSkill(
                id=tool_name,
                description=tool.description or f"Tool: {tool_name}",
                tags=tool.tags if tool.tags else [],
                input_schema=tool.input_schema or {},
                output_schema=tool.output_schema or {},
                examples=getattr(tool, "examples", None) or [],
            )
            detected_skills.append(skill)

        # Detect skills from public methods (excluding internal methods)
        if include_public_methods:
            for attr_name in dir(self):
                if not attr_name.startswith("_") and callable(getattr(self, attr_name)):
                    # Skip methods from base class and common methods
                    if attr_name not in ["handle_task", "handle_task_streaming", "add_tool", "tool", "call_tool"]:
                        method = getattr(self, attr_name)
                        description = method.__doc__ or f"Method: {attr_name}"
                        skill = AgentSkill(id=attr_name, description=description.strip())
                        detected_skills.append(skill)

        return detected_skills


class AgentConfigurationMixin(_AgentMixinBase):
    """Owns transport, model, storage, registry, status, and chat configuration."""

    @property
    def client(self) -> AgentClient | None:
        """Get the agent's client component.

        Returns:
            AgentClient instance if transport was provided, else None
        """
        return self._client

    @property
    def server(self) -> AgentServer | None:
        """Get the agent's server component.

        Returns:
            AgentServer instance if transport was provided, else None
        """
        return self._server

    @property
    def transport(self) -> Transport | None:
        return self._transport

    @transport.setter
    def transport(self, transport: TransportType | Transport | None) -> None:
        """Set the transport layer for this agent.

        Args:
            transport: Transport instance for communication
        """

        if transport is None:
            raise ValueError("transport must not be None")

        authenticator = getattr(self, "authenticator", None)
        credentials = getattr(self, "credentials", None)

        if isinstance(transport, str):
            transport_kwargs: dict[str, Any] = {
                "url": self.card.url,
                "authenticator": authenticator,
                "credentials": credentials,
            }
            if getattr(self, "_verbosity", 1) == 0:
                transport_kwargs["log_level"] = "critical"
                transport_kwargs["access_log"] = False
            transport = get_transport(
                transport,
                **transport_kwargs,
            )
        elif isinstance(transport, Transport):
            # Inject authenticator and credentials if the transport doesn't have them but the agent does
            if authenticator is not None and getattr(transport, "authenticator", None) is None:
                setattr(transport, "authenticator", authenticator)  # noqa: B010
            if credentials is not None and getattr(transport, "credentials", None) is None:
                setattr(transport, "credentials", credentials)  # noqa: B010
        else:
            raise ValueError("Invalid transport type")

        self._transport = transport
        self.card.capabilities.streaming = bool(getattr(transport, "supports_streaming", False))
        transport_type = getattr(transport, "transport_type", None)
        if transport_type:
            self.card.transport = transport_type
        # Initialize Agent-to-Agent Client
        self._client = AgentClient(transport=transport)
        # Exposes AgentProtocol to Server
        self._server = AgentServer(transport=transport, agent=self)

        # Update AgentCard security schemes if authenticator is configured
        if authenticator:
            scheme = getattr(authenticator, "security_scheme", None)
            if scheme:
                if self.card.security_schemes is None:
                    self.card.security_schemes = {}
                self.card.security_schemes[scheme.auth_type] = scheme.to_dict()

    @property
    def llm(self) -> LLM | None:
        """The agent's language model instance."""
        return self._llm

    @llm.setter
    def llm(self, llm: LLM | None) -> None:
        """Set the agent's LLM, validate the connection and update capabilities."""
        self._llm = llm
        # Update LLM capability in card (handles both object and dict formats)
        has_llm = bool(llm and llm.validate_connection())
        if hasattr(self.card.capabilities, "has_llm"):
            self.card.capabilities.has_llm = has_llm
        elif isinstance(self.card.capabilities, dict):
            self.card.capabilities["has_llm"] = has_llm

    @property
    def telemetry(self) -> Telemetry | None:
        return self._telemetry

    @telemetry.setter
    def telemetry(self, telemetry: Telemetry | None) -> None:
        """Sets the Agent's telemetry instance.

        Args:
            telemetry: Telemetry instance for observability
        """
        self._telemetry = telemetry

    @property
    def storage(self) -> Storage:
        """The agent's storage instance."""
        return self._storage

    @storage.setter
    def storage(self, storage: Storage) -> None:
        """Set the agent's storage instance and update session manager."""
        self._storage = storage
        if hasattr(self, "_state"):
            self._state.storage = storage

    def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]:
        """Return the agent's identity card.

        Returns:
            AgentCard with agent metadata
        """
        return self.card.to_dict() if as_json else self.card

    def get_status(self, output_format: Literal["html", "json"] = "html") -> str:
        """Return the agent's status as HTML or JSON.

        Args:
            output_format: Format of the returned status information

        Returns:
            String with agent status information in the specified format
        """
        if output_format == "html":
            return to_status_html(agent=self.card, start_time=self.start_time)
        elif output_format == "json":
            return str(self.card.to_dict())
        raise ValueError(f"Unknown format: {output_format}")

    def get_chat(self) -> str:
        """Return the chat UI page as HTML.

        This endpoint is only available if the agent has an LLM configured.
        It renders a self-contained chat interface that communicates with the agent's POST /chat endpoint.

        Returns:
            HTML string with the chat interface
        """

        if not self.llm:
            return "<html><body><h1>Chat not available</h1><p>This agent has no LLM configured.</p></body></html>"

        if not self._expose_chat:
            return "<html><body><h1>Chat not available</h1><p>This agent does not expose a chat UI.</p></body></html>"

        llm_info = {
            "provider": getattr(self.llm, "provider", None),
            "model": getattr(self.llm, "model", None),
            "model_type": getattr(self.llm, "model_type", None),
            "model_params": getattr(self.llm, "model_params", {}),
        }
        return to_chat_html(agent=self.card, llm_info=llm_info, start_time=self.start_time)

    async def handle_chat_message(self, data: dict[str, Any]) -> dict[str, str]:
        """Handle an incoming chat message from the chat UI.

        Expects a JSON body with 'message' and optional 'session_id'.
        Uses the agent's invoke() method under the hood.

        Args:
            data: Dict with 'message' (str) and optional 'session_id' (str)

        Returns:
            Dict with 'response' key containing the agent's reply
        """
        message = data.get("message", "")
        session_id = data.get("session_id", "chat_default")

        if not message:
            return {"error": "Empty message"}
        if not self.llm:
            return {"error": "Agent has no LLM configured"}
        if not self._expose_chat:
            return {"error": "Agent does not expose a chat endpoint"}

        try:
            response = await self.invoke(message=message, part_type="infer", session_id=session_id)
            return {"response": response}
        except Exception as e:
            return {"error": str(e)}

    def _build_tools_prompt(self) -> str | None:
        """Return a string with a list of the agent's tools to be used in  LLM prompts.

        Example:
                Tool 1:
                    "name": book_hotel,
                    "description": Book a hotel for a vacation. Returns booking confirmation with details.,
                    "input_schema": {
                        "location": {"type": "string", "required": True},
                        "check_in": {"type": "string", "required": True},
                        "check_out": {"type": "string", "required": True},
                        "guests": {"type": "integer", "default": 2, "required": False}
                    }
                    "output_schema": dict[str, str]
        """
        if not self.tools:
            return ""

        tool_prompts = []
        for i, (name, tool) in enumerate(self.tools.items(), start=1):
            tool_prompts.append(
                f"Tool {i}:\n"
                f'    "name": {name},\n'
                f'    "description": {tool.description},\n'
                f'    "input_schema": {tool.input_schema},\n'
                f'    "output_schema": {tool.output_schema}'
            )
        return "\n".join(tool_prompts)

    def set_registry(
        self, registry: TransportType | Registry | RegistryClient | None, registry_url: str | None = None
    ) -> None:
        """Set the registry client for this agent.

        Args:
            registry: RegistryClient instance for communication
            registry_url: URL of the registry
        """

        if registry:
            if isinstance(registry, Registry):
                self.registry_client = registry.client
            elif isinstance(registry, str):
                if registry_url is None:
                    self._logger.error("registry_url cannot be None")
                    return
                transport = get_transport(registry, url=registry_url)
                self.registry_client = RegistryClient(transport=transport)
            elif isinstance(registry, RegistryClient):
                self.registry_client = registry
            else:
                self.registry_client = None
                self._logger.error("Invalid registry type")
        else:
            self.registry_client = None
            self._logger.error("registry argument cannot be None")

    def __repr__(self) -> str:
        return f"Agent(name='{self.card.name}', url='{self.card.url}')"


class AgentSerializationMixin(_AgentMixinBase):
    """Serializes and reconstructs agent configuration dictionaries and YAML."""

    def _serialize_tool(self, tool: BaseTool) -> dict[str, Any]:
        """Serialize a tool to a dictionary representation."""
        tool_dict = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "tags": tool.tags,
            "examples": getattr(tool, "examples", None),
            "capabilities": list(getattr(tool, "capabilities", None) or ()),
        }
        # Check if it is an MCPToolAdapter
        if tool.__class__.__name__ == "MCPToolAdapter":
            tool_dict["type"] = "mcp"
            tool_dict["mcp_config"] = {
                "transport": getattr(tool, "transport", "stdio"),
                "command": getattr(tool, "command", None),
                "args": getattr(tool, "args", []),
                "url": getattr(tool, "url", None),
                "headers": getattr(tool, "headers", {}),
            }
        else:
            tool_dict["type"] = "native"
            if hasattr(tool, "func") and callable(tool.func):
                func = tool.func
                if hasattr(func, "__module__") and hasattr(func, "__name__") and func.__module__ != "builtins":
                    tool_dict["func_path"] = f"{func.__module__}:{func.__name__}"
        return tool_dict

    @classmethod
    def _deserialize_tool(cls, tool_dict: dict[str, Any]) -> BaseTool:
        """Deserialize a tool from a dictionary representation."""
        tool_type = tool_dict.get("type", "native")
        if tool_type == "mcp":
            try:
                from protolink.tools.adapters.mcp_adapter import MCPToolAdapter
            except ImportError:

                class MCPStubTool(BaseTool):
                    def __init__(self, name, description):
                        self.name = name
                        self.description = description
                        self.input_schema = {}
                        self.output_schema = None
                        self.tags = ["mcp"]
                        self.examples = []
                        self.capabilities = tuple(tool_dict.get("capabilities") or ())

                    async def __call__(self, **kwargs):
                        raise RuntimeError(
                            f"MCP tool '{self.name}' could not be invoked because MCP dependency is not installed."
                        )

                return MCPStubTool(tool_dict["name"], tool_dict.get("description", ""))

            mcp_config = tool_dict.get("mcp_config", {})
            adapter = MCPToolAdapter(
                transport=mcp_config.get("transport", "stdio"),
                command=mcp_config.get("command"),
                args=mcp_config.get("args"),
                url=mcp_config.get("url"),
                headers=mcp_config.get("headers"),
            )
            tool = adapter.wrap_tool(tool_dict["name"])
            tool.capabilities = tuple(tool_dict.get("capabilities") or ())
            return tool
        else:
            func_path = tool_dict.get("func_path")
            from collections.abc import Callable

            func: Callable[..., Any] | None = None
            if func_path:
                try:
                    import importlib

                    module_name, func_name = func_path.split(":")
                    module = importlib.import_module(module_name)
                    resolved = module
                    for part in func_name.split("."):
                        resolved = getattr(resolved, part)
                    if callable(resolved):
                        func = resolved
                    else:
                        raise TypeError(f"Object '{func_path}' is not callable")
                except Exception as e:

                    def make_stub(name, err_msg):
                        async def stub_func(**kwargs):
                            raise RuntimeError(
                                f"Tool '{name}' could not be executed because its function "
                                f"'{func_path}' failed to load: {err_msg}"
                            )

                        return stub_func

                    func = make_stub(tool_dict["name"], str(e))

            if func is None:

                def make_stub(name):
                    async def stub_func(**kwargs):
                        raise RuntimeError(f"Tool '{name}' has no associated python function.")

                    return stub_func

                func = make_stub(tool_dict["name"])

            from protolink.tools.tool import Tool

            return Tool(
                name=tool_dict["name"],
                description=tool_dict.get("description", ""),
                input_schema=tool_dict.get("input_schema"),
                output_schema=tool_dict.get("output_schema"),
                tags=tool_dict.get("tags"),
                examples=tool_dict.get("examples"),
                capabilities=tool_dict.get("capabilities"),
                func=func,
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the agent configuration to a dictionary representation."""
        level = getattr(self._logger, "level", 20)
        verbosity = 1
        if level == 30:
            verbosity = 0
        elif level == 10:
            verbosity = 2

        data = {
            "card": self.card.to_dict(),
            "skills": self.skills,
            "verbosity": verbosity,
            "expose_chat": self._expose_chat,
            "discovery_ttl": self._discovery_ttl,
            "override_system_prompt": self.override_system_prompt,
            "system_prompt": self._system_prompt,
            "credentials": self.credentials,
        }

        # Transport
        if self._transport:
            transport_config = {
                "type": getattr(self._transport, "transport_type", "http"),
                "url": self._transport.url,
                "timeout": getattr(self._transport, "timeout", 360.0),
            }
            if hasattr(self._transport, "backend"):
                backend_name = "starlette"
                if "FastAPIBackend" in self._transport.backend.__class__.__name__:
                    backend_name = "fastapi"
                transport_config["backend"] = backend_name
            if hasattr(self._transport, "backend") and hasattr(self._transport.backend, "validate_schema"):
                transport_config["validate_schema"] = getattr(self._transport.backend, "validate_schema", False)
            data["transport"] = transport_config

        # Registry
        if self.registry_client:
            data["registry"] = {
                "type": getattr(self.registry_client.transport, "transport_type", "http"),
                "url": self.registry_client.url,
            }

        # LLM
        if self.llm:
            llm_config = {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "model_params": self.llm._model_params,
                "reasoning": self.llm._reasoning,
            }
            base_url = getattr(self.llm, "base_url", None)
            if base_url:
                llm_config["base_url"] = base_url
            data["llm"] = llm_config

        # Authenticator
        if self.authenticator:
            auth_type = self.authenticator.__class__.__name__
            if auth_type == "BearerTokenAuth":
                data["authenticator"] = {
                    "type": "bearer",
                    "secret": getattr(self.authenticator, "secret", ""),
                    "algorithm": getattr(self.authenticator, "algorithm", "HS256"),
                }
            elif auth_type == "APIKeyAuth":
                data["authenticator"] = {
                    "type": "api_key",
                    "valid_keys": getattr(self.authenticator, "valid_keys", {}),
                }
            elif auth_type == "BasicAuth":
                data["authenticator"] = {
                    "type": "basic",
                    "valid_credentials": getattr(self.authenticator, "valid_credentials", {}),
                }
            elif auth_type == "OAuth2DelegationAuth":
                data["authenticator"] = {
                    "type": "oauth2",
                    "exchange_endpoint": getattr(self.authenticator, "exchange_endpoint", ""),
                    "client_id": getattr(self.authenticator, "client_id", ""),
                    "client_secret": getattr(self.authenticator, "client_secret", ""),
                }

        # Tools
        if self.tools:
            data["tools"] = [self._serialize_tool(t) for t in self.tools.values()]

        return data

    @classmethod
    def from_dict(cls: type[AgentSerializationT], data: dict[str, Any], **overrides) -> AgentSerializationT:
        """Reconstruct an Agent instance from a dictionary configuration.

        Args:
            data: The serialized configuration dictionary.
            **overrides: Override specific parameters passed to the Agent constructor.
        """
        card_data = overrides.get("card", data.get("card"))
        if not card_data:
            raise ValueError("Configuration dictionary must contain 'card' field.")

        # Authenticator
        authenticator = overrides.get("authenticator")
        if authenticator is None:
            auth_config = data.get("authenticator")
            if auth_config:
                t = auth_config.get("type")
                if t == "bearer":
                    from protolink.security.auth import BearerTokenAuth

                    authenticator = BearerTokenAuth(
                        secret=auth_config.get("secret", ""),
                        algorithm=auth_config.get("algorithm", "HS256"),
                    )
                elif t == "api_key":
                    from protolink.security.auth import APIKeyAuth

                    authenticator = APIKeyAuth(valid_keys=auth_config.get("valid_keys", {}))
                elif t == "basic":
                    from protolink.security.auth import BasicAuth

                    authenticator = BasicAuth(valid_credentials=auth_config.get("valid_credentials", {}))
                elif t == "oauth2":
                    from protolink.security.auth import OAuth2DelegationAuth

                    authenticator = OAuth2DelegationAuth(
                        exchange_endpoint=auth_config.get("exchange_endpoint", ""),
                        client_id=auth_config.get("client_id", ""),
                        client_secret=auth_config.get("client_secret", ""),
                    )

        # Credentials
        credentials = overrides.get("credentials", data.get("credentials"))

        # Transport
        transport = overrides.get("transport")
        if transport is None:
            transport_config = data.get("transport")
            if transport_config:
                transport_type = transport_config.get("type", "http")
                try:
                    from protolink.transport import get_transport

                    t_kwargs = {
                        "url": transport_config.get("url", card_data.get("url")),
                        "timeout": transport_config.get("timeout", 360.0),
                    }
                    if "backend" in transport_config:
                        t_kwargs["backend"] = transport_config["backend"]
                    if "validate_schema" in transport_config:
                        t_kwargs["validate_schema"] = transport_config["validate_schema"]

                    t_kwargs["authenticator"] = authenticator
                    t_kwargs["credentials"] = credentials

                    transport = get_transport(transport_type, **t_kwargs)
                except Exception:
                    transport = transport_type

        # Registry
        registry = overrides.get("registry")
        registry_url = overrides.get("registry_url")
        if registry is None:
            registry_config = data.get("registry")
            if registry_config:
                registry = registry_config.get("type")
                registry_url = registry_config.get("url")

        # LLM
        llm = overrides.get("llm")
        if llm is None:
            llm_config = data.get("llm")
            if llm_config:
                from protolink.llms import create_llm

                provider = llm_config.get("provider")
                l_kwargs = {
                    "model": llm_config.get("model"),
                    "model_params": llm_config.get("model_params", {}),
                    "reasoning": llm_config.get("reasoning", "none"),
                }
                base_url = llm_config.get("base_url")
                if base_url:
                    l_kwargs["base_url"] = base_url
                llm = create_llm(provider, **l_kwargs)

        storage = overrides.get("storage")
        state = overrides.get("state")
        telemetry = overrides.get("telemetry")
        logger = overrides.get("logger")

        skills_val = overrides.get("skills", data.get("skills"))
        skills: Literal["auto", "fixed"] = skills_val if skills_val in ("auto", "fixed") else "auto"

        verbosity_val = overrides.get("verbosity", data.get("verbosity"))
        verbosity: Literal[0, 1, 2] = verbosity_val if verbosity_val in (0, 1, 2) else 1

        expose_chat_val = overrides.get("expose_chat", data.get("expose_chat"))
        expose_chat: bool = bool(expose_chat_val) if expose_chat_val is not None else True

        discovery_ttl_val = overrides.get("discovery_ttl", data.get("discovery_ttl"))
        discovery_ttl: int = int(discovery_ttl_val) if discovery_ttl_val is not None else 0

        override_system_prompt_val = overrides.get("override_system_prompt", data.get("override_system_prompt"))
        override_system_prompt: bool = (
            bool(override_system_prompt_val) if override_system_prompt_val is not None else False
        )

        system_prompt = overrides.get("system_prompt", data.get("system_prompt"))

        agent = cls(
            card=card_data,
            transport=transport,
            registry=registry,
            registry_url=registry_url,
            llm=llm,
            system_prompt=system_prompt,
            storage=storage,
            state=state,
            telemetry=telemetry,
            skills=skills,
            logger=logger,
            discovery_ttl=discovery_ttl,
            override_system_prompt=override_system_prompt,
            verbosity=verbosity,
            expose_chat=expose_chat,
            authenticator=authenticator,
            credentials=credentials,
        )

        tools_data = data.get("tools", [])
        for tool_dict in tools_data:
            tool = cls._deserialize_tool(tool_dict)
            agent.add_tool(tool)

        return agent

    def to_yaml_string(self) -> str:
        """Serialize the agent configuration to a YAML string."""
        import yaml

        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    def to_yaml(self, filepath: str) -> None:
        """Export the agent configuration to a YAML file.

        Args:
            filepath: Absolute or relative path to the YAML file.
        """
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_yaml_string())

    @classmethod
    def from_yaml_string(cls: type[AgentSerializationT], yaml_str: str, **overrides) -> AgentSerializationT:
        """Reconstruct an Agent instance from a YAML string.

        Args:
            yaml_str: The YAML string containing agent configuration.
            **overrides: Override specific parameters passed to the Agent constructor.
        """
        import yaml

        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            raise ValueError("Invalid YAML configuration format. Must be a mapping/dictionary.")
        return cls.from_dict(data, **overrides)

    @classmethod
    def from_yaml(cls: type[AgentSerializationT], filepath: str, **overrides) -> AgentSerializationT:
        """Load and reconstruct an Agent instance from a YAML file.

        Args:
            filepath: Path to the YAML file.
            **overrides: Override specific parameters passed to the Agent constructor.
        """
        with open(filepath, encoding="utf-8") as f:
            yaml_str = f.read()
        return cls.from_yaml_string(yaml_str, **overrides)
