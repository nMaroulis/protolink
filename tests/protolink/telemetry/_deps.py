"""Lazy imports for telemetry backends"""


def require_langfuse():
    """Lazy import for Langfuse."""
    try:
        import langfuse  # type: ignore
        from langfuse import Langfuse  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "Langfuse telemetry requires the 'langfuse' library. Install it with: uv add langfuse or uv add protolink[telemetry]"  # noqa: E501
        ) from exc
    return langfuse, Langfuse


def require_langsmith():
    """Lazy import for LangSmith."""
    try:
        import langsmith  # type: ignore
        from langsmith import Client, RunTree  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "LangSmith telemetry requires the 'langsmith' library. Install it with: uv add langsmith or uv add protolink[telemetry]"  # noqa: E501
        ) from exc
    return langsmith, Client, RunTree
