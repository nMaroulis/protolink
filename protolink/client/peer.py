"""A bound remote agent with the same small calling interface as a local agent."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from protolink.core.agent_card import AgentCard
from protolink.core.invocation import prepare_task, response_content
from protolink.core.run_context import RunBudget, RunContext
from protolink.core.task import Task

if TYPE_CHECKING:
    from protolink.client.agent import AgentClient
    from protolink.client.registry import RegistryClient

ResponseT = TypeVar("ResponseT")


class AgentPeer:
    """Bind a URL, AgentCard, or unique registry name to an existing client.

    Obtain peers from ``agent.peer(target)`` or ``client.peer(target)``. Binding
    performs no I/O. Names resolve on every call so registry changes are visible;
    zero or multiple matches raise ValueError. URLs and cards need no registry.
    Credentials, transport settings, and A2A opt-in come from the owning client.
    """

    def __init__(
        self,
        client: AgentClient,
        target: str | AgentCard,
        *,
        registry: RegistryClient | None = None,
        protocol: Literal["auto", "protolink", "a2a"] = "auto",
        sender: Callable[..., Awaitable[Task]] | None = None,
    ) -> None:
        self.client, self.target, self.registry = client, target, registry
        self.protocol = protocol
        self._send = sender or client.send_task
        self.sync = SyncAgentPeer(self)

    async def _url(self) -> str:
        if isinstance(self.target, AgentCard):
            return self.target.url
        if "://" in self.target:
            return self.target
        if self.registry is None:
            raise ValueError("A peer name requires a registry; pass a URL or AgentCard instead")
        matches = [card for card in await self.registry.discover({"name": self.target}) if card.name == self.target]
        if len(matches) != 1:
            raise ValueError(f"Expected one peer named {self.target!r}; found {len(matches)}")
        return matches[0].url

    async def run_task(self, task: Task) -> Task:
        """Submit once and return the full task, including failed or incomplete states.

        Configure task context directly for full control. Transport and provider
        errors propagate; this facade never resubmits a failed request.
        """
        return await self._send(await self._url(), task, protocol=self.protocol)

    async def invoke(
        self,
        message: str,
        *,
        session_id: str | None = None,
        budget: RunBudget | None = None,
        context: RunContext | None = None,
    ) -> Any:
        """Infer remotely and return new response content, preserving falsey values.

        Controls follow Agent.invoke: explicit session/budget override a copied
        context. Failed or canceled tasks raise TaskExecutionError. Budgets travel
        with native ProtoLink tasks; A2A-only peers do not implement these controls.
        """
        task = prepare_task(
            Task.create_infer(prompt=message),
            session_id=session_id,
            budget=budget,
            context=context,
            default_session_id="invocation_session_id",
        )
        request_ids = {item.id for item in (*task.messages, *task.artifacts)}
        result = (await self.run_task(task)).raise_for_status()
        content = response_content(result, request_ids)
        return content if content is not None else "No response generated"

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a native peer's tool and return its raw result.

        Keyword arguments belong exclusively to the tool. Use run_task with an
        explicit context for per-call controls. Validation and authorization run
        on the receiving agent; failed/canceled tasks raise TaskExecutionError.
        A2A-only peers do not support ProtoLink tool-call tasks.
        """
        task = Task.create_tool_call(tool_name=tool_name, args=kwargs)
        request_ids = {item.id for item in task.messages}
        result = (await self.run_task(task)).raise_for_status()
        item = result.get_last_item()
        if item is None or item.id in request_ids or not item.parts or item.parts[-1].type != "tool_output":
            raise ValueError("Peer returned no tool output; inspect run_task() for custom responses")
        return item.parts[-1].as_tool_output().result

    async def invoke_typed(
        self,
        message: str,
        response_model: type[ResponseT],
        *,
        max_attempts: int = 1,
        session_id: str | None = None,
        budget: RunBudget | None = None,
        context: RunContext | None = None,
    ) -> ResponseT:
        """Validate a remote JSON answer, with Agent.invoke_typed's explicit repair rules.

        Each repair is a new task submission and may repeat tools. Remote budget
        counters are not globally shared; max_attempts bounds submissions and the
        local wall-clock budget bounds the complete call. Transport failures and
        incomplete tasks never trigger repair.
        """
        from protolink.flows.responses import invoke_typed

        return await invoke_typed(
            self.run_task,
            message,
            response_model,
            max_attempts=max_attempts,
            session_id=session_id,
            budget=budget,
            context=context,
        )


class SyncAgentPeer:
    """Blocking peer calls for scripts without an active asyncio loop."""

    def __init__(self, peer: AgentPeer) -> None:
        self._peer = peer

    @staticmethod
    def _run(method: Callable[..., Awaitable[ResponseT]], /, *args: Any, **kwargs: Any) -> ResponseT:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use await peer methods inside an active event loop")

        async def call() -> ResponseT:
            return await method(*args, **kwargs)

        return asyncio.run(call())

    def invoke(
        self,
        message: str,
        *,
        session_id: str | None = None,
        budget: RunBudget | None = None,
        context: RunContext | None = None,
    ) -> Any:
        """Blocking AgentPeer.invoke with identical results and run controls."""
        return self._run(self._peer.invoke, message, session_id=session_id, budget=budget, context=context)

    def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Blocking AgentPeer.call_tool; all keyword arguments are tool arguments."""
        return self._run(self._peer.call_tool, tool_name, **kwargs)

    def run_task(self, task: Task) -> Task:
        """Blocking AgentPeer.run_task, retaining the full task and its status."""
        return self._run(self._peer.run_task, task)

    def invoke_typed(
        self,
        message: str,
        response_model: type[ResponseT],
        *,
        max_attempts: int = 1,
        session_id: str | None = None,
        budget: RunBudget | None = None,
        context: RunContext | None = None,
    ) -> ResponseT:
        """Blocking AgentPeer.invoke_typed with the same explicit repair limit."""
        return self._run(
            self._peer.invoke_typed,
            message,
            response_model,
            max_attempts=max_attempts,
            session_id=session_id,
            budget=budget,
            context=context,
        )
