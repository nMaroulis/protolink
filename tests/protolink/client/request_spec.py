from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from protolink.types import ContentType, HttpMethod, RequestSourceType


@dataclass(frozen=True)
class ClientRequestSpec:
    name: str
    path: str
    method: HttpMethod
    response_parser: Callable[[Any], Any] | None = None
    request_source: RequestSourceType = "body"
    content_type: ContentType | None = None
    accept: ContentType | None = None
