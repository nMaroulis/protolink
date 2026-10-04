"""Durable default-loop execution, interruptions and committed action receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from typing import Any

from protolink.core.actions import RunAction
from protolink.core.budget import BudgetEnforcer, BudgetUsage
from protolink.core.run_context import RunContext
from protolink.core.task import Task, TaskState
from protolink.llms.history import ConversationHistory
from protolink.storage.durable import (
    SCHEMA_VERSION,
    CheckpointMismatchError,
    DurableExecutionError,
    DurableStore,
    UncertainExecutionError,
)
from protolink.utils.serialization import Serializer


@dataclass(frozen=True)
class RunInterruption:
    """A server-owned approval or user question that can survive a restart.

    Correlation IDs are not credentials. Applications authenticate responders
    and authorize access before invoking the local resume API.
    """

    run_id: str
    request_id: str
    kind: str
    request: dict[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "kind": self.kind,
            "request": self.request,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunInterruption:
        return cls(**data)


class RunInterrupted(DurableExecutionError):  # noqa: N818 - a public control-flow interruption
    """A convenience invocation paused; inspect ``interruption`` and ``task``."""

    def __init__(self, task: Task) -> None:
        self.task = task
        self.run_id = RunContext.from_task(task).run_id
        self.interruption = RunInterruption.from_dict(task.metadata["interruption"])
        super().__init__(f"Run '{self.run_id}' awaits {self.interruption.kind}")


class _SuspendRun(BaseException):
    """Internal control transfer; ordinary tool/handler error catches must not swallow it."""

    def __init__(self, interruption: RunInterruption) -> None:
        self.interruption = interruption


_active: ContextVar[DurableRun | None] = ContextVar("protolink_durable_run", default=None)
_response: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar("protolink_resume_response", default=None)
_streaming: ContextVar[bool] = ContextVar("protolink_durable_streaming", default=False)


def current_durable_run() -> DurableRun | None:
    return _active.get()


def is_durable_streaming() -> bool:
    return _streaming.get()


@contextmanager
def durable_streaming_scope() -> Iterator[None]:
    token = _streaming.set(True)
    try:
        yield
    finally:
        _streaming.reset(token)


def _json(value: Any) -> Any:
    """Reject uncheckpointable values before advancing the execution cursor."""
    return json.loads(json.dumps(Serializer.serialize_to_dict(value), allow_nan=False))


def configuration_fingerprint(agent: Any) -> str:
    """Fingerprint the declared execution contract, excluding secrets/live clients.

    Callback implementation changes cannot be inferred; applications supply an
    explicit ``execution_version`` when changing tool code or dependencies.
    """
    payload = {
        "agent": agent.card.name,
        "execution_version": agent.execution_version,
        "provider": getattr(agent.llm, "provider", None),
        "model": getattr(agent.llm, "model", None),
        "base_url": getattr(agent.llm, "base_url", None),
        "instructions": agent._system_prompt,
        "description": agent.card.description,
        "override_system_prompt": agent.override_system_prompt,
        "model_params": getattr(agent.llm, "_model_params", {}),
        "reasoning": getattr(agent.llm, "_reasoning", None),
        "subagent_limits": vars(agent.subagent_limits),
        "tools": {
            name: {
                "schema": tool.input_schema,
                "description": tool.description,
                "capabilities": sorted(getattr(tool, "capabilities", None) or ()),
            }
            for name, tool in agent.tools.items()
        },
        "subagents": sorted(agent.subagents),
    }
    return hashlib.sha256(json.dumps(_json(payload), sort_keys=True).encode()).hexdigest()


def _semantic_action(action: RunAction) -> Any:
    data = _json(action.to_dict())

    # Arguments and resource preconditions retain every field, including IDs.
    return {
        "kind": data["kind"],
        "name": data["name"],
        "payload": data["payload"],
        "capabilities": data["capabilities"],
        "artifacts": [
            {key: value for key, value in artifact.items() if key not in {"action_id", "timestamp", "id"}}
            for artifact in data["artifacts"]
        ],
        "description": data["description"],
        "metadata": data["metadata"],
    }


class DurableRun:
    """One leased task checkpoint within a possibly nested local run tree."""

    def __init__(self, agent: Any, task: Task, store: DurableStore, budget: BudgetEnforcer) -> None:
        self.agent = agent
        self.task = task
        self.store = store
        self.budget = budget
        self.parent = current_durable_run()
        self.root = self.parent.root if self.parent is not None else self
        self.context = RunContext.from_task(task)
        self.part_key = "part:0"
        self.slot = "part:0:0"
        last_item = task.get_last_item()
        initial = {
            "version": SCHEMA_VERSION,
            "configuration": configuration_fingerprint(agent),
            "task": task.to_dict(),
            "input_parts": [part.to_dict() for part in last_item.parts] if last_item else [],
            "outputs": {},
            "loops": {},
            "actions": {},
            "responses": {},
            "usage": budget.usage.to_dict(),
            "interruption": None,
        }
        self.token, record = store.acquire(self.context.run_id, agent.card.name, _json(initial))
        self.data = record.data
        self.status = record.status
        try:
            if self.data.get("version") != SCHEMA_VERSION or self.data.get("configuration") != initial["configuration"]:
                raise CheckpointMismatchError("Execution version, model, instructions or tool contract changed")
            if self.data["task"]["id"] != task.id:
                raise CheckpointMismatchError("Run ID is already bound to a different task")
            # Acquisition selects the authoritative snapshot: another worker
            # may have committed progress between get() and acquire(). Preserve
            # the caller's Task identity while restoring all fields and caches.
            restored = Task.from_dict(self.data["task"])
            for attribute in fields(Task):
                setattr(task, attribute.name, getattr(restored, attribute.name))
            if record.status in {"ready", "uncertain"} and task.state is TaskState.FAILED:
                task.state = TaskState.WORKING
                task.metadata.pop("error", None)
            if self.parent is None:
                budget.restore_usage(BudgetUsage.from_dict(self.data.get("usage")))
            response = _response.get()
            if response is not None and response[0] == self.context.run_id:
                self.respond(response[1])
            self.save("working")
        except BaseException:
            store.release(self.context.run_id, self.token)
            raise

    def save(self, status: str | None = None) -> None:
        self.data["task"] = self.task.to_dict()
        self.budget.evaluate()
        self.data["usage"] = self.budget.usage.to_dict()
        if status is not None:
            self.status = status
        # Commit shared counters before a child records a cursor that skips a
        # charge on recovery. A crash may conservatively reserve extra usage,
        # but cannot restore a child marker with an older, smaller root budget.
        if self.root is not self:
            self.root.save()
        self.store.save(self.context.run_id, self.token, self.status, _json(self.data))

    def respond(self, response: dict[str, Any]) -> None:
        pending = self.data.get("interruption")
        if pending is None:
            raise DurableExecutionError("Run has no pending interruption")
        if response.get("request_id") != pending["request_id"] or response.get("fingerprint") != pending["fingerprint"]:
            raise DurableExecutionError("Response does not match the pending request and fingerprint")
        if pending["kind"] == "approval":
            if not isinstance(response.get("approved"), bool) or "answer" in response:
                raise ValueError("An approval response requires approved=True or False")
        elif pending["kind"] == "input":
            if "approved" in response or "answer" not in response:
                raise ValueError("An input response requires answer=text or None to decline")
            answer = response["answer"]
            if answer is not None and (not isinstance(answer, str) or not answer.strip()):
                raise ValueError("answer must be nonblank text or None")
            if answer is not None and len(answer) > pending["request"].get("max_answer_chars", 16384):
                raise ValueError("answer exceeds the pending question's max_answer_chars")
        existing = self.data["responses"].get(pending["request_id"])
        if existing is not None and existing != response:
            raise DurableExecutionError("Pending request already has a different response")
        self.data["responses"][pending["request_id"]] = _json(response)

    @property
    def entry(self) -> dict[str, Any] | None:
        return self.data["actions"].get(self.slot)

    def prepare(self, action: RunAction) -> RunAction:
        entry = self.entry
        if entry is not None:
            stored = RunAction.from_dict(entry["action"])
            if _semantic_action(stored) != _semantic_action(action):
                raise CheckpointMismatchError("Prepared action or resource preconditions changed since checkpoint")
            return stored
        self.data["actions"][self.slot] = {"state": "prepared", "action": action.to_dict()}
        self.save()
        return action

    @property
    def tool_charged(self) -> bool:
        return self.entry is not None and self.entry.get("tool_charged", False)

    def mark_tool_charged(self) -> None:
        assert self.entry is not None
        self.entry["tool_charged"] = True
        self.save()

    def start_action(self) -> tuple[bool, Any]:
        entry = self.entry
        if entry is None:
            raise DurableExecutionError("Durable execution requires a prepared authorized action")
        if entry["state"] == "succeeded":
            return True, entry["result"]
        if entry["state"] in {"executing", "uncertain"} and not entry.get("child_task"):
            raise UncertainExecutionError(
                f"Action '{entry['action']['action_id']}' started without a committed outcome; reconcile it first"
            )
        entry["state"] = "executing"
        self.save()
        return False, None

    def complete_action(self, result: Any) -> Any:
        assert self.entry is not None
        # Serialization can fail after the effect; leave executing for honest recovery.
        encoded = _json(result)
        self.entry.update(state="succeeded", result=encoded)
        self.save()
        return encoded

    def request(self, kind: str, request: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
        entry = self.entry
        if entry is None:
            raise DurableExecutionError("Interruption has no prepared action")
        interruptions = entry.setdefault("interruptions", {})
        pending = interruptions.get(kind)
        if pending is None:
            interruption = RunInterruption(
                self.context.run_id, request["request_id"], kind, _json(request), fingerprint
            )
            pending = interruption.to_dict()
            interruptions[kind] = pending
        entry["interruption"] = pending
        response = self.root.data["responses"].get(pending["request_id"])
        if response is not None:
            return response
        entry["state"] = "waiting"
        self.data["interruption"] = pending
        self.save("input-required")
        raise _SuspendRun(RunInterruption.from_dict(pending))

    def loop_state(self) -> dict[str, Any] | None:
        return self.data["loops"].get(self.part_key)

    def save_loop(self, history: ConversationHistory, **state: Any) -> None:
        self.data["loops"][self.part_key] = {
            **state,
            "history": [message.to_dict() for message in history.messages_raw()],
        }
        self.save()


@contextmanager
def resume_response(run_id: str, response: dict[str, Any] | None) -> Iterator[None]:
    token = _response.set((run_id, response) if response is not None else None)
    try:
        yield
    finally:
        _response.reset(token)


@contextmanager
def durable_run_scope(agent: Any, task: Task, budget: BudgetEnforcer) -> Iterator[DurableRun | None]:
    parent = current_durable_run()
    store = parent.store if parent is not None else agent.durability
    if store is None:
        yield None
        return
    if parent is not None and parent.task.id == task.id:
        yield parent
        return
    from protolink.agents.engine import AgentExecutionMixin
    from protolink.llms.base import LLM

    if type(agent).handle_task is not AgentExecutionMixin.handle_task:
        raise DurableExecutionError("Durable execution requires the default Agent task handler")
    if agent.llm is not None and type(agent.llm).infer is not LLM.infer:
        raise DurableExecutionError("Durable execution requires the default LLM.infer loop")
    if agent.retrieval != "auto":
        raise DurableExecutionError("Durable execution requires retrieval='auto'; knowledge tools remain available")
    run = DurableRun(agent, task, store, budget)
    token = _active.set(run)
    try:
        yield run
        run.data["interruption"] = None
        task.metadata.pop("interruption", None)
        uncertain = any(entry["state"] in {"executing", "uncertain"} for entry in run.data["actions"].values())
        run.save("uncertain" if uncertain else task.state.value)
    except _SuspendRun as pause:
        if task.state is TaskState.SUBMITTED:
            task.begin()
        if task.state is TaskState.WORKING:
            task.require_input()
        task.metadata["interruption"] = pause.interruption.to_dict()
        run.data["interruption"] = pause.interruption.to_dict()
        run.save("input-required")
    except BaseException as exc:
        if isinstance(exc, asyncio.CancelledError):
            from protolink.core.cancellation import mark_task_canceled

            mark_task_canceled(task, str(exc) or "Execution canceled")
        uncertain = any(entry["state"] in {"executing", "uncertain"} for entry in run.data["actions"].values())
        run.save("uncertain" if uncertain else "canceled" if task.state is TaskState.CANCELED else "failed")
        raise
    finally:
        _active.reset(token)
        store.release(run.context.run_id, run.token)
