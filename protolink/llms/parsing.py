"""Parse model responses into strict runtime actions for ``LLM.infer``.

This module sits on the critical path between a provider response and the
deterministic Protolink runtime. The infer loop can execute tools, delegate to
agents, emit run events, enforce budgets, and terminate with a final response
only after the raw model output has been normalized into exactly one validated
``LLMAction``.

The boundary is intentionally narrow:

- The base ``LLM`` class owns orchestration, budgeting, history, telemetry, and
  dispatch.
- Provider adapters own provider-specific request/stream parsing and native
  tool-call translation.
- This module owns prompt-fallback JSON extraction, strict action validation,
  and conservative repair for a few deterministic legacy shorthands.

The repair layer is deliberately small and inspectable. It may reshape old
``payload`` wrappers or unambiguous ``tool(arg=value)`` text into canonical
action dictionaries, but it never executes tools, mutates history, chooses among
ambiguous agents, or invents missing behavior. If the response cannot be safely
repaired, normal Pydantic diagnostics are returned to the model so the next
infer step can self-correct.
"""

from __future__ import annotations

import ast
import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from protolink.llms.actions import LLMAction, validate_action_payload

if TYPE_CHECKING:
    from protolink.tools import BaseTool

_RAW_RESPONSE_PREVIEW_CHARS = 2_000


def parse_infer_response(
    response: str,
    *,
    tools: dict[str, BaseTool] | None = None,
    agent_cards: list[Any] | None = None,
) -> LLMAction:
    """Parse, repair, and validate one raw model action response.

    ``LLM.infer`` treats the model as an action proposer rather than an implicit
    executor. This function enforces that contract for prompt-fallback models:
    the response must contain one JSON object that validates against the
    discriminated ``LLMAction`` union. The validated result is then safe for the
    infer loop to route into final output handling, local tool execution, or
    delegated agent calls.

    Parsing follows three stages:

    1. Decode the response as JSON, with a narrow embedded-object fallback for
       models that wrap JSON in prose or code fences.
    2. Repair only deterministic compatibility shorthands using the supplied
       local tools and discovered agent cards as read-only context.
    3. Validate the final dictionary with the Pydantic action models and format
       field-level diagnostics on failure.

    Args:
        response: Raw text returned by the language model.
        tools: Local tools available to the current agent. These are used only
            to disambiguate fallback shorthand such as a delegated tool call
            that should actually be a local tool call.
        agent_cards: Discovered agents available to the current run. These are
            inspected only to infer a delegated agent when exactly one agent
            advertises the requested tool.

    Returns:
        The validated runtime action model. Callers receive a ``FinalAction``,
        ``ToolCallAction``, or ``AgentCallAction`` instance through the shared
        ``LLMAction`` type alias.

    Raises:
        ValueError: If no valid JSON object can be found or the parsed payload
            does not satisfy the strict ``LLMAction`` contract. Validation
            failures include field paths, Pydantic messages, and the parsed
            payload so the infer loop can inject useful self-correction
            feedback into conversation history.
    """
    data = _load_response_json(response)
    data = repair_fallback_action_payload(data, tools=tools or {}, agent_cards=agent_cards or [])

    try:
        return validate_action_payload(data)
    except ValidationError as exc:
        diagnostics = format_validation_errors(exc)
        raise ValueError(f"Action validation failed. Field-level errors:\n{diagnostics}\nParsed data: {data}") from exc
    except Exception as exc:
        raise ValueError(f"Action validation failed: {exc}\nParsed data: {data}") from exc


