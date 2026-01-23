from typing import Any, TypeVar

T = TypeVar("T")


def safe_import(*, package: str, module: str | None = None, class_name: str) -> type[Any] | None:
    """Safely import a class, returning None if the module is not available."""
    try:
        if module:
            imported_module = __import__(f"protolink.{package}.{module}", fromlist=[class_name])
        else:
            imported_module = __import__(f"protolink.{package}", fromlist=[class_name])
        return getattr(imported_module, class_name, None)
    except ImportError:
        return None
