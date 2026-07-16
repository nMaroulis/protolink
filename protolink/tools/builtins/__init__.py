"""Opt-in, dependency-free tools for common agent tasks.

Each factory returns a fresh :class:`protolink.tools.Tool`, so built-ins use the
same schema validation, AgentSkill advertising, capability policy, telemetry,
cancellation, and serialization paths as application-defined native tools.
"""

from collections.abc import Callable

from protolink.tools.tool import Tool

from .calculator import calculator
from .clock import current_datetime
from .web import fetch_url, web_search

_BUILTIN_FACTORIES: dict[str, Callable[[], Tool]] = {
    "calculator": calculator,
    "current_datetime": current_datetime,
    "fetch_url": fetch_url,
    "web_search": web_search,
}


def _create_builtin(builtin_id: str) -> Tool:
    """Restore one built-in through the fixed first-party factory registry."""
    factory = _BUILTIN_FACTORIES.get(builtin_id)
    if factory is None:
        raise ValueError(f"Unknown ProtoLink built-in tool: {builtin_id!r}")
    return factory()


__all__ = [
    "calculator",
    "current_datetime",
    "fetch_url",
    "web_search",
]
