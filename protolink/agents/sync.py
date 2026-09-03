"""Synchronous convenience facade for Agent."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Literal, TypeVar

from protolink.models import AgentCard, Task
from protolink.rag import RAGAnswer

ResultT = TypeVar("ResultT")


def _run_sync(method: Callable[..., Coroutine[Any, Any, ResultT]], /, *args: Any, **kwargs: Any) -> ResultT:
    """Run a bound async method without creating a coroutine in an active loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        name = getattr(method, "__name__", "method")
        raise RuntimeError(
            f"agent.sync.{name}() cannot run inside an active event loop. Use await agent.{name}(...) instead."
        )
    return asyncio.run(method(*args, **kwargs))


class SyncAgent:
    """Synchronous wrapper around Agent.

    This class provides blocking equivalents of async methods
    for use in:
    - scripts
    - CLI tools
    - notebooks without async support

    Internally uses `asyncio.run()` to execute async operations.

    Inside an active event loop, use the corresponding async Agent methods.
    Blocking calls detect this before creating a coroutine and raise an
    actionable ``RuntimeError`` without an unawaited-coroutine warning.
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
    ) -> Any:
        """Synchronously process a message.

        Args:
            message: User message text
            part_type: Type of part to create
            tool_name: Name of tool (if part_type is "tool_call")
            tool_args: Arguments for tool (if part_type is "tool_call")
            session_id: Conversation partition, shared by default when
                conversation state is enabled.

        Returns:
            Final response content, including ``ToolOutput`` in tool-call
            mode. Falsey values are preserved; missing content returns
            ``"No response generated"``.

        Raises:
            TaskExecutionError: The returned task failed or was canceled.
            RuntimeError: Called inside an active event loop; use
                ``await agent.invoke(...)`` instead.
        """
        return _run_sync(self._agent.invoke, message, part_type, tool_name, tool_args, session_id)

    def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Validate, authorize, and call a tool, returning its raw result.

        Args:
            tool_name: Registered tool name.
            **kwargs: Keyword arguments passed through normal tool validation
                and runtime policy authorization.

        Returns:
            The tool's return value, including ``None`` or falsey values.

        Raises:
            ValueError: The tool is not registered or arguments are invalid.
            RuntimeError: Called inside an active event loop.

        Tool, policy, and approval exceptions propagate unchanged. This direct
        call does not create a Task; use ``run_task`` for task state and durable
        task snapshots.
        """
        return _run_sync(self._agent.call_tool, tool_name, **kwargs)

    def run_task(self, task: Task) -> Task:
        """Run a complete task with cancellation control and persistence.

        Args:
            task: Task passed to the Agent's configured handler.

        Returns:
            The full task, including state, artifacts, and error metadata.
            Returned failed or canceled tasks remain inspectable; call
            ``result.raise_for_status()`` to turn them into exceptions.

        Raises:
            RuntimeError: Called inside an active event loop.

        Exceptions raised by the handler propagate unchanged after the failed
        task snapshot is offered to the configured run store.
        """
        return _run_sync(self._agent.run_task, task)

    def ask(
        self,
        question: str,
        *,
        knowledge: str | list[str] | tuple[str, ...] | None = None,
        k: int | None = None,
        where: dict[str, Any] | None = None,
        citations: bool = True,
        session_id: str = "ask_session_id",
    ) -> RAGAnswer:
        """Retrieve knowledge and answer through the normal task lifecycle.

        Arguments and results match :meth:`Agent.ask`. Returned failed or
        canceled tasks raise ``TaskExecutionError``. Inside an active event
        loop, use ``await agent.ask(...)`` instead.
        """
        return _run_sync(
            self._agent.ask,
            question,
            knowledge=knowledge,
            k=k,
            where=where,
            citations=citations,
            session_id=session_id,
        )

    def discover_agents(self, filter_by: dict[str, Any] | None = None) -> list[AgentCard]:
        """Synchronously discover agents in the registry.

        Args:
            filter_by: Optional filter criteria

        Returns:
            List of matching AgentCard objects
        """
        return _run_sync(self._agent.discover_agents, filter_by)

    def call_agent(
        self,
        agent_url: str,
        task: Task,
        *,
        protocol: Literal["auto", "protolink", "a2a"] = "auto",
    ) -> Task:
        """Synchronously send a task to another agent.

        Args:
            agent_url: URL of the target agent
            task: Task to send
            protocol: Native/A2A protocol selection, matching ``Agent.call_agent``.

        Returns:
            Task with updated state and response messages
        """
        return _run_sync(self._agent.call_agent, agent_url, task, protocol=protocol)

    def cancel_task(self, task_id: str, reason: str | None = None) -> Task:
        """Synchronously request cancellation of an active local task.

        The active task must be running on another coroutine or Agent background loop; a synchronous caller cannot
        cancel work while blocked inside that same call stack.
        """
        return _run_sync(self._agent.cancel_task, task_id, reason)
