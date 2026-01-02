import uuid

from protolink.core.context import Context
from protolink.utils.datetime import utc_now


class ContextManager:
    """Manages conversation contexts and their lifecycles.

    The ContextManager maintains active contexts, allowing agents to:
    - Track multi-turn conversations
    - Persist messages across requests
    - Share context across multiple agents
    - Clean up expired contexts

    Example:
        manager = ContextManager()
        context = manager.create_context()
        manager.add_message_to_context(context.context_id, message)
        context = manager.get_context(context.context_id)
    """

    def __init__(self):
        """Initialize the context manager."""
        self.contexts: dict[str, Context] = {}

    def create_context(self, context_id: str | None = None) -> Context:
        """Create a new context.

        Args:
            context_id: Optional specific ID (auto-generated if not provided)

        Returns:
            Newly created Context
        """
        if not context_id:
            context_id = str(uuid.uuid4())

        context = Context(context_id=context_id)
        self.contexts[context_id] = context
        return context

    def get_context(self, context_id: str) -> Context | None:
        """Retrieve an existing context.

        Args:
            context_id: ID of context to retrieve

        Returns:
            Context if found, None otherwise
        """
        context = self.contexts.get(context_id)
        if context:
            context.last_accessed = str(utc_now())
        return context

    def add_message_to_context(self, context_id: str, message) -> bool:
        """Add a message to an existing context.

        Args:
            context_id: ID of target context
            message: Message to add

        Returns:
            True if added, False if context not found
        """
        if context := self.get_context(context_id):
            context.add_message(message)
            return True
        return False

    def delete_context(self, context_id: str) -> bool:
        """Remove a context.

        Args:
            context_id: ID of context to delete

        Returns:
            True if deleted, False if not found
        """
        if context_id in self.contexts:
            del self.contexts[context_id]
            return True
        return False

    def list_contexts(self) -> list[Context]:
        """List all active contexts.

        Returns:
            List of all Context objects
        """
        return list(self.contexts.values())

    def clear_all(self) -> None:
        """Remove all contexts."""
        self.contexts.clear()

    def get_context_message_count(self, context_id: str) -> int:
        """Get message count for a context.

        Args:
            context_id: ID of context

        Returns:
            Number of messages, 0 if context not found
        """
        if context := self.get_context(context_id):
            return len(context.messages)
        return 0

    def __repr__(self) -> str:
        return f"ContextManager(contexts={len(self.contexts)})"
