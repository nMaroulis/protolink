from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def is_async_callable(fn: Callable[..., Any]) -> bool:
    """Return True if the callable is an async coroutine function.

    This detects functions declared with ``async def``.
    """

    return inspect.iscoroutinefunction(fn)
