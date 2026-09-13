"""Collect delegated evidence without replacing worker identities or parent state."""

from __future__ import annotations

from copy import deepcopy

from protolink.core.events import RunEvent
from protolink.core.execution import execution_scope, publish_runtime_event
from protolink.core.run_context import RunContext
from protolink.core.task import Task


class DelegationRecorder:
    """Forward one child's events and snapshots into the active parent's evidence.

    Event IDs deduplicate streamed receipts against the returned task snapshot.
    A child's final marker is retained as metadata: only the parent may close its
    stream. Nested delegation links are preserved when already present.
    """

    def __init__(self, parent: Task | None, context: RunContext, action_id: str | None = None) -> None:
        self.parent = parent
        self.context = context
        self.action_id = action_id
        self._seen = {event["event_id"] for event in parent.metadata.get("run_events", [])} if parent else set()

    async def emit(self, event: RunEvent) -> None:
        """Forward a detached event once, preserving its original execution identity."""
        if event.event_id in self._seen:
            return
        self._seen.add(event.event_id)
        if event.type == "task.status" and event.final:
            task_data = event.payload.get("metadata", {}).get("task")
            if isinstance(task_data, dict):
                await self.capture(Task.from_dict(task_data))
        forwarded = deepcopy(event)
        forwarded.metadata.setdefault("source_sequence", event.sequence)
        forwarded.metadata.setdefault("source_final", event.final)
        forwarded.metadata.setdefault("parent_run_id", self.context.parent_run_id)
        forwarded.sequence = None
        forwarded.final = False
        forwarded.parent_action_id = event.parent_action_id or self.action_id
        forwarded.delegation_id = event.delegation_id or self.action_id or self.context.run_id
        with execution_scope(self.parent):
            await publish_runtime_event(forwarded)

    async def capture(self, task: Task) -> None:
        """Merge returned receipts and artifacts even when delegated execution failed."""
        for event in task.metadata.get("run_events", []):
            await self.emit(RunEvent.from_dict(event))
        if self.parent is not None:
            known = {artifact.id for artifact in self.parent.artifacts}
            for artifact in task.artifacts:
                if artifact.id not in known:
                    self.parent.add_artifact(deepcopy(artifact))
                    known.add(artifact.id)
