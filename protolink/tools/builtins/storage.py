"""Small JSON key/value tools over an application-owned Storage namespace."""

from __future__ import annotations

import json
import threading
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import Field

from protolink.storage import Storage
from protolink.tools.builtins._integration import integration_tool
from protolink.tools.prepared import PreparedTool

_Key = Annotated[str, Field(min_length=1, max_length=256)]
_Limit = Annotated[int, Field(ge=1, le=1000)]
_Offset = Annotated[int, Field(ge=0)]


def _json_copy(value: Any, limit: int) -> Any:
    """Validate JSON compatibility and detach mutable values at the storage boundary."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Storage values must be finite JSON data") from None
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError("Storage data exceeds the configured byte limit")
    return json.loads(encoded)


def storage_tools(
    storage: Storage,
    *,
    allow_write: bool = False,
    max_value_bytes: int = 65536,
    max_store_bytes: int = 1048576,
    max_keys: int = 1000,
) -> tuple[PreparedTool, ...]:
    """Expose JSON get/list and optional set/delete operations in one namespace.

    Args:
        storage: Existing Storage instance dedicated to these tools. Its payload
            must be a string-keyed JSON object or None. No load occurs at setup.
        allow_write: Add set_value/delete_value with ``storage.write``. Reads use
            ``storage.read``. Ordinary Agent policies must be configured explicitly.
        max_value_bytes: Maximum UTF-8 JSON bytes for one value, default 64 KiB.
        max_store_bytes: Maximum UTF-8 JSON bytes for the whole map, default 1 MiB.
        max_keys: Maximum stored keys, default 1,000.

    Reuse the returned tools to share their lock. Reads/writes use the synchronous
    Storage contract and complete without an asyncio suspension; adapters should
    be fast. Updates load/save the whole map. Give this bundle exclusive ownership
    of its namespace: Storage has no cross-process transaction or compare-and-swap
    contract. Do not share it with Agent state or checkpoint storage. JSON null is
    distinguished from a missing key by ``found``. Deleting a missing key is a no-op.
    """
    for value in (max_value_bytes, max_store_bytes, max_keys):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("Storage limits must be positive integers")
    lock = threading.RLock()

    def load() -> dict[str, Any]:
        raw = storage.load()
        if raw is None:
            return {}
        if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
            raise ValueError("The selected Storage namespace must contain a JSON object")
        if len(raw) > max_keys:
            raise ValueError("Storage exceeds max_keys")
        return _json_copy(raw, max_store_bytes)

    async def get_value(key: _Key) -> dict[str, Any]:
        """Read a JSON value by key. found=false means absent; a stored null has found=true."""
        with lock:
            data = load()
            return {
                "key": key,
                "found": key in data,
                "value": _json_copy(data[key], max_value_bytes) if key in data else None,
            }

    async def list_keys(prefix: str = "", offset: _Offset = 0, limit: _Limit = 100) -> dict[str, Any]:
        """List sorted keys with an optional literal prefix. Offsets can shift if the store changes."""
        with lock:
            keys = sorted(key for key in load() if key.startswith(prefix))
            selected = keys[offset : offset + limit]
            end = offset + len(selected)
            return {"keys": selected, "next_offset": end if end < len(keys) else None}

    async def set_value(key: _Key, value: Any) -> dict[str, Any]:
        """Store or replace one JSON value. The exact key/value is previewed before authorization."""
        with lock:
            data = load()
            exists = key in data
            data[key] = _json_copy(value, max_value_bytes)
            if len(data) > max_keys:
                raise ValueError("Storage would exceed max_keys")
            storage.save(_json_copy(data, max_store_bytes))
            return {"key": key, "created": not exists}

    async def delete_value(key: _Key) -> dict[str, Any]:
        """Delete exactly one key, preserving all other keys in the configured namespace."""
        with lock:
            data = load()
            exists = key in data
            if exists:
                del data[key]
                storage.save(data)
            return {"key": key, "deleted": exists}

    def validate(arguments: dict[str, Any]) -> None:
        if "key" in arguments and (not arguments["key"].strip() or "\x00" in arguments["key"]):
            raise ValueError("Keys must be nonblank and contain no NUL")
        if "value" in arguments:
            arguments["value"] = _json_copy(arguments["value"], max_value_bytes)

    functions: list[tuple[Callable[..., Awaitable[dict[str, Any]]], str]] = [
        (get_value, "storage.read"),
        (list_keys, "storage.read"),
    ]
    if allow_write:
        functions += [(set_value, "storage.write"), (delete_value, "storage.write")]
    return tuple(
        integration_tool(
            function,
            capability=capability,
            target=f"{type(storage).__name__}:configured namespace",
            timeout_seconds=30,
            validate=validate,
        )
        for function, capability in functions
    )
