"""Convenience lifecycle and run handles around the existing Agent runtime."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from protolink.agents import Agent
from protolink.agents.subagents import SubagentHandle
from protolink.client import AgentClient
from protolink.core.admission import GroupLimits, _Admission, _Ticket
from protolink.core.answers import AnswerEvent, _AnswerProjector
from protolink.core.cancellation import TaskNotCancelableError, TaskNotFoundError, mark_task_canceled
from protolink.core.events import RunEvent, TaskStatusUpdateEvent
from protolink.core.evidence import ToolEvidence, _ToolEvidenceCollector
from protolink.core.execution import closing_stream
from protolink.core.handoff import RunHandoff
from protolink.core.invocation import response_content
from protolink.core.presentation import PresentationEvent
from protolink.core.redaction import RedactionPolicy
from protolink.core.report import RunRecorder, RunReport
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState
from protolink.discovery import Registry
from protolink.storage.run_store import RunStore


class StreamGapError(RuntimeError):
    """A subscription cursor precedes the handle's retained replay window.

    The full report remains available through ``handle.report``. Reconnecting
    must read that snapshot or restart observation, never submit the task again.
    """

    def __init__(self, after: int, first_available: int, latest: int) -> None:
        self.after, self.first_available, self.latest = after, first_available, latest
        super().__init__(f"Events after {after} are unavailable; retained window is {first_available}..{latest}")


@dataclass(frozen=True)
class GroupSnapshot:
    """Process-local lifecycle and admission counts, without provider probes."""

    state: str
    ready_agents: tuple[str, ...]
    active_runs: int
    queued_runs: int
    retained_runs: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible diagnostic snapshot."""
        return asdict(self)