def repair_fallback_action_payload(
    data: Any,
    *,
    tools: dict[str, BaseTool],
    agent_cards: list[Any],
) -> Any:
    """Repair narrow, legacy prompt-fallback action shorthands.

    The runtime still dispatches only strict ``LLMAction`` models. This helper
    exists to keep older examples and smaller-model fallbacks usable without
    weakening that contract. It runs before validation and converts historical
    or small-model-friendly forms into the canonical shape only when the repair
    is deterministic.

    Supported repairs are intentionally limited:

    - Flatten a legacy ``payload`` dictionary into the top-level action fields.
    - Convert ``{"type": "tool_call", "prompt": "tool(arg=1)"}`` into a
      canonical tool call with explicit ``tool`` and ``args`` fields.
    - Convert delegated ``agent_call`` tool shorthands into canonical
      ``action="tool_call"`` payloads.
    - Infer a missing delegated agent only when exactly one discovered
      ``AgentCard`` advertises the requested skill.
    - Downgrade an ``agent_call`` shorthand to a local ``tool_call`` when the
      requested tool is local and no unique remote agent can be inferred.

    The function does not guess between multiple agents, resolve schemas, call
    tools, or fabricate missing prompts. Ambiguous or unsupported shapes are
    returned unchanged so strict validation can produce actionable diagnostics.

    Args:
        data: Parsed JSON payload from the model response. Non-dictionary
            values are returned unchanged for validation to reject.
        tools: Local tools keyed by tool name.
        agent_cards: Discovered agent cards available for delegation.

    Returns:
        Either the original payload or a repaired dictionary ready for
        ``LLMAction`` validation.
    """
    if not isinstance(data, dict):
        return data

    repaired = dict(data)
    payload = repaired.get("payload")
    if isinstance(payload, dict):
        for key in ("agent", "action", "tool", "args", "prompt", "content"):
            if key not in repaired and key in payload:
                repaired[key] = payload[key]
        repaired.pop("payload", None)

    if repaired.get("type") == "tool_call" and "args" not in repaired:
        prompt = repaired.get("prompt")
        parsed_call = parse_function_call_shorthand(prompt) if isinstance(prompt, str) else None
        if parsed_call is not None:
            tool_name, call_args, _agent_name = parsed_call
            repaired.setdefault("tool", tool_name)
            repaired["args"] = call_args
            repaired.pop("prompt", None)

    if repaired.get("type") != "agent_call":
        return repaired

    if repaired.get("action") not in {"tool_call", None}:
        return repaired

    prompt = repaired.get("prompt")
    parsed_call = parse_function_call_shorthand(prompt) if isinstance(prompt, str) else None
    if parsed_call is not None:
        tool_name, call_args, agent_from_prompt = parsed_call
        repaired.setdefault("action", "tool_call")
        repaired.setdefault("tool", tool_name)
        repaired.setdefault("args", call_args)
        if agent_from_prompt and "agent" not in repaired:
            repaired["agent"] = agent_from_prompt
        repaired.pop("prompt", None)

    tool_name = repaired.get("tool")
    if isinstance(tool_name, str) and "agent" not in repaired:
        agent_name = infer_unique_agent_for_tool(tool_name, agent_cards)
        if agent_name:
            repaired["agent"] = agent_name
        elif tool_name in tools:
            return {"type": "tool_call", "tool": tool_name, "args": repaired.get("args") or {}}

    return repaired


def parse_function_call_shorthand(value: str | None) -> tuple[str, dict[str, Any], str | None] | None:
    """Parse ``tool(arg=value)`` or ``agent.tool(arg=value)`` fallback text.

    This is not a general expression evaluator; it accepts only Python AST
    function-call syntax with literal arguments. Positional arguments are
    supported only when they are a single dictionary literal, because arbitrary
    positional values cannot be mapped safely to tool parameters.

    Accepted examples:

    - ``search(query="docs", limit=3)``
    - ``planner.search({"query": "docs", "limit": 3})``

    Rejected examples include arithmetic expressions, variable references,
    splatted keyword arguments, method chains beyond ``agent.tool(...)``, and
    positional arguments that are not a single dictionary literal. Returning
    ``None`` tells the caller to leave the payload unchanged and let strict
    action validation handle the error.

    Args:
        value: Optional shorthand string emitted by a prompt-fallback model.

    Returns:
        ``(tool_name, args, agent_name)`` when the shorthand is safe to parse.
        ``agent_name`` is ``None`` for local tool calls.
    """
    if not value:
        return None
    text = value.strip().strip("`")
    try:
        expr = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(expr, ast.Call):
        return None

    agent_name: str | None = None
    if isinstance(expr.func, ast.Name):
        tool_name = expr.func.id
    elif isinstance(expr.func, ast.Attribute):
        tool_name = expr.func.attr
        if isinstance(expr.func.value, ast.Name):
            agent_name = expr.func.value.id
    else:
        return None

    args: dict[str, Any] = {}
    if len(expr.args) == 1 and not expr.keywords:
        try:
            literal = ast.literal_eval(expr.args[0])
        except (ValueError, TypeError):
            return None
        if not isinstance(literal, dict):
            return None
        args = literal
    elif expr.args:
        return None

    for keyword in expr.keywords:
        if keyword.arg is None:
            return None
        try:
            args[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError):
            return None

    return tool_name, args, agent_name


