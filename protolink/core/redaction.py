"""Shared redaction policy for runtime observability objects.

The runtime layer emits data that applications often persist: events, reports, approval requests, context manifests, and
telemetry payloads. This module keeps secret masking in one small, dependency-free policy object so those surfaces can
share the same behavior without coupling to a particular telemetry backend.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "credentials",
        "data_base64",
        "password",
        "secret",
        "token",
    }
)
"""Common key names that should be redacted from persisted observability data."""


@dataclass(frozen=True)
class RedactionPolicy:
    """Recursive redaction policy for JSON-compatible runtime data.

    Args:
        sensitive_keys: Case-insensitive field names treated as secrets. Keys are normalized by lower-casing and
            replacing ``-`` with ``_``.
        replacement: Value written in place of secret-bearing fields.
        max_string_length: Optional maximum length for non-secret strings.
        sensitive_values: Known nonempty secrets to mask wherever they occur in
            text, including command output and error messages. Matching is literal
            and case-sensitive, before optional string truncation.

    The policy also redacts keys ending in common secret suffixes such as ``"_api_key"``, ``"_secret"``, ``"_token"``,
    ``"_password"``, and ``"_credentials"``.
    """

    sensitive_keys: frozenset[str] = field(default_factory=lambda: DEFAULT_SENSITIVE_KEYS)
    replacement: str = "[REDACTED]"
    max_string_length: int | None = None
    sensitive_values: frozenset[str] = field(default_factory=frozenset, repr=False)
    _value_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Normalize keys and compile literal secret matches with longest values first."""
        normalized = frozenset(_normalize_key(key) for key in self.sensitive_keys)
        object.__setattr__(self, "sensitive_keys", normalized)
        values = frozenset(self.sensitive_values)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("sensitive_values must contain nonempty strings")
        object.__setattr__(self, "sensitive_values", values)
        if values:
            pattern = "|".join(re.escape(value) for value in sorted(values, key=lambda value: (-len(value), value)))
            object.__setattr__(self, "_value_pattern", re.compile(pattern))
        if self.max_string_length is not None and self.max_string_length < 0:
            raise ValueError("max_string_length must be non-negative")

    def is_sensitive_key(self, key: Any) -> bool:
        """Return whether ``key`` should have its value redacted."""
        normalized = _normalize_key(str(key))
        return normalized in self.sensitive_keys or normalized.endswith(
            ("_api_key", "_secret", "_token", "_password", "_credentials")
        )

    def redact(self, value: Any) -> Any:
        """Return ``value`` with sensitive fields masked recursively."""
        return _redact_value(_to_jsonable(value), self)


def _normalize_key(key: str) -> str:
    return key.lower().replace("-", "_")


DEFAULT_REDACTION_POLICY = RedactionPolicy()
"""Default runtime redaction policy used by reports and local telemetry."""


def _redact_value(value: Any, policy: RedactionPolicy) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            string_key = str(key)
            if policy.is_sensitive_key(string_key):
                redacted[string_key] = policy.replacement
            else:
                redacted[string_key] = _redact_value(item, policy)
        return redacted

    if isinstance(value, list):
        return [_redact_value(item, policy) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, policy) for item in value)
    if isinstance(value, set):
        return [_redact_value(item, policy) for item in value]
    if isinstance(value, str):
        if policy._value_pattern is not None:
            value = policy._value_pattern.sub(lambda _: policy.replacement, value)
        if policy.max_string_length is not None and len(value) > policy.max_string_length:
            return value[: policy.max_string_length] + "..."
    return value


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
