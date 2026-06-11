from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from protolink.types import HttpMethod, RequestSourceType


@dataclass(frozen=True)
class EndpointSpec:
    """Transport-agnostic endpoint declaration used by Protolink servers.

    Servers create endpoint specs; transports decide how to expose them over
    HTTP, WebSocket, runtime memory, or any future protocol. ``streaming`` and
    ``mode="stream"`` identify handlers that return async iterators instead of
    single request/response payloads.
    """

    name: str
    path: str
    method: HttpMethod
    handler: Callable[..., Any]  # Can be sync or async
    content_type: Literal["json", "html"] = "json"
    streaming: bool = False
    mode: Literal["request_response", "stream"] = "request_response"
    request_parser: Callable[[Any], Any] | None = None
    request_source: RequestSourceType = "none"
