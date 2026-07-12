"""Shared stream-lifecycle helpers for transport implementations."""

from __future__ import annotations

from typing import Any


def is_stream_terminal_event(event_payload: Any, *, event_final: bool) -> bool:
    """Return whether an event should close the transport-level task stream.

    Nested operations such as an LLM call may emit their own ``final=True`` event before the surrounding task completes.
    Typed task streams therefore close only on a final ``task_status_update``. Untyped custom events retain the
    historical behavior where ``final=True`` closes the stream.

    Args:
        event_payload: Serialized event emitted by the endpoint handler.
        event_final: Whether that event declares itself final.

    Returns:
        ``True`` when the transport should stop yielding task events.
    """
    if not event_final:
        return False
    if not isinstance(event_payload, dict):
        return True
    event_type = event_payload.get("type")
    if event_type is None:
        return True
    return event_type == "task_status_update"
