"""Simple continuation APIs over server-owned execution checkpoints."""

from __future__ import annotations

from typing import Any

from protolink.core.durable import RunInterrupted, _json, configuration_fingerprint, resume_response
from protolink.core.task import Task, TaskState
from protolink.storage.durable import SCHEMA_VERSION, CheckpointMismatchError, DurableExecutionError

from ._typing import _AgentMixinBase

_UNSET = object()


class AgentDurableMixin(_AgentMixinBase):
    """Continue the default loop without replaying its committed side effects."""

    async def resume_task(
        self,
        run_id: str,
        *,
        request_id: str | None = None,
        approved: bool | None = None,
        answer: Any = _UNSET,
        fingerprint: str | None = None,
    ) -> Task:
        """Resume a checkpoint and return its complete Task.

        Supply the current request ID and either ``approved=True/False`` or
        ``answer=text/None``. Omitting a response retries a safe saved boundary
        or returns the same pending interruption. Fingerprints may be supplied
        by an authenticated UI to reject stale previews. Run/request IDs are
        correlation values; the application authenticates and scopes access.
        """
        if self.durability is None:
            raise DurableExecutionError("Configure durability before resuming a run")
        checkpoint = self.durability.get(run_id)
        if checkpoint is None:
            raise DurableExecutionError(f"Unknown durable run '{run_id}'")
        if checkpoint.data.get("version") != SCHEMA_VERSION:
            raise CheckpointMismatchError("Unsupported execution checkpoint version")
        if checkpoint.agent_name != self.card.name or checkpoint.data["configuration"] != configuration_fingerprint(
            self
        ):
            raise CheckpointMismatchError("Checkpoint does not match this agent's execution contract")
        if checkpoint.status in {"failed", "canceled"}:
            raise DurableExecutionError(f"A {checkpoint.status} run cannot be resumed")
        response = None
        if approved is not None or answer is not _UNSET:
            pending = checkpoint.data.get("interruption")
            if pending is None:
                raise DurableExecutionError("Run has no pending approval or question")
            if request_id is None:
                raise ValueError("A response requires the pending request_id")
            response = {
                "request_id": request_id,
                "fingerprint": pending["fingerprint"] if fingerprint is None else fingerprint,
            }
            if approved is not None:
                if answer is not _UNSET:
                    raise ValueError("Supply approved or answer, not both")
                response["approved"] = approved
            else:
                response["answer"] = answer
        elif request_id is not None or fingerprint is not None:
            raise ValueError("request_id/fingerprint require an approval or input response")
        task = Task.from_dict(checkpoint.data["task"])
        if checkpoint.status == "completed":
            if response is not None:
                raise DurableExecutionError("Run is already complete")
            return task
        # A recovered execution is an explicit new attempt of the saved cursor.
        # An uncertain Task may have been marked failed by its old live wrapper.
        if task.state is TaskState.FAILED:
            task.state = TaskState.WORKING
            task.metadata.pop("error", None)
        with resume_response(run_id, response):
            return await self.run_task(task)

    async def resume(
        self,
        run_id: str,
        *,
        request_id: str | None = None,
        approved: bool | None = None,
        answer: Any = _UNSET,
        fingerprint: str | None = None,
    ) -> Any:
        """Resume and return final output, matching invoke's convenience contract.

        Raises RunInterrupted for another durable wait; use resume_task to
        inspect the protocol state instead. Completed runs return stored output.
        """
        task = await self.resume_task(
            run_id, request_id=request_id, approved=approved, answer=answer, fingerprint=fingerprint
        )
        if task.state is TaskState.INPUT_REQUIRED and "interruption" in task.metadata:
            raise RunInterrupted(task)
        task.raise_for_status()
        return task.get_output()

    def reconcile(self, run_id: str, action_id: str, *, result: Any) -> None:
        """Record an externally verified outcome for an uncertain action.

        Trusted application code calls this after inspecting the external system.
        It executes nothing and never invents rollback. The JSON result becomes
        the committed receipt used by the original pending action on resume.
        Local child records may be reconciled through their configured parent.
        """
        if self.durability is None:
            raise DurableExecutionError("Configure durability before reconciling a run")
        checkpoint = self.durability.get(run_id)
        if checkpoint is None:
            raise DurableExecutionError("Unknown durable run")
        if checkpoint.data.get("version") != SCHEMA_VERSION:
            raise CheckpointMismatchError("Unsupported execution checkpoint version")
        candidates: list[Any] = [self]
        visited: set[int] = set()
        owner = None
        while candidates:
            candidate = candidates.pop()
            if id(candidate) in visited:
                continue
            visited.add(id(candidate))
            if candidate.card.name == checkpoint.agent_name and checkpoint.data[
                "configuration"
            ] == configuration_fingerprint(candidate):
                owner = candidate
                break
            candidates.extend(candidate.subagents.values())
        if owner is None:
            raise CheckpointMismatchError("Checkpoint is outside this configured local agent tree")
        encoded = _json(result)
        token, record = self.durability.acquire(run_id, checkpoint.agent_name, checkpoint.data)
        try:
            if record.data.get("version") != SCHEMA_VERSION or record.data.get(
                "configuration"
            ) != configuration_fingerprint(owner):
                raise CheckpointMismatchError("Execution contract changed before reconciliation")
            entry = next(
                (entry for entry in record.data["actions"].values() if entry["action"]["action_id"] == action_id), None
            )
            if entry is None or entry["state"] not in {"executing", "uncertain"}:
                raise DurableExecutionError("Action is not an unresolved execution")
            entry.update(state="succeeded", result=encoded, reconciled=True)
            self.durability.save(run_id, token, "ready", record.data)
        finally:
            self.durability.release(run_id, token)
