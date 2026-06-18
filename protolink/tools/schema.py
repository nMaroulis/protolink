"""JSON Schema inference, normalization, and validation utilities for tools."""

from __future__ import annotations

import copy
import inspect
import types
import typing
from collections.abc import Callable
from dataclasses import MISSING, asdict, fields, is_dataclass
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel, TypeAdapter, ValidationError

JSON_SCHEMA_KEYS = {
    "$defs",
    "$ref",
    "$schema",
    "additionalProperties",
    "allOf",
    "anyOf",
    "const",
    "default",
    "description",
    "enum",
    "examples",
    "format",
    "items",
    "oneOf",
    "properties",
    "required",
    "title",
    "type",
}


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


def _is_pydantic_model(tp: Any) -> bool:
    """Return whether an annotation is a Pydantic BaseModel class."""
    return isinstance(tp, type) and issubclass(tp, BaseModel)


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline local ``$defs`` references for provider-friendly JSON Schema."""
    defs = schema.get("$defs", {})

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                ref_path = value["$ref"]
                if isinstance(ref_path, str) and ref_path.startswith("#/$defs/"):
                    name = ref_path.rsplit("/", 1)[-1]
                    if name in defs:
                        return resolve(copy.deepcopy(defs[name]))
            return {key: resolve(inner) for key, inner in value.items() if key != "$defs"}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return resolve(copy.deepcopy(schema))


def _with_title(schema: dict[str, Any], title: str | None) -> dict[str, Any]:
    """Attach a title when one is requested and the schema does not define one."""
    if title and "title" not in schema:
        schema = dict(schema)
        schema["title"] = title
    return schema


def _looks_like_json_schema(schema: dict[str, Any]) -> bool:
    """Return whether a dict is already a JSON Schema object."""
    if "type" in schema:
        valid_types = {"array", "boolean", "integer", "null", "number", "object", "string"}
        type_value = schema["type"]
        if isinstance(type_value, str):
            return type_value in valid_types
        if isinstance(type_value, list):
            return all(isinstance(item, str) and item in valid_types for item in type_value)
        return False
    return bool(JSON_SCHEMA_KEYS.intersection(schema.keys()))


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON schema dictionary."""
    if annotation in (Any, object) or annotation is inspect._empty:
        return {}

    if isinstance(annotation, str):
        string_aliases = {
            "str": {"type": "string"},
            "string": {"type": "string"},
            "int": {"type": "integer"},
            "integer": {"type": "integer"},
            "float": {"type": "number"},
            "number": {"type": "number"},
            "bool": {"type": "boolean"},
            "boolean": {"type": "boolean"},
            "dict": {"type": "object", "additionalProperties": True},
            "object": {"type": "object", "additionalProperties": True},
            "list": {"type": "array", "items": {}},
            "array": {"type": "array", "items": {}},
            "none": {"type": "null"},
            "null": {"type": "null"},
        }
        return string_aliases.get(annotation.strip().lower(), {})

    if annotation is None or annotation is type(None):
        return {"type": "null"}

    if _is_pydantic_model(annotation):
        return _inline_refs(annotation.model_json_schema())

    try:
        return _inline_refs(TypeAdapter(annotation).json_schema())
    except Exception:
        pass

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
    """Normalize any supported schema shape into a JSON Schema object.

    Accepted inputs:
    - Full JSON Schema objects.
    - Pydantic models and Python type annotations.
    - Legacy flat maps such as ``{"city": str}`` or
      ``{"city": {"type": "string", "required": True}}``.
    """
    if schema is None:
        return _with_title(
            {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            title,
        )

    if isinstance(schema, dict):
        if _looks_like_json_schema(schema):
            normalized = copy.deepcopy(schema)
            if "properties" in normalized and "type" not in normalized:
                normalized["type"] = "object"
            if normalized.get("type") == "object":
                normalized.setdefault("properties", {})
                normalized.setdefault("required", [])
                normalized.setdefault("additionalProperties", False)
            return _with_title(_inline_refs(normalized), title)

        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, definition in schema.items():
            prop_schema: dict[str, Any]
            required_flag: bool | None = None

            if isinstance(definition, dict):
                prop_schema = copy.deepcopy(definition)
                raw_required = prop_schema.pop("required", None)
                required_flag = bool(raw_required) if raw_required is not None else None
                if not _looks_like_json_schema(prop_schema):
                    prop_schema = normalize_schema(prop_schema)
            else:
                prop_schema = _annotation_to_schema(definition)

            if required_flag is None:
                required_flag = "default" not in prop_schema
            if required_flag:
                required.append(str(name))
            properties[str(name)] = prop_schema

        return _with_title(
            {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            title,
        )

    return _with_title(_annotation_to_schema(schema), title)


def infer_input_schema(func: Callable[..., Any], *, title: str) -> dict[str, Any]:
    """Infer a callable input schema as a JSON Schema object."""
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
            schema["default"] = param.default
        else:
            required.append(name)

        props[name] = schema

    return {
        "type": "object",
        "title": title,
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def infer_output_schema(func: Callable[..., Any], *, title: str) -> dict[str, Any]:
    """Infer the output schema for a callable as JSON Schema."""
    hints = _safe_get_type_hints(func)
    ann = hints.get("return", Any)
    return _with_title(_annotation_to_schema(ann), title)


def _coerce_integer(value: Any, path: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{path} must be an integer, got boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("+-").isdigit():
            return int(stripped)
    raise ValueError(f"{path} must be an integer, got {type(value).__name__}")


def _coerce_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool):
        raise ValueError(f"{path} must be a number, got boolean")
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    raise ValueError(f"{path} must be a number, got {type(value).__name__}")


def _coerce_boolean(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"{path} must be a boolean, got {type(value).__name__}")


def _validate_json_schema_value(value: Any, schema: Any, path: str = "value") -> Any:
    """Validate and lightly coerce a value against the JSON Schema subset tools use."""
    if schema in (None, True) or schema == {}:
        return value
    if schema is False:
        raise ValueError(f"{path} is not allowed by schema")
    if not isinstance(schema, dict):
        return value

    if "anyOf" in schema:
        errors = []
        for option in schema["anyOf"]:
            try:
                return _validate_json_schema_value(value, option, path)
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(f"{path} did not match any allowed schema: {'; '.join(errors)}")

    if "oneOf" in schema:
        matches = []
        for option in schema["oneOf"]:
            try:
                matches.append(_validate_json_schema_value(value, option, path))
            except ValueError:
                pass
        if len(matches) != 1:
            raise ValueError(f"{path} must match exactly one allowed schema, matched {len(matches)}")
        return matches[0]

    if "allOf" in schema:
        current = value
        for option in schema["allOf"]:
            current = _validate_json_schema_value(current, option, path)
        return current

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        errors = []
        for option_type in schema_type:
            option_schema = dict(schema)
            option_schema["type"] = option_type
            try:
                return _validate_json_schema_value(value, option_schema, path)
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(f"{path} did not match any allowed type: {'; '.join(errors)}")

    if schema_type is None:
        if "properties" in schema:
            schema_type = "object"
        elif "items" in schema:
            schema_type = "array"

    if schema_type == "null":
        if value is not None:
            raise ValueError(f"{path} must be null")
        coerced = None
    elif schema_type == "boolean":
        coerced = _coerce_boolean(value, path)
    elif schema_type == "integer":
        coerced = _coerce_integer(value, path)
    elif schema_type == "number":
        coerced = _coerce_number(value, path)
    elif schema_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string, got {type(value).__name__}")
        coerced = value
    elif schema_type == "array":
        if not isinstance(value, list | tuple):
            raise ValueError(f"{path} must be an array, got {type(value).__name__}")
        item_schema = schema.get("items", {})
        coerced = [_validate_json_schema_value(item, item_schema, f"{path}[{idx}]") for idx, item in enumerate(value)]
    elif schema_type == "object":
        if isinstance(value, BaseModel):
            value = value.model_dump()
        elif is_dataclass(value) and not isinstance(value, type):
            value = asdict(value)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object, got {type(value).__name__}")

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        additional = schema.get("additionalProperties", True)
        coerced = {}

        for name in required:
            if name not in value:
                raise ValueError(f"{path}.{name} is required")

        for name, prop_schema in properties.items():
            if name in value:
                coerced[name] = _validate_json_schema_value(value[name], prop_schema, f"{path}.{name}")
            elif isinstance(prop_schema, dict) and "default" in prop_schema:
                coerced[name] = copy.deepcopy(prop_schema["default"])

        extras = set(value.keys()) - set(properties.keys())
        if additional is False and extras:
            names = ", ".join(sorted(str(name) for name in extras))
            raise ValueError(f"{path} received unexpected field(s): {names}")
        for name in extras:
            if isinstance(additional, dict):
                coerced[name] = _validate_json_schema_value(value[name], additional, f"{path}.{name}")
            else:
                coerced[name] = value[name]
    else:
        coerced = value

    if "const" in schema and coerced != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and coerced not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']!r}")

    return coerced


def _coerce_with_annotation(value: Any, annotation: Any, path: str) -> Any:
    """Coerce one value with a Python annotation when Pydantic can handle it."""
    if annotation in (Any, object, inspect._empty):
        return value
    try:
        adapter = TypeAdapter(annotation)
    except Exception:
        return value
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {}
        message = first_error.get("msg", str(exc))
        raise ValueError(f"{path} failed annotation validation: {message}") from exc


def validate_tool_args(
    args: dict[str, Any] | None,
    input_schema: dict[str, Any] | None,
    *,
    type_hints: dict[str, Any] | None = None,
    signature: inspect.Signature | None = None,
) -> dict[str, Any]:
    """Validate and coerce tool call arguments before execution."""
    raw_args = dict(args or {})
    if input_schema:
        schema = normalize_schema(input_schema)
        raw_args = _validate_json_schema_value(raw_args, schema, "tool args")

    if signature is not None:
        parameters = {
            name: param
            for name, param in signature.parameters.items()
            if name not in {"self", "cls"}
            and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        }
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
        if not accepts_kwargs:
            extras = set(raw_args) - set(parameters)
            if extras:
                names = ", ".join(sorted(extras))
                raise ValueError(f"tool args received unexpected field(s): {names}")
        for name, param in parameters.items():
            if name not in raw_args and param.default is inspect._empty:
                raise ValueError(f"tool args.{name} is required")

    if type_hints:
        for name, annotation in type_hints.items():
            if name == "return" or name not in raw_args:
                continue
            raw_args[name] = _coerce_with_annotation(raw_args[name], annotation, f"tool args.{name}")

    return raw_args
