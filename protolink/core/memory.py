from protolink.llms.history import ConversationHistory
from protolink.storage.base import Storage
from protolink.types import MemoryModeType


class SessionManager:
    """Manages agent conversation sessions using a provided storage backend.

    This class handles the logic of loading and saving conversation histories
    keyed by session IDs. It allows agents to remain stateless while delegating
    persistence to this component.
    """

    def __init__(self, storage: Storage, memory_mode: MemoryModeType = "none"):
        """Initialize the session manager.

        Args:
            storage: The storage backend to use for persisting sessions.
            memory_mode: The memory persistence mode ("none" or "session").
        """
        self.storage = storage
        self.memory_mode = memory_mode

    def get_history(self, session_id: str, default_system_prompt: str | None = None) -> ConversationHistory:
        """Retrieve the conversation history for a given session.

        If no history exists for the session, a new one is created with the
        provided system prompt.

        Args:
            session_id: Unique identifier for the session.
            default_system_prompt: The system prompt to use if a new history is created.

        Returns:
            The ConversationHistory instance for the session.
        """
        if self.memory_mode == "none":
            return ConversationHistory(system_prompt=default_system_prompt)

        # Load all sessions from storage.
        # Note: Current Storage ABC is single-key, so we store a dict of all sessions.
        all_sessions = self.storage.load() or {}
        history_data = all_sessions.get(session_id)

        if history_data:
            return ConversationHistory.from_list(history_data)

        return ConversationHistory(system_prompt=default_system_prompt)

    def save_history(self, session_id: str, history: ConversationHistory):
        """Save the conversation history for a given session.

        Args:
            session_id: Unique identifier for the session.
            history: The ConversationHistory instance to save.
        """
        if self.memory_mode == "none":
            return

        all_sessions = self.storage.load() or {}
        all_sessions[session_id] = history.to_list()
        self.storage.save(all_sessions)

    def clear_session(self, session_id: str):
        """Remove a session from storage.

        Args:
            session_id: Unique identifier for the session.
        """
        if self.memory_mode == "none":
            return

        all_sessions = self.storage.load() or {}
        if session_id in all_sessions:
            del all_sessions[session_id]
            self.storage.save(all_sessions)
