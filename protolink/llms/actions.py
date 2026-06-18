"""Typed action protocol used by the Protolink inference runtime.

The inference loop treats language models as planners, not executors. A model
may produce user-facing text, request a local tool, or delegate work to another
agent, but every side effect still flows through the runtime. The models below
are the hard boundary for that contract: prompt-fallback adapters parse into
them, provider-native tool calls normalize into them, and the runtime dispatches
only after Pydantic validation succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class _ActionModel(BaseModel):
    """Base configuration shared by all runtime action models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FinalAction(_ActionModel):
    """Validated request to finish the inference loop with user-facing text."""

    thought: str | None = None
    type: Literal["final"] = "final"
    content: str = Field(min_length=1)


class ToolCallAction(_ActionModel):
    """Validated request to execute one local Protolink tool."""

    thought: str | None = None
    type: Literal["tool_call"] = "tool_call"
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class AgentCallAction(_ActionModel):
    """Validated request to delegate inference or a tool call to another agent.

    Agent delegation intentionally stays explicit. ``action="infer"`` must
    carry a prompt and no tool payload, while ``action="tool_call"`` must carry
    a tool name plus an argument object. This keeps ambiguous hybrid responses
    from reaching the dispatcher.
    """

    thought: str | None = None
    type: Literal["agent_call"] = "agent_call"
    agent: str = Field(min_length=1)
    action: Literal["tool_call", "infer"]
    tool: str | None = None
    args: dict[str, Any] | None = None
    prompt: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> AgentCallAction:
        """Enforce action-specific required and mutually exclusive fields."""
        if self.action == "tool_call":
            if not self.tool:
                raise ValueError("field 'tool' is required when action is 'tool_call'")
            if self.prompt is not None:
                raise ValueError("field 'prompt' is not allowed when action is 'tool_call'")
            if self.args is None:
                self.args = {}
        elif self.action == "infer":
            if not self.prompt or not self.prompt.strip():
                raise ValueError("field 'prompt' is required when action is 'infer'")
            if self.tool is not None:
                raise ValueError("field 'tool' is not allowed when action is 'infer'")
            if self.args is not None:
                raise ValueError("field 'args' is not allowed when action is 'infer'")
        return self


LLMAction = Annotated[FinalAction | ToolCallAction | AgentCallAction, Field(discriminator="type")]
"""Discriminated union for every action the runtime is allowed to dispatch."""

ACTION_ADAPTER: TypeAdapter[LLMAction] = TypeAdapter(LLMAction)
"""Reusable Pydantic adapter for validating untrusted model/provider payloads."""


@dataclass(frozen=True)
class LLMActionResult:
    """Normalized result returned by provider adapters for one inference step.

    ``action`` is the already validated runtime action. ``raw_response`` is a
    stable textual representation recorded in conversation history and emitted
    to observability hooks. ``native`` indicates whether the action came from a
    provider-native tool/structured-output channel or from the prompt fallback.
    ``metadata`` is intentionally outside the action model so provider-specific
    IDs and transport fields never leak into runtime dispatch validation.
    """

    action: FinalAction | ToolCallAction | AgentCallAction
    raw_response: str
    native: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_action_payload(data: Any) -> FinalAction | ToolCallAction | AgentCallAction:
    """Validate unknown data against the runtime action protocol."""
    return ACTION_ADAPTER.validate_python(data)


def action_to_json(action: FinalAction | ToolCallAction | AgentCallAction) -> str:
    """Serialize a validated action into stable JSON for history and traces."""
    return action.model_dump_json(exclude_none=True)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a JSON schema with local ``$defs`` references inlined."""
    import copy

    if not isinstance(schema, dict):
        return schema

    defs = schema.get("$defs", {})

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                ref_path = value["$ref"]
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.rsplit("/", 1)[-1]
                    if def_name in defs:
                        return resolve(copy.deepcopy(defs[def_name]))
            return {key: resolve(inner) for key, inner in value.items() if key != "$defs"}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return resolve(schema)


def prompt_action_schema() -> dict[str, Any]:
    """Schema used by JSON-mode prompt fallback providers.

    Native providers should prefer real tool/function declarations because each
    tool then carries its own exact argument schema. This fallback schema is a
    root object, not a top-level union, so providers with simpler JSON-schema
    modes such as Ollama can still constrain the response shape without
    forbidding dynamic tool argument keys.
    """
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_object = {"anyOf": [{"type": "object", "additionalProperties": True}, {"type": "null"}]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "thought": nullable_string,
            "type": {"type": "string", "enum": ["final", "tool_call", "agent_call"]},
            "content": nullable_string,
            "tool": nullable_string,
            "args": nullable_object,
            "agent": nullable_string,
            "action": {"anyOf": [{"type": "string", "enum": ["tool_call", "infer"]}, {"type": "null"}]},
            "prompt": nullable_string,
        },
        "required": ["type"],
    }
