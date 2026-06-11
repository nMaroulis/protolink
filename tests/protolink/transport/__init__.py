from __future__ import annotations

import importlib
from typing import Any

from .base import Transport
from .factory import get_transport

__all__ = [
    "HTTPTransport",
    "RuntimeTransport",
    "SSEJSONRPCTransport",
    "Transport",
    "WebSocketTransport",
    "get_transport",
]

_EXPORTS = {
    "HTTPTransport": "protolink.transport.http_transport.HTTPTransport",
    "RuntimeTransport": "protolink.transport.runtime_transport.RuntimeTransport",
    "SSEJSONRPCTransport": "protolink.transport.sse_jsonrpc_transport.SSEJSONRPCTransport",
    "WebSocketTransport": "protolink.transport.websocket_transport.WebSocketTransport",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_path, attr = _EXPORTS[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value
