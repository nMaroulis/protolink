"""Official A2A protocol adapters.

ProtoLink's internal models remain optimized for its Python runtime.  Adapters
in this package translate those models at the network boundary so protocol
compatibility does not leak into agent business logic.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "A2A_PROTOCOL_VERSION",
    "A2AClientError",
    "A2AJSONRPCAdapter",
    "A2AJSONRPCClientAdapter",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    value = getattr(importlib.import_module("protolink.a2a.v1"), name)
    globals()[name] = value
    return value
