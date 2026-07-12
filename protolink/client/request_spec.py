from collections.abc import Callable
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
