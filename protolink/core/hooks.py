"""Authoritative lifecycle extensions around the default Agent inference loop."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from protolink.core.run_context import RunContext
from protolink.tools.base import BaseTool

if TYPE_CHECKING:
    from protolink.llms.history import ConversationHistory


@dataclass
class ModelRequest:
    """Mutable model input with a detached context and the available tool roster.

    Hooks may edit history or remove tools. They cannot introduce executable tools,
    change the runtime's permissions or bypass action authorization. The history is
    the active conversation; applications must treat injected material as trusted
    instructions only when its provenance warrants that treatment.
    """

    history: ConversationHistory
    tools: dict[str, BaseTool]
    context: RunContext
    step: int


@dataclass
class ToolObservation:
    """A copied successful result to prepare for model context.

    Mutating ``result`` changes the observation, never the committed execution
    receipt. Hooks should be deterministic and free of external side effects:
    recovery can repeat observation preparation after reusing a tool receipt.
    """

    name: str
    result: Any
    context: RunContext
    step: int


@dataclass
class FinalResponse:
    """Proposed final content that hooks can validate or replace before completion."""

    content: Any
    context: RunContext
    step: int


@dataclass(frozen=True)
class AgentHooks:
    """Optional sync/async hooks; failures abort execution and remain visible.

    Callbacks receive ModelRequest, ToolObservation or FinalResponse and mutate
    that object in place, returning None. ``Agent(hooks=[function])`` treats bare
    functions as before_model callbacks. Use this object for named lifecycle
    stages. Authorization remains in ``policy`` and diagnostics in ``telemetry``.
    Increment the Agent execution_version when callback behavior changes.
    """

    before_model: Callable[[ModelRequest], Any] | None = None
    after_tool: Callable[[ToolObservation], Any] | None = None
    before_complete: Callable[[FinalResponse], Any] | None = None

    def __post_init__(self) -> None:
        for callback in (self.before_model, self.after_tool, self.before_complete):
            if callback is not None and not callable(callback):
                raise TypeError("Lifecycle hooks must be callable")


def normalize_hooks(hooks: Iterable[AgentHooks | Callable[..., Any]] | None) -> tuple[AgentHooks, ...]:
    """Validate an executable hook roster once at Agent construction."""
    result = []
    for hook in hooks or ():
        if isinstance(hook, AgentHooks):
            result.append(hook)
        elif callable(hook):
            result.append(AgentHooks(before_model=hook))
        else:
            raise TypeError("hooks must contain AgentHooks or before_model functions")
    return tuple(result)


async def apply_hooks(hooks: tuple[AgentHooks, ...], stage: str, value: Any) -> None:
    """Run callbacks in registration order without swallowing authoritative errors."""
    for hook in hooks:
        callback = getattr(hook, stage)
        if callback is not None:
            result = callback(value)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                raise TypeError(f"{stage} hooks mutate their request and must return None")
