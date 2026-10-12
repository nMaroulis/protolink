"""Validate delegated intent against advertised request support before dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from protolink.core.tool_errors import ToolRejectedError
from protolink.tools.schema import validate_tool_args


def _field(record: Any, name: str, default: Any = None) -> Any:
    """Read native cards and their serialized equivalents without interpreting prose."""
    return record.get(name, default) if isinstance(record, Mapping) else getattr(record, name, default)


def validate_delegation_request(
    agent_name: str,
    action: str,
    payload: dict[str, Any],
    cards: Sequence[Any] | None,
    *,
    agent_chain: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a validated payload or reject an unsupported request before effects.

    Card names and skill IDs are exact identifiers. Advertised input schemas
    use the same argument validation/coercion as local tools. Empty schemas
    provide no argument constraints. ``cards=None`` preserves custom callback
    integrations without a catalog; a supplied catalog limits selectable
    targets and tools. It is discovery data, never execution authorization.

    ``supports_inference=False`` rejects inference before dispatch. ``True``
    accepts custom prompt handlers as well as LLM agents. Missing/``None``
    declarations preserve legacy and external handler compatibility; ``has_llm``
    is only a positive correction hint for these cards, never a negative gate.
    The validator never converts a tool request to inference or invents a tool,
    target or prompt.

    Args:
        agent_name: Exact target identifier selected by the model.
        action: Canonical ``infer`` or ``tool_call`` action, already schema-validated.
        payload: Canonical action data passed to the delegation callback.
        cards: Agent cards or their serialized mappings; ``None`` omits catalog checks.
        agent_chain: Ancestor identities that cannot be selected again.

    Returns:
        A detached top-level payload with validated/coerced tool arguments.

    Raises:
        ToolRejectedError: A direct URL, cycle, unavailable target, unsupported
            inference request, unknown delegated tool or invalid arguments were
            rejected before dispatch.
    """
    if "://" in agent_name:
        raise ToolRejectedError(
            "Direct URL delegation is not allowed for model-originated agent calls.",
            code="invalid_agent_target",
            suggestion="Use an exact agent name advertised by discovery.",
        )
    if agent_name.strip().casefold() in {name.strip().casefold() for name in agent_chain}:
        raise ToolRejectedError(
            f"Delegation cycle detected: '{agent_name}' is already in the current agent chain.",
            code="delegation_cycle",
            suggestion="Choose another advertised agent or finish the current task.",
        )
    if cards is None:
        return dict(payload)
    card = next((card for card in cards if _field(card, "name") == agent_name), None)
    if card is None:
        raise ToolRejectedError(
            f"Agent '{agent_name}' is not available in the current delegation catalog.",
            code="unknown_agent",
            details={"available_agents": [_field(card, "name") for card in cards]},
            suggestion="Choose an advertised agent or another action.",
        )
    capabilities = _field(card, "capabilities", {})
    inference_support = _field(capabilities, "supports_inference")
    skills = _field(card, "skills", []) or []
    if action == "infer":
        if inference_support is False:
            raise ToolRejectedError(
                f"Agent '{agent_name}' does not support infer requests.",
                code="unsupported_inference",
                details={
                    "agent": agent_name,
                    "requested_action": action,
                    "supports_inference": False,
                    "available_tools": [_field(skill, "id") for skill in skills],
                },
                suggestion=(
                    "Use action='tool_call' with an advertised tool and valid args, or choose an agent "
                    "that supports inference."
                    if skills
                    else "Choose another agent that supports inference, or another action."
                ),
            )
        return dict(payload)

    tool_name = payload.get("tool")
    skill = next((skill for skill in skills if _field(skill, "id") == tool_name), None)
    details = {
        "agent": agent_name,
        "requested_action": action,
        "requested_tool": tool_name,
        "available_tools": [_field(skill, "id") for skill in skills],
    }
    if skill is None:
        inference_hint = inference_support is True or (
            inference_support is None and _field(capabilities, "has_llm", default=False) is True
        )
        raise ToolRejectedError(
            f"Agent '{agent_name}' does not advertise tool '{tool_name}'.",
            code="unknown_delegated_tool",
            details=details,
            suggestion=(
                f"To ask '{agent_name}' to reason or generate a response, use action='infer' and a top-level prompt."
                if inference_hint
                else "Choose a tool advertised by this agent, or select another agent."
            ),
        )
    try:
        arguments = validate_tool_args(payload.get("args"), _field(skill, "input_schema"))
    except (TypeError, ValueError) as error:
        raise ToolRejectedError(
            f"Arguments for '{agent_name}.{tool_name}' are invalid: {error}",
            code="invalid_delegated_arguments",
            details=details,
            suggestion="Correct args using the advertised tool input schema.",
        ) from error
    return {**payload, "args": arguments}
