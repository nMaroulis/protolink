"""Structured data models used by Protolink developer tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CheckStatus = Literal["ok", "warn", "error"]
"""Status values emitted by devtool health checks."""


@dataclass(frozen=True)
class CheckResult:
    """One health or readiness check produced by ``protolink doctor``."""

    name: str
    status: CheckStatus
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the check into JSON-compatible data."""
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DoctorReport:
    """Aggregated readiness report for local Protolink development."""

    checks: tuple[CheckResult, ...]

    @property
    def status(self) -> CheckStatus:
        """Return the strongest status across all checks."""
        statuses = {check.status for check in self.checks}
        if "error" in statuses:
            return "error"
        if "warn" in statuses:
            return "warn"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report into JSON-compatible data."""
        return {
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class RunReplayItem:
    """A compact timeline item derived from a run report or task snapshot."""

    event_type: str
    summary: str
    timestamp: str | None = None
    severity: str = "info"
    task_id: str | None = None
    agent_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this timeline item."""
        return {
            "event_type": self.event_type,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class RunReplayView:
    """Human-facing replay projection for one run or task snapshot."""

    run_id: str
    session_id: str | None = None
    trace_id: str | None = None
    agent_name: str | None = None
    final_task: dict[str, Any] | None = None
    items: tuple[RunReplayItem, ...] = ()
    source: Literal["report", "task", "missing"] = "missing"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the replay projection."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "final_task": self.final_task,
            "source": self.source,
            "items": [item.to_dict() for item in self.items],
        }
