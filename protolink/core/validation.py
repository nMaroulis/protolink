"""Application-defined acceptance checks over execution receipts and revisions."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from protolink.core.artifact import Artifact
from protolink.core.execution import emit_runtime_event, execution_scope
from protolink.core.report import RunReport
from protolink.core.resources import ResourceRevision
from protolink.core.run_context import RunContext
from protolink.core.task import Task


@dataclass(frozen=True)
class ToolOutcome:
    """An executed tool's structured result; a preview or approval is not an outcome."""

    action_id: str
    name: str
    result: Any = None
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class CompletionEvidence:
    """Typed task, executed outcomes, artifacts, and report exposed to a predicate."""

    task: Task
    outcomes: tuple[ToolOutcome, ...]
    artifacts: tuple[Artifact, ...]
    report: RunReport


@dataclass(frozen=True)
class ValidationResult:
    """A structured acceptance decision with explicit resource dependencies."""

    name: str
    status: str
    code: str | None = None
    message: str | None = None
    action_ids: tuple[str, ...] = ()
    revisions: tuple[ResourceRevision, ...] = ()

    @property
    def passed(self) -> bool:
        """Whether the recorded check passed at its recorded revisions."""
        return self.status == "passed"

    def is_current(self, revisions: Sequence[ResourceRevision]) -> bool:
        """Require a current matching version for every resource used as evidence."""
        current = {revision.resource_id: revision.version for revision in revisions}
        return all(current.get(revision.resource_id) == revision.version for revision in self.revisions)

    def to_dict(self) -> dict[str, Any]:
        """Serialize acceptance evidence for native events and RunReport."""
        return {
            "name": self.name,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "action_ids": list(self.action_ids),
            "revisions": [revision.to_dict() for revision in self.revisions],
        }


AcceptancePredicate = Callable[[CompletionEvidence], bool | ValidationResult | Awaitable[bool | ValidationResult]]


@dataclass(frozen=True)
class CompletionCheck:
    """An application acceptance predicate with explicit evidence requirements.

    By default at least one execution receipt is required. Set ``action_ids``
    to require particular actions. Pure answer checks may explicitly disable
    ``require_execution``. Revisions are checked both before and after awaiting
    the predicate, so asynchronous checks cannot certify a changed resource.
    """

    name: str
    predicate: AcceptancePredicate
    require_execution: bool = True
    action_ids: tuple[str, ...] = ()
    revisions: tuple[ResourceRevision, ...] = ()
    read_revision: Callable[[str], ResourceRevision] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Require a version reader when acceptance depends on resource revisions."""
        if not self.name or (self.revisions and self.read_revision is None):
            raise ValueError("Checks need a name and resource-dependent checks need read_revision")


class CompletionValidator:
    """Evaluate application checks without inferring success from model prose."""

    def __init__(self, checks: Sequence[CompletionCheck]) -> None:
        """Register named acceptance predicates without performing any checks."""
        self.checks = tuple(checks)
        if len({check.name for check in checks}) != len(checks):
            raise ValueError("Completion check names must be unique")

    async def validate(self, task: Task, *, report: RunReport | None = None) -> tuple[ValidationResult, ...]:
        """Evaluate checks and append structured validation events to this task.

        Validation never reexecutes tools or changes terminal task state. A flow
        may route on these results; a caller decides whether failed acceptance
        ends the workflow or permits a bounded new attempt.
        """
        context = RunContext.ensure_task_context(task)
        report = report or RunReport.from_task(task)
        outcomes: dict[str, ToolOutcome] = {}
        for event in report.events:
            if event.type != "action.completed" or not event.action_id:
                continue
            action = event.payload.get("action", {})
            metadata = event.payload.get("metadata", {})
            if not isinstance(action, dict) or action.get("kind") == "agent.call":
                continue
            name = action.get("name") or metadata.get("tool")
            if name:
                outcomes[event.action_id] = ToolOutcome(
                    event.action_id, name, event.payload.get("result", metadata.get("result"))
                )
        evidence = CompletionEvidence(task, tuple(outcomes.values()), tuple(task.artifacts), report)
        results = []
        with execution_scope(task):
            for check in self.checks:
                ids = check.action_ids or tuple(outcomes)
                if check.require_execution and (not ids or any(key not in outcomes for key in ids)):
                    result = ValidationResult(check.name, "blocked", "execution_evidence_missing")
                elif not self._current(check):
                    result = ValidationResult(
                        check.name, "stale", "resource_revision_changed", revisions=check.revisions
                    )
                else:
                    try:
                        value = check.predicate(evidence)
                        if inspect.isawaitable(value):
                            value = await value
                        if isinstance(value, ValidationResult):
                            from dataclasses import replace

                            result = replace(value, name=check.name, action_ids=ids, revisions=check.revisions)
                        elif isinstance(value, bool):
                            result = ValidationResult(
                                check.name, "passed" if value else "failed", action_ids=ids, revisions=check.revisions
                            )
                        else:
                            raise TypeError("Acceptance predicates must return bool or ValidationResult")
                    except Exception as exc:
                        result = ValidationResult(check.name, "failed", "predicate_error", str(exc))
                    if not self._current(check):
                        result = ValidationResult(
                            check.name, "stale", "resource_revision_changed", revisions=check.revisions
                        )
                results.append(result)
                await emit_runtime_event("validation.completed", context, validation=result.to_dict())
        task.metadata["validation_results"] = [result.to_dict() for result in results]
        return tuple(results)

    @staticmethod
    def _current(check: CompletionCheck) -> bool:
        if check.read_revision is None:
            return True
        try:
            return all(check.read_revision(revision.resource_id) == revision for revision in check.revisions)
        except (OSError, ValueError):
            return False
