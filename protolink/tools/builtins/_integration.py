"""Shared native policy boundary for configured asynchronous service integrations."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Awaitable, Callable
from typing import Any

from protolink.core.actions import RunAction
from protolink.core.artifact import Artifact
from protolink.core.execution import ToolExecution
from protolink.core.part import Part
from protolink.core.run_context import RunContext
from protolink.tools.prepared import PreparedTool


def integration_tool(
    function: Callable[..., Awaitable[dict[str, Any]]],
    *,
    capability: str,
    target: str,
    timeout_seconds: float,
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> PreparedTool:
    """Wrap one typed service operation with an exact preview and bounded wait."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    name = getattr(function, "__name__", type(function).__name__)
    signature = inspect.signature(function)

    def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
        bound = signature.bind(**arguments)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        if validate is not None:
            validate(arguments)
        action = RunAction(
            kind="tool.call",
            name=name,
            payload={"arguments": dict(arguments), "target": target},
            capabilities=frozenset({capability}),
        )
        return action.with_artifacts(
            [
                Artifact(
                    kind="preview",
                    name=name,
                    parts=[Part.json({"target": target, **arguments})],
                )
            ]
        )

    async def execute(execution: ToolExecution) -> dict[str, Any]:
        execution.check()
        remaining = execution.remaining_seconds
        timeout = min(timeout_seconds, remaining) if remaining is not None else timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                return await function(**execution.authorization.action.payload["arguments"])
        except TimeoutError:
            execution.check()
            raise

    tool = PreparedTool(function, prepare=prepare, execute=execute, capabilities=(capability,))
    tool.tags = ["builtin", capability.split(".")[0], "integration"]
    return tool
