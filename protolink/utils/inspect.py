from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def is_async_callable(fn: Callable[..., Any]) -> bool:
    """Return True if the callable is an async coroutine function.

    This detects functions declared with ``async def``.
    """

    return inspect.iscoroutinefunction(fn)


def callable_expects_input(handler: Callable) -> bool:
    """Check if Callable expects input parameters."""
    sig = inspect.signature(handler)
    # Skip 'self' parameter for instance methods
    params = list(sig.parameters.values())[1:] if inspect.ismethod(handler) else list(sig.parameters.values())
    return len(params) > 0
