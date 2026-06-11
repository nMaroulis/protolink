"""
Conversation state management for ProtoLink agents.
"""

from protolink.llms.history import ConversationHistory
from protolink.storage.base import Storage


class ConversationState:
    """Manages LLM conversation state using a provided storage backend.

    This class handles loading and saving LLM conversation histories keyed by session IDs.
    It allows agents to maintain context across multiple interactions by delegating persistence to a storage backend.
    """

    def __init__(self, storage: Storage):
        """Initialize the conversation state manager.

        Args:
            storage: The storage backend used for persisting conversation histories.
        """
        self._storage = storage

    def get_history(self, session_id: str, default_system_prompt: str | None = None) -> ConversationHistory:
        """Retrieve the conversation history for a given session.

        If no history exists for the session, a new one is initialized.

        Args:
            session_id: Unique identifier for the conversation session.
            default_system_prompt: Optional system prompt to use for a new history.

        Returns:
            A ConversationHistory instance populated with stored messages, or a new one.
        """
        # Load all sessions from storage.
        # Note: Current Storage ABC is single-key, so we store a dict of all sessions.
        all_sessions = self._storage.load() or {}
        history_data = all_sessions.get(session_id)

        if history_data:
            return ConversationHistory.from_list(history_data)

        return ConversationHistory(system_prompt=default_system_prompt)

    def save_history(self, session_id: str, history: ConversationHistory):
        """Persist the conversation history for a given session.

        Args:
            session_id: Unique identifier for the conversation session.
            history: The ConversationHistory instance to be saved.
        """
        all_sessions = self._storage.load() or {}
        all_sessions[session_id] = history.to_list()
        self._storage.save(all_sessions)

    def clear_session(self, session_id: str):
        """Remove a specific conversation session from storage.

        Args:
            session_id: Unique identifier for the session to clear.
        """
        all_sessions = self._storage.load() or {}
        if session_id in all_sessions:
            del all_sessions[session_id]
            self._storage.save(all_sessions)

    def to_dict(self) -> dict:
        """Convert the conversation state to a serializable dictionary.

        Returns:
            A dictionary containing all stored conversation sessions.
        """
        return self._storage.load() or {}
