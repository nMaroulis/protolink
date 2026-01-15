import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from protolink.tools.base import BaseTool
from protolink.tools.schema import infer_input_schema, infer_output_schema


@dataclass
class Tool(BaseTool):
    """Native Protolink tool wrapper.

    This class adapts a Python callable into the :class:`~protolink.tools.base.BaseTool`
    interface.

    In addition to storing basic metadata (name/description/tags), it can
    automatically infer simple JSON-schema-like ``input_schema`` and
    ``output_schema`` definitions from the wrapped function's signature and type
    annotations.
    """

    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    tags: list[str] | None

    func: Callable[..., Any]
    args: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Populate missing schemas.

        If ``input_schema`` and/or ``output_schema`` are not provided explicitly,
        they are inferred from the wrapped callable.
        """
        if self.input_schema is None:
            self.input_schema = infer_input_schema(self.func, title=f"{self.name}Input")
        if self.output_schema is None:
            self.output_schema = infer_output_schema(self.func, title=f"{self.name}Output")

    async def __call__(self, **kwargs: Any) -> Any:
        """Invoke the underlying tool function.

        The wrapped function may be either synchronous (``def``) or asynchronous
        (``async def``). This method normalizes both forms to an async call.
        """

        result = self.func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
