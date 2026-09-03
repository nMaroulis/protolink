"""Internal helpers for agent request normalization."""

from __future__ import annotations

from typing import Any

from protolink.core.task import Task
from protolink.llms.compaction import HistoryCompactionStrategy
from protolink.state.operations import StateOperationRequest


def _response_content(task: Task, request_item_ids: set[str]) -> Any:
    """Return new response content without mistaking the input for an answer."""
    last_item = task.get_last_item()
    if last_item is None or last_item.id in request_item_ids:
        return None
    return task.get_last_part_content()


def _coerce_state_operation_request(
    request: str | StateOperationRequest | dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
    stores: tuple[str, ...] | list[str] | None = None,
    include_data: bool | None = None,
    strategy: HistoryCompactionStrategy | None = None,
    max_messages: int | None = None,
    max_tokens: int | None = None,
    preserve_recent: int | None = None,
    summary_max_tokens: int | None = None,
) -> StateOperationRequest:
    """Normalize public state-control arguments into one request object."""
    if isinstance(request, StateOperationRequest):
        base = request.to_dict()
    elif isinstance(request, dict):
        base = StateOperationRequest.from_dict(request).to_dict()
    elif isinstance(request, str):
        base = StateOperationRequest(session_id=request).to_dict()
    elif request is None:
        base = StateOperationRequest().to_dict()
    else:
        raise TypeError("state operation request must be a session id, StateOperationRequest, dictionary, or None")

    if session_id is not None:
        base["session_id"] = session_id
    if stores is not None:
        base["stores"] = list(stores)
    if include_data is not None:
        base["include_data"] = include_data
    if strategy is not None:
        base["strategy"] = strategy
    if max_messages is not None:
        base["max_messages"] = max_messages
    if max_tokens is not None:
        base["max_tokens"] = max_tokens
    if preserve_recent is not None:
        base["preserve_recent"] = preserve_recent
    if summary_max_tokens is not None:
        base["summary_max_tokens"] = summary_max_tokens
    return StateOperationRequest.from_dict(base)
