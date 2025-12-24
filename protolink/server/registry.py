"""Registry server implementation for handling incoming requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from protolink.models import AgentCard
from protolink.transport import RegistryTransport


class RegistryServer:
    """Thin wrapper that wires a task handler into a transport."""

    def __init__(
        self,
        transport: RegistryTransport,
        register_handler: Callable[[AgentCard], Awaitable[None]] | None = None,
        unregister_handler: Callable[[str], Awaitable[None]] | None = None,
        discover_handler: Callable[[dict[str, Any]], Awaitable[list[AgentCard]]] | None = None,
        status_handler: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        if transport is None:
            raise ValueError("RegistryServer requires a transport instance")

        self._transport = transport
        self._register_handler = None
        self._unregister_handler = None
        self._discover_handler = None
        self._status_handler = None
        self._is_running = False

        if register_handler is not None:
            self.set_register_handler(register_handler)

        if unregister_handler is not None:
            self.set_unregister_handler(unregister_handler)

        if discover_handler is not None:
            self.set_discover_handler(discover_handler)

        if status_handler is not None:
            self.set_status_handler(status_handler)

    def set_register_handler(self, handler: Callable[[AgentCard], Awaitable[None]]) -> None:
        """Register the coroutine used to process incoming register requests from agents."""

        self._register_handler = handler
        self._transport.on_register_received(handler)

    def set_unregister_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Register the coroutine used to process incoming unregister requests from agents."""

        self._unregister_handler = handler
        self._transport.on_unregister_received(handler)

    def set_discover_handler(self, handler: Callable[[dict[str, Any]], Awaitable[list[AgentCard]]]) -> None:
        """Register the coroutine used to process incoming discover requests from agents."""

        self._discover_handler = handler
        self._transport.on_discover_received(handler)

    def set_status_handler(self, handler: Callable[[], Awaitable[str]]) -> None:
        """Register the coroutine used to process incoming status requests from agents."""
        self._status_handler = handler
        self._transport.on_status_received(handler)

    async def start(self) -> None:
        """Start the underlying transport."""

        if self._is_running:
            return

        if not self._register_handler:
            raise RuntimeError("No register handler registered. Call set_register_handler() first.")

        if not self._unregister_handler:
            raise RuntimeError("No unregister handler registered. Call set_unregister_handler() first.")

        await self._transport.start()
        self._is_running = True

    async def stop(self) -> None:
        """Stop the underlying transport and mark the server as idle."""

        if not self._is_running:
            return

        await self._transport.stop()
        self._is_running = False
