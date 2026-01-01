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

        if not agent_card.description or not isinstance(agent_card.description, str):
            return False, "Agent description is required and must be a string"

        if not agent_card.url or not isinstance(agent_card.url, str):
            return False, "Agent URL is required and must be a string"

        if not agent_card.version or not isinstance(agent_card.version, str):
            return False, "Agent version is required and must be a string"

        if not agent_card.protocol_version or not isinstance(agent_card.protocol_version, str):
            return False, "Agent protocol version is required and must be a string"

        # Validate capabilities
        if not isinstance(agent_card.capabilities, object):
            return False, "Agent capabilities are required"

        return True, ""

    @classmethod
    def validate_message(cls, message: Message) -> tuple[bool, str]:
        """Validate a Message object.

        Args:
            message: Message to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not message.id or not cls._is_valid_uuid(message.id):
            return False, "Message ID is required and must be a valid UUID"

        if not message.role or not isinstance(message.role, str):
            return False, "Message role is required and must be a string"

        if not message.parts or not isinstance(message.parts, list):
            return False, "Message parts are required and must be a list"

        if not message.timestamp or not isinstance(message.timestamp, str):
            return False, "Message timestamp is required and must be a string"

        return True, ""

    @classmethod
    def validate_task(cls, task: Task) -> tuple[bool, str]:
        """Validate a Task object.

        Args:
            task: Task to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not task.id or not cls._is_valid_uuid(task.id):
            return False, "Task ID is required and must be a valid UUID"

        if not task.state or not isinstance(task.state, str):
            return False, "Task state is required and must be a string"

        if not task.messages or not isinstance(task.messages, list):
            return False, "Task messages are required and must be a list"

        if not task.artifacts or not isinstance(task.artifacts, list):
            return False, "Task artifacts are required and must be a list"

        if not task.metadata or not isinstance(task.metadata, dict):
            return False, "Task metadata are required and must be a dict"

        return True, ""

    @classmethod
    def validate_task_id(cls, task_id: str) -> tuple[bool, str]:
        """Validate a task ID.

        Args:
            task_id: Task ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not task_id or not cls._is_valid_uuid(task_id):
            return False, "Task ID must be a valid UUID"
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
