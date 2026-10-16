"""Structured progress at a cooperative, checkpointed inference boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from protolink.core.budget import BudgetUsage


@dataclass(frozen=True)
class RunHandoff:
    """A worker yielded unfinished work without claiming completion.

    ``completed_action_ids`` identifies committed operations in the existing
    execution report; it is not a claim that the assignment was verified.
    ``usage`` is cumulative across the shared run, while ``steps`` counts this
    inference loop's logical steps. The application determines what remains and
    whether another slice is worthwhile. No extra model call creates a summary.

    Read this value with ``RunHandoff.from_task(task)`` or ``RunResult.handoff``.
    Explicitly call the owning root agent's ``resume_task(run_id)`` to grant
    another slice. Cancellation, exhausted hard budgets, denied actions and
    uncertain effects remain stopping conditions, rather than handoffs.
    """

    run_id: str
    reason: str
    steps: int
    usage: BudgetUsage
    completed_action_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize progress without exposing private conversations or results."""
        return {
            "run_id": self.run_id,
            "reason": self.reason,
            "steps": self.steps,
            "usage": self.usage.to_dict(),
            "completed_action_ids": list(self.completed_action_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunHandoff:
        """Restore a handoff from its public interruption request."""
        return cls(
            run_id=data["run_id"],
            reason=data["reason"],
            steps=data["steps"],
            usage=BudgetUsage.from_dict(data.get("usage")),
            completed_action_ids=tuple(data.get("completed_action_ids", ())),
        )

    @classmethod
    def from_task(cls, task: Any) -> RunHandoff | None:
        """Read the current handoff, returning ``None`` for other task states.

        A root task may expose a suspended child's handoff. In that case
        ``run_id`` identifies the child, but continuation still goes through
        the configured root's ``resume_task`` API and its root run identity.
        """
        if getattr(task.state, "value", task.state) != "input-required":
            return None
        interruption = task.metadata.get("interruption")
        if not isinstance(interruption, dict) or interruption.get("kind") != "yield":
            return None
        return cls.from_dict(interruption["request"])
