"""Provider-neutral context manifests for LLM calls.

``ContextManifest`` describes the prompt budget that is about to enter a model
without depending on a provider SDK or tokenizer catalog. It is designed for
CLIs, dashboards, tests, policy hooks, and local runtimes that need a stable
pre-call view before the model produces any usage metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from protolink.core.run_context import RunContext
from protolink.llms.history import ConversationHistory, LLMMessage, LLMMessageRole
from protolink.llms.metrics import LLMModelProfile, estimate_token_count
from protolink.utils import utc_now


@dataclass(frozen=True)
class ContextItem:
    """One logical section of context prepared for a model call."""

    kind: str
    name: str
    tokens: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the context item into a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextItem:
        """Create a context item from serialized data."""
        return cls(
            kind=str(data.get("kind") or "context"),
            name=str(data.get("name") or data.get("kind") or "context"),
            tokens=max(_coerce_int(data.get("tokens")) or 0, 0),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ContextManifest:
    """Provider-neutral preflight summary of one model input.

    The token fields are estimates unless a caller supplies a tokenizer-backed
    counting function in the future. ``system_tokens`` is the non-tool portion
    of the compiled system prompt, while ``tool_prompt_tokens`` estimates tool
    and delegation declarations separately so applications can see which part
    of the system prompt belongs to runtime affordances.
    """

    run_id: str | None = None
    session_id: str | None = None
    agent_name: str | None = None
    provider: str | None = None
    model: str | None = None
    system_tokens: int = 0
    history_tokens: int = 0
    tool_prompt_tokens: int = 0
    user_tokens: int = 0
    context_items: tuple[ContextItem, ...] = field(default_factory=tuple)
    total_estimated_tokens: int = 0
    context_window: int | None = None
    estimated: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: utc_now())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the manifest into a JSON-compatible dictionary."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "system_tokens": self.system_tokens,
            "history_tokens": self.history_tokens,
            "tool_prompt_tokens": self.tool_prompt_tokens,
            "user_tokens": self.user_tokens,
            "context_items": [item.to_dict() for item in self.context_items],
            "total_estimated_tokens": self.total_estimated_tokens,
            "context_window": self.context_window,
            "estimated": self.estimated,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextManifest:
        """Create a manifest from serialized data."""
        return cls(
            run_id=_optional_str(data.get("run_id")),
            session_id=_optional_str(data.get("session_id")),
            agent_name=_optional_str(data.get("agent_name")),
            provider=_optional_str(data.get("provider")),
            model=_optional_str(data.get("model")),
            system_tokens=max(_coerce_int(data.get("system_tokens")) or 0, 0),
            history_tokens=max(_coerce_int(data.get("history_tokens")) or 0, 0),
            tool_prompt_tokens=max(_coerce_int(data.get("tool_prompt_tokens")) or 0, 0),
            user_tokens=max(_coerce_int(data.get("user_tokens")) or 0, 0),
            context_items=tuple(ContextItem.from_dict(item) for item in data.get("context_items") or []),
            total_estimated_tokens=max(_coerce_int(data.get("total_estimated_tokens")) or 0, 0),
            context_window=_coerce_int(data.get("context_window")),
            estimated=bool(data.get("estimated", True)),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or utc_now()),
        )


def build_context_manifest(
    *,
    history: ConversationHistory,
    query: str,
    run_context: RunContext | None = None,
    agent_name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    profile: LLMModelProfile | None = None,
    tools: dict[str, Any] | None = None,
    agent_cards: list[Any] | None = None,
) -> ContextManifest:
    """Build a context manifest for the next LLM call.

    Args:
        history: Current conversation history after prompt construction.
        query: Current user query. The most recent matching user message is
            counted as ``user_tokens`` instead of historical context.
        run_context: Optional active run context for correlation fields.
        agent_name: Optional current agent name. Defaults to the last agent in
            the context chain when available.
        provider: Optional LLM provider name.
        model: Optional model identifier used by token estimation.
        profile: Optional model profile providing context-window metadata.
        tools: Tools exposed to the current inference loop.
        agent_cards: Delegation targets exposed to the current inference loop.

    Returns:
        A provider-neutral, JSON-serializable manifest.
    """
    messages = history.messages_raw()
    tool_prompt_tokens = estimate_token_count(
        {
            "tools": [_tool_descriptor(name, tool) for name, tool in sorted((tools or {}).items())],
            "agents": [_agent_descriptor(card) for card in agent_cards or []],
        },
        model=model,
    )
    if not tools and not agent_cards:
        tool_prompt_tokens = 0

    system_raw_tokens = 0
    history_tokens = 0
    current_user_message = _find_current_user_message(messages, query)
    for message in messages:
        message_tokens = estimate_token_count(message.content, model=model)
        if message.role == LLMMessageRole.SYSTEM:
            system_raw_tokens += message_tokens
        elif message is current_user_message:
            continue
        else:
            history_tokens += message_tokens

    user_tokens = estimate_token_count(query, model=model) if query else 0
    system_tokens = max(system_raw_tokens - tool_prompt_tokens, 0)
    total_estimated_tokens = system_tokens + tool_prompt_tokens + history_tokens + user_tokens

    items = [
        ContextItem(
            kind="system",
            name="system_prompt",
            tokens=system_tokens,
            metadata={"raw_system_tokens": system_raw_tokens},
        ),
        ContextItem(
            kind="history",
            name="conversation_history",
            tokens=history_tokens,
            metadata={"message_count": len([msg for msg in messages if msg is not current_user_message])},
        ),
        ContextItem(kind="user", name="current_user_query", tokens=user_tokens),
    ]
    if tool_prompt_tokens:
        items.insert(
            1,
            ContextItem(
                kind="tool_prompt",
                name="runtime_affordances",
                tokens=tool_prompt_tokens,
                metadata={
                    "tool_count": len(tools or {}),
                    "agent_count": len(agent_cards or []),
                    "included_in": "system_prompt",
                },
            ),
        )

    resolved_agent_name = agent_name
    if resolved_agent_name is None and run_context and run_context.agent_chain:
        resolved_agent_name = run_context.agent_chain[-1]

    return ContextManifest(
        run_id=run_context.run_id if run_context else None,
        session_id=run_context.session_id if run_context else None,
        agent_name=resolved_agent_name,
        provider=provider,
        model=model,
        system_tokens=system_tokens,
        history_tokens=history_tokens,
        tool_prompt_tokens=tool_prompt_tokens,
        user_tokens=user_tokens,
        context_items=tuple(items),
        total_estimated_tokens=total_estimated_tokens,
        context_window=profile.context_window if profile else None,
        metadata={"raw_system_tokens": system_raw_tokens},
    )


def _find_current_user_message(messages: list[LLMMessage], query: str) -> LLMMessage | None:
    """Return the newest user message matching ``query``."""
    if not query:
        return None
    for message in reversed(messages):
        if message.role == LLMMessageRole.USER and message.content == query:
            return message
    return None


def _tool_descriptor(name: str, tool: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": getattr(tool, "description", None),
        "input_schema": getattr(tool, "input_schema", None),
        "capabilities": sorted(getattr(tool, "capabilities", None) or ()),
    }


def _agent_descriptor(card: Any) -> dict[str, Any]:
    if hasattr(card, "to_dict") and callable(card.to_dict):
        return card.to_dict()
    return {
        "name": getattr(card, "name", None),
        "description": getattr(card, "description", None),
        "url": getattr(card, "url", None),
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
