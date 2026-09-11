"""Optional native tools that execute the exact operation prepared for policy."""

from collections.abc import Awaitable, Callable
from typing import Any

from protolink.core.execution import ToolExecution
from protolink.tools.tool import ActionBuilder, Tool


class PreparedTool(Tool):
    """A tool with a typed input signature and an authorization-aware executor.

    The signature callable describes arguments only; it is never invoked.
    Register this tool on an Agent. Calling it directly fails closed because no
    prepared authorization, cancellation token, or budget is available.
    """

    def __init__(
        self,
        signature: Callable[..., Any],
        *,
        prepare: ActionBuilder,
        execute: Callable[[ToolExecution], Awaitable[Any]],
        capabilities: tuple[str, ...],
        name: str | None = None,
    ) -> None:
        """Infer schemas from ``signature`` and install preparation/execution hooks."""
        template = Tool.from_callable(signature, name=name, capabilities=capabilities, action_builder=prepare)
        super().__init__(
            name=template.name,
            description=template.description,
            input_schema=template.input_schema,
            output_schema=template.output_schema,
            tags=template.tags,
            func=signature,
            capabilities=capabilities,
            action_builder=prepare,
        )
        self._execute_prepared = execute

    async def __call__(self, **kwargs: Any) -> Any:
        """Reject execution outside the Agent authorization pipeline."""
        raise RuntimeError("Prepared tools must execute through an Agent with authorization")

    async def execute_authorized(self, execution: ToolExecution) -> Any:
        """Execute one prepared operation using its live runtime context."""
        return await self._execute_prepared(execution)
