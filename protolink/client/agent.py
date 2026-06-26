"""Agent Client - High-level interface for agent-to-agent and User-to-agent communication.

This module provides the `AgentClient` class, which abstracts transport details and offers convenient methods for
sending tasks, messages, and retrieving agent cards.

The client uses `ClientRequestSpec` objects to define API contracts in a transport-agnostic way. This allows the same
client code to work over HTTP, WebSocket, or any other transport.

Example:
    >>> from protolink.client import AgentClient
    >>> from protolink.models import Task
    >>>
    >>> client = AgentClient(transport="http", url="http://localhost:8000")
    >>> task = Task.create_infer(prompt="What's the weather?")
    >>> result = await client.send_task("http://localhost:8010", task)
"""

import asyncio
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any

from protolink.llms.compaction import HistoryCompactionStrategy
from protolink.models import (
    AgentCard,
    ClientRequestSpec,
    HistoryCompactionRequest,
    HistoryCompactionResult,
    Message,
    StateOperationRequest,
    StateOperationResult,
    Task,
    TaskCancellationRequest,
)
from protolink.transport import Transport, get_transport
from protolink.types import TransportType


class AgentClient:
    """High-level client for Agent-to-Agent and User-to-Agent communication.

    This client provides a unified interface for interacting with Protolink agents over different
    transports (HTTP, WebSocket, etc.).

    It exposes both:
    - Async API (recommended for modern applications)
    - Sync API (for scripts and simple usage)

    The sync API is accessible via `client.sync`.

    Architecture
    ------------
    - Async methods are the source of truth
    - Sync methods are thin wrappers over async execution
    - Transport layer is fully abstracted

    Design Philosophy
    ------------------
    This client is designed to:
    - Be transport-agnostic
    - Support both async and sync workflows
    - Keep a minimal and predictable API surface
    - Avoid exposing transport details to users

    Example
    -------
    Async usage (recommended):
        >>> client = AgentClient(transport="http", url="http://localhost:8000")
        >>> task = Task.create_infer(prompt="Hello")
        >>> result = await client.send_task("http://agent:8001", task)

    Sync usage (scripts / notebooks / CLI):
        >>> client = AgentClient(transport="http", url="http://localhost:8000")
        >>> task = Task.create_infer(prompt="Hello")
        >>> result = client.sync.send_task("http://agent:8001", task)
    """

    TASK_REQUEST = ClientRequestSpec(
        name="send_task",
        path="/tasks/",
        method="POST",
        response_parser=Task.from_dict,
        request_source="body",
    )

    AGENT_CARD_REQUEST = ClientRequestSpec(
        name="get_agent_card",
        path="/.well-known/agent.json",
        method="GET",
        response_parser=AgentCard.from_dict,
        request_source="none",
    )

    TASK_STREAM_REQUEST = ClientRequestSpec(
        name="send_task_stream",
        path="/tasks/stream",
        method="POST",
        request_source="body",
    )

    TASK_CANCEL_REQUEST = ClientRequestSpec(
        name="cancel_task",
        path="/tasks/cancel",
        method="POST",
        response_parser=Task.from_dict,
        request_source="body",
        channel="control",
    )

    COMPACT_HISTORY_REQUEST = ClientRequestSpec(
        name="compact_history",
        path="/llm/history/compact",
        method="POST",
        response_parser=HistoryCompactionResult.from_dict,
        request_source="body",
        channel="control",
    )

    DESCRIBE_STATE_REQUEST = ClientRequestSpec(
        name="describe_state",
        path="/state/describe",
        method="POST",
        response_parser=StateOperationResult.from_dict,
        request_source="body",
        channel="control",
    )

    RESET_STATE_REQUEST = ClientRequestSpec(
        name="reset_state",
        path="/state/reset",
        method="POST",
        response_parser=StateOperationResult.from_dict,
        request_source="body",
        channel="control",
    )

    COMPACT_STATE_REQUEST = ClientRequestSpec(
        name="compact_state",
        path="/state/compact",
        method="POST",
        response_parser=StateOperationResult.from_dict,
        request_source="body",
        channel="control",
    )

    def __init__(self, transport: Transport | TransportType, url: str | None = None, timeout: int = 300) -> None:
        if isinstance(transport, Transport):
            self._transport = transport
        else:
            self._transport = get_transport(transport=transport, url=url, timeout=timeout)

        self.sync = SyncAgentClient(self)

    # ----------------------------------------------------------------------
    # Agent-to-Agent Communication
    # ----------------------------------------------------------------------

    async def send_task(self, agent_url: str, task: Task) -> Task:
        """Send a task to a remote agent and return the processed result.

        This is the core communication primitive for agent-to-agent interaction.

        Args:
            agent_url: Target agent endpoint URL.
            task: Task object containing instructions or input payload.

        Returns:
            Task: Updated task containing the response from the remote agent.

        Example:
            >>> result = await client.send_task(
            ...     "http://agent:8001",
            ...     Task.create_infer(prompt="What is AI?")
            ... )
        """
        return await self._transport.send(self.TASK_REQUEST, agent_url, data=task)

    async def send_task_streaming(self, agent_url: str, task: Task) -> AsyncIterator[Any]:
        """Send a task to a remote agent and receive streamed events.

        This method is the high-level streaming entry point for agent-to-agent
        communication. It delegates to the configured transport's
        ``subscribe()`` implementation, so the same client call works with
        streaming-capable transports such as ``"sse"``, ``"json-rpc"``,
        ``"websocket"``, and ``"runtime"``.

        Args:
            agent_url: Target agent endpoint URL.
            task: Task to execute.

        Yields:
            Streaming events emitted by the remote agent. Transports may yield
            dictionaries or event objects depending on the backend.

        Raises:
            NotImplementedError: If the configured transport does not advertise
                streaming support or does not implement ``subscribe()``.

        Example:
            >>> async for event in client.send_task_streaming(url, task):
            ...     print(event)
        """
        if not getattr(self._transport, "supports_streaming", False):
            transport_name = self._transport.__class__.__name__
            raise NotImplementedError(f"{transport_name} does not support streaming")

        subscribe = getattr(self._transport, "subscribe", None)
        if subscribe is None:
            transport_name = self._transport.__class__.__name__
            raise NotImplementedError(f"{transport_name} does not implement streaming subscriptions")

        async for event in subscribe(agent_url, task):
            yield event

    async def cancel_task(
        self,
        agent_url: str,
        task_id: str,
        *,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Request best-effort cancellation of a task running on an agent.

        The task ID is known before submission because Protolink tasks are
        client-created. This allows a second coroutine, UI action, or control
        request to cancel a blocking or streaming execution already in flight.

        Args:
            agent_url: Target agent endpoint URL.
            task_id: Identifier of the active task to cancel.
            reason: Optional human-readable cancellation reason.
            metadata: Additional A2A task-ID metadata.

        Returns:
            The remote task after the cancellation attempt is accepted.

        Raises:
            RuntimeError: The remote task is unknown, terminal, or currently
                cannot be canceled.
        """
        request = TaskCancellationRequest(
            id=task_id,
            reason=reason,
            metadata=metadata or {},
        )
        return await self._transport.send(
            self.TASK_CANCEL_REQUEST,
            agent_url,
            data=request,
        )

    async def compact_history(
        self,
        agent_url: str,
        *,
        strategy: HistoryCompactionStrategy = "recent",
        max_messages: int = 20,
        max_tokens: int = 4_000,
        preserve_recent: int = 6,
        summary_max_tokens: int = 512,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HistoryCompactionResult:
        """Request LLM-history compaction from an agent control endpoint.

        This uses the transport-neutral ``COMPACT_HISTORY_REQUEST`` spec and
        calls ``POST /llm/history/compact`` on the target agent. It does not
        send a task, does not create a model-visible tool, and does not modify
        the LLM prompt.
        """
        request = HistoryCompactionRequest(
            strategy=strategy,
            max_messages=max_messages,
            max_tokens=max_tokens,
            preserve_recent=preserve_recent,
            summary_max_tokens=summary_max_tokens,
            session_id=session_id,
            metadata=metadata or {},
        )
        return await self._transport.send(
            self.COMPACT_HISTORY_REQUEST,
            agent_url,
            data=request,
        )

    async def describe_state(
        self,
        agent_url: str,
        *,
        session_id: str | None = None,
        stores: tuple[str, ...] | list[str] | None = None,
        include_data: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> StateOperationResult:
        """Describe persistent state on a remote agent."""
        request = StateOperationRequest(
            session_id=session_id,
            stores=tuple(stores or ()),
            include_data=include_data,
            metadata=metadata or {},
        )
        return await self._transport.send(
            self.DESCRIBE_STATE_REQUEST,
            agent_url,
            data=request,
        )

    async def reset_state(
        self,
        agent_url: str,
        *,
        session_id: str | None = None,
        stores: tuple[str, ...] | list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateOperationResult:
        """Reset persistent state on a remote agent."""
        request = StateOperationRequest(
            session_id=session_id,
            stores=tuple(stores or ()),
            metadata=metadata or {},
        )
        return await self._transport.send(
            self.RESET_STATE_REQUEST,
            agent_url,
            data=request,
        )

    async def compact_state(
        self,
        agent_url: str,
        *,
        session_id: str,
        strategy: HistoryCompactionStrategy = "tokens",
        max_messages: int = 20,
        max_tokens: int = 4_000,
        preserve_recent: int = 6,
        summary_max_tokens: int = 512,
        metadata: dict[str, Any] | None = None,
    ) -> StateOperationResult:
        """Compact persistent conversation state on a remote agent."""
        request = StateOperationRequest(
            session_id=session_id,
            stores=("conversation",),
            strategy=strategy,
            max_messages=max_messages,
            max_tokens=max_tokens,
            preserve_recent=preserve_recent,
            summary_max_tokens=summary_max_tokens,
            metadata=metadata or {},
        )
        return await self._transport.send(
            self.COMPACT_STATE_REQUEST,
            agent_url,
            data=request,
        )

    async def send_message(self, agent_url: str, message: Message) -> Message:
        """Send a simple message to a remote agent and return its response.

        This is a convenience wrapper over task-based communication.

        Internally:
            Message → Task → Agent execution → Response Message

        Args:
            agent_url: Target agent endpoint URL.
            message: Input message.

        Returns:
            Message: Final response message from the agent.

        Example:
            >>> response = await client.send_message(
            ...     "http://agent:8001",
            ...     Message(role="user", content="Hello")
            ... )
        """
        task = Task.create(message)
        result_task = await self.send_task(agent_url, task)
        if result_task.messages:
            return result_task.messages[-1]
        raise RuntimeError("No response messages returned by agent")

    async def get_agent_card(self, agent_url: str) -> AgentCard:
        """Retrieve the public metadata (AgentCard) of an agent.

        The AgentCard contains:
            - capabilities
            - identity
            - endpoints
            - supported features

        Args:
            agent_url: Target agent endpoint URL.

        Returns:
            AgentCard: Metadata describing the remote agent.

        Example:
            >>> card = await client.get_agent_card("http://agent:8001")
            >>> print(card.name)
        """

        return await self._transport.send(self.AGENT_CARD_REQUEST, agent_url)


# ----------------------------------------------------------------------
# Synchronous API
# ----------------------------------------------------------------------


class SyncAgentClient:
    """Synchronous wrapper around AgentClient.

    This class provides blocking equivalents of async methods
    for use in:
    - scripts
    - CLI tools
    - notebooks without async support

    Internally uses `asyncio.run()` to execute async operations.

    Warning:
        This API should NOT be used inside an active event loop
        (e.g., FastAPI, Jupyter async cells).

    Example:
        >>> client = AgentClient(transport="http", url="http://localhost:8000")
        >>> result = client.sync.send_task(url, task)
    """

    def __init__(self, async_client: AgentClient):
        self._client = async_client

    def send_task(self, agent_url: str, task: Task) -> Task:
        """Synchronously send a task to a remote agent.

        This is a blocking version of `send_task()`.

        Internally runs the async implementation in a new event loop.

        Example:
            >>> result = client.sync.send_task(
            ...     "http://agent:8001",
            ...     Task.create_infer(prompt="Hello")
            ... )
        """
        return asyncio.run(self._client.send_task(agent_url, task))

    def send_task_streaming(self, agent_url: str, task: Task) -> Iterator[Any]:
        """Synchronously stream events from a remote agent.

        This wrapper runs the async streaming API in a background thread and
        yields events to the caller as they arrive. It is useful for scripts,
        notebooks without an active event loop, and terminal UIs that want a
        blocking iterator while still using Protolink's async transports.

        Example:
            >>> for event in client.sync.send_task_streaming(url, task):
            ...     print(event)
        """
        event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        done = object()

        async def consume() -> None:
            try:
                async for event in self._client.send_task_streaming(agent_url, task):
                    event_queue.put(("event", event))
            except BaseException as exc:
                event_queue.put(("error", exc))
            finally:
                event_queue.put(("done", done))

        def runner() -> None:
            asyncio.run(consume())

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()

        while True:
            kind, payload = event_queue.get()
            if kind == "event":
                yield payload
            elif kind == "error":
                thread.join()
                if isinstance(payload, BaseException):
                    raise payload
                raise RuntimeError(f"Streaming worker failed with non-exception payload: {payload!r}")
            else:
                thread.join()
                return

    def cancel_task(
        self,
        agent_url: str,
        task_id: str,
        *,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Synchronously request cancellation of a remote active task."""
        return asyncio.run(
            self._client.cancel_task(
                agent_url,
                task_id,
                reason=reason,
                metadata=metadata,
            )
        )

    def compact_history(
        self,
        agent_url: str,
        *,
        strategy: HistoryCompactionStrategy = "recent",
        max_messages: int = 20,
        max_tokens: int = 4_000,
        preserve_recent: int = 6,
        summary_max_tokens: int = 512,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HistoryCompactionResult:
        """Synchronously request LLM-history compaction from an agent."""
        return asyncio.run(
            self._client.compact_history(
                agent_url,
                strategy=strategy,
                max_messages=max_messages,
                max_tokens=max_tokens,
                preserve_recent=preserve_recent,
                summary_max_tokens=summary_max_tokens,
                session_id=session_id,
                metadata=metadata,
            )
        )

    def describe_state(
        self,
        agent_url: str,
        *,
        session_id: str | None = None,
        stores: tuple[str, ...] | list[str] | None = None,
        include_data: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> StateOperationResult:
        """Synchronously describe persistent state on a remote agent."""
        return asyncio.run(
            self._client.describe_state(
                agent_url,
                session_id=session_id,
                stores=stores,
                include_data=include_data,
                metadata=metadata,
            )
        )

    def reset_state(
        self,
        agent_url: str,
        *,
        session_id: str | None = None,
        stores: tuple[str, ...] | list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateOperationResult:
        """Synchronously reset persistent state on a remote agent."""
        return asyncio.run(
            self._client.reset_state(
                agent_url,
                session_id=session_id,
                stores=stores,
                metadata=metadata,
            )
        )

    def compact_state(
        self,
        agent_url: str,
        *,
        session_id: str,
        strategy: HistoryCompactionStrategy = "tokens",
        max_messages: int = 20,
        max_tokens: int = 4_000,
        preserve_recent: int = 6,
        summary_max_tokens: int = 512,
        metadata: dict[str, Any] | None = None,
    ) -> StateOperationResult:
        """Synchronously compact persistent conversation state on a remote agent."""
        return asyncio.run(
            self._client.compact_state(
                agent_url,
                session_id=session_id,
                strategy=strategy,
                max_messages=max_messages,
                max_tokens=max_tokens,
                preserve_recent=preserve_recent,
                summary_max_tokens=summary_max_tokens,
                metadata=metadata,
            )
        )

    def send_message(self, agent_url: str, message: Message) -> Message:
        """Synchronously send a message to a remote agent.

        Blocking convenience wrapper for simple interactions.

        Example:
            >>> response = client.sync.send_message(
            ...     "http://agent:8001",
            ...     Message(role="user", content="Hi")
            ... )
        """
        return asyncio.run(self._client.send_message(agent_url, message))

    def get_agent_card(self, agent_url: str) -> AgentCard:
        """Synchronously retrieve an agent's metadata (AgentCard).

        Example:
            >>> card = client.sync.get_agent_card("http://agent:8001")
            >>> print(card.capabilities)
        """
        return asyncio.run(self._client.get_agent_card(agent_url))
