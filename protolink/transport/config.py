"""Shared configuration and capability declarations for ProtoLink transports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TransportCapabilities:
    """Describe behavior guaranteed by a transport implementation.

    Applications normally inspect this through ``transport.capabilities``
    rather than constructing it directly.

    Args:
        networked: Whether the transport crosses a process/network boundary.
        streaming: Whether ``subscribe()`` yields live task events.
        tls: Whether the transport supports native TLS configuration.
        bidirectional: Whether one connection can carry traffic both ways.
        persistent_connections: Whether clients pool or retain connections.
    """

    networked: bool = True
    streaming: bool = False
    tls: bool = False
    bidirectional: bool = False
    persistent_connections: bool = False


@dataclass(frozen=True, slots=True)
class TransportLimits:
    """Bound transport resource usage.

    Args:
        max_request_bytes: Maximum serialized outbound request size.
        max_response_bytes: Maximum serialized unary response size.
        max_event_bytes: Maximum serialized event size in a stream.
        max_concurrent_requests: Per-event-loop unary request concurrency.
        max_concurrent_streams: Per-event-loop active stream concurrency.
    """

    max_request_bytes: int = 16 * 1024 * 1024
    max_response_bytes: int = 16 * 1024 * 1024
    max_event_bytes: int = 4 * 1024 * 1024
    max_concurrent_requests: int = 100
    max_concurrent_streams: int = 100

    def __post_init__(self) -> None:
        """Reject limits that cannot safely bound resources."""
        for name in (
            "max_request_bytes",
            "max_response_bytes",
            "max_event_bytes",
            "max_concurrent_requests",
            "max_concurrent_streams",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

    def to_dict(self) -> dict[str, int]:
        """Return JSON-safe limit settings."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configure bounded retries for explicitly idempotent requests.

    ``max_attempts=1`` disables retries and is the default. ProtoLink never
    retries a request unless its ``ClientRequestSpec`` declares it idempotent.

    Args:
        max_attempts: Total attempts including the initial call.
        initial_backoff: Delay before the first retry in seconds.
        max_backoff: Maximum delay between attempts in seconds.
        jitter: Random delay added to each backoff in seconds.
        retryable_methods: HTTP-style methods eligible for retry when the
            request spec is also marked idempotent.
    """

    max_attempts: int = 1
    initial_backoff: float = 0.1
    max_backoff: float = 2.0
    jitter: float = 0.1
    retryable_methods: frozenset[str] = frozenset({"DELETE", "GET", "POST", "PUT"})

    def __post_init__(self) -> None:
        """Validate retry timing and attempt bounds."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.initial_backoff < 0 or self.max_backoff < 0 or self.jitter < 0:
            raise ValueError("retry backoff and jitter values must not be negative")
        if self.max_backoff < self.initial_backoff:
            raise ValueError("max_backoff must be greater than or equal to initial_backoff")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe retry settings."""
        return {
            "max_attempts": self.max_attempts,
            "initial_backoff": self.initial_backoff,
            "max_backoff": self.max_backoff,
            "jitter": self.jitter,
            "retryable_methods": sorted(self.retryable_methods),
        }


@dataclass(frozen=True, slots=True)
class TransportConfig:
    """Configure production behavior shared by every transport.

    The default configuration preserves existing behavior: requests are not
    retried, metrics are collected locally, and conservative resource limits
    protect network and in-process transports alike.

    Args:
        limits: Request, response, event, and concurrency limits.
        retry: Retry policy for explicitly idempotent requests.
        keepalive_interval: Optional connection keepalive interval in seconds.
        keepalive_timeout: Seconds to wait for a keepalive response.
        shutdown_timeout: Grace period for transport shutdown.
        idempotency_ttl: Seconds to retain completed idempotent responses.
        idempotency_cache_size: Maximum cached idempotent responses.
        collect_metrics: Record in-process transport counters and latency.
    """

    limits: TransportLimits = field(default_factory=TransportLimits)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    keepalive_interval: float | None = 20.0
    keepalive_timeout: float = 20.0
    shutdown_timeout: float = 5.0
    idempotency_ttl: float = 300.0
    idempotency_cache_size: int = 1024
    collect_metrics: bool = True

    def __post_init__(self) -> None:
        """Validate shared lifecycle and cache settings."""
        if self.keepalive_interval is not None and self.keepalive_interval <= 0:
            raise ValueError("keepalive_interval must be greater than zero or None")
        if self.keepalive_timeout <= 0 or self.shutdown_timeout <= 0:
            raise ValueError("keepalive_timeout and shutdown_timeout must be greater than zero")
        if self.idempotency_ttl <= 0 or self.idempotency_cache_size <= 0:
            raise ValueError("idempotency cache settings must be greater than zero")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete transport configuration."""
        return {
            "limits": self.limits.to_dict(),
            "retry": self.retry.to_dict(),
            "keepalive_interval": self.keepalive_interval,
            "keepalive_timeout": self.keepalive_timeout,
            "shutdown_timeout": self.shutdown_timeout,
            "idempotency_ttl": self.idempotency_ttl,
            "idempotency_cache_size": self.idempotency_cache_size,
            "collect_metrics": self.collect_metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransportConfig:
        """Restore a transport configuration from serialized data."""
        values = dict(data)
        limits_data = values.pop("limits", {})
        retry_data = dict(values.pop("retry", {}))
        methods = retry_data.get("retryable_methods")
        if methods is not None:
            retry_data["retryable_methods"] = frozenset(methods)
        return cls(
            limits=TransportLimits(**limits_data),
            retry=RetryPolicy(**retry_data),
            **values,
        )
