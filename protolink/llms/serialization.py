"""Serialization helpers for LLM conversation history."""

from dataclasses import asdict, is_dataclass
from typing import Any


def json_history_default(obj: Any) -> Any:
    """Convert framework objects to JSON values for LLM history messages."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)
