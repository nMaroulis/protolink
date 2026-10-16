"""Small typed tool declarations that select one native local delegation route.

Worker facades are schema aliases, not executable wrappers around ``invoke``.
The inference engine resolves their tool calls to canonical agent actions before
authorization or checkpointing. Child execution therefore keeps the existing
supervisor, inherited policy, cancellation, budget and receipt machinery.
"""

from __future__ import annotations

import copy
import re
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from protolink.llms.actions import AgentCallAction, LLMAction, ToolCallAction
from protolink.tools.base import BaseTool
from protolink.tools.schema import validate_tool_args

if TYPE_CHECKING:
    from protolink.agents._typing import _AgentMixinBase


@dataclass(frozen=True)
class WorkerTool:
    """A declaration bound to one configured child and optional child tool.

    Obtain instances through ``parent.add_worker_tool``. The child cannot be
    chosen or replaced through model arguments, and a removed/replaced local
    worker never falls back to registry discovery. Schemas are detached copies
    of the child's declaration; the live child contract is validated again by
    the normal delegation dispatcher.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: Any
    worker_name: str
    tool_name: str | None
    _parent: weakref.ReferenceType[Any] = field(repr=False, compare=False)
    _worker: weakref.ReferenceType[Any] = field(repr=False, compare=False)
    tags: list[str] = field(default_factory=lambda: ["worker"])
    examples: list[Any] = field(default_factory=list)
    capabilities: tuple[str, ...] = ("agent.delegate",)

    @property
    def binding(self) -> dict[str, str]:
        """Return the execution contract used for serialization/fingerprinting."""
        return {
            "agent": self.worker_name,
            "action": "tool_call" if self.tool_name is not None else "infer",
            **({"tool": self.tool_name} if self.tool_name is not None else {}),
        }

    def require_parent(self, parent: Any) -> None:
        """Keep live declarations local; configuration reconnects a new binding."""
        if self._parent() is not parent:
            raise ValueError(f"Worker facade '{self.name}' belongs to another parent; register a new facade")

    def to_action(self, arguments: dict[str, Any]) -> AgentCallAction:
        """Validate the facade shape and resolve only its exact configured route."""
        parent, worker = self._parent(), self._worker()
        if parent is None or worker is None or parent.subagents.get(self.worker_name) is not worker:
            raise ValueError(
                f"Worker facade '{self.name}' requires its originally registered worker '{self.worker_name}'"
            )
        arguments = validate_tool_args(arguments, self.input_schema)
        if self.tool_name is not None:
            return AgentCallAction(agent=self.worker_name, action="tool_call", tool=self.tool_name, args=arguments)
        prompt = arguments["task"]
        if not prompt.strip():
            raise ValueError(f"Worker facade '{self.name}' requires a nonblank task")
        return AgentCallAction(agent=self.worker_name, action="infer", prompt=prompt)

    async def __call__(self, **kwargs: Any) -> Any:
        """Reject callable wrappers outside the native parent dispatch boundary."""
        raise ValueError(
            f"Worker facade '{self.name}' is a native parent tool declaration; "
            "use parent.invoke() or standalone parent.call_tool() to enforce policy, budgets and child ownership"
        )


def make_worker_tool(
    parent: _AgentMixinBase,
    worker: str,
    *,
    name: str | None = None,
    tool: str | None = None,
    description: str | None = None,
) -> WorkerTool:
    """Prepare one facade without replacing existing tools or executing work."""
    if not isinstance(worker, str) or worker not in parent.subagents:
        raise ValueError("worker must be the exact name of a registered local subagent")
    child = parent.subagents[worker]
    if tool is not None and (not isinstance(tool, str) or tool not in child.tools):
        raise ValueError(f"Worker '{worker}' has no registered tool '{tool}'")
    if tool is None and child.card.capabilities.supports_inference is False:
        raise ValueError(f"Worker '{worker}' does not support inference; choose an explicit child tool")
    alias = name if name is not None else worker if tool is None else f"{worker}_{tool}"
    if not isinstance(alias, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", alias) is None:
        raise ValueError("Worker facade names must be 1-64 letters, digits, underscores or hyphens; supply name=...")
    from protolink.llms.tool_calling import AGENT_INFER_TOOL_NAME, AGENT_TOOL_CALL_TOOL_NAME

    if alias in parent.tools or alias in {AGENT_INFER_TOOL_NAME, AGENT_TOOL_CALL_TOOL_NAME}:
        raise ValueError(f"Worker facade name '{alias}' conflicts with an existing or reserved tool")
    if description is not None and not isinstance(description, str):
        raise TypeError("Worker facade description must be a string")
    if tool is None:
        input_schema = {
            "type": "object",
            "properties": {"task": {"type": "string", "minLength": 1, "description": "The task for this worker."}},
            "required": ["task"],
            "additionalProperties": False,
        }
        output_schema = None
        default_description = f"Ask {worker} to complete a task. {child.card.description}".strip()
    else:
        child_tool = child.tools[tool]
        input_schema = copy.deepcopy(child_tool.input_schema or {})
        output_schema = copy.deepcopy(child_tool.output_schema)
        default_description = f"Use {worker}'s {tool} tool. {child_tool.description}".strip()
    return WorkerTool(
        name=alias,
        description=description if description is not None else default_description,
        input_schema=input_schema,
        output_schema=output_schema,
        worker_name=worker,
        tool_name=tool,
        _parent=weakref.ref(parent),
        _worker=weakref.ref(child),
    )


def normalize_worker_action(action: LLMAction, tools: dict[str, BaseTool]) -> LLMAction:
    """Resolve only real registered facade instances; ordinary tool calls pass through."""
    if isinstance(action, ToolCallAction):
        tool = tools.get(action.tool)
        if isinstance(tool, WorkerTool):
            return tool.to_action(action.args)
    return action


def worker_result(action: AgentCallAction, result: Any) -> Any:
    """Expose the declared child-tool result, retaining canonical native receipts.

    Native delegation returns a ``ToolOutput`` envelope; durable receipts store
    its serialized dictionary. A facade's public output schema describes the
    enclosed result, so unwrap one framework envelope after supervised execution.
    """
    from protolink.core.part import ToolOutput

    if action.action == "tool_call":
        if isinstance(result, ToolOutput):
            return result.result
        if isinstance(result, dict) and {"call_id", "result", "error"}.issubset(result):
            return result["result"]
    return result


async def execute_worker_tool(parent, facade, arguments, *, task, context, budget, cancellation):
    """Dispatch an explicit facade task through native local child supervision.

    The parent authorizes an ``agent.call`` action. It does not reserve a tool
    call for the declaration: an actual child tool reserves its own call once.
    Prepared action/child receipts and approvals belong to the existing durable
    scope, so suspension and recovery cannot create an unrelated child run.
    """
    import asyncio

    from protolink.core.actions import RunAction
    from protolink.core.budget import BudgetExceededError
    from protolink.core.execution import emit_runtime_event
    from protolink.core.tool_errors import ToolRejectedError
    from protolink.llms.delegation import validate_delegation_request

    action = facade.to_action(arguments)
    facade.require_parent(parent)
    payload = validate_delegation_request(
        action.agent,
        action.action,
        action.model_dump(exclude_none=True),
        [parent.subagents[action.agent].card],
        agent_chain=context.agent_chain,
    )
    operation = RunAction(
        kind="agent.call",
        name=action.agent,
        payload=payload,
        capabilities=frozenset({"agent.delegate"}),
        description=f"Delegate {action.action} action to agent '{action.agent}'",
    )
    authorization = await parent.authorize_action(operation, context)
    operation = authorization.action
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    decision = budget.evaluate()
    if not decision.allowed:
        raise BudgetExceededError(decision)
    await emit_runtime_event("action.started", context, action_id=operation.action_id, action=operation.to_dict())
    try:
        result = await parent._handle_agent_call(
            action.agent,
            action.action,
            payload,
            parent_context=context,
            parent_action_id=operation.action_id,
        )
    except asyncio.CancelledError:
        await emit_runtime_event("action.canceled", context, action_id=operation.action_id, action=operation.to_dict())
        raise
    except ToolRejectedError as error:
        await emit_runtime_event(
            "action.rejected",
            context,
            action_id=operation.action_id,
            action=operation.to_dict(),
            rejection=error.to_dict(),
        )
        raise
    except Exception as error:
        await emit_runtime_event(
            "action.failed",
            context,
            action_id=operation.action_id,
            action=operation.to_dict(),
            error={"code": type(error).__name__, "message": str(error)},
        )
        raise
    await emit_runtime_event(
        "action.completed",
        context,
        action_id=operation.action_id,
        action=operation.to_dict(),
        result=result,
    )
    return worker_result(action, result)
