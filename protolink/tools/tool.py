import inspect
import typing
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import Any, ClassVar

from protolink.core.actions import RunAction
from protolink.core.run_context import RunContext
from protolink.tools.base import BaseTool
from protolink.tools.schema import infer_input_schema, infer_output_schema, normalize_schema, validate_tool_args

ActionBuilder = Callable[[dict[str, Any], RunContext], RunAction | Awaitable[RunAction]]
"""Callable that enriches a tool action before policy evaluation."""


@dataclass
class Tool(BaseTool):
    """Native Protolink tool wrapper.

    This class adapts a Python callable into the :class:`~protolink.tools.base.BaseTool`
    interface.

    In addition to storing basic metadata (name/description/tags), it can
    automatically infer JSON Schema ``input_schema`` and ``output_schema``
    definitions from the wrapped function's signature and type annotations.
    """

    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: Any | None
    tags: list[str] | None

    func: Callable[..., Any]
    args: dict[str, Any] | None = None
    examples: list[Any] | None = None
    capabilities: Collection[str] | None = None
    action_builder: ActionBuilder | None = field(default=None, repr=False)
    _signature: inspect.Signature = field(init=False, repr=False)
    _type_hints: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    _protolink_builtin_id: str | None = field(init=False, repr=False, default=None)
    _protolink_validates_args: ClassVar[bool] = True

    def __post_init__(self) -> None:
        """Populate missing schemas.

        If ``input_schema`` and/or ``output_schema`` are not provided explicitly,
        they are inferred from the wrapped callable.
        """
        self._signature = inspect.signature(self.func)
        try:
            self._type_hints = typing.get_type_hints(self.func, include_extras=True)
        except Exception:
            self._type_hints = {}

        # Input Schema
        if self.input_schema is None:
            self.input_schema = infer_input_schema(self.func, title=f"{self.name}Input")
        else:
            self.input_schema = normalize_schema(self.input_schema, title=f"{self.name}Input")
        # Output Schema
        if self.output_schema is None:
            self.output_schema = infer_output_schema(self.func, title=f"{self.name}Output")
        else:
            self.output_schema = normalize_schema(self.output_schema, title=f"{self.name}Output")

        if self.tags is None:
            self.tags = []
        if self.examples is None:
            self.examples = []
        if self.capabilities is None:
            self.capabilities = ()
        else:
            self.capabilities = tuple(dict.fromkeys(str(item) for item in self.capabilities if str(item)))

    def validate_args(self, kwargs: dict[str, Any] | None) -> dict[str, Any]:
        """Validate and coerce keyword arguments before tool execution."""
        return validate_tool_args(
            kwargs,
            self.input_schema,
            type_hints=self._type_hints,
            signature=self._signature,
        )

    async def __call__(self, **kwargs: Any) -> Any:
        """Invoke the underlying tool function.

        The wrapped function may be either synchronous (``def``) or asynchronous
        (``async def``). This method normalizes both forms to an async call.
        """

        kwargs = self.validate_args(kwargs)
        result = self.func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def prepare_action(self, arguments: dict[str, Any], context: RunContext) -> RunAction:
        """Build the concrete runtime action evaluated before this tool runs.

        ``action_builder`` lets an application attach structured preview
        artifacts or metadata without moving its domain logic into Protolink.
        The tool's declared capabilities are always merged into the returned
        action so a custom builder cannot accidentally bypass policy checks.

        Args:
            arguments: Validated keyword arguments proposed for the tool call.
            context: Typed context for the active run.

        Returns:
            A domain-neutral ``RunAction`` ready for policy evaluation.

        Raises:
            TypeError: The configured builder does not return a ``RunAction``.
        """
        action = RunAction(
            kind="tool.call",
            name=self.name,
            payload={"arguments": arguments},
            capabilities=frozenset(self.capabilities or ()),
            description=self.description or None,
        )
        if self.action_builder is None:
            return action

        prepared = self.action_builder(arguments, context)
        if inspect.isawaitable(prepared):
            prepared = await prepared
        if not isinstance(prepared, RunAction):
            raise TypeError("Tool action_builder must return RunAction")
        prepared = prepared.with_capabilities(self.capabilities or ())
        return prepared.with_artifacts(prepared.artifacts)
