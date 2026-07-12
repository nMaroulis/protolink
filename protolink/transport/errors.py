"""Typed exceptions raised consistently by ProtoLink transports."""

from __future__ import annotations


class TransportError(Exception):
    """Base exception for transport-layer failures.

    Args:
        message: Human-readable failure description.
        url: Remote or local endpoint associated with the failure.
        request_id: Correlation identifier for the logical request.
        retryable: Whether a retry policy may safely retry this failure.
        status_code: Optional protocol-native status code.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        status_code: int | str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.request_id = request_id
        self.retryable = retryable
        self.status_code = status_code


class TransportConnectionError(TransportError, ConnectionError):
    """The transport could not establish or retain a connection."""


class TransportTimeoutError(TransportError, TimeoutError):
    """A transport operation exceeded its configured deadline."""


class TransportProtocolError(TransportError, RuntimeError):
    """A peer sent malformed or protocol-incompatible data."""


class TransportRemoteError(TransportError, RuntimeError):
    """A reachable peer rejected or failed the requested operation."""


class TransportLimitError(TransportError, ValueError):
    """A serialized request, response, or stream event exceeded its byte limit."""
