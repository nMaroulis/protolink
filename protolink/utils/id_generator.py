"""ID generation utilities for Protolink.

This module provides functions for generating various types of IDs used in Protolink.
"""

import uuid
from datetime import datetime, timezone
from typing import ClassVar


class IDGenerator:
    """ID generation helper class for Protolink."""

    # Prefixes for different ID types
    MSG_PREFIX: ClassVar[str] = "msg_"
    TASK_PREFIX: ClassVar[str] = "task_"
    CTX_PREFIX: ClassVar[str] = "ctx_"
    ARTIFACT_PREFIX: ClassVar[str] = "art_"
    TOOL_CALL_PREFIX: ClassVar[str] = "tool_call_"
    TOOL_OUTPUT_PREFIX: ClassVar[str] = "tool_output_"

    @staticmethod
    def generate_uuid() -> str:
        """Generate a UUID4 string.

        Returns:
            A UUID4 string
        """
        return str(uuid.uuid4())

    @classmethod
    def generate_message_id(cls, prefix: str | None = None) -> str:
        """Generate a message ID with optional prefix.

        Args:
            prefix: Optional prefix for the ID (default: 'msg_')

        Returns:
            A unique message ID string
        """
        prefix = prefix or cls.MSG_PREFIX
        return f"{prefix}{IDGenerator._generate_timestamp()}_{uuid.uuid4().hex[:8]}"

    @classmethod
    def generate_task_id(cls, prefix: str | None = None) -> str:
        """Generate a task ID with optional prefix.

        Args:
            prefix: Optional prefix for the ID (default: 'task_')

        Returns:
            A unique task ID string
        """
        prefix = prefix or cls.TASK_PREFIX
        return f"{prefix}{IDGenerator._generate_timestamp()}_{uuid.uuid4().hex[:8]}"

    @classmethod
    def generate_context_id(cls, prefix: str | None = None) -> str:
        """Generate a context ID with optional prefix.

        Args:
            prefix: Optional prefix for the ID (default: 'ctx_')

        Returns:
            A unique context ID string
        """
        prefix = prefix or cls.CTX_PREFIX
        return f"{prefix}{IDGenerator._generate_timestamp()}_{uuid.uuid4().hex[:6]}"

    @classmethod
    def generate_artifact_id(cls, prefix: str | None = None) -> str:
        """Generate an artifact ID with optional prefix.

        Args:
            prefix: Optional prefix for the ID (default: 'art_')

        Returns:
            A unique artifact ID string
        """
        prefix = prefix or cls.ARTIFACT_PREFIX
        return f"{prefix}{IDGenerator._generate_timestamp()}_{uuid.uuid4().hex[:8]}"

    @classmethod
    def generate_tool_call_id(cls, prefix: str | None = None) -> str:
        """Generate a tool call ID with optional prefix.

        Args:
            prefix: Optional prefix for the ID (default: 'tool_call_')

        Returns:
            A unique tool call ID string
        """
        prefix = prefix or cls.TOOL_CALL_PREFIX
        return f"{prefix}{IDGenerator._generate_timestamp()}_{uuid.uuid4().hex[:8]}"

    @classmethod
    def generate_tool_output_id(cls, prefix: str | None = None) -> str:
        """Generate a tool output ID with optional prefix.

        Args:
            prefix: Optional prefix for the ID (default: 'tool_output_')

        Returns:
            A unique tool output ID string
        """
        prefix = prefix or cls.TOOL_OUTPUT_PREFIX
        return f"{prefix}{IDGenerator._generate_timestamp()}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _generate_timestamp() -> str:
        """Generate a timestamp string in a compact format."""
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
