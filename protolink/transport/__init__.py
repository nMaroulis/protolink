from __future__ import annotations

import importlib
from typing import Any

from .base import Transport, TransportRequestContext
from .config import RetryPolicy, TransportCapabilities, TransportConfig, TransportLimits
from .errors import (
    TransportConnectionError,
    TransportError,
    TransportLimitError,
    TransportProtocolError,
    TransportRemoteError,
    TransportTimeoutError,
)
from .factory import get_transport
from .metrics import TransportMetricsSnapshot

__all__ = [
    "GRPCTransport",
    "HTTPTransport",
    "RetryPolicy",
    "RuntimeTransport",
    "SSEJSONRPCTransport",
    "Transport",
    "TransportCapabilities",
    "TransportConfig",
    "TransportConnectionError",
    "TransportError",
    "TransportLimitError",
    "TransportLimits",
    "TransportMetricsSnapshot",
    "TransportProtocolError",
    "TransportRemoteError",
    "TransportRequestContext",
    "TransportTimeoutError",
    "WebSocketTransport",
    "get_transport",
]

_EXPORTS = {
    "GRPCTransport": "protolink.transport.grpc_transport.GRPCTransport",
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
