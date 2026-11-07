"""Optional FIFO admission for runs submitted through an embedded group."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from protolink.core.events import RunEvent


@dataclass(frozen=True)
class GroupLimits:
    """Bound root submissions without charging queued work against run budgets.

    Limits apply only to ``AgentGroup.run``. Delegated children share their
    parent's slot; direct Agent calls retain their normal execution controls.
    ``queue_timeout`` measures seconds from submission, including time before
    the handle's worker first runs. Omit group limits for unlimited admission.
    """

    max_concurrent_runs: int = 4
    max_queued_runs: int = 64
    queue_timeout: float | None = None

    def __post_init__(self) -> None:
        for name, minimum in (("max_concurrent_runs", 1), ("max_queued_runs", 0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if self.queue_timeout is not None and (
            isinstance(self.queue_timeout, bool) or not math.isfinite(self.queue_timeout) or self.queue_timeout <= 0
        ):
            raise ValueError("queue_timeout must be finite and positive")


class RunAdmissionError(RuntimeError):
    """A root submission was rejected or expired before executing any work."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _Admission:
    def __init__(self, limits: GroupLimits) -> None:
        self.limits = limits
        self.active = 0
        self.waiting: deque[_Ticket] = deque()

    def request(self) -> _Ticket:
        ticket = _Ticket(self)
        if self.active < self.limits.max_concurrent_runs:
            self.active += 1
            ticket.admitted.set()
        elif len(self.waiting) < self.limits.max_queued_runs:
            self.waiting.append(ticket)
            ticket.queued = True
        else:
            ticket.rejected = True
        return ticket

    def release(self, ticket: _Ticket) -> None:
        if ticket.released:
            return
        ticket.released = True
        if ticket in self.waiting:
            self.waiting.remove(ticket)
        elif ticket.admitted.is_set():
            self.active -= 1
        while self.waiting and self.active < self.limits.max_concurrent_runs:
            next_ticket = self.waiting.popleft()
            self.active += 1
            next_ticket.admitted.set()


class _Ticket:
    def __init__(self, owner: _Admission) -> None:
        self.owner = owner
        self.admitted = asyncio.Event()
        self.queued = self.rejected = self.released = False
        timeout = owner.limits.queue_timeout
        self.deadline = asyncio.get_running_loop().time() + timeout if timeout is not None else None

    async def wait(self, canceled: asyncio.Event, emit: Callable[[RunEvent], Awaitable[RunEvent]]) -> None:
        if canceled.is_set():
            if self.queued:
                await emit(RunEvent(type="run.canceled", summary="Queued run canceled"))
            raise asyncio.CancelledError
        if self.rejected:
            await emit(RunEvent(type="run.rejected", summary="Run queue is full"))
            raise RunAdmissionError("queue_full", "Run queue is full")
        if self.queued:
            await emit(RunEvent(type="run.queued", summary="Run is waiting for capacity"))
            ready = asyncio.create_task(self.admitted.wait())
            cancel = asyncio.create_task(canceled.wait())
            try:
                async with asyncio.timeout_at(self.deadline):
                    await asyncio.wait((ready, cancel), return_when=asyncio.FIRST_COMPLETED)
            except TimeoutError:
                await emit(RunEvent(type="run.expired", summary="Run queue deadline expired"))
                raise RunAdmissionError("queue_timeout", "Run queue deadline expired") from None
            finally:
                ready.cancel()
                cancel.cancel()
                await asyncio.gather(ready, cancel, return_exceptions=True)
            if canceled.is_set():
                await emit(RunEvent(type="run.canceled", summary="Queued run canceled"))
                raise asyncio.CancelledError
            if self.deadline is not None and asyncio.get_running_loop().time() >= self.deadline:
                await emit(RunEvent(type="run.expired", summary="Run queue deadline expired"))
                raise RunAdmissionError("queue_timeout", "Run queue deadline expired")
        await emit(RunEvent(type="run.admitted", summary="Run admitted"))

    def release(self) -> None:
        self.owner.release(self)
