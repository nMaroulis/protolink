"""
ProtoLink - Agent Base Class

Simple agent implementation extending Google's A2A protocol making the Agent component more centralised,
incorporating both client and server functionalities.
"""

from collections.abc import AsyncIterator
from typing import Any, Literal

from protolink.client import RegistryClient
from protolink.client.agent_client import AgentClient
from protolink.core.context_manager import ContextManager
from protolink.discovery.registry import Registry
from protolink.llms.base import LLM
from protolink.models import AgentCard, AgentSkill, Message, Task
from protolink.security.auth import Authenticator, SecurityContext
from protolink.server import AgentServer
from protolink.tools import BaseTool, Tool
from protolink.transport import AgentTransport, HTTPRegistryTransport
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class Agent:
    """Base class for creating A2A-compatible agents.

    Users should subclass this and implement the handle_task method.
    Optionally implement handle_task_streaming for real-time updates.
    """

    def __init__(
        self,
        card: AgentCard | dict[str, Any],
        llm: LLM | None = None,
        transport: AgentTransport | None = None,
        registry: Registry | RegistryClient | str | None = None,
        authenticator: Authenticator | None = None,
        skills: Literal["auto", "fixed"] = "auto",
    ):
        """Initialize agent with its identity card and transport layer.

        Args:
            card: AgentCard describing this agent
            llm: Optional LLM instance for the agent to use
            transport: Transport layer for client/server communication
            registry: Optional registry for agent discovery. The Agent uses the RegistryClient to communicate with the
                Registry. If a Registry class is passed, its RegistryClient will be extracted. If a string is passed, it
                will be used as the registry URL. (default HTTPRegistryTransport)
            authenticator: Optional authentication provider
            skills: Skills mode - "auto" to automatically detect and add skills, "fixed" to use only the skills defined
            by the user in the AgentCard.
        """

        # Field Validation is handled by the AgentCard dataclass.
        self.card = AgentCard.from_json(card) if isinstance(card, dict) else card
        self.context_manager = ContextManager()
        self.llm = llm
        self.tools: dict[str, BaseTool] = {}
        self.skills: Literal["auto", "fixed"] = skills
        self.authenticator = authenticator
        self._security_context: SecurityContext | None = None

        # Initilize Registry Client
        self.registry_client: RegistryClient | None = None
        if registry:
            if isinstance(registry, Registry):
                self.registry_client = registry.get_client()
            elif isinstance(registry, str):
                # defaults to HTTPRegistryTransport
                self.registry_client = RegistryClient(transport=HTTPRegistryTransport(url=registry))
            elif isinstance(registry, RegistryClient):
                self.registry_client = registry
            else:
                raise ValueError("Invalid registry type")

        # Initialize client and server components
        if transport is None:
            self._client, self._server = None, None
            logger.warning(
                "No transport provided, agent will not be able to receive tasks. Call set_transport() to configure."
            )
        else:
            self._client = AgentClient(transport=transport)
            self._server = AgentServer(transport, self.handle_task)
            self._server.validate_agent_url(self.card.url)
            # Transport and AgentCard URL must match.
            if getattr(transport, "url", None) != self.card.url:
                raise ValueError(f"Transport URL {transport.url} does not match AgentCard URL {self.card.url}")

        # LLM Validation
        if self.llm is not None:
            if self.llm.validate_connection():
                self.card.capabilities.has_llm = True  # Override even if defined by the user.

        # Resolve and add necessairy skills
        self._resolve_skills(skills)

    async def start(self, *, register: bool = True) -> None:
        """Start the agent's server component if available."""
        # Start the Agent server
        if self._server:
            await self._server.start()
        # Register to the Registry
        if register and self.registry_client:
            await self.registry_client.register(self.card)

    async def stop(self) -> None:
        """Stop the agent's server component if available."""
        # Stop the Agent Server
        if self._server:
            await self._server.stop()
        # Unregister from the Registry
        if self.registry_client:
            await self.registry_client.unregister(self.card.url)

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

    def get_agent_card(self) -> AgentCard:
        """Return the agent's identity card.

        Returns:
            AgentCard with agent metadata
        """
        return self.card

    def set_llm(self, llm: LLM) -> None:
        """Sets the Agent's LLM and validates the connection."""
        self.llm = llm
        _ = self.llm.validate_connection()

    async def handle_task(self, task: Task) -> Task:
        """Process a task and return the result.

        This is the core method that users must implement.

        Args:
            task: Task to process

        Returns:
            Task with updated state and response messages

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Agent subclasses must implement handle_task()")

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
            result_task = self.handle_task(task)

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

    def process(self, message_text: str) -> str:
        """Simple synchronous processing (convenience method).

        Args:
            message_text: User input text

        Returns:
            Agent response text
        """
        # Create a task with the user message
        task = Task.create(Message.user(message_text))

        # Process the task
        result_task = self.handle_task(task)

        # Extract response
        if result_task.messages:
            last_message = result_task.messages[-1]
            if last_message.role == "agent" and last_message.parts:
                return last_message.parts[0].content

        return "No response generated"

    def set_transport(self, transport: AgentTransport | None) -> None:
        """Set the transport layer for this agent.

        Args:
            transport: Transport instance for communication
        """
        if transport is None:
            raise ValueError("transport must not be None")
        if not isinstance(transport, AgentTransport):
            raise TypeError("transport must be an instance of AgentTransport")

        self._client = AgentClient(transport=transport)
        self._server = AgentServer(transport, self.handle_task)

    async def send_task_to(self, agent_url: str, task: Task) -> Task:
        """Send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send

        Returns:
            Task with response from target agent

        Raises:
            RuntimeError: If no transport is configured
        """
        if not self._client:
            raise RuntimeError("No transport client configured. Call set_transport() first.")

        return await self._client.send_task(agent_url, task)

    async def send_message_to(self, agent_url: str, message: Message) -> Message:
        """Send a message to another agent.

        Args:
            agent_url: URL of the target agent
            message: Message to send

        Returns:
            Response message from target agent

        Raises:
            RuntimeError: If no transport is configured
        """
        if not self._client:
            raise RuntimeError("No transport client configured. Call set_transport() first.")

        return await self._client.send_message(agent_url, message)

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
        return self.registry_client.discover(filter_by=filter_by)

    def register(self) -> None:
        """Register this agent in the global registry.

        Raises:
            ValueError: If agent with same URL or name already exists
        """
        self.registry_client.register(self.get_agent_card())

    def unregister(self) -> None:
        """Unregister this agent from the global registry."""
        self.registry_client.unregister(self.get_agent_card().url)

    # ----------------------------------------------------------------------
    # Authentication
    # ----------------------------------------------------------------------

    async def verify_request_auth(self, auth_header: str | None = None) -> SecurityContext | None:
        """NEW in v0.3.0: Verify authentication of incoming request.

        Args:
            auth_header: Authorization header (e.g., "Bearer token")
            skill: Skill being requested for scope verification

        Returns:
            AuthContext if verified, None if no auth required

        Raises:
            PermissionError: If auth fails or insufficient scopes
        """
        if not self.authenticator:
            # No auth configured, request always allowed
            return None

        if not auth_header:
            raise PermissionError("Authentication required but no credentials provided")

        # Extract bearer token
        if not auth_header.startswith("Bearer "):
            raise PermissionError("Invalid authorization header format")

        token = auth_header[7:]  # Remove "Bearer "

        # Authenticate
        try:
            context = await self.authenticator.authenticate(token)
        except Exception as e:
            raise PermissionError(f"Authentication failed: {e}")  # noqa: B904

        # Check if expired
        if context.is_expired():
            raise PermissionError("Token expired")

        self._security_context = context
        return context

    def get_security_context(self) -> SecurityContext | None:
        """Get current authenticated context (NEW v0.3.0).

        Returns:
            SecurityContext if authenticated, None otherwise
        """
        return self._security_context

    # ----------------------------------------------------------------------
    # Tool Management
    # ----------------------------------------------------------------------

    def add_tool(self, tool: BaseTool) -> None:
        """Register a Tool instance with the agent."""
        self.tools[tool.name] = tool
        skill = AgentSkill(id=tool.name, description=tool.description or f"Tool: {tool.name}", tags=tool.tags)
        self._add_skill_to_agent_card(skill)

    def tool(self, name: str, description: str, tags: list[str] | None = None):
        """Decorator helper for defining inline tool functions."""

        # decorator for Native functions
        def decorator(func):
            self.add_tool(Tool(name=name, description=description, tags=tags, func=func))
            return func

        return decorator

    async def call_tool(self, tool_name: str, **kwargs):
        """Invoke a registered tool by name with provided kwargs."""
        tool = self.tools.get(tool_name, None)
        if not tool:
            raise ValueError(f"Tool {tool_name} not found")
        return await tool(**kwargs)

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
        # TODO(): Get LLM's skills.
        # Detect skills from tools
        for tool_name, tool in self.tools.items():
            skill = AgentSkill(id=tool_name, description=tool.description or f"Tool: {tool_name}", tags=tool.tags)
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

    def __repr__(self) -> str:
        return f"Agent(name='{self.card.name}', url='{self.card.url}')"
