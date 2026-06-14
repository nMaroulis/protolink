"""
ProtoLink - Agent Base Class

Simple agent implementation extending Google's A2A protocol making the Agent component more centralised,
incorporating both client and server functionalities.

The Agent is the central component of the ProtoLink framework, and it is used to manage the agent's identity,
capabilities, and interactions with other agents.

The philosophy is that the Agent should be self-contained and able to function independently. Each module is
pluggable to the agent and can be replaced with your own implementation. The Agent incorporates:
- Tools
- LLM
- Transport
- Memory
- Storage
- Telemetry
- Logger

Receives Tasks from other Agents or Users -> handle_task() function
Sends Tasks to other Agents -> call_agent() function

The task is the primary unit of work in the ProtoLink framework. Agents receive & send tasks from/to other agents.

The Agent is also responsible for registering itself to the registry and fetching other agents from the registry.
If another agent invokes the agent's LLM for inference ('infer' action type), an inference cycle starts until the Task
is resolved, all handled automatically by Protolink.
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from protolink.client import AgentClient, RegistryClient
from protolink.core.task import TaskState
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.logging import BaseLogger, ConsoleLogger, get_agent_farewell, get_agent_greeting
from protolink.models import AgentCard, AgentSkill, Artifact, Message, Part, Task
from protolink.security.auth import Authenticator
from protolink.server import AgentServer
from protolink.state import State
from protolink.storage import InMemoryStorage, Storage
from protolink.telemetry.base import Telemetry
from protolink.tools import BaseTool, Tool
from protolink.transport import Transport, get_transport
from protolink.types import StateMode, TransportType
from protolink.utils.renderers.chat import to_chat_html
from protolink.utils.renderers.status import to_status_html


class Agent:
    """Base class for creating A2A-compatible agents.

    Users should subclass this and implement the handle_task method.
    Optionally implement handle_task_streaming for real-time updates.
    """

    def __init__(
        self,
        card: AgentCard | dict[str, Any],
        transport: TransportType | Transport | None = None,
        registry: TransportType | Registry | RegistryClient | None = None,
        registry_url: str | None = None,
        llm: LLM | None = None,
        system_prompt: str | None = None,
        storage: Storage | None = None,
        state: list[StateMode] | State | None = None,
        telemetry: Telemetry | None = None,
        skills: Literal["auto", "fixed"] = "auto",
        logger: BaseLogger | None = None,
        discovery_ttl: int = 0,
        *,
        override_system_prompt: bool = False,
        verbosity: Literal[0, 1, 2] = 1,
        expose_chat: bool = True,
        authenticator: Authenticator | None = None,
        credentials: str | None = None,
    ):
        """Initialize agent with its identity card and transport layer.

        Args:
            card: AgentCard or dict describing this agent's identity and capabilities.
            transport: Transport instance or transport type string. If a Transport object is provided, it's used
                directly. If a string is provided (e.g., "http", "websocket"), a new Transport instance is created
                (transport factory) using the agent's card URL.
            registry: Registry instance, RegistryClient, or transport type string. If a Registry object is provided,
                its RegistryClient is extracted. If a RegistryClient is provided, it's used directly.
                If a string is provided, a new RegistryClient is created using the transport factory with registry_url.
            registry_url: URL of registry when using string transport type for registry creation.
            llm: Optional LLM instance for agent reasoning and inference.
            system_prompt: This is used as complementary text in the system prompt, which is responsible for explaining
                the agent logic and role. The agent calling, tool calling and other A2A functionalities are already
                predefined, so the LLM already has the knowledge on how to interact with its environment.
                If you wish to override the system prompt completely, set override_system_prompt to True.
            storage: Optional Storage instance for agent data persistence. It's also used for State persistence.
            state: Agent state. Choose for which modules state should be persistent.
                - ``None`` (default): Stateless. State is wiped on every task.
                - ``["conversation"]``: Persistent conversation history per session. Conversation Session State is
                preserved across tasks with the same ``session_id``.
                Example: ``state=["conversation"]``
            telemetry: Optional Telemetry instance for agent observability and tracing.
            skills: Skills mode - "auto" to detect from tools, "fixed" to use only card-defined skills.
            logger: Custom logger instance. If not provided, a ConsoleLogger will be used.
            discovery_ttl: Time to live in seconds for caching Agent information discovered from the Registry.
            override_system_prompt: If True, overrides system_prompt completely with the system_prompt provided.
            verbosity: Verbosity level - 0 for silent, 1 for normal, 2 for verbose (debug mode).
            expose_chat: Whether the Agent will expose a chat endpoint for interaction with a UI.
            authenticator: Optional Authenticator instance for verifying incoming requests to this agent.
            credentials: Optional credentials string used for authenticating outgoing requests.
        """

        # Field Validation is handled by the AgentCard dataclass.
        self.card: AgentCard = AgentCard.from_dict(card) if isinstance(card, dict) else card
        # LLM validation is handled by the @llm.setter property.
        self._llm: LLM | None = None
        self.llm = llm
        # Storage
        self._storage: Storage
        self.storage = storage if storage is not None else InMemoryStorage(namespace=self.card.name)
        # Telemetry
        self._telemetry: Telemetry | None = None
        self.telemetry = telemetry
        # Tools & skills
        self.tools: dict[str, BaseTool] = {}
        self.skills: Literal["auto", "fixed"] = skills
        # Logger - Maps verbosity to WARNING, INFO, DEBUG for default console logger.
        self._logger = (
            ConsoleLogger(name=f"protolink.agents.{self.card.name}", level={0: 50, 1: 20, 2: 10}.get(verbosity, 20))
            if logger is None
            else logger
        )
        # Agent State Persistence
        if isinstance(state, State):
            self._state: State = state
        else:
            if state is None:
                self._logger.debug(f"State not provided, agent {self.card.name} will be stateless.")
                self._state: State = State(storage=self.storage, enabled=[])
            else:
                self._state: State = State(storage=self.storage, enabled=state)
                self._logger.debug(f"Agent {self.card.name} state set to {self._state.to_dict()}")
        # LLM prompt
        self._system_prompt: str | None = system_prompt
        self.override_system_prompt: bool = override_system_prompt
        self._verbosity: Literal[0, 1, 2] = verbosity
        # Store authentication configuration
        self.authenticator: Authenticator | None = authenticator
        self.credentials: str | None = credentials
        # Initialize client and server components
        if transport is None:
            self._transport, self._client, self._server = None, None, None
            self._logger.warning(
                "No transport provided, agent will not be able to receive tasks. Set agent.transport property"
                " (e.g. agent.transport = 'http') to configure."
            )
        else:
            self.transport = transport  # init _transport, _client, _server properties
        # Initialize Registry Client
        if not registry:
            self.registry_client = None
            self._logger.warning(
                "No registry provided, agent will not be able to register to the registry or fetch agents.\n"
                "Call set_registry() to configure."
            )
        else:
            self.set_registry(registry, registry_url)
        # Runtime Lifecycle State
        self._background_task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Resolve and add necessairy skills
        self._resolve_skills(skills)
        # Uptime
        self.start_time: float | None = None
        # Discovery TTL Cache
        self._discovery_ttl = discovery_ttl
        self._discovery_cache: dict[str, tuple[float, list[AgentCard]]] = {}
        # Expose Chat
        self._expose_chat = expose_chat
        # Sync API
        self.sync = SyncAgent(self)

    # ----------------------------------------------------------------------
    # Agent Server Lifecycle - A2A Operations
    # ----------------------------------------------------------------------

    ### -------------------- Internal Runtime Operations -------------------

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

    ### ---------------------------- Public API ----------------------------

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

    # ----------------------------------------------------------------------
    # Agent to Agent Communication - Client & Server
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # Message & Task handling - A2A Server Operations
    # ----------------------------------------------------------------------

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
        if self.telemetry:
            await self.telemetry.on_task_start(task, self.card.name)

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
        """Process a task while streaming tool, LLM, and completion events."""
        from protolink.core.events import (
            TaskArtifactUpdateEvent,
            TaskErrorEvent,
            TaskProgressEvent,
            TaskStatusUpdateEvent,
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

        try:
            last_item = task.get_last_item()
            if last_item is None:
                previous_state = self._state_value(task.state)
                task.update_state(TaskState.COMPLETED)
                yield TaskStatusUpdateEvent(
                    task_id=task.id,
                    previous_state=previous_state,
                    new_state=self._state_value(task.state),
                    final=True,
                    metadata={"task": task.to_dict()},
                )
                return

            session_id = task.metadata.get("session_id", task.id)
            if self.llm and self._state.conversation:
                self.llm.history = self._state.conversation.get_history(
                    session_id, default_system_prompt=self.llm.system_prompt
                )

            outputs: list[Part | Message] = []

            for part in last_item.parts:
                if part.type == "tool_call":
                    tool_name = getattr(part.content, "tool_name", None)
                    if tool_name is None and isinstance(part.content, dict):
                        tool_name = part.content.get("tool_name")
                    yield TaskProgressEvent(
                        task_id=task.id,
                        message=f"Executing tool: {tool_name or 'unknown'}",
                        metadata={"agent": self.card.name, "part_type": part.type},
                    )
                    outputs.append(await self.execute_tool(part))
                elif part.type == "infer":
                    async for event in self.call_llm_stream(part, task=task):
                        if isinstance(event, dict) and "__protolink_part__" in event:
                            outputs.append(Part.from_dict(event["__protolink_part__"]))
                            continue
                        if isinstance(event, TaskErrorEvent):
                            previous_state = self._state_value(task.state)
                            if not task.is_terminal:
                                task.fail(event.error_message)
                            yield event
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

            for out in outputs:
                if isinstance(out, Message):
                    task.add_message(out)
                else:
                    task.add_artifact(Artifact(parts=[out]))

            if self.llm and self._state.conversation:
                self._state.conversation.save_history(session_id, self.llm.history)

            previous_state = self._state_value(task.state)
            self._finalize_task_state(task, outputs)

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

    # ----------------------------------------------------------------------
    # Task & Message Delegation - A2A Client Operations
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # Invoke Agent - Convenience Methods for direct / test invocation
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # Registry
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # Tool Management
    # ----------------------------------------------------------------------

    def add_tool(self, tool: BaseTool) -> None:
        """Register a Tool instance with the agent."""
        self.tools[tool.name] = tool
        skill = AgentSkill(
            id=tool.name,
            description=tool.description or f"Tool: {tool.name}",
            input_schema=tool.input_schema or {},
            output_schema=tool.output_schema or {},
            tags=tool.tags or [],
        )
        self._add_skill_to_agent_card(skill)

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ):
        """Decorator helper for defining inline tool functions."""

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
                )
            )
            return func

        return decorator

    async def call_tool(self, tool_name: str, **kwargs):
        """Invoke a registered tool by name with provided kwargs."""
        tool = self.tools.get(tool_name, None)
        if not tool:
            raise ValueError(f"Tool {tool_name} not found")
        return await tool(**kwargs)

    # ----------------------------------------------------------------------
    # Task & Tool Execution
    # ----------------------------------------------------------------------

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

        self._begin_task_if_needed(task)

        try:
            last_item = task.get_last_item()
            if last_item is None:
                task.update_state(TaskState.COMPLETED)
                return task

            # ---- Session Conversation State: Load session history ----
            # If conversation is enabled in the State, we attempt to resume context using session_id from task metadata.
            # If no session_id is found, we fall back to the task.id (stateless behavior).
            session_id = task.metadata.get("session_id", task.id)
            if self.llm and self._state.conversation:
                self.llm.history = self._state.conversation.get_history(
                    session_id, default_system_prompt=self.llm.system_prompt
                )

            outputs: list[Part | Message] = []

            # ---- Inspect Parts in the last item only ----
            for part in last_item.parts:
                if part.type == "tool_call":
                    outputs.append(await self.execute_tool(part))
                elif part.type == "infer":
                    outputs.append(await self.call_llm(part, task=task))
                else:
                    self._logger.debug(f"Unknown part type '{part.type}'. Ignoring.")
            # ---- Attach outputs to the Task ----
            for out in outputs:
                if isinstance(out, Message):
                    task.add_message(out)
                else:
                    task.add_artifact(Artifact(parts=[out]))
            # ---- Session Conversation State: Save session history ----
            # Persist the current state of the conversation (including the latest responses) back to storage.
            if self.llm and self._state.conversation:
                self._state.conversation.save_history(session_id, self.llm.history)

            self._finalize_task_state(task, outputs)
        except Exception as exc:
            if not task.is_terminal:
                task.fail(str(exc))
            raise

        return task

    async def execute_tool(self, part: Part) -> Part:
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
            result = await tool(**args)
            if self.telemetry:
                await self.telemetry.on_tool_end(tool_name, result)
            return Part.tool_output(call_id=call_id, result=result)
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

        # Get Available Agents (Guardrail: excluding ourselves to prevent self-delegation loops)
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
        _ = self.llm.build_system_prompt(
            user_instructions=self._system_prompt,
            agent_cards=agent_cards,
            tools=self._build_tools_prompt(),
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

        response: Part = await self.llm.infer(
            query=query,
            tools=self.tools,
            agent_callback=self._handle_agent_call if self.card.capabilities.delegation else None,
            streaming=streaming,
            event_callback=emit_inference_event if self.telemetry or event_callback else None,
        )

        if self.telemetry:
            await self.telemetry.on_llm_end(response)

        return response

    async def call_llm_stream(self, infer_part: Part, task: Task | None = None) -> AsyncIterator[Any]:
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

    async def _handle_agent_call(
        self,
        agent_name: str,
        action: str,
        payload: dict[str, Any],
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

        if action == "tool_call":
            tool_name = payload.get("tool")
            args = payload.get("args", {})
            if not tool_name:
                raise ValueError(f"tool_call agent_call must specify 'tool' field. Received payload: {payload}")
            # Create task with tool_call part for the remote agent to execute
            task = Task.create(Message(role="agent", parts=[Part.tool_call(tool_name=tool_name, args=args)]))
            result_task = await self.call_agent(agent_url, task)
            return result_task.get_last_part_content()

        elif action == "infer":
            prompt = payload.get("prompt", "")
            # Create task with infer message for the remote agent to process
            task = Task.create(Message.infer(prompt=prompt))
            result_task = await self.call_agent(agent_url, task)
            return result_task.get_last_part_content()

        raise ValueError(f"Unknown agent_call action: {action}")

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

    # ----------------------------------------------------------------------
    # Skill Management
    # ----------------------------------------------------------------------

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
        # "fixed" mode - just use card skills as-is

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

    # ----------------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # Getters & Setters
    # ----------------------------------------------------------------------

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

    # ----------------------------------------------------------------------
    # Private Methods
    # ----------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Agent(name='{self.card.name}', url='{self.card.url}')"

    # ----------------------------------------------------------------------
    # Serialization & Deserialization (YAML/Dict)
    # ----------------------------------------------------------------------

    def _serialize_tool(self, tool: BaseTool) -> dict[str, Any]:
        """Serialize a tool to a dictionary representation."""
        tool_dict = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "tags": tool.tags,
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
            return adapter.wrap_tool(tool_dict["name"])
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
    def from_dict(cls, data: dict[str, Any], **overrides) -> "Agent":
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
    def from_yaml_string(cls, yaml_str: str, **overrides) -> "Agent":
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
    def from_yaml(cls, filepath: str, **overrides) -> "Agent":
        """Load and reconstruct an Agent instance from a YAML file.

        Args:
            filepath: Path to the YAML file.
            **overrides: Override specific parameters passed to the Agent constructor.
        """
        with open(filepath, encoding="utf-8") as f:
            yaml_str = f.read()
        return cls.from_yaml_string(yaml_str, **overrides)


class SyncAgent:
    """Synchronous wrapper around Agent.

    This class provides blocking equivalents of async methods
    for use in:
    - scripts
    - CLI tools
    - notebooks without async support

    Internally uses `asyncio.run()` to execute async operations.

    Warning:
        This API should NOT be used inside an active event loop.
    """

    def __init__(self, agent: "Agent"):
        self._agent = agent

    def invoke(
        self,
        message: str,
        part_type: Literal["tool_call", "infer"] = "infer",
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        session_id: str = "invocation_session_id",
    ) -> str:
        """Synchronously process a message.

        Args:
            message: User message text
            part_type: Type of part to create
            tool_name: Name of tool (if part_type is "tool_call")
            tool_args: Arguments for tool (if part_type is "tool_call")
            session_id: Session ID to use for the task

        Returns:
            Agent response text
        """
        return asyncio.run(self._agent.invoke(message, part_type, tool_name, tool_args, session_id))

    def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Synchronously discover agents in the registry.

        Args:
            filter_by: Optional filter criteria

        Returns:
            List of matching AgentCard objects
        """
        return asyncio.run(self._agent.discover_agents(filter_by))

    def call_agent(self, agent_url: str, task: Task) -> Task:
        """Synchronously send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send

        Returns:
            Task with updated state and response messages
        """
        return asyncio.run(self._agent.call_agent(agent_url, task))
