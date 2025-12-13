"""Agent server implementation for handling incoming requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from protolink.models import Task
from protolink.transport import AgentTransport


class AgentServer:
    """Thin wrapper that wires a task handler into a transport."""

    def __init__(
        self,
        transport: AgentTransport,
        task_handler: Callable[[Task], Awaitable[Task]] | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("AgentServer requires a transport instance")

        self._transport = transport
        self._task_handler = None
        self._is_running = False

        if task_handler is not None:
            self.set_task_handler(task_handler)

    def set_task_handler(self, handler: Callable[[Task], Awaitable[Task]]) -> None:
        """Register the coroutine used to process incoming tasks."""

        self._task_handler = handler
        self._transport.on_task_received(handler)

    async def start(self) -> None:
        """Start the underlying transport."""

        if self._is_running:
            return

        if not self._task_handler:
            raise RuntimeError("No task handler registered. Call set_task_handler() first.")

        await self._transport.start()
        self._is_running = True

    async def stop(self) -> None:
        """Stop the underlying transport and mark the server as idle."""

        if not self._is_running:
            return

        await self._transport.stop()
        self._is_running = False

    def validate_agent_url(self, agent_url: str) -> None:
        """Validate the agent URL."""
        if not self._transport.validate_agent_url(agent_url):
            raise ValueError("Agent and Transport URL mismatch")
