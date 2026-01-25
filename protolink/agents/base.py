"""
ProtoLink - Agent Base Class

Simple agent implementation extending Google's A2A protocol making the Agent component more centralised,
incorporating both client and server functionalities.
"""

import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from protolink.client import AgentClient, RegistryClient
from protolink.core.context_manager import ContextManager
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.models import AgentCard, AgentSkill, Artifact, Message, Part, Task
from protolink.server import AgentServer
from protolink.tools import BaseTool, Tool
from protolink.transport import Transport, get_transport
from protolink.types import TransportType
from protolink.utils.logging import get_logger
from protolink.utils.renderers import to_status_html

logger = get_logger(__name__)


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
        skills: Literal["auto", "fixed"] = "auto",
        *,
        override_system_prompt: bool = False,
    ):
        """Initialize agent with its identity card and transport layer.

        Args:
            card: AgentCard or dict describing this agent's identity and capabilities
            transport: Transport instance or transport type string. If a Transport object is provided, it's used
                directly. If a string is provided (e.g., "http", "websocket"), a new Transport instance is created
                (transport factory) using the agent's card URL.
            registry: Registry instance, RegistryClient, or transport type string. If a Registry object is provided,
                its RegistryClient is extracted. If a RegistryClient is provided, it's used directly.
                If a string is provided, a new RegistryClient is created using the transport factory with registry_url.
            registry_url: URL of registry when using string transport type for registry creation.
            llm: Optional LLM instance for agent reasoning and inference
            system_prompt: This is used as complementary text in the system prompt, which is responsible for explaining
                the agent logic and role. The agent calling, tool calling and other A2A functionalities are already
                predefined, so the LLM already has the knowledge on how to interact with its environment.
                If you wish to override the system prompt completely, set override_system_prompt to True.
            skills: Skills mode - "auto" to detect from tools, "fixed" to use only card-defined skills
            override_system_prompt: If True, overrides system_prompt completely with the system_prompt provided
        """

        # Field Validation is handled by the AgentCard dataclass.
        self.card: AgentCard = AgentCard.from_dict(card) if isinstance(card, dict) else card
        self.context_manager = ContextManager()
        self.llm = llm
        self.tools: dict[str, BaseTool] = {}
        self.skills: Literal["auto", "fixed"] = skills

        # LLM prompt
        self.system_prompt: str | None = system_prompt
        self.override_system_prompt: bool = override_system_prompt

        # Initialize client and server components
        if transport is None:
            self._client, self._server = None, None
            logger.warning(
                "No transport provided, agent will not be able to receive tasks. Call set_transport() to configure."
            )
        else:
            self.set_transport(transport)

        # Initilize Registry Client
        if not registry:
            self.registry_client = None
            logger.warning(
                "No registry provided, agent will not be able to register to the registry or fetch agents.\n"
                "Call set_registry() to configure."
            )
        else:
            self.set_registry(registry, registry_url)

        # LLM Validation
        if self.llm is not None:
            if self.llm.validate_connection():
                self.card.capabilities.has_llm = True  # Override even if defined by the user.

        # Resolve and add necessairy skills
        self._resolve_skills(skills)

        # Uptime
        self.start_time: float | None = None

    # ----------------------------------------------------------------------
    # Agent Server Lifecycle - A2A Operations
    # ----------------------------------------------------------------------

    async def start(self, *, register: bool = True) -> None:
        """Start the agent's server component if available."""
        # Start the Agent server
        if self._server:
            try:
                await self._server.start()
            except Exception as e:
                logger.exception(f"Unexpected error during server start: {e}")
                raise
        # Register to the Registry
        if register and self.registry_client:
            try:
                _ = await self.registry_client.register(self.card)
                logger.info(f"Registered to registry at {self.registry_client.url}")
            except ConnectionError as e:
                logger.exception(
                    f"Failed to register to registry: {e}. Agent will continue running but won't be discoverable."
                )
            except Exception as e:
                logger.exception(f"Unexpected error during registry registration: {e}")

        self.start_time = time.time()

    async def stop(self) -> None:
        """Stop the agent's server component if available."""
        # Stop the Agent Server
        if self._server:
            await self._server.stop()
        # Unregister from the Registry
        if self.registry_client:
            await self.registry_client.unregister(self.card.url)

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
        return await self.execute_task(task)

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

    async def process(self, message_text: str) -> str:
        """Simple synchronous processing (convenience method).

        Args:
            message_text: User input text

        Returns:
            Agent response text
        """
        # Create a task with the user message
        task = Task.create(Message.user(message_text))

        # Process the task
        result_task = await self.handle_task(task)

        # Extract response
        if result_task.messages:
            last_message = result_task.messages[-1]
            if last_message.role == "agent" and last_message.parts:
                return last_message.parts[0].content

        return "No response generated"

    # ----------------------------------------------------------------------
    # Message & Task Sending - A2A Client Operations
    # ----------------------------------------------------------------------

    async def send_task_to(self, agent_url: str, task: Task) -> Task:
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
        return await self._client.send_task(agent_url, task)

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
    # Context Management
    # ----------------------------------------------------------------------

    def get_context_manager(self) -> ContextManager:
        """Get the context manager for this agent (NEW in v0.2.0).

        Returns:
            ContextManager instance
        """
        return self.context_manager

    # ----------------------------------------------------------------------
    # Registry
    # ----------------------------------------------------------------------

    def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Discover agents in the registry.

        Args:
            filter_by: Optional filter criteria (e.g., {"capabilities.streaming": True})

        Returns:
            List of matching AgentCard objects
        """
        if not self.registry_client:
            return []

        return self.registry_client.discover(filter_by=filter_by)

    async def register(self) -> None:
        """Register this agent in the global registry.

        Raises:
            ValueError: If agent with same URL or name already exists
        """
        if not self.registry_client:
            return
        await self.registry_client.register(self.get_agent_card(as_json=False))

    async def unregister(self) -> None:
        """Unregister this agent from the global registry."""
        if not self.registry_client:
            return
        await self.registry_client.unregister(self.get_agent_card(as_json=False).url)

    # ----------------------------------------------------------------------
    # Tool Management
    # ----------------------------------------------------------------------

    def add_tool(self, tool: BaseTool) -> None:
        """Register a Tool instance with the agent."""
        self.tools[tool.name] = tool
        skill = AgentSkill(
            id=tool.name, description=tool.description or f"Tool: {tool.name}", tags=tool.tags if tool.tags else []
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

        outputs: list[Part | Message] = []

        # ---- Inspect Parts in the last item only ----
        for part in last_item.parts:
            if part.type == "tool_call":
                outputs.append(await self.execute_tool(part))

            elif part.type == "infer":
                outputs.append(await self.call_llm(part))
        # ---- Attach outputs to the Task ----
        for out in outputs:
            if isinstance(out, Message):
                task.add_message(out)
            else:
                task.add_artifact(Artifact(parts=[out]))

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

        tool_name = part.content["tool_name"]
        args = part.content.get("args", {})
        call_id = part.content.get("call_id")

        tool = self.tools.get(tool_name)
        if not tool:
            return Part.tool_output(
                call_id=call_id,
                error={"message": f"Tool '{tool_name}' not found"},
            )

        try:
            result = await tool(**args)
            return Part.tool_output(call_id=call_id, result=result)
        except Exception as e:
            return Part.tool_output(
                call_id=call_id,
                error={"message": str(e)},
            )

    async def call_llm(self, infer_part: Part) -> Part:
        """
        Invoke the agent's LLM.

        The LLM may:
        - return text
        - return tool_call parts
        - return infer parts (loop)
        """

        if not self.llm:
            return [
                Part.error(
                    code="no_llm",
                    message="Agent has no LLM but received a infer instruction",
                )
            ]

        # Get Available Agents
        agent_cards = ""
        for i, agent in enumerate(self.discover_agents(), start=1):
            agent_cards += f"""
            Agent {i}:
                {agent.get_prompt_format()}
            """

        # Build the System Prompt
        _ = self.llm.build_system_prompt(
            user_instructions=self.system_prompt,
            agent_cards=agent_cards,
            tools=self.get_tools_for_prompt(),
            override_system_prompt=self.override_system_prompt,
        )

        response: Part = await self.llm.infer(query=infer_part.content.get("prompt", ""), tools=self.tools)
        return response

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
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
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
    # Getters & Setters
    # ----------------------------------------------------------------------

    def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]:
        """Return the agent's identity card.

        Returns:
            AgentCard with agent metadata
        """
        return self.card.to_dict() if as_json else self.card

    def get_agent_status_html(self) -> str:
        """Return the agent's status as HTML.

        Returns:
            HTML string with agent status information
        """
        return to_status_html(agent=self.card, start_time=self.start_time)

    def get_tools_for_prompt(self) -> str | None:
        """Return a string with a list of the agent's tools to be used in  LLM prompts."""
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

    def get_transport(self) -> Transport | None:
        """
        Get the transport layer for this agent.

        Returns:
            Transport instance for communication
        """
        return self._transport

    def set_transport(self, transport: TransportType | Transport | None) -> None:
        """Set the transport layer for this agent.

        Args:
            transport: Transport instance for communication
        """

        if transport is None:
            self._transport, self._client, self._server = None, None, None
            raise ValueError("transport must not be None")

        if isinstance(transport, str):
            transport = get_transport(transport, url=self.card.url)
        elif isinstance(transport, Transport):
            # Transport and AgentCard URL must match if transport has a URL.
            transport_url = getattr(transport, "url", None)
            if transport_url is not None and transport_url != self.card.url:
                raise ValueError(f"Transport URL {transport.url} does not match AgentCard URL {self.card.url}")
            transport = transport
        else:
            raise ValueError("Invalid transport type")

        self._transport = transport
        # Initialize Agent-to-Agent Client
        self._client = AgentClient(transport=transport)
        # Exposes AgentProtocol to Server
        self._server = AgentServer(transport=transport, agent=self)

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
                    logger.error("registry_url cannot be None")
                    return
                transport = get_transport(registry, url=registry_url)
                self.registry_client = RegistryClient(transport=transport)
            elif isinstance(registry, RegistryClient):
                self.registry_client = registry
            else:
                self.registry_client = None
                logger.error("Invalid registry type")
        else:
            self.registry_client = None
            logger.error("registry argument cannot be None")

    def set_llm(self, llm: LLM) -> None:
        """Sets the Agent's LLM and validates the connection."""
        self.llm = llm
        _ = self.llm.validate_connection()

    # ----------------------------------------------------------------------
    # Private Methods
    # ----------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"Agent(name='{self.card.name}', url='{self.card.url}')"
