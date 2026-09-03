import inspect
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import Any, ClassVar

from protolink.core.actions import RunAction
from protolink.core.run_context import RunContext
from protolink.tools.base import BaseTool
from protolink.tools.schema import (
    _safe_get_type_hints,
    infer_input_schema,
    infer_output_schema,
    normalize_schema,
    validate_tool_args,
)

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
    _protolink_knowledge_tool: bool = field(init=False, repr=False, default=False)
    _protolink_knowledge_name: str | None = field(init=False, repr=False, default=None)
    _protolink_ephemeral_result: bool = field(init=False, repr=False, default=False)
    _protolink_validates_args: ClassVar[bool] = True

    @classmethod
    def from_callable(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: Any | None = None,
        tags: list[str] | None = None,
        examples: list[Any] | None = None,
        capabilities: Collection[str] | None = None,
        action_builder: ActionBuilder | None = None,
    ) -> "Tool":
        """Create a reusable tool from a typed Python callable.

        The callable's name and cleaned docstring supply default metadata.
        Callables without a docstring use ``"Call <name>."``. Explicit metadata
        takes precedence, and missing schemas are inferred as in the regular
        constructor. Use ``agent.add_tool(func)`` for inferred defaults, or
        register this configured wrapper with ``agent.add_tool(tool)`` to keep
        explicit metadata when invoking through Agent policy and task execution.

        Args:
            func: Synchronous or asynchronous callable to wrap.
            name: Public tool name; defaults to the callable's name or class name.
            description: Tool purpose; defaults to the callable's docstring.
            input_schema: Optional schema overriding inferred keyword arguments.
            output_schema: Optional schema overriding the return annotation.
            tags: Optional discovery and presentation labels.
            examples: Optional examples advertised on the agent's skill card.
            capabilities: Permission capabilities required before execution.
            action_builder: Optional callback enriching the prepared runtime action.

        Returns:
            A tool with the same schema, validation, and policy metadata as one
            constructed explicitly.

        Raises:
            TypeError: ``func`` is not callable or cannot be inspected, or the
                explicit or inferred name is not a string.
            ValueError: The tool name is empty or whitespace-only, or the
                callable signature or explicit schema is invalid.
        """
        if not callable(func):
            raise TypeError("Tool.from_callable requires a callable")
        tool_name = name if name is not None else getattr(func, "__name__", type(func).__name__)
        if not isinstance(tool_name, str):
            raise TypeError("Tool name must be a string")
        if not tool_name.strip():
            raise ValueError("Tool name must not be empty or whitespace-only")
        return cls(
            name=tool_name,
            description=description if description is not None else inspect.getdoc(func) or f"Call {tool_name}.",
            input_schema=input_schema,
            output_schema=output_schema,
            tags=tags,
            func=func,
            examples=examples,
            capabilities=capabilities,
            action_builder=action_builder,
        )

    def __post_init__(self) -> None:
        """Populate missing schemas.

        If ``input_schema`` and/or ``output_schema`` are not provided explicitly,
        they are inferred from the wrapped callable.
        """
        self._signature = inspect.signature(self.func)
        self._type_hints = _safe_get_type_hints(self.func)

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
