"""Owned local child runs using ordinary Agents and the existing delegation contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from protolink.core.actions import RunAction
from protolink.core.budget import BudgetEnforcer
from protolink.core.cancellation import mark_task_canceled
from protolink.core.delegation import DelegationRecorder
from protolink.core.durable import DurableExecutionError, RunInterruption, _SuspendRun, current_durable_run
from protolink.core.execution import execution_scope, shared_budget_scope
from protolink.core.policy import inherited_policy_scope
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState
from protolink.tools import Tool


class SubagentLimitError(RuntimeError):
    """Child count, depth or nested concurrency would exceed configured limits."""


@dataclass(frozen=True)
class SubagentLimits:
    """Run-tree limits; background model tools are an explicit opt-in.

    ``max_children`` bounds total children, including queued and completed work.
    ``max_concurrency`` bounds simultaneously running child tasks. Depth one
    permits direct children. Children share root budgets and ancestor policies.
    """

    max_children: int = 8
    max_concurrency: int = 4
    max_depth: int = 1
    background: bool = False

    def __post_init__(self) -> None:
        for name in ("max_children", "max_concurrency", "max_depth"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.background, bool):
            raise TypeError("background must be a bool")


class SubagentHandle:
    """A child owned by its parent's run; await its Task or request cancellation."""

    def __init__(self, task: Task, worker: asyncio.Task[Task]) -> None:
        self.task = task
        self._worker = worker
        self.id = task.id
        self.run_id = RunContext.from_task(task).run_id

    async def result(self) -> Task:
        """Await the child without a cancelled waiter orphaning or cancelling it."""
        return await asyncio.shield(self._worker)

    async def cancel(self, reason: str = "Parent cancelled child") -> None:
        """Cancel and drain cooperative work; external effects may already exist."""
        self._worker.cancel(reason)
        await asyncio.gather(self._worker, return_exceptions=True)
        if not self.task.is_terminal:
            mark_task_canceled(self.task, reason)


_active: ContextVar[SubagentSupervisor | None] = ContextVar("protolink_subagent_supervisor", default=None)


class SubagentSupervisor:
    """One run's roster and handles, sharing limits/accounting with ancestors."""

    def __init__(self, agent: Any, task: Task, budget: BudgetEnforcer) -> None:
        self.agent = agent
        self.task = task
        self.context = RunContext.from_task(task)
        self.budget = budget
        self.parent = _active.get()
        self.root = self.parent.root if self.parent is not None else self
        self.depth = self.parent.depth + 1 if self.parent is not None else 0
        self.handles: dict[str, SubagentHandle] = {}
        self.closed = False
        if self.root is self:
            self.limits = agent.subagent_limits
            self.semaphore = asyncio.Semaphore(self.limits.max_concurrency)
            durable = current_durable_run()
            self.count = durable.data.get("subagent_count", 0) if durable is not None else 0
            self.running = 0

    async def spawn(
        self,
        name: str,
        prompt: str,
        *,
        action: str = "infer",
        arguments: dict[str, Any] | None = None,
        action_id: str | None = None,
        blocking: bool = False,
    ) -> SubagentHandle:
        if self.closed:
            raise RuntimeError("The parent run has ended")
        child = self.agent.subagents.get(name)
        if child is None:
            raise ValueError(f"Unknown local subagent '{name}'")
        if name.casefold() in {item.casefold() for item in self.context.agent_chain}:
            raise ValueError("Local delegation would create an ancestor cycle")
        limits = self.root.limits
        if self.depth + 1 > limits.max_depth:
            raise SubagentLimitError("Subagent nesting depth exceeded")
        if self.depth and self.root.running >= limits.max_concurrency:
            raise SubagentLimitError("Nested delegation has no free child slot; increase max_concurrency")
        durable = current_durable_run()
        if child.durability is not None and durable is None:
            raise DurableExecutionError("A durable local child requires a durable parent run")
        if (durable is not None or self.agent.durability is not None) and not blocking:
            raise DurableExecutionError(
                "Durable runs support blocking local delegation; background children are live-only"
            )
        if action not in {"infer", "tool_call"}:
            raise ValueError("Subagent action must be infer or tool_call")
        if action == "infer" and (not isinstance(prompt, str) or not prompt.strip()):
            raise ValueError("Subagent prompt must be nonblank text")
        if action_id is None:
            authorization = await self.agent.authorize_action(
                RunAction(
                    kind="agent.call",
                    name=name,
                    capabilities=frozenset({"agent.delegate"}),
                    payload={"action": action, "prompt": prompt, "arguments": arguments or {}},
                ),
                self.context,
            )
            action_id = authorization.action.action_id
        saved_child = durable.entry.get("child_task") if durable is not None and durable.entry is not None else None
        if saved_child is None and self.root.count >= limits.max_children:
            raise SubagentLimitError("Total subagent count exceeded")
        if saved_child is not None:
            assert durable is not None
            task = Task.from_dict(saved_child)
            record = durable.store.get(RunContext.from_task(task).run_id)
            if record is not None:
                task = Task.from_dict(record.data["task"])
                if record.status == "ready" and task.state in {TaskState.FAILED, TaskState.CANCELED}:
                    task.state = TaskState.WORKING
                    task.metadata.pop("error", None)
                    task.metadata.pop("cancel_reason", None)
        else:
            # Reserve the tree count before committing the child pointer.
            # Recovery must never find a created child absent from root limits.
            self.root.count += 1
            if durable is not None:
                durable.root.data["subagent_count"] = self.root.count
                durable.root.save()
            task = Task.create_infer(prompt) if action == "infer" else Task.create_tool_call(prompt, arguments or {})
            context = self.context.child(agent_name=name)
            # Context independence is separate from filesystem/credential isolation.
            context.session_id = context.run_id
            context.attach_to_task(task)
            if durable is not None:
                assert durable.entry is not None
                durable.entry["child_task"] = task.to_dict()
                durable.save()
        context = RunContext.from_task(task)
        recorder = DelegationRecorder(self.task, context, action_id)

        async def run_child() -> Task:
            token = _active.set(self)
            try:
                async with self.root.semaphore:
                    self.root.running += 1
                    try:
                        with (
                            execution_scope(task, recorder),
                            shared_budget_scope(self.budget),
                            inherited_policy_scope(self.agent.action_authorizer.policy),
                        ):
                            result = task if task.is_terminal else await child.run_task(task)
                        return result
                    finally:
                        self.root.running -= 1
            finally:
                try:
                    await recorder.capture(task)
                finally:
                    _active.reset(token)

        handle = SubagentHandle(task, asyncio.create_task(run_child()))
        self.handles[handle.id] = handle
        runs = self.task.metadata.setdefault("subagent_runs", [])
        if not any(item["run_id"] == context.run_id for item in runs):
            runs.append({"task_id": task.id, "run_id": context.run_id, "agent": name, "action_id": action_id})
        return handle

    async def call(self, name: str, action: str, payload: dict[str, Any], action_id: str | None) -> Any:
        durable = current_durable_run()
        if durable is not None:
            replay, result = durable.start_action()
            if replay:
                return result
        handle = await self.spawn(
            name,
            payload.get("prompt", "") if action == "infer" else payload.get("tool", ""),
            action=action,
            arguments=payload.get("args"),
            action_id=action_id,
            blocking=True,
        )
        checkpoint = durable.store.get(handle.run_id) if durable is not None else None
        request_ids = (
            frozenset(item["id"] for item in checkpoint.data["task"]["messages"][:1])
            if checkpoint is not None
            else frozenset(item.id for item in (*handle.task.messages, *handle.task.artifacts))
        )
        task = await handle.result()
        if task.state is TaskState.INPUT_REQUIRED and "interruption" in task.metadata:
            raise _SuspendRun(RunInterruption.from_dict(task.metadata["interruption"]))
        result = self.agent._require_completed_delegation(task, name, request_item_ids=request_ids)
        if durable is not None:
            result = durable.complete_action(result)
        return result

    async def close(self) -> None:
        self.closed = True
        unfinished = [handle for handle in self.handles.values() if not handle._worker.done()]
        if unfinished:
            await asyncio.gather(*(handle.cancel("Parent run ended") for handle in unfinished))


