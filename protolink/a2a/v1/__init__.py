"""A2A protocol version 1.0 JSON-RPC support."""

from protolink.a2a.v1.adapter import A2AJSONRPCAdapter
from protolink.a2a.v1.serialization import (
    A2A_AGENT_CARD_PATH,
    A2A_PROTOCOL_VERSION,
    agent_card_to_a2a,
    message_from_a2a,
    message_to_a2a,
    task_to_a2a,
)

__all__ = [
    "A2A_AGENT_CARD_PATH",
    "A2A_PROTOCOL_VERSION",
    "A2AJSONRPCAdapter",
    "agent_card_to_a2a",
    "message_from_a2a",
    "message_to_a2a",
    "task_to_a2a",
]
