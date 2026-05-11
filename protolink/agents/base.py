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
from protolink.core.context_manager import ContextManager
from protolink.core.memory import SessionManager
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.logging import BaseLogger, ConsoleLogger
from protolink.models import AgentCard, AgentSkill, Artifact, Message, Part, Task
from protolink.server import AgentServer
from protolink.storage import InMemoryStorage, Storage
from protolink.telemetry.base import Telemetry
from protolink.tools import BaseTool, Tool
from protolink.transport import Transport, get_transport
from protolink.types import MemoryModeType, TransportType
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
        telemetry: Telemetry | None = None,
        skills: Literal["auto", "fixed"] = "auto",
        logger: BaseLogger | None = None,
        discovery_ttl: int = 0,
        *,
        override_system_prompt: bool = False,
        verbosity: Literal[0, 1, 2] = 1,
        memory: MemoryModeType = "none",
        expose_chat: bool = True,
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
            storage: Optional Storage instance for agent data persistence.
            telemetry: Optional Telemetry instance for agent observability and tracing.
            skills: Skills mode - "auto" to detect from tools, "fixed" to use only card-defined skills.
            logger: Custom logger instance. If not provided, a ConsoleLogger will be used.
            discovery_ttl: Time to live in seconds for caching Agent information discovered from the Registry.
            override_system_prompt: If True, overrides system_prompt completely with the system_prompt provided.
            verbosity: Verbosity level - 0 for silent, 1 for normal, 2 for verbose (debug mode).
            memory: Conversation memory mode.
                - ``"none"`` (default): Stateless. History is wiped on every task.
                - ``"session"``: Persistent per session. History is preserved across tasks with the same ``session_id``.
            expose_chat: Whether the Agent will expose a chat endpoint for interaction with a UI.
        """

        # Field Validation is handled by the AgentCard dataclass.
        self.card: AgentCard = AgentCard.from_dict(card) if isinstance(card, dict) else card
        self.context_manager = ContextManager()
        # LLM validation is handled by the @llm.setter property.
        self._llm: LLM | None = None
        self.llm = llm
        self._storage: Storage
        self.storage = storage if storage is not None else InMemoryStorage(namespace=self.card.name)
        self._telemetry: Telemetry | None = None
        self.telemetry = telemetry
        self.tools: dict[str, BaseTool] = {}
        self.skills: Literal["auto", "fixed"] = skills

        # Conversation Memory & Persistence
        # memory_mode determines if history is wiped per task ("none") or kept per session ("session")
        self.memory_mode = memory
        # SessionManager provides a modular interface to load/save histories via self.storage
        self._session_manager = SessionManager(storage=self._storage, memory_mode=memory)

        # LLM prompt
        self._system_prompt: str | None = system_prompt
        self.override_system_prompt: bool = override_system_prompt

        # Logger - Maps verbosity to WARNING, INFO, DEBUG for default console logger.
        self._logger = (
            ConsoleLogger(name=f"protolink.agents.{self.card.name}", level={0: 30, 1: 20, 2: 10}.get(verbosity, 20))
            if logger is None
            else logger
        )

        # Initialize client and server components
        if transport is None:
            self._transport, self._client, self._server = None, None, None
            self._logger.warning(
                "No transport provided, agent will not be able to receive tasks. Set agent.transport property"
                " (e.g. agent.transport = 'http') to configure."
            )
        else:
            self.transport = transport  # init _transport, _client, _server properties

        # Initilize Registry Client
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

        # Discovery TTL Cache - TODO(): Implement proper cache
        self._discovery_ttl = discovery_ttl

        # Expose Chat
        self._expose_chat = expose_chat

    # ----------------------------------------------------------------------
    # Agent Server Lifecycle - A2A Operations
    # ----------------------------------------------------------------------

    ### ------- Internal Runtime Operations -------

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

    async def _stop(self) -> None:
        """Internal async shutdown primitive."""

        # Stop server
        if self._server:
            await self._server.stop()

        # Unregister
        if self.registry_client:
            await self.registry_client.unregister(self.card.url)

    ### ------- Public API -------

    def start(
        self,
        *,
        register: bool = True,
        background: bool = False,
    ) -> None | asyncio.Task:
        """Start the agent runtime.

        This is the main public entrypoint for running the agent and is compatible with:
        - standard Python scripts
        - async applications
        - Jupyter notebooks
        - interactive environments

        The method automatically detects whether an asyncio event loop is already running and adapts
        execution accordingly.

        Args:
            register: If True, registers the agent with the configured registry.
            background:
                Controls execution mode.

                - If True, starts the agent in the background and returns immediately.
                - If False (default), blocks execution until shutdown.

        Returns:
            asyncio.Task | None:
                - Returns an asyncio Task when running inside an existing async event loop.
                - Returns None in blocking/script execution mode.

        Notes:
            - This is the recommended entrypoint for all users.
            - Advanced users should avoid calling internal lifecycle methods directly.
        """

        async def _lifecycle():
            await self._serve(register=register)

            if not background:
                await self._serve_forever()

        try:
            # Existing event loop (Jupyter / async app)
            loop = asyncio.get_running_loop()

            self._background_task = loop.create_task(_lifecycle())
            return self._background_task

        except RuntimeError:
            # Standard Python script

            if background:

                def _thread_target():
                    self._loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._loop)

                    self._background_task = self._loop.create_task(_lifecycle())

                    try:
                        self._loop.run_until_complete(self._background_task)
                    finally:
                        self._loop.close()

                self._thread = threading.Thread(
                    target=_thread_target,
                    daemon=True,
                )
                self._thread.start()

                return None

            # Blocking mode
            asyncio.run(_lifecycle())
            return None

    def stop(self) -> None | asyncio.Task:
        """Stop the agent runtime.

        This method automatically handles shutdown across:
        - scripts
        - async environments
        - background threads
        - Jupyter notebooks

        Returns:
            asyncio.Task | None:
                - Returns the asyncio Task being cancelled when running inside an async event loop.
                - Returns None otherwise.

        Notes:
            - Safe to call multiple times.
            - Cancels active runtime tasks before cleanup.
        """

        # Async task mode
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            return self._background_task

        # Background thread event loop
        if self._loop and self._loop.is_running():

            async def _shutdown():
                await self._stop()

            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)

            # Stop loop safely
            self._loop.call_soon_threadsafe(self._loop.stop)

        return None

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
        self._logger.debug(f"Received task: {task}")
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
        """Process a task with streaming updates (NEW in v0.2.0).

        Optional method for agents that want to emit real-time updates.
        Yields events as the task progresses.

        Args:
            task: Task to process

        Yields:
            Event objects (TaskStatusUpdateEvent, TaskArtifactUpdateEvent, etc.)

        Note:
            Default implementation calls handle_task and emits completion event.
            Override this method to provide streaming updates.
        """
        from protolink.core.events import TaskStatusUpdateEvent

        # Default: emit working status, call sync handler, emit complete
        yield TaskStatusUpdateEvent(task_id=task.id, previous_state="submitted", new_state="working")

        try:
            result_task = await self.handle_task(task)

            # Emit artifacts if any (NEW in v0.2.0)
            for artifact in result_task.artifacts:
                from protolink.core.events import TaskArtifactUpdateEvent

                yield TaskArtifactUpdateEvent(task_id=task.id, artifact=artifact)

            # Emit completion
            yield TaskStatusUpdateEvent(
                task_id=result_task.id, previous_state="working", new_state="completed", final=True
            )
        except Exception as e:
            from protolink.core.events import TaskErrorEvent

            yield TaskErrorEvent(task_id=task.id, error_code="task_failed", error_message=str(e), recoverable=False)

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
        self._logger.debug(f"Sending to agent {agent_url} the task: {task}")
        result: Task = await self._client.send_task(agent_url, task)
        self._logger.debug(f"Received response Task from agent {agent_url}: {result}")
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

    def invoke_sync(
        self,
        message: str,
        part_type: Literal["tool_call", "infer"] = "infer",
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        session_id: str = "invocation_session_id",
    ) -> str:
        """Simple synchronous processing (convenience method)."""
        return asyncio.run(self.invoke(message, part_type, tool_name, tool_args, session_id))

    # ----------------------------------------------------------------------
    # Context Management
    # ----------------------------------------------------------------------
    # TODO(): Remove
    def get_context_manager(self) -> ContextManager:
        """Get the context manager for this agent (NEW in v0.2.0).

        Returns:
            ContextManager instance
        """
        return self.context_manager

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

        return await self.registry_client.discover(filter_by=filter_by)

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

        Determinism guarantees:
        - No intent inference
        - No fallback behavior
        - No automatic execution unless explicitly declared
        - If nothing executable is found, this method is a no-op

        Task lifecycle (state transitions) is NOT handled here.
        This method only produces outputs and appends them to the Task.

        Args:
            task: The Task to execute.

        Returns:
            The same Task instance, augmented with new Messages or Artifacts.
        """

        last_item = task.get_last_item()
        if last_item is None:
            return task

        # ---- Session memory: Load session history ----
        # If memory is enabled, we attempt to resume context using session_id from task metadata.
        # If no session_id is found, we fall back to the task.id (stateless behavior).
        session_id = task.metadata.get("session_id", task.id)
        if self.llm:
            self.llm.history = self._session_manager.get_history(
                session_id, default_system_prompt=self.llm.system_prompt
            )

        outputs: list[Part | Message] = []

        # ---- Inspect Parts in the last item only ----
        for part in last_item.parts:
            if part.type == "tool_call":
                outputs.append(await self.execute_tool(part))
            elif part.type == "infer":
                outputs.append(await self.call_llm(part))
            else:
                self._logger.debug(f"Unknown part type '{part.type}'. Ignoring.")
        # ---- Attach outputs to the Task ----
        for out in outputs:
            if isinstance(out, Message):
                task.add_message(out)
            else:
                task.add_artifact(Artifact(parts=[out]))
        # ---- Session memory: Save session history ----
        # Persist the current state of the conversation (including the latest responses) back to storage.
        if self.llm:
            self._session_manager.save_history(session_id, self.llm.history)

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

        if hasattr(part.content, "tool_name"):
            # Handle the dataclass object (in-memory execution)
            tool_name = part.content.tool_name
            args = part.content.args
            call_id = part.content.call_id
            self._logger.debug(f"Executing tool: {tool_name}")
        else:
            # Handle the dictionary (network/JSON execution)
            tool_name = part.content.get("tool_name")
            args = part.content.get("args", {})
            call_id = part.content.get("call_id")
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

    async def call_llm(self, infer_part: Part) -> Part:
        """
        Invoke the agent's LLM to process an inference request.

        This method orchestrates a complete LLM inference cycle by:
        1. Discovering available agents from the registry
        2. Building a system prompt with tools, agent cards, and user instructions
        3. Invoking the LLM's inference loop with tool and agent delegation support

        The LLM may respond with:
        - A final text response (returned as ``infer_output`` Part)
        - Tool calls (handled internally via ``_inject_tool_call``)
        - Agent delegation (handled via ``_handle_agent_call`` callback)

        Args:
            infer_part: A Part of type ``infer`` containing:
                - prompt (str): The user query or instruction to process

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

        # Get Available Agents
        agent_cards = ""
        for i, agent in enumerate(await self.discover_agents(), start=1):
            agent_cards += f"""
            Agent {i}:
                {agent.get_prompt_format()}
            """

        # Build the System Prompt
        _ = self.llm.build_system_prompt(
            user_instructions=self._system_prompt,
            agent_cards=agent_cards,
            tools=self.get_tools_for_prompt(),
            override_system_prompt=self.override_system_prompt,
            persist=self.memory_mode == "session",
        )

        if self.telemetry:
            prompt = (
                infer_part.content.get("prompt", "")
                if isinstance(infer_part.content, dict)
                else getattr(infer_part.content, "prompt", "")
            )
            model_name = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", None)
            await self.telemetry.on_llm_start(prompt, model_name)

        query = (
            infer_part.content.get("prompt", "")
            if isinstance(infer_part.content, dict)
            else getattr(infer_part.content, "prompt", "")
        )
        response: Part = await self.llm.infer(
            query=query,
            tools=self.tools,
            agent_callback=self._handle_agent_call,
        )

        if self.telemetry:
            await self.telemetry.on_llm_end(response)

        return response

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
            # Create task with user message for the remote agent to process
            task = Task.create(Message.user(prompt))
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

        # Look up in discovered agents
        discovered = await self.discover_agents()
        for agent in discovered:
            if agent.name == agent_name:
                return agent.url

        raise ValueError(
            f"Agent '{agent_name}' not found in registry. Available agents: {[a.name for a in discovered]}"
        )

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

        if isinstance(transport, str):
            transport = get_transport(transport, url=self.card.url)
        elif isinstance(transport, Transport):
            # TODO(): Examine here
            # Transport and AgentCard URL must match if transport has a URL.
            # transport_url = getattr(transport, "url", None)
            # if transport_url is not None and transport_url != self.card.url:
            #     raise ValueError(f"Transport URL {transport.url} does not match AgentCard URL {self.card.url}")
            transport = transport
        else:
            raise ValueError("Invalid transport type")

        self._transport = transport
        # Initialize Agent-to-Agent Client
        self._client = AgentClient(transport=transport)
        # Exposes AgentProtocol to Server
        self._server = AgentServer(transport=transport, agent=self)

    @property
    def llm(self) -> LLM | None:
        """The agent's language model instance."""
        return self._llm

    @llm.setter
    def llm(self, llm: LLM | None) -> None:
        """Set the agent's LLM, validate the connection and update capabilities."""
        self._llm = llm
        if llm is not None:
            if llm.validate_connection():
                self.card.capabilities.has_llm = True
        else:
            self.card.capabilities.has_llm = False

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
        if hasattr(self, "_session_manager"):
            self._session_manager.storage = storage

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

    def get_tools_for_prompt(self) -> str | None:
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
            return None

        tool_prompt: str = ""
        for i, (name, tool) in enumerate(self.tools.items(), start=1):
            tool_prompt += f"""
            Tool {i}:
                "name": {name},
                "description": {tool.description},
                "input_schema": {tool.input_schema},
                "output_schema": {tool.output_schema}
            \n
            """
        return tool_prompt

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
