"""Inventory and controls for explicitly configured durable Agent applications."""

from __future__ import annotations

import builtins
import importlib
from collections.abc import Iterable
from typing import Any

from protolink.agents.base import Agent
from protolink.core.durable import configuration_fingerprint
from protolink.core.redaction import RedactionPolicy
from protolink.core.task import Task, TaskState
from protolink.storage.durable import (
    CheckpointMismatchError,
    DurableExecutionError,
    RunCheckpoint,
    UncertainExecutionError,
)


def checkpoint_view(record: RunCheckpoint, *, redaction_policy: RedactionPolicy | None = None) -> dict[str, Any]:
    """Project a private checkpoint into bounded, redacted management metadata."""
    policy = redaction_policy or RedactionPolicy(max_string_length=12000)
    return policy.redact(
        {
            "run_id": record.run_id,
            "agent_name": record.agent_name,
            "status": record.status,
            "interruption": record.data.get("interruption"),
            "usage": record.data.get("usage", {}),
            "uncertain_actions": [
                {"action_id": item["action"]["action_id"], "name": item["action"]["name"], "state": item["state"]}
                for item in record.data.get("actions", {}).values()
                if item["state"] in {"executing", "uncertain"}
            ],
        }
    )


class RunManager:
    """Inspect and operate runs belonging to an application-owned Agent roster.

    Agents reconnect their own clients, callbacks, tools and private checkpoint
    stores. Inspection exports a bounded redacted projection, not conversations
    or raw tool results. Run IDs do not authorize access: network applications
    must authenticate and scope users before invoking this trusted local API.
    Live leases remain fenced; offline cancellation never steals ownership or
    invents a result for an uncertain external action.
    """

    def __init__(self, agents: Agent | Iterable[Agent], *, redaction_policy: RedactionPolicy | None = None) -> None:
        self.agents: dict[str, Agent] = {}
        for agent in [agents] if isinstance(agents, Agent) else agents:
            if not isinstance(agent, Agent) or agent.durability is None:
                raise ValueError("RunManager requires configured durable Agents")
            if agent.card.name in self.agents:
                raise ValueError("RunManager agent names must be unique")
            self.agents[agent.card.name] = agent
        if not self.agents:
            raise ValueError("Configure at least one durable Agent")
        self.redaction_policy = redaction_policy or RedactionPolicy(max_string_length=12000)

    def list(self, *, status: str | None = None, limit: int = 20) -> builtins.list[dict[str, Any]]:
        """List root-agent checkpoints; custom stores may implement the optional list API."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        result = []
        for agent in self.agents.values():
            method = getattr(agent.durability, "list", None)
            if not callable(method):
                raise DurableExecutionError("This checkpoint store does not support inventory")
            result.extend(
                self._project(record) for record in method(status=status, agent_name=agent.card.name, limit=limit)
            )
        return result[:limit]

    def _owner(self, run_id: str) -> tuple[Agent, RunCheckpoint]:
        for agent in self.agents.values():
            assert agent.durability is not None
            record = agent.durability.get(run_id)
            if record is not None and record.agent_name == agent.card.name:
                if record.data.get("configuration") != configuration_fingerprint(agent):
                    raise CheckpointMismatchError("Configured application no longer matches this run")
                return agent, record
        raise DurableExecutionError("Run is outside the configured application roster")

    def _project(self, record: RunCheckpoint) -> dict[str, Any]:
        return checkpoint_view(record, redaction_policy=self.redaction_policy)

    def inspect(self, run_id: str) -> dict[str, Any]:
        """Read pending requests and uncertainty metadata without executing anything."""
        _, record = self._owner(run_id)
        return self._project(record)

    async def resume(self, run_id: str, **response: Any) -> dict[str, Any]:
        """Continue through Agent.resume_task; subsequent waits remain inspectable."""
        if set(response) - {"request_id", "fingerprint", "answer", "approved"}:
            raise ValueError("Unknown continuation response fields")
        agent, _ = self._owner(run_id)
        task = await agent.resume_task(run_id, **response)
        return self.redaction_policy.redact({"task": task.to_dict(), "run": self.inspect(run_id)})

    def reconcile(self, run_id: str, action_id: str, *, result: Any) -> dict[str, Any]:
        """Commit an application-verified outcome without dispatching another action."""
        agent, _ = self._owner(run_id)
        agent.reconcile(run_id, action_id, result=result)
        return self.inspect(run_id)

    def cancel(self, run_id: str) -> dict[str, Any]:
        """Cancel a stopped checkpoint under its lease; live or uncertain work is rejected."""
        agent, record = self._owner(run_id)
        assert agent.durability is not None
        token, record = agent.durability.acquire(run_id, record.agent_name, record.data)
        try:
            if record.data.get("configuration") != configuration_fingerprint(agent):
                raise CheckpointMismatchError("Application changed before cancellation")
            if any(item["state"] in {"executing", "uncertain"} for item in record.data.get("actions", {}).values()):
                raise UncertainExecutionError("Inspect/reconcile unresolved effects before canceling the checkpoint")
            task = Task.from_dict(record.data["task"])
            if record.status == "ready" and task.state is TaskState.FAILED:
                # Reconciliation makes a failed attempt resumable, matching the
                # default loop's recovery transition without dispatching work.
                task.state = TaskState.WORKING
                task.metadata.pop("error", None)
            if not task.is_terminal:
                task.update_state(TaskState.CANCELED)
                task.metadata["cancel_reason"] = "Canceled through durable run management"
                task.metadata.pop("interruption", None)
                record.data.update(task=task.to_dict(), interruption=None)
                agent.durability.save(run_id, token, "canceled", record.data)
        finally:
            agent.durability.release(run_id, token)
        return self.inspect(run_id)


def load_run_manager(reference: str) -> RunManager:
    """Import an explicitly trusted module:function application factory.

    The function takes no arguments and returns an Agent, a roster, or RunManager.
    Importing executes application code; the CLI/server operator selects this
    reference at startup. Browser requests cannot change the factory reference.
    """
    module, separator, name = reference.partition(":")
    if not separator or not module or not name.isidentifier():
        raise ValueError("Use an importable module:function application factory")
    factory = getattr(importlib.import_module(module), name)
    if not callable(factory):
        raise TypeError("The application factory must be callable")
    result = factory()
    return result if isinstance(result, RunManager) else RunManager(result)
