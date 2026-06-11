"""Schema inference and conversion utilities for Protolink tools.

This module provides functionality to automatically generate JSON-schema-like
definitions from Python type hints and function signatures.
"""

import inspect
import types
import typing
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints


def _safe_get_type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """Safely extract type hints from a callable.

    Handles potential TypeErrors or other exceptions during type hint resolution.
    """
    try:
        return get_type_hints(func, include_extras=True)
    except TypeError:
        return get_type_hints(func)
    except Exception:
        return {}


def _is_typed_dict(tp: Any) -> bool:
    """Check if a type is a TypedDict."""
    return isinstance(tp, type) and hasattr(tp, "__total__") and hasattr(tp, "__annotations__")


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON schema dictionary."""
    if annotation in (Any, object) or annotation is inspect._empty:
        return {}

    if annotation is None or annotation is type(None):
        return {"type": "null"}

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is None:
        if annotation is str:
            return {"type": "string"}
        if annotation is int:
            return {"type": "integer"}
        if annotation is float:
            return {"type": "number"}
        if annotation is bool:
            return {"type": "boolean"}

        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return {"enum": [m.value for m in annotation]}

        if _is_typed_dict(annotation):
            props: dict[str, Any] = {}
            required: list[str] = []
            total = bool(getattr(annotation, "__total__", True))
            for name, ann in getattr(annotation, "__annotations__", {}).items():
                props[name] = _annotation_to_schema(ann)
                if total:
                    required.append(name)
            schema: dict[str, Any] = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
            return schema

        if is_dataclass(annotation):
            props = {f.name: _annotation_to_schema(f.type) for f in fields(annotation)}
            required = [f.name for f in fields(annotation) if f.default is MISSING and f.default_factory is MISSING]
            schema = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
            return schema

        if isinstance(annotation, type) and hasattr(annotation, "__annotations__"):
            props = {k: _annotation_to_schema(v) for k, v in getattr(annotation, "__annotations__", {}).items()}
            return {"type": "object", "properties": props}

        return {}

    # Union / Optional
    if origin in (typing.Union, types.UnionType):
        variants = [a for a in args if a is not type(None)]
        has_none = len(variants) != len(args)
        any_of = [_annotation_to_schema(v) for v in variants] or [{}]
        if has_none:
            any_of.append({"type": "null"})
        return {"anyOf": any_of}

    # list/tuple/set => array
    if origin in (list, tuple, set):
        item_ann = args[0] if args else Any
        return {"type": "array", "items": _annotation_to_schema(item_ann)}

    # dict => object
    if origin is dict:
        value_ann = args[1] if len(args) == 2 else Any
        return {"type": "object", "additionalProperties": _annotation_to_schema(value_ann)}

    # Literal => enum
    if origin is typing.Literal:
        return {"enum": list(args)}

    return {}


def normalize_schema(schema: Any, title: str | None = None) -> dict[str, Any]:
    """Normalize a schema into a flat dictionary of parameter definitions."""
    if isinstance(schema, dict):
        # If it's already a complex schema, extract properties
        if "properties" in schema:
            props = schema["properties"]
            required_list = schema.get("required", [])
            for name, pdef in props.items():
                if isinstance(pdef, dict):
                    pdef["required"] = name in required_list
            return props

        # Assume it's a mapping of param name -> type
        out = {}
        for name, ann in schema.items():
            out[name] = _annotation_to_schema(ann)
            out[name]["required"] = True  # Default to True for explicit dict-based schema
        return out

    return _annotation_to_schema(schema)


def infer_input_schema(func: Callable[..., Any], *, title: str) -> dict[str, Any]:
    """Infer the input schema for a callable as a flat dictionary of parameters.

    Extracts parameter names, types, and default values.

    Example:
        >>> infer_input_schema(book_hotel, title="book_hotel")
            "input_schema": {
                'location': {'type': 'string', 'required': True},
                'check_in': {'type': 'string', 'required': True},
                'check_out': {'type': 'string', 'required': True},
                'guests': {'type': 'integer', 'default': 2, 'required': False},
                'budget': {'type': 'string', 'default': 'mid-range', 'required': False}
            },
    """
    sig = inspect.signature(func)
    hints = _safe_get_type_hints(func)

    props: dict[str, Any] = {}

    for name, param in sig.parameters.items():
        if name in {"self", "cls"}:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        ann = hints.get(name, param.annotation)
        schema = _annotation_to_schema(ann)

        if param.default is not inspect._empty:
            schema["default"] = param.default
            schema["required"] = False
        else:
            schema["required"] = True

        props[name] = schema

    return props


def infer_output_schema(func: Callable[..., Any], *, title: str) -> str:
    """Infer the output type for a callable.

    Returns the name of the return type annotation as a string.
    """
    hints = _safe_get_type_hints(func)
    ann = hints.get("return", Any)
    if isinstance(ann, type):
        return ann.__name__
    return str(ann)
