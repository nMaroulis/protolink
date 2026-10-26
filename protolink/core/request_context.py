"""Private application dependencies scoped to one asynchronous request.

Unlike :class:`RunContext`, these values are never attached to tasks or
serialized by ProtoLink. Tools, hooks and model factories read them explicitly
with :func:`current_request_context`; they do not become model-facing inputs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class _RequestContext:
    values: Mapping[str, Any]
    inherit: frozenset[str]


_EMPTY = _RequestContext(MappingProxyType({}), frozenset())
_active: ContextVar[_RequestContext] = ContextVar("protolink_request_context", default=_EMPTY)


def current_request_context() -> Mapping[str, Any]:
    """Return the current request's private, read-only application mapping.

    The mapping is empty outside :func:`request_context`. Values are ordinary
    Python references; nested objects are not copied or made immutable. Freeze
    configuration snapshots before binding them and keep tools' returned values
    free of credentials that the application does not want to expose.
    """
    return _active.get().values


@contextmanager
def request_context(
    values: Mapping[str, Any], *, inherit: Iterable[str] = ()
) -> Generator[Mapping[str, Any], None, None]:
    """Bind private dependencies for tasks started inside this scope.

    ``values`` is shallow-copied immediately. Independent asyncio tasks retain
    independent bindings, including tasks queued by ``start_run`` after this
    scope exits. Nested scopes replace the current mapping and restore it on
    exit. ``inherit`` names the only keys passed to configured local subagents;
    by default children receive none. Network and runtime transport boundaries
    receive none: the receiving application must resolve its own dependencies.

    A synchronous ``with`` block works inside either sync or async application
    code. No dependency is injected into a function signature or tool schema.
    """
    if not isinstance(values, Mapping) or any(not isinstance(key, str) for key in values):
        raise TypeError("request context must be a mapping with string keys")
    if isinstance(inherit, str):
        raise TypeError("inherit must be an iterable of context keys, not a string")
    inherited = frozenset(inherit)
    if any(not isinstance(key, str) for key in inherited) or not inherited.issubset(values):
        raise ValueError("inherit must contain only keys present in the request context")
    context = _RequestContext(MappingProxyType(dict(values)), inherited)
    token = _active.set(context)
    try:
        yield context.values
    finally:
        _active.reset(token)


@contextmanager
def _inherited_request_context() -> Generator[None, None, None]:
    """Apply the parent's explicit allowlist at a local delegation boundary."""
    current = _active.get()
    child = _RequestContext(MappingProxyType({key: current.values[key] for key in current.inherit}), current.inherit)
    token = _active.set(child)
    try:
        yield
    finally:
        _active.reset(token)


@contextmanager
def _isolated_request_context() -> Generator[None, None, None]:
    """Clear ambient application dependencies across a transport boundary."""
    token = _active.set(_EMPTY)
    try:
        yield
    finally:
        _active.reset(token)


async def _isolated_request_stream(source: AsyncIterator[Any]) -> AsyncIterator[Any]:
    """Advance a transport stream without leaking bindings across its yields."""
    receiving_context = _EMPTY
    try:
        while True:
            token = _active.set(receiving_context)
            try:
                try:
                    event = await anext(source)
                except StopAsyncIteration:
                    return
            finally:
                # Receiving middleware may resolve its own dependencies once
                # around the entire generator. Keep that binding for its next
                # advancement while restoring the caller before each yield.
                receiving_context = _active.get()
                _active.reset(token)
            yield event
    finally:
        token = _active.set(receiving_context)
        try:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()
        finally:
            _active.reset(token)
