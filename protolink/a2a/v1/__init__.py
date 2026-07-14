"""A2A protocol version 1.0 JSON-RPC support."""

from __future__ import annotations

import importlib
from typing import Any

from protolink.a2a.v1.serialization import (
    A2A_AGENT_CARD_PATH,
    A2A_PROTOCOL_VERSION,
    agent_card_to_a2a,
    artifact_from_a2a,
    message_from_a2a,
    message_to_a2a,
    task_from_a2a,
    task_to_a2a,
)

__all__ = [
    "A2A_AGENT_CARD_PATH",
    "A2A_PROTOCOL_VERSION",
    "A2AClientError",
    "A2AInterface",
    "A2AJSONRPCAdapter",
    "A2AJSONRPCClientAdapter",
    "agent_card_to_a2a",
    "artifact_from_a2a",
    "message_from_a2a",
    "message_to_a2a",
    "task_from_a2a",
    "task_to_a2a",
]

_LAZY_EXPORTS = {
    "A2AJSONRPCAdapter": "protolink.a2a.v1.adapter.A2AJSONRPCAdapter",
    "A2AClientError": "protolink.a2a.v1.client.A2AClientError",
    "A2AInterface": "protolink.a2a.v1.client.A2AInterface",
    "A2AJSONRPCClientAdapter": "protolink.a2a.v1.client.A2AJSONRPCClientAdapter",
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_path, attribute = target.rsplit(".", 1)
    value = getattr(importlib.import_module(module_path), attribute)
    globals()[name] = value
    return value
