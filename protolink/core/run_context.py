"""Runtime context primitives for Protolink task execution.

The context model in this module gives applications a typed place for runtime
metadata that used to drift into ad hoc ``Task.metadata`` keys. It intentionally
stays domain-neutral: a workspace may be a local directory, browser profile,
dataset URI, ticket collection, or any other application boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator

RUN_CONTEXT_METADATA_KEY = "run_context"
"""Task metadata key used to store the serialized ``RunContext``."""


@dataclass
class RunBudget:
    """Optional execution limits carried with a run.

    Budgets are advisory runtime metadata. They provide a stable typed container
    that applications and custom policies can read, render, or enforce without
    inventing their own task metadata shape.

    Attributes:
        max_steps: Maximum logical runtime steps allowed for the run.
        max_llm_calls: Maximum model calls allowed for the run.
        max_tool_calls: Maximum tool calls allowed for the run.
        max_runtime_seconds: Maximum wall-clock runtime in seconds.
        max_input_tokens: Optional aggregate input-token budget.
        max_output_tokens: Optional aggregate output-token budget.
        metadata: Extra budget fields for application-specific limit systems.
    """

    max_steps: int | None = None
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_runtime_seconds: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the budget into a JSON-compatible dictionary."""
        return {
            "max_steps": self.max_steps,
            "max_llm_calls": self.max_llm_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RunBudget:
        """Create a budget from serialized data.

        Unknown keys are preserved in ``metadata`` so older Protolink versions
        can safely round-trip newer application budget fields.
        """
        if not data:
            return cls()

        known_keys = {
            "max_steps",
            "max_llm_calls",
            "max_tool_calls",
            "max_runtime_seconds",
            "max_input_tokens",
            "max_output_tokens",
            "metadata",
        }
        metadata = dict(data.get("metadata") or {})
        metadata.update({key: value for key, value in data.items() if key not in known_keys})

        return cls(
            max_steps=_coerce_optional_int(data.get("max_steps")),
            max_llm_calls=_coerce_optional_int(data.get("max_llm_calls")),
            max_tool_calls=_coerce_optional_int(data.get("max_tool_calls")),
            max_runtime_seconds=_coerce_optional_float(data.get("max_runtime_seconds")),
            max_input_tokens=_coerce_optional_int(data.get("max_input_tokens")),
            max_output_tokens=_coerce_optional_int(data.get("max_output_tokens")),
            metadata=metadata,
        )


@dataclass
class RunContext:
    """Typed runtime metadata propagated through Protolink task execution.

    ``RunContext`` is the generic execution envelope for a task run. It keeps
    product/application concerns out of core models while still giving local
    CLIs, servers, tests, and multi-agent systems a stable contract for session
    continuity, trace correlation, parent/child execution, budgets, permissions,
    and cancellation state.

    The context is serialized into ``Task.metadata["run_context"]`` and mirrors
    common legacy keys such as ``session_id`` and ``trace_id`` for compatibility
    with existing Protolink integrations.

    Attributes:
        run_id: Stable identifier for one logical execution run.
        session_id: Optional conversation/session identifier shared across runs.
        trace_id: Optional observability trace identifier.
        workspace_uri: Optional URI for the run boundary, such as a directory,
            browser profile, dataset, project, account, or ticket collection.
        parent_run_id: Optional parent run for nested agent or tool execution.
        agent_chain: Ordered list of agents that have handled this run.
        permissions: Domain-neutral capability rules or scoped policy metadata.
        budget: Optional execution limits.
        canceled: Whether the run has been canceled by the caller or runtime.
        cancel_reason: Optional human-readable cancel reason.
        metadata: Additional application metadata that should travel with the run.
        created_at: ISO timestamp for context creation.
    """

    run_id: str = field(default_factory=lambda: IDGenerator.generate_context_id(prefix="run_"))
    session_id: str | None = None
    trace_id: str | None = None
    workspace_uri: str | None = None
    parent_run_id: str | None = None
    agent_chain: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    budget: RunBudget = field(default_factory=RunBudget)
    canceled: bool = False
    cancel_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the context into a JSON-compatible dictionary."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "workspace_uri": self.workspace_uri,
            "parent_run_id": self.parent_run_id,
            "agent_chain": list(self.agent_chain),
            "permissions": self.permissions,
            "budget": self.budget.to_dict(),
            "canceled": self.canceled,
            "cancel_reason": self.cancel_reason,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RunContext:
        """Create a context from serialized data."""
        if not data:
            return cls()

        agent_chain = data.get("agent_chain") or []
        if not isinstance(agent_chain, list):
            agent_chain = [str(agent_chain)]

        return cls(
            run_id=str(data.get("run_id") or IDGenerator.generate_context_id(prefix="run_")),
            session_id=_optional_str(data.get("session_id")),
            trace_id=_optional_str(data.get("trace_id")),
            workspace_uri=_optional_str(data.get("workspace_uri") or data.get("workspace")),
            parent_run_id=_optional_str(data.get("parent_run_id")),
            agent_chain=[str(agent) for agent in agent_chain],
            permissions=dict(data.get("permissions") or {}),
            budget=RunBudget.from_dict(data.get("budget") or data.get("budgets")),
            canceled=bool(data.get("canceled", data.get("cancelled", False))),
            cancel_reason=_optional_str(data.get("cancel_reason") or data.get("cancellation_reason")),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or utc_now()),
        )

    @classmethod
    def from_task(cls, task: Any, *, default_session_id: str | None = None) -> RunContext:
        """Read a context from a task and merge compatible legacy metadata.

        Existing applications may already store ``session_id``, ``trace_id``,
        ``workspace`` or ``workspace_uri`` directly in ``Task.metadata``. This
        method accepts that shape, builds a typed context, and prefers explicit
        context fields when both representations exist.
        """
        metadata = getattr(task, "metadata", {}) or {}
        context = cls.from_dict(metadata.get(RUN_CONTEXT_METADATA_KEY))

        task_id = getattr(task, "id", None)
        if not metadata.get(RUN_CONTEXT_METADATA_KEY) and task_id:
            context.run_id = str(metadata.get("run_id") or task_id)

        context.session_id = context.session_id or _optional_str(metadata.get("session_id")) or default_session_id
        context.trace_id = context.trace_id or _optional_str(metadata.get("trace_id"))
        context.workspace_uri = context.workspace_uri or _optional_str(
            metadata.get("workspace_uri") or metadata.get("workspace")
        )

        legacy_parent = _optional_str(metadata.get("parent_run_id") or metadata.get("parent_agent"))
        context.parent_run_id = context.parent_run_id or legacy_parent

        if not context.permissions and isinstance(metadata.get("permissions"), dict):
            context.permissions = dict(metadata["permissions"])
        if context.budget == RunBudget() and isinstance(metadata.get("budget"), dict):
            context.budget = RunBudget.from_dict(metadata["budget"])
        elif context.budget == RunBudget() and isinstance(metadata.get("budgets"), dict):
            context.budget = RunBudget.from_dict(metadata["budgets"])

        if metadata.get("canceled") is True or metadata.get("cancelled") is True:
            context.canceled = True
        context.cancel_reason = context.cancel_reason or _optional_str(
            metadata.get("cancel_reason") or metadata.get("cancellation_reason")
        )
        return context

    @classmethod
    def ensure_task_context(
        cls,
        task: Any,
        *,
        default_session_id: str | None = None,
        agent_name: str | None = None,
    ) -> RunContext:
        """Return a task context and persist it back to ``Task.metadata``.

        Args:
            task: Any object with a mutable ``metadata`` dictionary, typically a
                ``Task``.
            default_session_id: Fallback session ID when neither the context nor
                legacy metadata defines one.
            agent_name: Optional agent name to append to the execution chain.

        Returns:
            The normalized context now attached to the task.
        """
        context = cls.from_task(task, default_session_id=default_session_id)
        if agent_name:
            context = context.with_agent(agent_name)
        context.attach_to_task(task)
        return context

    def attach_to_task(self, task: Any) -> None:
        """Persist this context into a task's metadata.

        The serialized context is stored under ``run_context``. Frequently used
        correlation keys are mirrored at the top level for compatibility with
        older code paths and telemetry integrations.
        """
        metadata = getattr(task, "metadata", None)
        if metadata is None:
            metadata = {}
            task.metadata = metadata

        metadata[RUN_CONTEXT_METADATA_KEY] = self.to_dict()
        metadata["run_id"] = self.run_id
        if self.session_id is not None:
            metadata["session_id"] = self.session_id
        if self.trace_id is not None:
            metadata["trace_id"] = self.trace_id
        if self.workspace_uri is not None:
            metadata["workspace_uri"] = self.workspace_uri
        if self.parent_run_id is not None:
            metadata["parent_run_id"] = self.parent_run_id
        if self.canceled:
            metadata["canceled"] = True
        if self.cancel_reason is not None:
            metadata["cancel_reason"] = self.cancel_reason

    def with_agent(self, agent_name: str) -> RunContext:
        """Return a context with ``agent_name`` appended to the agent chain."""
        chain = list(self.agent_chain)
        if not chain or chain[-1] != agent_name:
            chain.append(agent_name)
        return self.copy(agent_chain=chain)

    def child(self, *, run_id: str | None = None, agent_name: str | None = None) -> RunContext:
        """Create a child context for delegated work.

        The child keeps the same session, trace, workspace, permissions, budget,
        and metadata, while setting ``parent_run_id`` to the current ``run_id``.
        """
        child_context = self.copy(
            run_id=run_id or IDGenerator.generate_context_id(prefix="run_"),
            parent_run_id=self.run_id,
            agent_chain=list(self.agent_chain),
        )
        if agent_name:
            child_context = child_context.with_agent(agent_name)
        return child_context

    def cancel(self, reason: str | None = None) -> RunContext:
        """Return a canceled copy of this context."""
        return self.copy(canceled=True, cancel_reason=reason)

    def copy(self, **overrides: Any) -> RunContext:
        """Return a shallow copy with selected fields replaced."""
        data = self.to_dict()
        data.update(overrides)
        if isinstance(data.get("budget"), RunBudget):
            data["budget"] = data["budget"].to_dict()
        return RunContext.from_dict(data)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
