"""Bounded worker execution shared by native tools and synchronous providers.

Admission happens before submission. A canceled await leaves its worker slot
occupied until the Python call really finishes; Python cannot stop that thread.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import partial
from typing import Any, Literal, TypeVar

SyncExecution = Literal["inline", "thread"]
_T = TypeVar("_T")


class SyncWorkerPool:
    """Lazily start at most ``max_workers`` calls, including canceled calls.

    Waiting coroutines are cancelable and submit no work until admitted. The
    pool can be shared across event loops. ``close()`` stops admission without
    waiting for running calls, whose side effects remain the application's
    responsibility.
    """

    def __init__(self, max_workers: int = 4) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_sync_workers must be a positive integer")
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._active = 0
        self._waiting: deque[Future[None]] = deque()
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    async def _acquire(self) -> None:
        ticket: Future[None] = Future()
        with self._lock:
            if self._closed:
                raise RuntimeError("Synchronous worker pool is closed")
            if self._active < self.max_workers:
                self._active += 1
                ticket.set_result(None)
            else:
                self._waiting.append(ticket)
        try:
            await asyncio.wrap_future(ticket)
        except BaseException:
            with self._lock:
                granted = not ticket.cancel() and ticket.exception() is None
                if not granted:
                    try:
                        self._waiting.remove(ticket)
                    except ValueError:
                        pass
            if granted:
                self._release()
            raise

    def _release(self) -> None:
        with self._lock:
            while self._waiting:
                ticket = self._waiting.popleft()
                if ticket.set_running_or_notify_cancel():
                    ticket.set_result(None)
                    return
            self._active -= 1

    async def run(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """Run a call with copied context variables and prompt await cancellation.

        Cancellation discards the eventual result, but cannot terminate a
        running thread. Exceptions propagate unchanged to an active waiter.
        """
        await self._acquire()
        try:
            context = copy_context()
            with self._lock:
                if self._closed:
                    raise RuntimeError("Synchronous worker pool is closed")
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="protolink")
                future = self._executor.submit(context.run, partial(func, *args, **kwargs))
        except BaseException:
            self._release()
            raise
        # The concurrent future completes when the thread actually exits, even
        # if its asyncio wrapper or the event loop has already been canceled.
        future.add_done_callback(lambda _: self._release())
        return await asyncio.wrap_future(future)

    def close(self) -> None:
        """Reject pending/new calls and let already running threads finish."""
        with self._lock:
            self._closed = True
            waiting, self._waiting = self._waiting, deque()
            executor = self._executor
        for ticket in waiting:
            if ticket.set_running_or_notify_cancel():
                ticket.set_exception(RuntimeError("Synchronous worker pool is closed"))
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


_default_pool = SyncWorkerPool()
_sync_scope: ContextVar[tuple[SyncExecution, SyncWorkerPool]] = ContextVar(
    "protolink_sync_execution", default=("inline", _default_pool)
)


@contextmanager
def sync_execution_scope(mode: SyncExecution, pool: SyncWorkerPool) -> Generator[None, None, None]:
    """Bind an agent's synchronous execution defaults within this invocation."""
    token = _sync_scope.set((mode, pool))
    try:
        yield
    finally:
        _sync_scope.reset(token)


def current_sync_execution() -> SyncExecution:
    """Return the active agent's synchronous tool execution default."""
    return _sync_scope.get()[0]


async def run_sync(func: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """Run a synchronous callable through the active bounded worker pool."""
    return await _sync_scope.get()[1].run(func, *args, **kwargs)


async def _reserve_sync_worker() -> Callable[[], None]:
    """Reserve bounded admission for a stream that needs its own affinity worker.

    Release exactly once, after the dedicated worker has actually closed its
    stream. Canceling admission does not reserve a slot or start any worker.
    """
    pool = _sync_scope.get()[1]
    await pool._acquire()
    return pool._release
