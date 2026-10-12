"""Explicit, side-effect-free tool rejection and bounded correction failures."""

from __future__ import annotations

import json
from typing import Any


class ToolRejectedError(RuntimeError):
    """Reject a request that made no changes and can be corrected by the model.

    Raise this exception only when the tool guarantees that it performed no
    mutation or external effect. Ordinary execution errors, partial writes,
    permission denials and uncertain outcomes must use their normal exceptions.
    ProtoLink cannot verify this guarantee for application code.

    Args:
        message: Explanation of why the request cannot be accepted.
        code: Stable application error code, such as ``invalid_check_selection``.
        details: JSON object containing useful correction data, such as valid IDs.
        suggestion: Optional instruction describing an acceptable request.

    Details are copied through JSON serialization. Keep feedback concise and
    safe to expose to the model, event observers and persisted run reports.
    Raising this exception from a directly called tool does not retry it;
    automatic correction belongs to the inference loop.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "tool_rejected",
        details: dict[str, Any] | None = None,
        suggestion: str | None = None,
    ) -> None:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Tool rejection message must be nonblank text")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Tool rejection code must be nonblank text")
        if suggestion is not None and (not isinstance(suggestion, str) or not suggestion.strip()):
            raise ValueError("Tool rejection suggestion must be nonblank text or None")
        if details is not None and not isinstance(details, dict):
            raise TypeError("Tool rejection details must be a JSON object")
        self.code = code
        self.message = message
        self.details = json.loads(json.dumps(details or {}, allow_nan=False))
        self.suggestion = suggestion
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return correction feedback that explicitly records no changes."""
        return {
            "status": "rejected",
            "changes_made": False,
            "code": self.code,
            "message": self.message,
            "details": json.loads(json.dumps(self.details, allow_nan=False)),
            "suggestion": self.suggestion,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolRejectedError:
        """Restore a recorded rejection without executing the tool again."""
        if data.get("status") != "rejected" or data.get("changes_made") is not False:
            raise ValueError("A tool rejection must explicitly guarantee no changes")
        return cls(data["message"], code=data["code"], details=data.get("details"), suggestion=data.get("suggestion"))


class ToolCorrectionLimitError(RuntimeError):
    """Stop inference after its configured tool-correction allowance is spent.

    ``attempts`` counts rejected requests, while ``limit`` counts permitted
    corrections. A limit of two allows two corrective model turns; a third
    rejection stops inference. Successful actions do not replenish the limit.
    The last rejected request made no changes; earlier successful actions may
    already have committed effects and retain their normal receipts.
    Local tool and delegated-request validation share this allowance. For a
    delegated request, ``tool_name`` identifies the target as ``agent.tool``
    or ``agent.infer``; the public configuration remains ``max_tool_corrections``.
    """

    def __init__(self, *, tool_name: str, attempts: int, limit: int, last_error: ToolRejectedError) -> None:
        self.tool_name = tool_name
        self.attempts = attempts
        self.limit = limit
        self.last_error = last_error
        super().__init__(
            f"Tool correction limit ({limit}) exhausted after {attempts} rejected requests. "
            f"Last request to '{tool_name}' was rejected; nothing changed in that request. "
            f"[{last_error.code}] {last_error.message}"
        )
