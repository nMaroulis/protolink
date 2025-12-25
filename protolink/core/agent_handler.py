from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from protolink.types import HttpMethod


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    path: str
    method: HttpMethod
    handler: Callable[..., Awaitable]
    content_type: Literal["json", "html"] = "json"
    streaming: bool = False
    is_async: bool = False
    mode: Literal["request_response", "stream"] = "request_response"
