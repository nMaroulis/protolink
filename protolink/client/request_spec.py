"""Transport-neutral declarations for outbound ProtoLink operations."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from protolink.types import ContentType, HttpMethod, RequestSourceType


@dataclass(frozen=True)
class ClientRequestSpec:
    """Transport-neutral description of one client request.

    ``channel`` lets multiplexed transports isolate control-plane requests such
    as cancellation from a long-lived streaming data channel. Request/response
    transports may ignore it. ``idempotent`` is an explicit safety declaration:
    configured retry policies never retry a request unless it is true.

    Args:
        name: Stable operation name used by clients and diagnostics.
        path: Transport-neutral endpoint path.
        method: HTTP-style method used consistently across transports.
        response_parser: Optional conversion from wire data to a domain model.
        request_source: Whether input is sent as a body, query parameters, or
            omitted.
        content_type: Optional request media type.
        accept: Optional expected response media type.
        headers: Optional protocol-specific request headers. Transports that do
            not use headers may ignore them.
        channel: Multiplexing channel used to isolate concurrent traffic.
        idempotent: Whether retries and server-side response deduplication are
            safe for this operation.
    """

    name: str
    path: str
    method: HttpMethod
    response_parser: Callable[[Any], Any] | None = None
    request_source: RequestSourceType = "body"
    content_type: ContentType | None = None
    accept: ContentType | None = None
    channel: str = "default"
    idempotent: bool = False
    headers: Mapping[str, str] | None = None
