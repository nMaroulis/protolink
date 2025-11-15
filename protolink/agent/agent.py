"""
ProtoLink - Agent Base Class

Simple agent implementation following Google's A2A protocol.
"""

from collections.abc import AsyncIterator

from protolink.core.agent_card import AgentCard
from protolink.core.context_manager import ContextManager
from protolink.core.message import Message
from protolink.core.task import Task
from protolink.security.auth import AuthContext, AuthProvider


class Agent:
    """Base class for creating A2A-compatible agents.

    Users should subclass this and implement the handle_task method.
    Optionally implement handle_task_streaming for real-time updates.

    Example:
        class MyAgent(Agent):
            def __init__(self):
                card = AgentCard(
                    name="my-agent",
                    description="A helpful agent",
                    url="http://localhost:8000"
                )
                super().__init__(card)

            def handle_task(self, task: Task) -> Task:
                # Get the user's message
                user_message = task.messages[0]
                user_text = user_message.parts[0].content

                # Process and respond
                response = f"You said: {user_text}"
                return task.complete(response)

            # Optional: support streaming
            async def handle_task_streaming(self, task: Task):
                from protolink.events import TaskStatusUpdateEvent

                yield TaskStatusUpdateEvent(
                    task_id=task.id,
                    new_state='working'
                )

                # ... do work ...

                yield TaskStatusUpdateEvent(
                    task_id=task.id,
                    new_state='completed',
                    final=True
                )
    """

    def __init__(self, card: AgentCard, auth_provider: AuthProvider | None = None):
        """Initialize agent with its identity card.

        Args:
            card: AgentCard describing this agent
        """
        self.card = card
        self._transport = None
        self.context_manager = ContextManager()
        self.auth_provider = auth_provider
        self._auth_context = None

    def get_agent_card(self) -> AgentCard:
        """Return the agent's identity card.

        Returns:
            AgentCard with agent metadata
        """
        return self.card

    def handle_task(self, task: Task) -> Task:
        """Process a task and return the result.

        This is the core method that users must implement.

        Args:
            task: Task to process

        Returns:
            Task with updated state and response messages

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement handle_task()")

    async def verify_request_auth(self, auth_header: str | None = None, skill: str = "default") -> AuthContext | None:
        """NEW in v0.3.0: Verify authentication of incoming request.

        Args:
            auth_header: Authorization header (e.g., "Bearer token")
            skill: Skill being requested for scope verification

        Returns:
            AuthContext if verified, None if no auth required

        Raises:
            PermissionError: If auth fails or insufficient scopes
        """
        if not self.auth_provider:
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
            context = await self.auth_provider.authenticate(token)
        except Exception as e:
            raise PermissionError(f"Authentication failed: {e}")  # noqa: B904

        # Check if expired
        if context.is_expired():
            raise PermissionError("Token expired")

        # Authorize for skill
        if skill != "default":
            try:
                if not await self.auth_provider.authorize(context, skill):
                    raise PermissionError(f"Not authorized for skill: {skill}")
            except Exception as e:
                raise PermissionError(f"Authorization failed: {e}")  # noqa: B904

        self._auth_context = context
        return context

    def get_auth_context(self) -> AuthContext | None:
        """Get current authenticated context (NEW v0.3.0).

        Returns:
            AuthContext if authenticated, None otherwise
        """
        return self._auth_context

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

    def set_transport(self, transport):
        """Set the transport layer for this agent.

        Args:
            transport: Transport instance for communication
        """
        self._transport = transport

    async def send_task_to(self, agent_url: str, task: Task, skill: str | None = None) -> Task:
        """Send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send

        Returns:
            Task with response from target agent

        Raises:
            RuntimeError: If no transport is configured
        """
        if not self._transport:
            raise RuntimeError("No transport configured. Call set_transport() first.")

        # NEW v0.3.0: Pass skill for authorization
        if skill and hasattr(self._transport, "send_task") and hasattr(self._transport.send_task, "__code__"):
            import inspect

            sig = inspect.signature(self._transport.send_task)
            if "skill" in sig.parameters:
                return await self._transport.send_task(agent_url, task, skill=skill)

        return await self._transport.send_task(agent_url, task)

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
        if not self._transport:
            raise RuntimeError("No transport configured. Call set_transport() first.")

        return await self._transport.send_message(agent_url, message)

    def get_context_manager(self) -> ContextManager:
        """Get the context manager for this agent (NEW in v0.2.0).

        Returns:
            ContextManager instance
        """
        return self.context_manager

    def __repr__(self) -> str:
        return f"Agent(name='{self.card.name}', url='{self.card.url}')"
