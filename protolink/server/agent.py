"""
Agent server implementation responsible for exposing an agent over a transport.

The AgentServer acts as a thin coordination layer between:
- an Agent (business logic)
- a Transport (HTTP, WS, etc.)

It does **not** implement networking itself. Instead, it:
- declares the agent-facing endpoints
- binds agent handlers to transport routes
- manages the server lifecycle
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from protolink.models import (
    AgentCard,
    HistoryCompactionRequest,
    HistoryCompactionResult,
    Task,
    TaskCancellationRequest,
)
from protolink.server.endpoint_handler import EndpointSpec
from protolink.state.operations import StateOperationRequest, StateOperationResult
from protolink.transport import Transport


class AgentInterface(Protocol):
    """Public interface an Agent must implement to be served.

    This protocol defines the minimal surface required by an AgentServer.
    Agents are not required to inherit from this protocol explicitly;
    structural typing (duck typing) is sufficient.
    """

    async def handle_task(self, task: Task) -> Task:
        """Handle an incoming task and return the updated task."""

    async def run_task(self, task: Task) -> Task:
        """Run the task handler under live cancellation control."""

    def handle_task_streaming(self, task: Task) -> AsyncIterator[Any]:
        """Stream task events."""

    def run_task_streaming(self, task: Task) -> AsyncIterator[Any]:
        """Stream the task handler under live cancellation control."""

    async def cancel_task(self, request: TaskCancellationRequest) -> Task:
        """Request cancellation of an active task."""

    async def compact_history(self, request: HistoryCompactionRequest) -> HistoryCompactionResult:
        """Compact the agent's LLM conversation history."""

    async def describe_state(self, request: StateOperationRequest) -> StateOperationResult:
        """Describe the agent's persistent state."""

    async def reset_state(self, request: StateOperationRequest) -> StateOperationResult:
        """Reset the agent's persistent state."""

    async def compact_state(self, request: StateOperationRequest) -> StateOperationResult:
        """Compact the agent's persistent conversation state."""

    def get_agent_card(self, *, as_json: bool = True) -> AgentCard | dict[str, Any]:
        """Return the agent's public metadata and capabilities."""

    def get_status(self, output_format: Literal["html", "json"] = "html") -> str:
        """Return the agent's status as HTML or JSON."""

    def get_chat(self) -> str:
        """Return the chat UI page as HTML."""

    async def handle_chat_message(self, data: dict[str, Any]) -> dict[str, str]:
        """Handle an incoming chat message and return the response."""


class AgentServer:
    """Binds an agent implementation to a transport.

    The AgentServer is responsible for:
    - defining the HTTP (or transport-specific) endpoints
    - wiring agent handlers to those endpoints
    - starting and stopping the underlying transport

    It intentionally contains no transport-specific or agent-specific logic.
    """

    def __init__(self, transport: Transport, agent: AgentInterface) -> None:
        if transport is None:
            raise ValueError("AgentServer requires a transport instance")

        self._transport = transport
        self._agent = agent
        self._is_running = False

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def _build_endpoints(self) -> None:
        """Register agent endpoints with the transport.

        This method declares the public API surface of the agent and binds each
        endpoint to the corresponding agent handler. Streaming endpoints are
        registered only when the chosen transport advertises
        ``supports_streaming=True``.
        """

        endpoints = [
            EndpointSpec(
                name="task",
                path="/tasks/",
                method="POST",
                handler=self._agent.run_task,
                request_source="body",
                request_parser=Task.from_dict,
            ),
            EndpointSpec(
                name="task_cancel",
                path="/tasks/cancel",
                method="POST",
                handler=self._agent.cancel_task,
                request_source="body",
                request_parser=TaskCancellationRequest.from_dict,
            ),
            EndpointSpec(
                name="compact_history",
                path="/llm/history/compact",
                method="POST",
                handler=self._agent.compact_history,
                request_source="body",
                request_parser=HistoryCompactionRequest.from_dict,
            ),
            EndpointSpec(
                name="describe_state",
                path="/state/describe",
                method="POST",
                handler=self._agent.describe_state,
                request_source="body",
                request_parser=StateOperationRequest.from_dict,
            ),
            EndpointSpec(
                name="reset_state",
                path="/state/reset",
                method="POST",
                handler=self._agent.reset_state,
                request_source="body",
                request_parser=StateOperationRequest.from_dict,
            ),
            EndpointSpec(
                name="compact_state",
                path="/state/compact",
                method="POST",
                handler=self._agent.compact_state,
                request_source="body",
                request_parser=StateOperationRequest.from_dict,
            ),
            EndpointSpec(
                name="agent_card",
                path="/.well-known/agent.json",
                method="GET",
                handler=self._agent.get_agent_card,
                request_source="none",
            ),
            EndpointSpec(
                name="status",
                path="/status",
                method="GET",
                handler=self._agent.get_status,
                request_source="none",
                content_type="html",
            ),
            EndpointSpec(
                name="health",
                path="/healthz",
                method="GET",
                handler=self._transport.health,
                request_source="none",
            ),
            EndpointSpec(
                name="readiness",
                path="/readyz",
                method="GET",
                handler=self._transport.health,
                request_source="none",
            ),
            EndpointSpec(
                name="chat_page",
                path="/chat",
                method="GET",
                handler=self._agent.get_chat,
                request_source="none",
                content_type="html",
            ),
        ]

        if getattr(self._transport, "supports_streaming", False):
            endpoints.append(
                EndpointSpec(
                    name="task_stream",
                    path="/tasks/stream",
                    method="POST",
                    handler=self._agent.run_task_streaming,
                    request_source="body",
                    request_parser=Task.from_dict,
                    streaming=True,
                    mode="stream",
                )
            )

        self._transport.setup_routes(endpoints)

        # ── Chat endpoints (only when the agent has an LLM) ──
        has_llm = bool(getattr(self._agent, "llm", None))
        if not has_llm:
            card = getattr(self._agent, "card", None)
            has_llm = bool(card and getattr(getattr(card, "capabilities", None), "has_llm", False))
        if has_llm:
            chat_endpoints = [
                EndpointSpec(
                    name="chat_message",
                    path="/chat",
                    method="POST",
                    handler=self._agent.handle_chat_message,
                    request_source="body",
                ),
            ]
            self._transport.setup_routes(chat_endpoints)

    async def start(self) -> None:
        """Start the agent server.

        This will:
        1. Register all agent endpoints with the transport
        2. Start the underlying transport server

        Calling this method multiple times is safe.
        """

        if self._is_running:
            return

        self._build_endpoints()
        await self._transport.start()
        self._is_running = True

    async def stop(self) -> None:
        """Stop the agent server.

        Shuts down the underlying transport and marks the server as inactive.
        Calling this method when the server is not running is a no-op.
        """

        if not self._is_running:
            return

        await self._transport.stop()
        self._is_running = False
