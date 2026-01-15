import inspect
import types
import typing
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints


def _safe_get_type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return get_type_hints(func, include_extras=True)
    except TypeError:
        return get_type_hints(func)
    except Exception:
        return {}


def _is_typed_dict(tp: Any) -> bool:
    return isinstance(tp, type) and hasattr(tp, "__total__") and hasattr(tp, "__annotations__")


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
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
            return {"enum": [m.value for m in annotation]}  # type: ignore[misc]

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
            required = [
                f.name
                for f in fields(annotation)
                if f.default is MISSING and f.default_factory is MISSING  # type: ignore[attr-defined]
            ]
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


def infer_input_schema(func: Callable[..., Any], *, title: str) -> dict[str, Any]:
    sig = inspect.signature(func)
    hints = _safe_get_type_hints(func)

    props: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in {"self", "cls"}:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        ann = hints.get(name, param.annotation)
        schema = _annotation_to_schema(ann)
        if param.default is not inspect._empty:
            schema = {**schema, "default": param.default}
        else:
            required.append(name)

        props[name] = schema

    out: dict[str, Any] = {"title": title, "type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def infer_output_schema(func: Callable[..., Any], *, title: str) -> dict[str, Any]:
    hints = _safe_get_type_hints(func)
    ann = hints.get("return", Any)
    schema = _annotation_to_schema(ann)
    return {"title": title, **schema} if schema else {"title": title}
