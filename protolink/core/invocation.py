"""Shared task preparation for the public convenience facades."""

from __future__ import annotations

import copy
from typing import Any

from protolink.core.run_context import RunBudget, RunContext
from protolink.core.task import Task


def prepare_task(
    task: Task,
    *,
    session_id: str | None = None,
    budget: RunBudget | None = None,
    context: RunContext | None = None,
    default_session_id: str | None = None,
) -> Task:
    """Attach copied controls; explicit options override context defaults.

    Existing task context is retained when no replacement context is supplied.
    Caller-owned contexts and budgets are never mutated. A default conversation
    partition is used only if neither the task nor the options supply one.
    """
    active = (
        RunContext.from_dict(copy.deepcopy(context.to_dict())) if context is not None else RunContext.from_task(task)
    )
    if session_id is not None:
        active.session_id = session_id
    elif active.session_id is None:
        active.session_id = default_session_id
    if budget is not None:
        active.budget = copy.deepcopy(budget)
    active.attach_to_task(task)
    return task


def response_content(task: Task, request_item_ids: set[str]) -> Any:
    """Read new output without returning an unchanged request as an answer."""
    last_item = task.get_last_item()
    if last_item is None or last_item.id in request_item_ids:
        return None
    return task.get_last_part_content()
