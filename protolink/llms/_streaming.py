"""Internal streaming adapters; provider callbacks always run on the event loop."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, asynccontextmanager
from contextvars import copy_context
from typing import Any


@asynccontextmanager
async def http_stream(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
    provider: str,
) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
    """Open an async NDJSON/SSE response and close it on every exit path.

    The client belongs to this request, so separate runs and event loops never
    share a live connection. HTTPX decodes split UTF-8 characters and partial
    lines; protocol completion markers stop reading even on a persistent
    connection. Error frames fail the call instead of producing a partial action.
    HTTPX remains optional for applications that do not stream HTTP backends.
    """
    try:
        import httpx
    except ImportError as exc:
        raise ImportError(
            "HTTP LLM streaming requires httpx. Install it with: pip install httpx or pip install 'protolink[llms]'"
        ) from exc

    async def chunks(response: Any) -> AsyncIterator[dict[str, Any]]:
        async for line in response.aiter_lines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].lstrip()
            if line == "[DONE]":
                return
            if not line or line.startswith((":", "event:", "id:", "retry:")):
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{provider} returned invalid streaming JSON: {line}") from exc
            if not isinstance(chunk, dict):
                raise RuntimeError(f"{provider} returned an invalid streaming payload: {chunk}")
            if "error" in chunk:
                raise RuntimeError(f"{provider} API returned an error during stream: {chunk['error']}")
            yield chunk
            if chunk.get("done") is True:
                return

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if not response.is_success:
                await response.aread()
                raise RuntimeError(
                    f"{provider} API streaming request failed with status {response.status_code}: {response.text}"
                )
            yield chunks(response)


@asynccontextmanager
async def threaded_stream(factory: Callable[[], Any]) -> AsyncIterator[AsyncIterator[Any]]:
    """Read a synchronous SDK or local model iterator without blocking asyncio.

    Opening, reading and closing all happen on one worker, preserving iterator
    thread affinity. Only one item is requested at a time; there is no producer
    queue or generation ahead of the consumer. Callbacks stay on the caller's
    event loop. Context variables are copied to the worker.

    Cancellation returns promptly. Python cannot interrupt a synchronous SDK
    read or a local model evaluation already in progress, so cleanup is queued
    on that same worker and runs when the operation returns (or times out).
    The worker never calls ``close()`` on an executing generator.
    """
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="protolink-stream")
    context = copy_context()
    stack = ExitStack()
    done = object()

    def open_stream() -> Iterator[Any]:
        source = factory()
        if hasattr(source, "__enter__"):
            source = stack.enter_context(source)
        else:
            close = getattr(source, "close", None)
            if close is not None:
                stack.callback(close)
        return iter(source)

    async def chunks() -> AsyncIterator[Any]:
        source = await loop.run_in_executor(executor, context.run, open_stream)
        while True:
            item = await loop.run_in_executor(executor, context.run, next, source, done)
            if item is done:
                return
            yield item

    canceled = False
    try:
        yield chunks()
    except asyncio.CancelledError:
        canceled = True
        raise
    finally:
        cleanup = executor.submit(context.run, stack.close)
        executor.shutdown(wait=False)
        if not canceled:
            await asyncio.wrap_future(cleanup)
