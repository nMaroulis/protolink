"""Synchronous SDK streams share bounded capacity with tools and unary models."""

import asyncio
import threading

import pytest

from protolink.core.workers import SyncWorkerPool, run_sync, sync_execution_scope
from protolink.llms._streaming import threaded_stream


async def _consume(factory):
    async with threaded_stream(factory) as stream:
        return [item async for item in stream]


@pytest.mark.asyncio
async def test_canceled_sdk_read_holds_capacity_and_canceled_admission_never_opens_source():
    pool = SyncWorkerPool(1)
    reading, release, closed = threading.Event(), threading.Event(), threading.Event()
    waiting_opened = threading.Event()
    next_opened = threading.Event()

    def blocked_source():
        try:
            yield "first"
            reading.set()
            assert release.wait(3)
            yield "late"
        finally:
            closed.set()

    def waiting_source():
        waiting_opened.set()
        return iter(["never"])

    def next_source():
        next_opened.set()
        return iter(["next"])

    with sync_execution_scope("thread", pool):
        first = asyncio.create_task(_consume(blocked_source))
        try:
            assert await asyncio.to_thread(reading.wait, 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(first, 1)
            assert not closed.is_set()
            waiting = asyncio.create_task(_consume(waiting_source))
            await asyncio.sleep(0)
            assert len(pool._waiting) == 1
            assert not waiting_opened.is_set()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert not waiting_opened.is_set()
            assert not pool._waiting
            next_stream = asyncio.create_task(_consume(next_source))
            await asyncio.sleep(0)
            assert len(pool._waiting) == 1
            assert not next_opened.is_set()
            release.set()
            assert await asyncio.wait_for(next_stream, 2) == ["next"]
            assert closed.is_set()
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            pool.close()


@pytest.mark.asyncio
async def test_cancel_during_sdk_cleanup_keeps_capacity_until_close_finishes():
    pool = SyncWorkerPool(1)
    closing, release, closed = threading.Event(), threading.Event(), threading.Event()
    work_started = threading.Event()
    worker_threads = []

    class Source:
        def __iter__(self):
            worker_threads.append(threading.get_ident())
            return self

        def __next__(self):
            worker_threads.append(threading.get_ident())
            raise StopIteration

        def close(self):
            worker_threads.append(threading.get_ident())
            closing.set()
            assert release.wait(3)
            closed.set()

    def work():
        work_started.set()
        return "completed"

    with sync_execution_scope("thread", pool):
        stream = asyncio.create_task(_consume(Source))
        try:
            assert await asyncio.to_thread(closing.wait, 2)
            stream.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(stream, 1)
            queued = asyncio.create_task(run_sync(work))
            await asyncio.sleep(0)
            assert len(pool._waiting) == 1
            assert not work_started.is_set()
            release.set()
            assert await asyncio.wait_for(queued, 2) == "completed"
            assert closed.is_set()
            assert len(set(worker_threads)) == 1
            assert worker_threads[0] != threading.get_ident()
        finally:
            release.set()
            await asyncio.gather(stream, return_exceptions=True)
            pool.close()


@pytest.mark.asyncio
async def test_worker_failure_releases_stream_admission():
    pool = SyncWorkerPool(1)

    def fail():
        raise ValueError("provider failed before opening")

    with sync_execution_scope("thread", pool):
        try:
            with pytest.raises(ValueError, match="before opening"):
                await _consume(fail)
            assert await asyncio.wait_for(_consume(lambda: iter(["recovered"])), 1) == ["recovered"]
        finally:
            pool.close()
