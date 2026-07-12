"""
ProtoLink - Agent to Agent (A2A) Transport Layer

Agent-to-Agent (A2A) transport implementations for agent communication.
Supports in-memory and JSON-RPC over HTTP/WebSocket.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import random
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from protolink.transport.config import TransportCapabilities, TransportConfig
from protolink.transport.errors import TransportError, TransportLimitError
from protolink.transport.metrics import TransportMetrics, TransportMetricsSnapshot
from protolink.utils.serialization import Serializer

if TYPE_CHECKING:
    from protolink.client.request_spec import ClientRequestSpec
    from protolink.server.endpoint_handler import EndpointSpec


T = TypeVar("T")
AsyncCloser = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TransportRequestContext:
    """Correlation and idempotency metadata for one logical request.

    Args:
        request_id: Identifier retained across every attempt of the request.
        idempotency_key: Optional operation key used for response deduplication.
        attempt: One-based wire-attempt number.
    """

    request_id: str
    idempotency_key: str | None = None
    attempt: int = 1

    def next_attempt(self) -> TransportRequestContext:
        """Return context for the next retry attempt."""
        return TransportRequestContext(
            request_id=self.request_id,
            idempotency_key=self.idempotency_key,
            attempt=self.attempt + 1,
        )


class Transport(ABC):
    """Abstract base class for transport implementations.

    Concrete transports retain ownership of protocol I/O while this base class
    provides one contract for capabilities, configuration, limits, retries,
    metrics, correlation identifiers, and health reporting.
    """

    transport_type: ClassVar[str] = "custom"
    supports_streaming: ClassVar[bool] = False
    capabilities: ClassVar[TransportCapabilities] = TransportCapabilities()

    def __init__(self, *, config: TransportConfig | None = None) -> None:
        """Initialize shared production behavior for a concrete transport.

        Args:
            config: Limits, retries, keepalive, shutdown, idempotency, and
                metrics settings. Defaults to a new ``TransportConfig``.
        """
        self.config = config or TransportConfig()
        self._metrics = TransportMetrics(enabled=self.config.collect_metrics)
        self._request_semaphores: dict[int, asyncio.Semaphore] = {}
        self._stream_semaphores: dict[int, asyncio.Semaphore] = {}
        self._resource_lock = threading.Lock()
        self._loop_resources: dict[Hashable, tuple[asyncio.AbstractEventLoop, AsyncCloser]] = {}
        self._idempotency_lock = threading.Lock()
        self._idempotency_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._idempotency_inflight: dict[str, concurrent.futures.Future[Any]] = {}
        self._transport_running = False

    @abstractmethod
    async def send(
        self, request_spec: ClientRequestSpec, base_url: str, data: Any = None, params: dict | None = None
    ) -> Any:
        """Send a generic request to an agent endpoint.

        Args:
            request_spec: The request specification (method, path, parser).
            base_url: The base URL of the agent (e.g. "http://localhost:8080").
            data: The payload to send (for body).
            params: Query parameters (for GET requests etc).

        Returns:
            The parsed response.
        """
        pass

    async def subscribe(self, agent_url: str, task: Any) -> AsyncIterator[Any]:
        """Stream events from a remote agent when supported."""
        if False:  # pragma: no cover - preserves the async-iterator contract
            yield None
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming")

    @abstractmethod
    def setup_routes(self, endpoints: list[EndpointSpec]) -> None:
        """Setup routes for the transport server.

        Args:
            endpoints: List of endpoint specifications to register.
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start the transport server.

        For server-side transports, this should start listening for incoming requests.
        For client-only transports, this can be a no-op.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport server.

        For server-side transports, this should stop listening and clean up resources.
        For client-only transports, this can be a no-op.
        """
        pass

    @abstractmethod
    def validate_url(self) -> bool:
        """Validate provided URL"""
        pass

    @property
    @abstractmethod
    def url(self) -> str:
        """Get the URL of the transport."""
        pass

    @property
    def metrics(self) -> TransportMetricsSnapshot:
        """Return current dependency-free transport metrics."""
        metrics = getattr(self, "_metrics", None)
        return metrics.snapshot() if metrics is not None else TransportMetricsSnapshot()

    @property
    def is_running(self) -> bool:
        """Whether the transport server is currently running."""
        return bool(getattr(self, "_transport_running", False))

    def health(self) -> dict[str, Any]:
        """Return transport state, capabilities, and metrics as JSON-safe data."""
        return {
            "status": "ready" if self.is_running else "stopped",
            "ready": self.is_running,
            "transport": self.transport_type,
            "url": self.url,
            "capabilities": {
                "networked": self.capabilities.networked,
                "streaming": self.capabilities.streaming,
                "tls": self.capabilities.tls,
                "bidirectional": self.capabilities.bidirectional,
                "persistent_connections": self.capabilities.persistent_connections,
            },
            "metrics": self.metrics.to_dict(),
        }

    def new_request_context(self, request_spec: ClientRequestSpec, data: Any = None) -> TransportRequestContext:
        """Create correlation and idempotency metadata for a logical request.

        Idempotent requests prefer a stable ``id``, ``task_id``, or
        ``agent_url`` from the payload. Otherwise the generated request ID is
        also used as the idempotency key.

        Args:
            request_spec: Operation contract controlling idempotency.
            data: Optional domain model or mapping sent by the request.

        Returns:
            A first-attempt request context.
        """
        request_id = uuid.uuid4().hex
        idempotency_key: str | None = None
        if request_spec.idempotent:
            candidate = getattr(data, "id", None) or getattr(data, "task_id", None)
            if candidate is None and isinstance(data, dict):
                candidate = data.get("id") or data.get("task_id") or data.get("agent_url")
            idempotency_key = str(candidate) if candidate else request_id
        return TransportRequestContext(request_id=request_id, idempotency_key=idempotency_key)

    def register_loop_resource(self, key: Hashable, closer: AsyncCloser) -> None:
        """Record an async resource and the event loop that owns it."""
        loop = asyncio.get_running_loop()
        with self._resource_lock:
            self._loop_resources[key] = (loop, closer)

    def discard_loop_resource(self, key: Hashable) -> None:
        """Forget a closed or invalidated loop-owned resource."""
        with self._resource_lock:
            self._loop_resources.pop(key, None)

    async def close_loop_resources(self) -> None:
        """Close every pooled resource on its owning event loop.

        Resources whose event loop has already stopped are forgotten because
        asyncio cannot safely drive their asynchronous close operation.
        """
        with self._resource_lock:
            resources = list(self._loop_resources.items())
            self._loop_resources.clear()

        current_loop = asyncio.get_running_loop()
        for _key, (owner_loop, closer) in resources:
            if owner_loop is current_loop:
                await self._close_with_timeout(closer)
                continue
            if not owner_loop.is_running() or owner_loop.is_closed():
                continue
            future = asyncio.run_coroutine_threadsafe(self._run_closer(closer), owner_loop)
            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(future),
                    timeout=self.config.shutdown_timeout,
                )
            except (TimeoutError, asyncio.CancelledError):
                future.cancel()
            except Exception:
                continue

    async def _close_with_timeout(self, closer: AsyncCloser) -> None:
        """Run one asynchronous closer under the shutdown grace period."""
        try:
            await asyncio.wait_for(closer(), timeout=self.config.shutdown_timeout)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    @staticmethod
    async def _run_closer(closer: AsyncCloser) -> None:
        """Adapt a general awaitable closer to an asyncio coroutine."""
        await closer()

    async def acquire_idempotent_response(self, key: str | None) -> tuple[bool, Any | None]:
        """Claim an idempotent operation or await its in-flight response.

        Returns ``(True, None)`` to the request that should execute the
        operation. Concurrent and later duplicates receive ``(False, result)``.
        """
        if key is None:
            return True, None
        now = time.monotonic()
        with self._idempotency_lock:
            cached = self._idempotency_cache.get(key)
            if cached is not None:
                created_at, response = cached
                if now - created_at <= self.config.idempotency_ttl:
                    self._idempotency_cache.move_to_end(key)
                    return False, response
                self._idempotency_cache.pop(key, None)

            pending = self._idempotency_inflight.get(key)
            if pending is None:
                pending = concurrent.futures.Future()
                pending.add_done_callback(self._consume_future_exception)
                self._idempotency_inflight[key] = pending
                return True, None

        return False, await asyncio.wrap_future(pending)

    def complete_idempotent_response(self, key: str | None, response: Any) -> None:
        """Publish a completed response to concurrent and later duplicates."""
        if key is None:
            return
        with self._idempotency_lock:
            self._idempotency_cache[key] = (time.monotonic(), response)
            self._idempotency_cache.move_to_end(key)
            while len(self._idempotency_cache) > self.config.idempotency_cache_size:
                self._idempotency_cache.popitem(last=False)
            pending = self._idempotency_inflight.pop(key, None)
        if pending is not None and not pending.done():
            pending.set_result(response)

    def abort_idempotent_response(self, key: str | None, error: BaseException) -> None:
        """Release concurrent duplicates when the owning operation fails."""
        if key is None:
            return
        with self._idempotency_lock:
            pending = self._idempotency_inflight.pop(key, None)
        if pending is not None and not pending.done():
            pending.set_exception(error)

    @staticmethod
    def _consume_future_exception(future: concurrent.futures.Future[Any]) -> None:
        """Mark shared-future exceptions as observed when no duplicate awaits them."""
        if not future.cancelled():
            future.exception()

    def payload_size(self, payload: Any) -> int:
        """Estimate serialized payload size using ProtoLink's normal serializer."""
        if payload is None:
            return 0
        normalized = Serializer.serialize_to_dict(payload)
        return len(json.dumps(normalized, separators=(",", ":"), default=str).encode("utf-8"))

    def check_payload_limit(self, payload: Any, *, kind: str, url: str | None = None) -> int:
        """Validate a serialized payload against configured byte limits."""
        size = self.payload_size(payload)
        limits = self.config.limits
        maximum = {
            "request": limits.max_request_bytes,
            "response": limits.max_response_bytes,
            "event": limits.max_event_bytes,
        }[kind]
        if size > maximum:
            raise TransportLimitError(
                f"Transport {kind} payload is {size} bytes; configured maximum is {maximum} bytes",
                url=url,
            )
        return size

    @asynccontextmanager
    async def request_slot(self):
        """Bound per-loop concurrent unary requests and update active metrics."""
        loop_id = id(asyncio.get_running_loop())
        semaphore = self._request_semaphores.setdefault(
            loop_id,
            asyncio.Semaphore(self.config.limits.max_concurrent_requests),
        )
        async with semaphore:
            self._metrics.add(requests_started=1, active_requests=1)
            try:
                yield
            finally:
                self._metrics.add(active_requests=-1)

    @asynccontextmanager
    async def stream_slot(self):
        """Bound per-loop concurrent streams and update active metrics."""
        loop_id = id(asyncio.get_running_loop())
        semaphore = self._stream_semaphores.setdefault(
            loop_id,
            asyncio.Semaphore(self.config.limits.max_concurrent_streams),
        )
        async with semaphore:
            self._metrics.add(streams_started=1, active_streams=1)
            try:
                yield
            except BaseException:
                self._metrics.add(streams_failed=1)
                raise
            else:
                self._metrics.add(streams_completed=1)
            finally:
                self._metrics.add(active_streams=-1)

    @asynccontextmanager
    async def inbound_request_slot(self):
        """Bound inbound unary execution and record its complete outcome."""
        loop_id = id(asyncio.get_running_loop())
        semaphore = self._request_semaphores.setdefault(
            loop_id,
            asyncio.Semaphore(self.config.limits.max_concurrent_requests),
        )
        async with semaphore:
            self._metrics.add(requests_started=1, active_requests=1)
            started = time.perf_counter()
            try:
                yield
            except BaseException:
                self._metrics.add(
                    requests_failed=1,
                    total_latency_ms=(time.perf_counter() - started) * 1000,
                )
                raise
            else:
                self._metrics.add(
                    requests_succeeded=1,
                    total_latency_ms=(time.perf_counter() - started) * 1000,
                )
            finally:
                self._metrics.add(active_requests=-1)

    async def run_with_retries(
        self,
        request_spec: ClientRequestSpec,
        context: TransportRequestContext,
        operation: Callable[[TransportRequestContext], Awaitable[T]],
    ) -> T:
        """Run an operation under the configured idempotent retry policy."""
        policy = self.config.retry
        may_retry = request_spec.idempotent and request_spec.method.upper() in policy.retryable_methods
        current = context
        started = time.perf_counter()
        last_error: TransportError | None = None

        for attempt in range(1, policy.max_attempts + 1):
            try:
                result = await operation(current)
                self._metrics.add(
                    requests_succeeded=1,
                    total_latency_ms=(time.perf_counter() - started) * 1000,
                )
                return result
            except TransportError as exc:
                last_error = exc
                if not may_retry or not exc.retryable or attempt >= policy.max_attempts:
                    self._metrics.add(
                        requests_failed=1,
                        total_latency_ms=(time.perf_counter() - started) * 1000,
                    )
                    raise
                self._metrics.add(retries=1)
                delay = min(policy.initial_backoff * (2 ** (attempt - 1)), policy.max_backoff)
                if policy.jitter:
                    delay += random.uniform(0, policy.jitter)
                await asyncio.sleep(delay)
                current = current.next_attempt()
            except Exception:
                self._metrics.add(
                    requests_failed=1,
                    total_latency_ms=(time.perf_counter() - started) * 1000,
                )
                raise

        if last_error is not None:  # pragma: no cover - loop always returns or raises
            raise last_error
        raise RuntimeError("Retry loop exited without a result or transport error")
