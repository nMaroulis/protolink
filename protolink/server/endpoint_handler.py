from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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


@dataclass(frozen=True, slots=True)
class EndpointRequest:
    """Transport-neutral view of an inbound HTTP-style request.

    Most ProtoLink endpoints only need a body or query mapping. Protocol
    adapters sometimes also need service headers and route parameters, so
    ``request_source="request"`` provides those details without coupling the
    server layer to Starlette or FastAPI request objects.
    """

    body: Any = None
    query_params: Mapping[str, str] = field(default_factory=dict)
    path_params: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    method: str = ""
    url: str = ""
    principal_id: str | None = None