@asynccontextmanager
async def subagent_scope(agent: Any, task: Task, budget: BudgetEnforcer) -> AsyncIterator[SubagentSupervisor | None]:
    current = _active.get()
    if current is None and not agent.subagents:
        yield None
        return
    if current is not None and current.task.id == task.id:
        yield current
        return
    supervisor = SubagentSupervisor(agent, task, budget)
    token = _active.set(supervisor)
    agent._subagent_runs[task.id] = supervisor
    try:
        with shared_budget_scope(budget):
            yield supervisor
    finally:
        try:
            await supervisor.close()
        finally:
            agent._subagent_runs.pop(task.id, None)
            _active.reset(token)


def current_subagent_supervisor() -> SubagentSupervisor | None:
    return _active.get()


def supervision_tools() -> list[Tool]:
    """Optional ordinary tools; the base inference action union stays unchanged."""

    def supervisor() -> SubagentSupervisor:
        active = current_subagent_supervisor()
        if active is None:
            raise RuntimeError("Subagent tools require an active parent run")
        return active

    async def spawn_subagent(agent: str, prompt: str) -> dict[str, str]:
        """Start a configured local specialist; use wait_subagent to collect its work."""
        handle = await supervisor().spawn(agent, prompt)
        return {"child_id": handle.id, "run_id": handle.run_id}

    async def wait_subagent(child_id: str) -> dict[str, Any]:
        """Await an owned child and inspect its status, output and failure evidence."""
        task = await supervisor().handles[child_id].result()
        return {"child_id": child_id, "state": task.state.value, "output": task.get_output(), "metadata": task.metadata}

    async def cancel_subagent(child_id: str) -> dict[str, str]:
        """Cancel cooperative child work; completed external effects remain recorded."""
        handle = supervisor().handles[child_id]
        await handle.cancel()
        return {"child_id": child_id, "state": handle.task.state.value}

    tools = [
        Tool.from_callable(function, capabilities=["agent.delegate"])
        for function in (
            spawn_subagent,
            wait_subagent,
            cancel_subagent,
        )
    ]
    for tool in tools:
        tool._protolink_supervision_tool = True
    return tools
