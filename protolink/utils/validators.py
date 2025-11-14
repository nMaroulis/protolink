"""Validation utilities for Protolink.

This module provides validation functions for Protolink objects and identifiers.
"""

import re
import uuid

from protolink.core.agent_card import AgentCard
from protolink.core.message import Message
from protolink.core.task import Task


class Validator:
    """Validation helper class for Protolink objects and identifiers."""

    # Regex patterns for validation
    ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
    CONTEXT_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,128}$"

    @classmethod
    def validate_agent_card(cls, agent_card: AgentCard) -> tuple[bool, str]:
        """Validate an AgentCard object.

        Args:
            agent_card: AgentCard to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not agent_card.name or not isinstance(agent_card.name, str):
            return False, "Agent name is required and must be a string"

        if not agent_card.id or not cls._is_valid_uuid(agent_card.id):
            return False, "Agent ID is required and must be a valid UUID"

        if not agent_card.version or not isinstance(agent_card.version, str):
            return False, "Agent version is required and must be a string"

        return True, ""

    @classmethod
    def validate_message(cls, message: Message) -> tuple[bool, str]:
        """Validate a Message object.

        Args:
            message: Message to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not message.message_id or not cls._is_valid_id(message.message_id):
            return (
                False,
                "Message ID is required and must be alphanumeric with underscores or hyphens",
            )

        if not message.role or not isinstance(message.role, str):
            return False, "Message role is required and must be a string"

        if message.context_id and not cls._is_valid_context_id(message.context_id):
            return False, "Invalid context ID format"

        return True, ""

    @classmethod
    def validate_task(cls, task: Task) -> tuple[bool, str]:
        """Validate a Task object.

        Args:
            task: Task to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not task.id or not cls._is_valid_id(task.id):
            return (
                False,
                "Task ID is required and must be alphanumeric with underscores or hyphens",
            )

        if not task.task_type or not isinstance(task.task_type, str):
            return False, "Task type is required and must be a string"

        if task.context_id and not cls._is_valid_context_id(task.context_id):
            return False, "Invalid context ID format"

        return True, ""

    @classmethod
    def validate_task_id(cls, task_id: str) -> tuple[bool, str]:
        """Validate a task ID.

        Args:
            task_id: Task ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not task_id or not cls._is_valid_id(task_id):
            return False, "Task ID must be alphanumeric with underscores or hyphens"
        return True, ""

    @classmethod
    def validate_context_id(cls, context_id: str) -> tuple[bool, str]:
        """Validate a context ID.

        Args:
            context_id: Context ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not context_id or not cls._is_valid_context_id(context_id):
            return False, "Context ID must be alphanumeric with underscores or hyphens"
        return True, ""

    @classmethod
    def _is_valid_id(cls, id_str: str) -> bool:
        """Check if a string is a valid ID."""
        return bool(re.match(cls.ID_PATTERN, id_str))

    @classmethod
    def _is_valid_context_id(cls, context_id: str) -> bool:
        """Check if a string is a valid context ID."""
        return bool(re.match(cls.CONTEXT_ID_PATTERN, context_id))

    @staticmethod
    def _is_valid_uuid(uuid_str: str) -> bool:
        """Check if a string is a valid UUID."""
        try:
            uuid.UUID(uuid_str)
            return True
        except (ValueError, TypeError):
            return False
