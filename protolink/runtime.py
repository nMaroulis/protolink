"""Convenience lifecycle and run handles around the existing Agent runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from protolink.agents import Agent
from protolink.agents.helpers import _response_content
from protolink.client import AgentClient
from protolink.core.cancellation import TaskNotCancelableError, TaskNotFoundError, mark_task_canceled
from protolink.core.events import RunEvent, TaskStatusUpdateEvent
from protolink.core.execution import closing_stream
from protolink.core.redaction import RedactionPolicy
from protolink.core.report import RunRecorder, RunReport
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState
from protolink.discovery import Registry
from protolink.storage.run_store import RunStore


@dataclass(frozen=True)
class RunResult:
    """Normalized terminal result for local and transported task execution.

    ``uncertain`` means a stream/transport ended without a final task. It does
    not imply the remote side effect failed; callers must inspect before deciding
    on new work. ``report`` always contains the events observed so far.
    """

    status: str
    task: Task | None
    output: Any
    report: RunReport
    error: dict[str, Any] | None = None


class RunHandle:
    """Consume typed events, request cancellation, and await one final result.

    Start with ``RunHandle.start(agent, task)`` or an AgentClient plus URL. The
    handle consumes the original task stream exactly once, even if only
    ``result()`` is awaited. Multiple event consumers see the recorded sequence.
    It never retries a failed request or replays an action.
    """

    def __init__(
        self,
        target: Agent | str,
        task: Task,
        *,
        client: AgentClient | None = None,
        store: RunStore | None = None,
        redaction_policy: RedactionPolicy | None = None,
    ) -> None:
        """Create a running handle inside an active asyncio loop."""
        if isinstance(target, str) and client is None:
            raise ValueError("Remote run handles require an AgentClient")
        self.target = target
        self.task = task
        self.client = client
        self.store = store if store is not None else (target.run_store if isinstance(target, Agent) else None)
        self.redaction_policy = redaction_policy
        self.context = RunContext.ensure_task_context(task)
        self._recorder = RunRecorder(context=self.context)
        self._changed = asyncio.Condition()
        self._cancel_reason: str | None = None
        self._submitted = False
        self._worker = asyncio.create_task(self._drive())

    @classmethod
    def start(cls, target: Agent | str, task: Task, **kwargs: Any) -> RunHandle:
        """Start exactly one existing Agent or AgentClient task stream."""
        return cls(target, task, **kwargs)

    async def _record(self, event: Any) -> RunEvent:
        normalized = RunEvent.from_task_event(event, context=self.context)
        if self.redaction_policy is not None:
            normalized = RunEvent.from_dict(normalized.to_dict(redaction_policy=self.redaction_policy))
        await self._recorder.emit(normalized)
        async with self._changed:
            self._changed.notify_all()
        return normalized

    async def _remote_stream(self) -> AsyncIterator[Any]:
        """Adapt transports without subscriptions using their single task response."""
        assert self.client is not None and isinstance(self.target, str)
        transport = getattr(self.client, "transport", None)
        if transport is not None and not transport.supports_streaming:
            yield await self.client.send_task(self.target, self.task)
        else:
            async for event in self.client.send_task_streaming(self.target, self.task):
                yield event

    async def _drive(self) -> RunResult:
        final_task: Task | None = None
        error: dict[str, Any] | None = None
        request_ids = {item.id for item in (*self.task.messages, *self.task.artifacts)}
        try:
            if self._cancel_reason is not None:
                mark_task_canceled(self.task, self._cancel_reason)
            self._submitted = True
            if isinstance(self.target, Agent):
                stream = self.target.run_task_streaming(self.task)
            else:
                assert self.client is not None
                stream = self._remote_stream()
            async with closing_stream(stream):
                async for raw in stream:
                    if isinstance(raw, Task):
                        raw = TaskStatusUpdateEvent(
                            task_id=raw.id, new_state=raw.state.value, final=True, metadata={"task": raw.to_dict()}
                        )
                    event = await self._record(raw)
                    data = event.payload.get("metadata", {}).get("task")
                    if event.type == "task.status" and event.final and isinstance(data, dict):
                        final_task = Task.from_dict(data)
            if final_task is None:
                error = {
                    "code": "missing_terminal_result",
                    "message": "Stream ended without a final task; effect unknown",
                }
        except asyncio.CancelledError:
            if isinstance(self.target, Agent):
                mark_task_canceled(self.task, self._cancel_reason or "Run handle canceled")
                final_task = self.task
            else:
                error = {"code": "interrupted_stream", "message": "Remote effect unknown after stream interruption"}
        except Exception as exc:
            error = {"code": type(exc).__name__, "message": str(exc)}
            if isinstance(self.target, Agent):
                if not self.task.is_terminal:
                    self.task.fail(str(exc))
                final_task = self.task
        if final_task is not None:
            # Nonstreamed native receipts can arrive through the final snapshot.
            known = {event.event_id for event in self._recorder.events}
            for event in final_task.metadata.get("run_events", []):
                if event.get("event_id") not in known:
                    await self._record(event)
                    known.add(event.get("event_id"))
        report = self._recorder.to_report(
            final_task=final_task.to_dict() if final_task else None,
            redaction_policy=self.redaction_policy,
        )
        if self.store is not None:
            try:
                self.store.save_report(report)
            except Exception as exc:
                error = {"code": "report_persistence_failed", "message": str(exc)}
        status = final_task.state.value if final_task is not None else "uncertain"
        if final_task is not None and final_task.state is TaskState.FAILED and error is None:
            error = {
                "code": "task_failed",
                "message": final_task.metadata.get("error"),
                "blockers": final_task.metadata.get("blockers", []),
            }
        output = _response_content(final_task, request_ids) if final_task else None
        if final_task is not None:
            last = final_task.get_last_item()
            if last is not None and last.id not in request_ids and last.parts and last.parts[-1].type == "tool_output":
                output = last.parts[-1].as_tool_output().result
        result = RunResult(status, final_task, output, report, error)
        async with self._changed:
            # No suspension follows releasing the lock, so listeners observe
            # the completed worker when they acquire it.
            self._changed.notify_all()
        return result

    async def events(self) -> AsyncIterator[RunEvent]:
        """Yield recorded history, then live events as the run produces them.

        Model text arrives in ``event.payload["content"]`` when
        ``event.payload.get("llm_event_type") == "llm_chunk"``. JSON-action
        models emit raw JSON fragments; native tools are assembled separately.
        ``llm_final`` carries the complete answer, and the terminal task status
        ends the run. Leaving this iterator does not cancel the shared run;
        call ``await handle.cancel()`` to stop it explicitly.
        """
        index = 0
        while True:
            events = self._recorder.events
            while index < len(events):
                yield events[index]
                index += 1
            if self._worker.done():
                return
            async with self._changed:
                await self._changed.wait_for(
                    lambda index=index: len(self._recorder.events) > index or self._worker.done()
                )

    async def result(self) -> RunResult:
        """Await the normalized result without propagating waiter cancellation to the run."""
        return await asyncio.shield(self._worker)

    @property
    def report(self) -> RunReport:
        """Return the final report when done, otherwise a snapshot of observed events."""
        if self._worker.done():
            return self._worker.result().report
        return self._recorder.to_report(redaction_policy=self.redaction_policy)

    async def cancel(self, reason: str = "Application requested cancellation") -> None:
        """Cancel through the native control plane; never resubmit the task."""
        if self._worker.done():
            return
        self._cancel_reason = reason
        if not self._submitted:
            return  # _drive observes this before submission.
        if isinstance(self.target, Agent):
            try:
                await self.target.cancel_task(self.task.id, reason=reason)
            except (TaskNotFoundError, TaskNotCancelableError):
                if not self.task.is_terminal:
                    self._worker.cancel()
        else:
            assert self.client is not None
            await self.client.cancel_task(self.target, self.task.id, reason=reason)


class AgentGroup:
    """Own an embedded group without imposing agent roles or network conventions.

    ``agents`` are owned: their existing lifecycle starts/stops with the group.
    ``external_agents``, a supplied client, and the registry (unless explicitly
    owned) remain application-owned. Configure transports, credentials, policies,
    storage, and LLMs on each Agent normally. Agents without transports run by
    direct local invocation; runtime:// transports require no network server.
    """

    def __init__(
        self,
        agents: Sequence[Agent],
        *,
        external_agents: Sequence[Agent] = (),
        registry: Registry | None = None,
        own_registry: bool = False,
        client: AgentClient | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        """Declare ownership explicitly; construction starts no resources."""
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be positive")
        members = (*agents, *external_agents)
        if len({id(agent) for agent in members}) != len(members):
            raise ValueError("An agent cannot appear in more than one ownership group")
        if len({agent.card.name for agent in members}) != len(members):
            raise ValueError("Agent names must be unique within a group")
        self.agents = {agent.card.name: agent for agent in members}
        self._owned = tuple(agents)
        self.registry, self.own_registry, self.client = registry, own_registry, client
        self.startup_timeout = startup_timeout
        self._started_resources: list[Agent | Registry] = []
        self._handles: set[RunHandle] = set()
        self._started = self._closed = False

    async def start(self) -> AgentGroup:
        """Start owned resources, await readiness, and roll back partial startup."""
        if self._closed:
            raise RuntimeError("A closed AgentGroup cannot be restarted")
        if self._started:
            return self
        try:
            async with asyncio.timeout(self.startup_timeout):
                if self.registry is not None and self.own_registry:
                    self._started_resources.append(self.registry)
                    await self.registry._serve()
                    await self.registry.client.discover()
                for agent in self._owned:
                    self._started_resources.append(agent)
                    await agent._serve(register=False)
                    if agent._client is not None and agent._server is not None:
                        await agent._client.get_agent_card(agent.card.url)
                    if self.registry is not None and agent.registry_client is None:
                        agent.set_registry(self.registry)
                    if agent.registry_client is not None:
                        # _serve historically tolerates registration failures;
                        # group readiness requires explicit successful registration.
                        await agent.registry_client.register(agent.card)
                        agent._start_registry_heartbeat()
        except BaseException:
            await self.close()
            raise
        self._started = True
        return self

    def run(self, agent: str | Agent, task: Task, **kwargs: Any) -> RunHandle:
        """Start a group member or configured remote URL using the ordinary runtime."""
        if not self._started or self._closed:
            raise RuntimeError("Start the AgentGroup before submitting work")
        target = self.agents.get(agent, agent) if isinstance(agent, str) else agent
        handle = RunHandle.start(target, task, client=self.client, **kwargs)
        self._handles.add(handle)
        handle._worker.add_done_callback(lambda _: self._handles.discard(handle))
        return handle

    async def close(self) -> None:
        """Cancel group-started runs and stop every owned resource in reverse order."""
        if self._closed:
            return
        self._closed = True
        failures: list[Exception] = []
        for handle in tuple(self._handles):
            try:
                await handle.cancel("Agent group is shutting down")
                await handle.result()
            except Exception as exc:
                failures.append(exc)
        for resource in reversed(self._started_resources):
            try:
                await resource._stop()
            except Exception as exc:
                failures.append(exc)
        self._started_resources.clear()
        if failures:
            raise ExceptionGroup("AgentGroup cleanup failed", failures)

    async def __aenter__(self) -> AgentGroup:
        """Start the group before entering its application scope."""
        return await self.start()

    async def __aexit__(self, *exc: Any) -> None:
        """Shut down owned resources when the application scope exits."""
        await self.close()