def _submission_fingerprint(target: Agent | str, task: Task) -> str:
    """Hash semantic wire input, excluding generated task/message identities."""
    data = copy.deepcopy(task.to_dict())
    for key in ("id", "state", "created_at"):
        data.pop(key, None)
    for collection in ("messages", "artifacts"):
        for item in data.get(collection, []):
            item.pop("id", None)
            item.pop("timestamp", None)
            for part in item.get("parts", []):
                if part.get("type") in {"tool_call", "agent_call"} and isinstance(part.get("content"), dict):
                    part["content"].pop("call_id", None)
    context = data.get("metadata", {}).get("run_context")
    data.get("metadata", {}).pop("run_id", None)
    if isinstance(context, dict):
        for key in ("run_id", "created_at"):
            context.pop(key, None)
    identity = (id(target), target.card.name, target.card.url) if isinstance(target, Agent) else target
    encoded = json.dumps([identity, data], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


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

    @property
    def tool_evidence(self) -> tuple[ToolEvidence, ...]:
        """Return the report's terminal tool observations, including delegated tools."""
        return self.report.tool_evidence

    @property
    def handoff(self) -> RunHandoff | None:
        """The unfinished worker's structured progress, if this run yielded.

        ``status`` remains ``input-required`` rather than successful completion.
        Continue through the owning root Agent's checkpoint/resume API.
        """
        return RunHandoff.from_task(self.task) if self.task is not None else None


class RunHandle:
    """Consume typed events, request cancellation and await one final result.

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
        event_buffer_size: int | None = None,
        _admission: _Ticket | None = None,
    ) -> None:
        """Create a running handle inside an active asyncio loop."""
        if isinstance(target, str) and client is None:
            raise ValueError("Remote run handles require an AgentClient")
        if event_buffer_size is not None and (
            isinstance(event_buffer_size, bool) or not isinstance(event_buffer_size, int) or event_buffer_size < 1
        ):
            raise ValueError("event_buffer_size must be a positive integer or None")
        self.target = target
        self.task = task
        self.client = client
        self.store = store if store is not None else (target.run_store if isinstance(target, Agent) else None)
        self.redaction_policy = redaction_policy
        self.context = RunContext.ensure_task_context(task)
        self._recorder = RunRecorder(context=self.context)
        self._buffer: deque[RunEvent] = deque(maxlen=event_buffer_size)
        self._sequence = 0
        self._answers: list[AnswerEvent] = []
        self._answer_enabled = any(
            part.type in {"infer", "text"} for message in task.messages for part in message.parts
        )
        self._answer_projector = _AnswerProjector(task.id, redaction_policy=redaction_policy)
        self._admission = _admission
        self._changed = asyncio.Condition()
        self._canceled = asyncio.Event()
        self._cancel_reason: str | None = None
        self._submitted = False
        self._worker = asyncio.create_task(self._drive())

    @classmethod
    def start(cls, target: Agent | str, task: Task, **kwargs: Any) -> RunHandle:
        """Start exactly one existing Agent or AgentClient task stream."""
        return cls(target, task, **kwargs)

    async def _record(self, event: Any) -> RunEvent:
        normalized = RunEvent.from_task_event(event, context=self.context)
        self._sequence += 1
        normalized = replace(
            normalized,
            sequence=self._sequence,
            run_id=normalized.run_id or self.context.run_id,
            task_id=normalized.task_id or self.task.id,
        )
        # Project before per-event masking so secrets split across chunks are
        # recognized by the answer projector's own streaming redaction.
        if self._answer_enabled:
            self._answers.extend(self._answer_projector.feed(normalized))
        if self.redaction_policy is not None:
            normalized = RunEvent.from_dict(normalized.to_dict(redaction_policy=self.redaction_policy))
        await self._recorder.emit(normalized)
        self._buffer.append(normalized)
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
        try:
            return await self._execute()
        finally:
            if self._admission is not None:
                self._admission.release()
            async with self._changed:
                self._changed.notify_all()

    async def _execute(self) -> RunResult:
        final_task: Task | None = None
        error: dict[str, Any] | None = None
        request_ids = {item.id for item in (*self.task.messages, *self.task.artifacts)}
        terminal_seen = False
        try:
            if self._admission is not None:
                await self._admission.wait(self._canceled, self._record)
            if self._canceled.is_set():
                raise asyncio.CancelledError
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
                        terminal_seen = True
            if final_task is None:
                error = {
                    "code": "missing_terminal_result",
                    "message": "Stream ended without a final task; effect unknown",
                }
        except asyncio.CancelledError:
            if isinstance(self.target, Agent) or not self._submitted:
                mark_task_canceled(self.task, self._cancel_reason or "Run handle canceled")
                final_task = self.task
            else:
                error = {"code": "interrupted_stream", "message": "Remote effect unknown after stream interruption"}
        except Exception as exc:
            error = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
            if isinstance(self.target, Agent) or not self._submitted:
                if not self.task.is_terminal:
                    self.task.fail(str(exc))
                final_task = self.task
        if final_task is not None and not terminal_seen:
            await self._record(
                TaskStatusUpdateEvent(
                    task_id=final_task.id,
                    new_state=final_task.state.value,
                    final=True,
                    metadata={"task": final_task.to_dict()},
                )
            )
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
        output = response_content(final_task, request_ids) if final_task else None
        if final_task is not None:
            last = final_task.get_last_item()
            if last is not None and last.id not in request_ids and last.parts and last.parts[-1].type == "tool_output":
                output = last.parts[-1].as_tool_output().result
        result = RunResult(status, final_task, output, report, error)
        self._answers.extend(self._answer_projector.finish(status, output if self._answer_enabled else None))
        async with self._changed:
            # No suspension follows releasing the lock, so listeners observe
            # the completed worker when they acquire it.
            self._changed.notify_all()
        return result

    async def events(self, *, after: int = 0) -> AsyncIterator[RunEvent]:
        """Yield recorded history, then live events as the run produces them.

        Model text arrives in ``event.payload["content"]`` when
        ``event.payload.get("llm_event_type") == "llm_chunk"``. JSON-action
        models emit raw JSON fragments; native tools are assembled separately.
        ``llm_final`` carries the complete answer and the terminal task status
        ends the run. Leaving this iterator does not cancel the shared run;
        call ``await handle.cancel()`` to stop it explicitly.
        """
        if isinstance(after, bool) or not isinstance(after, int) or after < 0 or after > self._sequence:
            raise ValueError("after must be a non-negative sequence already observed by this handle")
        cursor = after
        while True:
            first = self._buffer[0].sequence if self._buffer else self._sequence + 1
            assert first is not None
            if cursor < first - 1:
                raise StreamGapError(cursor, first, self._sequence)
            # One bounded snapshot per batch avoids rescanning the whole
            # history for each fragment. A later eviction produces a gap.
            batch = tuple(item for item in self._buffer if (item.sequence or 0) > cursor)
            if batch:
                for event in batch:
                    cursor = event.sequence or cursor
                    yield event
                continue
            if self._worker.done():
                return
            async with self._changed:
                await self._changed.wait_for(lambda cursor=cursor: self._sequence > cursor or self._worker.done())

    async def answer_events(self, *, after: int = 0) -> AsyncIterator[AnswerEvent]:
        """Stream root answer deltas, replacements and authoritative completion.

        ``delta`` appends text; ``replacement`` replaces it. Only ``completed``
        confirms a successful answer. Markdown is preserved; protocol envelopes,
        reasoning and child answers are excluded. ``after`` is this answer
        stream's sequence, independent of the raw event cursor. Disconnecting
        leaves execution active. Late subscribers replay safe answer history.
        """
        if isinstance(after, bool) or not isinstance(after, int) or not 0 <= after <= len(self._answers):
            raise ValueError("after must be an observed answer sequence")
        index = after
        while True:
            while index < len(self._answers):
                yield self._answers[index]
                index += 1
            if self._worker.done():
                return
            async with self._changed:
                await self._changed.wait_for(lambda index=index: len(self._answers) > index or self._worker.done())

    async def presentation_events(self, *, after: int = 0) -> AsyncIterator[PresentationEvent]:
        """Yield allowlisted activity fields with raw-event reconnect cursors.

        Arguments, results, prompts, reasoning and diagnostic error strings are
        omitted. Correlation IDs retain owned child activity. Use answer_events
        for text and result() for the authoritative terminal outcome.
        """
        async for event in self.events(after=after):
            activity = PresentationEvent.from_run_event(event, redaction_policy=self.redaction_policy)
            if activity is not None:
                yield activity

    async def result(self) -> RunResult:
        """Await the normalized result without propagating waiter cancellation to the run."""
        return await asyncio.shield(self._worker)

    async def tool_evidence(self) -> AsyncIterator[ToolEvidence]:
        """Yield each terminal tool observation once, from history then live events.

        Multiple subscribers share the original execution. Rejected, failed
        and canceled actions remain distinct from completed effects. Results
        respect the owning Agent's ``expose_tool_results`` privacy setting.
        Leaving the iterator does not cancel the run.
        """
        collector = _ToolEvidenceCollector()
        async for event in self.events():
            evidence = collector.add(event)
            if evidence is not None:
                yield evidence

    async def spawn(self, agent: str, prompt: str) -> SubagentHandle:
        """Start an owned local specialist while this live parent is running.

        The child shares root limits/policies and is drained when the parent
        ends. Durable runs use blocking agent_call delegation instead.
        """
        if not isinstance(self.target, Agent):
            raise RuntimeError("Local child supervision requires a local Agent")
        if not self.target.subagents:
            raise RuntimeError("Parent requires a local subagent roster")
        if self.target.durability is not None:
            raise RuntimeError("Durable runs use blocking agent_call delegation")
        while self.task.id not in self.target._subagent_runs and not self._worker.done():
            await asyncio.sleep(0)
        supervisor = self.target._subagent_runs.get(self.task.id)
        if supervisor is None:
            raise RuntimeError("Parent is not running with a local subagent roster")
        from protolink.core.execution import execution_scope

        with execution_scope(self.task):
            return await supervisor.spawn(agent, prompt)

    async def chunks(self) -> AsyncIterator[str]:
        """Yield raw model text fragments from this run's recorded/live events.

        JSON-action models emit JSON fragments, not just the final answer.
        Tools and final-message events are omitted; no parsing or concatenation
        is performed. Multiple consumers do not execute the run again. Inspect
        result() for terminal failure; leaving this iterator does not cancel work.
        """
        async for event in self.events():
            if event.payload.get("llm_event_type") == "llm_chunk":
                content = event.payload.get("content")
                if isinstance(content, str):
                    yield content

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
        self._canceled.set()
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
    ``external_agents``, a supplied client and the registry (unless explicitly
    owned) remain application-owned. Configure transports, credentials, policies,
    storage and LLMs on each Agent normally. Agents without transports run by
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
        limits: GroupLimits | None = None,
        event_buffer_size: int | None = None,
        max_retained_runs: int = 100,
    ) -> None:
        """Declare ownership explicitly; construction starts no resources."""
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be positive")
        if isinstance(max_retained_runs, bool) or not isinstance(max_retained_runs, int) or max_retained_runs < 0:
            raise ValueError("max_retained_runs must be a non-negative integer")
        if event_buffer_size is not None and (
            isinstance(event_buffer_size, bool) or not isinstance(event_buffer_size, int) or event_buffer_size < 1
        ):
            raise ValueError("event_buffer_size must be a positive integer or None")
        members = (*agents, *external_agents)
        if len({id(agent) for agent in members}) != len(members):
            raise ValueError("An agent cannot appear in more than one ownership group")
        if len({agent.card.name for agent in members}) != len(members):
            raise ValueError("Agent names must be unique within a group")
        self.agents = {agent.card.name: agent for agent in members}
        self._owned = tuple(agents)
        self.registry, self.own_registry, self.client = registry, own_registry, client
        self.startup_timeout = startup_timeout
        self.event_buffer_size, self.max_retained_runs = event_buffer_size, max_retained_runs
        self._admission = _Admission(limits) if limits is not None else None
        self._started_resources: list[Agent | Registry] = []
        self._handles: set[RunHandle] = set()
        self._runs: OrderedDict[str, RunHandle] = OrderedDict()
        self._requests: dict[str, tuple[str, RunHandle]] = {}
        self._started = self._closed = False

    async def start(self) -> AgentGroup:
        """Start owned resources, await readiness and roll back partial startup."""
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

    def run(self, agent: str | Agent, task: Task, *, request_id: str | None = None, **kwargs: Any) -> RunHandle:
        """Submit once, optionally reusing an application-scoped request ID.

        A retained ID with the same target and serialized input returns its
        original handle, including queued, canceled and failed runs. Different
        input raises ValueError. IDs are local to this group and expire when
        completed handles are evicted; they do not guarantee exactly-once
        external effects or survive process restarts. Scope IDs to authenticated
        callers in the application. Private dependencies are not fingerprinted.
        """
        if not self._started or self._closed:
            raise RuntimeError("Start the AgentGroup before submitting work")
        target = self.agents.get(agent, agent) if isinstance(agent, str) else agent
        # Freeze accepted wire input before it can wait in the group queue.
        # Keep caller identity values while execution owns its mutable state.
        task = Task.from_dict(copy.deepcopy(task.to_dict()))
        context = RunContext.ensure_task_context(task)
        fingerprint = None
        if request_id is not None:
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("request_id must be a nonempty string")
            fingerprint = _submission_fingerprint(target, task)
            existing = self._requests.get(request_id)
            if existing is not None:
                if existing[0] != fingerprint:
                    raise ValueError("request_id was already used with different input")
                return existing[1]
        if context.run_id in self._runs:
            raise ValueError("Run ID is already retained; use get_run() to observe existing work")
        kwargs.setdefault("event_buffer_size", self.event_buffer_size)
        ticket = self._admission.request() if self._admission is not None else None
        try:
            handle = RunHandle.start(target, task, client=self.client, _admission=ticket, **kwargs)
        except BaseException:
            if ticket is not None:
                ticket.release()
            raise
        self._handles.add(handle)
        self._runs[handle.context.run_id] = handle
        if request_id is not None:
            assert fingerprint is not None
            self._requests[request_id] = (fingerprint, handle)
        handle._worker.add_done_callback(lambda _: self._finished(handle))
        return handle

    def _finished(self, handle: RunHandle) -> None:
        self._handles.discard(handle)
        completed = [run_id for run_id, run in self._runs.items() if run._worker.done()]
        for run_id in completed[: max(0, len(completed) - self.max_retained_runs)]:
            expired = self._runs.pop(run_id)
            self._requests = {key: value for key, value in self._requests.items() if value[1] is not expired}

    def get_run(self, run_id: str) -> RunHandle:
        """Look up retained work without submitting it; unknown/evicted IDs raise KeyError.

        Active runs are never evicted. Completed handles obey max_retained_runs;
        persistent reports remain in each handle's RunStore. This lookup does
        not authenticate browser callers; apply application authorization first.
        """
        return self._runs[run_id]

    def snapshot(self) -> GroupSnapshot:
        """Inspect lifecycle, registration readiness and root admission counts.

        Readiness records successful group startup, independently of model
        availability. No provider request is made. Thread worker capacity and
        delegated child concurrency keep their separate native controls.
        """
        state = "closed" if self._closed else "ready" if self._started else "created"
        queued = len(self._admission.waiting) if self._admission is not None else 0
        active = self._admission.active if self._admission is not None else len(self._handles)
        return GroupSnapshot(
            state,
            tuple(agent.card.name for agent in self._owned) if state == "ready" else (),
            active,
            queued,
            len(self._runs),
        )

    async def close(self) -> None:
        """Cancel group-started runs and stop every owned resource in reverse order."""
        if self._closed:
            return
        self._closed = True
        failures: list[Exception] = []
        handles = tuple(self._handles)
        # Mark every waiter before cancellation can release an active slot.
        for handle in handles:
            handle._cancel_reason = "Agent group is shutting down"
            handle._canceled.set()
        for handle in handles:
            try:
                await handle.cancel("Agent group is shutting down")
            except Exception as exc:
                failures.append(exc)
        for handle in handles:
            try:
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
