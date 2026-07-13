"""Official A2A protocol adapters.

ProtoLink's internal models remain optimized for its Python runtime.  Adapters
in this package translate those models at the network boundary so protocol
compatibility does not leak into agent business logic.
"""

from protolink.a2a.v1 import A2A_PROTOCOL_VERSION, A2AJSONRPCAdapter

__all__ = ["A2A_PROTOCOL_VERSION", "A2AJSONRPCAdapter"]
