"""Dependency-free transport metrics for health checks and observability."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TransportMetricsSnapshot:
    """Immutable counters and latency totals for one transport instance.

    Request and stream counters describe logical operations, while ``retries``
    counts additional wire attempts. Byte counters measure serialized payloads.
    ``total_latency_ms`` is cumulative request latency so callers can derive an
    average without the transport imposing a metrics backend.
    """

    requests_started: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    retries: int = 0
    streams_started: int = 0
    streams_completed: int = 0
    streams_failed: int = 0
    active_requests: int = 0
    active_streams: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    total_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible metrics mapping."""
        return asdict(self)


class TransportMetrics:
    """Thread-safe mutable recorder backing transport metric snapshots."""

    _FIELDS = tuple(TransportMetricsSnapshot.__dataclass_fields__)

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._values: dict[str, int | float] = dict.fromkeys(self._FIELDS, 0)
        self._lock = threading.Lock()

    def add(self, **values: int | float) -> None:
        """Atomically add values to known counters."""
        if not self.enabled:
            return
        with self._lock:
            for name, value in values.items():
                if name not in self._values:
                    raise KeyError(f"Unknown transport metric: {name}")
                self._values[name] += value

    def snapshot(self) -> TransportMetricsSnapshot:
        """Return a consistent immutable snapshot."""
        with self._lock:
            values = self._values.copy()
        return TransportMetricsSnapshot(
            requests_started=int(values["requests_started"]),
            requests_succeeded=int(values["requests_succeeded"]),
            requests_failed=int(values["requests_failed"]),
            retries=int(values["retries"]),
            streams_started=int(values["streams_started"]),
            streams_completed=int(values["streams_completed"]),
            streams_failed=int(values["streams_failed"]),
            active_requests=int(values["active_requests"]),
            active_streams=int(values["active_streams"]),
            bytes_sent=int(values["bytes_sent"]),
            bytes_received=int(values["bytes_received"]),
            total_latency_ms=float(values["total_latency_ms"]),
        )