def infer_unique_agent_for_tool(tool_name: str, agent_cards: list[Any]) -> str | None:
    """Return the only discovered agent advertising ``tool_name``, if any.

    Delegated tool-call shorthand is safe to repair only when discovery makes
    the target unambiguous. This helper scans each discovered card's ``skills``
    and returns an agent name only if exactly one unique agent advertises a
    skill whose ``id`` matches ``tool_name``.

    Args:
        tool_name: Tool or skill identifier requested by the model.
        agent_cards: Discovered agent cards supplied to the infer loop.

    Returns:
        The unique agent name, or ``None`` when no agent or multiple agents
        advertise the tool.
    """
    candidates: list[str] = []
    for card in agent_cards:
        agent_name = getattr(card, "name", None)
        for skill in getattr(card, "skills", []) or []:
            if getattr(skill, "id", None) == tool_name and agent_name:
                candidates.append(str(agent_name))
    unique = sorted(set(candidates))
    return unique[0] if len(unique) == 1 else None


def format_validation_errors(exc: Any) -> str:
    """Render Pydantic validation errors as model self-correction feedback.

    The infer loop injects parser failures back into conversation history so
    the model can repair its next response. A useful error needs more than
    ``invalid JSON`` or ``validation failed``; it should point at the exact
    action branch and field that failed. This formatter extracts the Pydantic
    location path, message, and error type into a stable bullet-list string.

    Args:
        exc: Usually a Pydantic ``ValidationError``. The type is intentionally
            broad so callers can still format unexpected validation-like
            exceptions without losing the original message.

    Returns:
        A multi-line diagnostic string suitable for logs and prompt feedback.
    """
    lines: list[str] = []
    try:
        for error in exc.errors():
            loc = " -> ".join(str(part) for part in error.get("loc", []))
            msg = error.get("msg", "unknown error")
            err_type = error.get("type", "")
            if loc:
                lines.append(f"  - Field '{loc}': {msg} (type: {err_type})")
            else:
                lines.append(f"  - {msg} (type: {err_type})")
    except Exception:
        lines.append(f"  - {exc}")
    return "\n".join(lines) if lines else str(exc)


def _load_response_json(response: str) -> Any:
    """Load a JSON object from a raw model response.

    The primary contract is a strict JSON action object. As a practical
    fallback for smaller or less instruction-following models, this helper also
    accepts exactly one balanced, valid JSON object embedded in prose or a code
    fence. The extractor tracks JSON string and escape state, so braces inside
    string values do not terminate an object early. Multiple valid objects are
    rejected rather than selecting one ambiguously.

    This function does not validate the action schema; it only decodes JSON.
    Schema validation remains in ``parse_infer_response`` so malformed objects
    and semantically invalid actions produce the same field-level diagnostics.

    Args:
        response: Raw provider text.

    Returns:
        The decoded JSON value, usually a dictionary.

    Raises:
        ValueError: If neither the full response nor the embedded-object
            fallback can be decoded, or if multiple embedded objects are found.
            A bounded raw-response preview is included for debugging and model
            feedback.
    """
    try:
        return json.loads(response, strict=False)
    except json.JSONDecodeError as original_error:
        objects = []
        for candidate_text in _extract_balanced_top_level_objects(response):
            try:
                candidate = json.loads(candidate_text, strict=False)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                objects.append(candidate)
        if len(objects) == 1:
            return objects[0]
        raw_diagnostic = _format_raw_response_diagnostic(response)
        if len(objects) > 1:
            raise ValueError(
                f"Invalid JSON action response: found {len(objects)} valid top-level JSON objects; "
                f"expected exactly one.\n{raw_diagnostic}"
            ) from original_error
        raise ValueError(f"Invalid JSON: {original_error}\n{raw_diagnostic}") from original_error


def _extract_balanced_top_level_objects(response: str) -> list[str]:
    """Extract disjoint top-level object spans in one string-aware pass.

    Quotes outside an object belong to arbitrary wrapper prose and do not alter
    scanning. Once an opening brace starts a candidate, JSON string and escape
    state ensure literal braces inside values do not change nesting. Unterminated
    candidates are ignored, matching the conservative fallback contract without
    repeated rescans of adversarial brace-heavy responses.
    """
    objects: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(response):
        if depth == 0:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(response[start : index + 1])
                start = None
    return objects


def _format_raw_response_diagnostic(response: str) -> str:
    """Return a bounded response preview suitable for parse diagnostics."""
    if len(response) <= _RAW_RESPONSE_PREVIEW_CHARS:
        return f"Raw response: {response}"

    head_chars = _RAW_RESPONSE_PREVIEW_CHARS // 2
    tail_chars = _RAW_RESPONSE_PREVIEW_CHARS - head_chars
    omitted_chars = len(response) - _RAW_RESPONSE_PREVIEW_CHARS
    preview = f"{response[:head_chars]}\n... [{omitted_chars} characters omitted] ...\n{response[-tail_chars:]}"
    return f"Raw response (truncated; {len(response)} characters total): {preview}"
