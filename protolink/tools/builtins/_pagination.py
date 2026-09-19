"""Small opaque cursors bound to an integration's account and query."""

import base64
import hashlib
import json
from typing import Any


def scope_key(*values: Any) -> str:
    """Fingerprint cursor parameters; this is correlation, not authentication."""
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def encode_cursor(scope: str, value: Any) -> str:
    """Encode a continuation value and its fixed resource/query binding."""
    return base64.urlsafe_b64encode(json.dumps({"scope": scope, "value": value}).encode()).decode()


def decode_cursor(token: str, scope: str) -> Any:
    """Reject malformed cursors or reuse against a different account/query."""
    try:
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise ValueError
        data = json.loads(base64.b64decode(token, altchars=b"-_", validate=True))
        if not isinstance(data, dict) or data.get("scope") != scope or "value" not in data:
            raise ValueError
        return data["value"]
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("Invalid page token or changed account/query; restart pagination") from None
