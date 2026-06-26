"""Synchronous convenience facade for Agent."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from protolink.models import AgentCard, Task


class SyncAgent:
    """Synchronous wrapper around Agent.

    This class provides blocking equivalents of async methods
    for use in:
    - scripts
    - CLI tools
    - notebooks without async support

    Internally uses `asyncio.run()` to execute async operations.

    Warning:
        This API should NOT be used inside an active event loop.
    """

    def __init__(self, agent: Any):
        self._agent = agent

    def invoke(
        self,
        message: str,
        part_type: Literal["tool_call", "infer"] = "infer",
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        session_id: str = "invocation_session_id",
    ) -> str:
        """Synchronously process a message.

        Args:
            message: User message text
            part_type: Type of part to create
            tool_name: Name of tool (if part_type is "tool_call")
            tool_args: Arguments for tool (if part_type is "tool_call")
            session_id: Session ID to use for the task

        Returns:
            Agent response text
        """
        return asyncio.run(self._agent.invoke(message, part_type, tool_name, tool_args, session_id))

    def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Synchronously discover agents in the registry.

        Args:
            filter_by: Optional filter criteria

        Returns:
            List of matching AgentCard objects
        """
        return asyncio.run(self._agent.discover_agents(filter_by))

    def call_agent(self, agent_url: str, task: Task) -> Task:
        """Synchronously send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send

        Returns:
            Task with updated state and response messages
        """
        return asyncio.run(self._agent.call_agent(agent_url, task))

    def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
        """Synchronously request cancellation of an active local task.

        The active task must be running on another coroutine or Agent background
        loop; a synchronous caller cannot cancel work while blocked inside that
        same call stack.
        """
        return asyncio.run(self._agent.cancel_task(task_id, reason))
