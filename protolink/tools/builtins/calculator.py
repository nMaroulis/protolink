"""A bounded arithmetic tool for agents that need basic calculations."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import Field

from protolink.tools.tool import Tool

_MAX_AST_NODES = 64
_MAX_INTEGER_BITS = 4096
_MAX_EXPONENT = 100
_MAX_ABSOLUTE_FLOAT = 1e308

_Expression = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        description="Arithmetic expression using numbers, parentheses, and +, -, *, /, //, %, or **.",
    ),
]

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _bounded_number(value: Any) -> int | float:
    """Validate that a computed value is a bounded real JSON number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("calculator accepts real numbers only")
    if isinstance(value, int):
        if value.bit_length() > _MAX_INTEGER_BITS:
            raise ValueError(f"calculator integer results are limited to {_MAX_INTEGER_BITS} bits")
        return value
    if not math.isfinite(value) or abs(value) > _MAX_ABSOLUTE_FLOAT:
        raise ValueError("calculator result must be finite and within the supported magnitude")
    return value


def _validate_power(base: int | float, exponent: int | float) -> None:
    """Reject power operations that could create excessive intermediate values."""
    if abs(exponent) > _MAX_EXPONENT:
        raise ValueError(f"calculator exponents are limited to +/-{_MAX_EXPONENT}")
    if isinstance(base, int) and isinstance(exponent, int) and exponent > 0:
        estimated_bits = max(1, base.bit_length()) * exponent
        if estimated_bits > _MAX_INTEGER_BITS:
            raise ValueError(f"calculator integer results are limited to {_MAX_INTEGER_BITS} bits")


def _evaluate(node: ast.AST) -> int | float:
    """Recursively evaluate one node from the restricted arithmetic grammar."""
    if isinstance(node, ast.Constant):
        return _bounded_number(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        operand = _evaluate(node.operand)
        return _bounded_number(_UNARY_OPERATORS[type(node.op)](operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            _validate_power(left, right)
        try:
            value = _BINARY_OPERATORS[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise ValueError("calculator cannot divide by zero") from exc
        except OverflowError as exc:
            raise ValueError("calculator result exceeds the supported magnitude") from exc
        return _bounded_number(value)
    raise ValueError("calculator expression contains an unsupported operation")


async def _run_calculator(expression: _Expression) -> dict[str, Any]:
    """Evaluate one arithmetic expression without executing Python code."""
    candidate = expression.strip()
    if not candidate:
        raise ValueError("calculator expression must not be empty")
    try:
        tree = ast.parse(candidate, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise ValueError("calculator expression is not valid arithmetic") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        raise ValueError(f"calculator expressions are limited to {_MAX_AST_NODES} syntax nodes")
    result = _evaluate(tree.body)
    return {"expression": candidate, "result": result}


def calculator() -> Tool:
    """Create a safe, dependency-free arithmetic tool.

    The tool accepts a single arithmetic expression. It uses a restricted AST
    evaluator rather than ``eval`` and rejects names, calls, attributes,
    booleans, complex values, non-finite values, and resource-heavy powers.

    Returns:
        A fresh :class:`~protolink.tools.Tool` named ``calculator``.
    """
    tool = Tool(
        name="calculator",
        description=(
            "Evaluate bounded arithmetic with numbers, parentheses, and +, -, *, /, //, %, or **. "
            "This tool never executes Python names or functions."
        ),
        input_schema=None,
        output_schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "result": {"anyOf": [{"type": "integer"}, {"type": "number"}]},
            },
            "required": ["expression", "result"],
            "additionalProperties": False,
        },
        tags=["builtin", "math", "read-only"],
        examples=[{"expression": "(18 * 4) + 3"}],
        capabilities=(),
        func=_run_calculator,
    )
    tool._protolink_builtin_id = "calculator"
    return tool
