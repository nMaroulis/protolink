from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from protolink.types import HttpMethod


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    path: str
    method: HttpMethod
    handler: Callable[..., Awaitable]
    content_type: Literal["json", "html"] = "json"
    streaming: bool = False
    mode: Literal["request_response", "stream"] = "request_response"
    request_parser: Callable[[Any], Any] | None = None
    request_source: Literal["none", "body", "query_params", "form", "headers", "path_params"] = "none"
