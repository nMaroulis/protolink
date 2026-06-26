"""Provider-neutral conversation history compaction.

``HistoryCompactor`` is composed into each base LLM and owns compaction policy
plus isolated summary generation. Pure helpers in this module perform the
underlying history transformations without provider SDK coupling.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, TypeAlias

from protolink.llms.history import ConversationHistory, LLMMessage, LLMMessageRole
from protolink.llms.metrics import estimate_token_count
from protolink.llms.serialization import json_history_default

HistoryCompactionStrategy: TypeAlias = Literal["recent", "tokens", "summary"]
"""Supported history compaction algorithms."""

HistorySummarizer: TypeAlias = Callable[[list[dict[str, Any]], int], str]
"""Callback used to summarize chronological full-message dictionaries."""


@dataclass(frozen=True)
class HistoryCompactionRequest:
    """Transport-neutral request to compact an agent's LLM history.

    The request is used by client/server control endpoints and direct Agent
    calls. It is intentionally not a task part or model tool, so applications
    can request context maintenance without increasing the LLM prompt surface.

    Args:
        strategy: Compaction algorithm: ``"recent"``, ``"tokens"``, or
            ``"summary"``.
        max_messages: Retained-message limit for ``"recent"``.
        max_tokens: Estimated token ceiling for ``"tokens"``.
        preserve_recent: Newest non-system messages protected by ``"tokens"``
            and ``"summary"``.
        summary_max_tokens: Requested maximum summary length.
        session_id: Optional persistent conversation session to load, compact,
            and save when the agent has ``state=["conversation"]`` enabled.
        metadata: Additional application metadata for logs or future control
            policies. The compactor ignores it.
    """

    strategy: HistoryCompactionStrategy = "recent"
    max_messages: int = 20
    max_tokens: int = 4_000
    preserve_recent: int = 6
    summary_max_tokens: int = 512
    session_id: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the request for a transport body."""
        data = asdict(self)
        if self.metadata is None:
            data["metadata"] = {}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryCompactionRequest:
        """Create a request from a JSON-compatible dictionary."""
        strategy = data.get("strategy", "recent")
        if strategy not in {"recent", "tokens", "summary"}:
            raise ValueError("strategy must be one of: recent, tokens, summary")
        session_id = data.get("session_id")
        return cls(
            strategy=strategy,
            max_messages=int(data.get("max_messages", 20)),
            max_tokens=int(data.get("max_tokens", 4_000)),
            preserve_recent=int(data.get("preserve_recent", 6)),
            summary_max_tokens=int(data.get("summary_max_tokens", 512)),
            session_id=str(session_id) if session_id is not None else None,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class HistoryCompactionResult:
    """Structured report returned after a history compaction attempt."""

    strategy: HistoryCompactionStrategy
    before_messages: int
    after_messages: int
    removed_messages: int
    before_tokens: int
    after_tokens: int
    summary_created: bool = False

    @property
    def changed(self) -> bool:
        """Return whether any source messages were compacted."""
        return self.removed_messages > 0 or self.summary_created

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report for task results, telemetry, or logging."""
        return {**asdict(self), "changed": self.changed}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryCompactionResult:
        """Create a compaction report from a JSON-compatible dictionary."""
        return cls(
            strategy=data.get("strategy", "recent"),
            before_messages=int(data.get("before_messages", 0)),
            after_messages=int(data.get("after_messages", 0)),
            removed_messages=int(data.get("removed_messages", 0)),
            before_tokens=int(data.get("before_tokens", 0)),
            after_tokens=int(data.get("after_tokens", 0)),
            summary_created=bool(data.get("summary_created", False)),
        )


class _CompactionTarget(Protocol):
    """Minimal LLM surface required by ``HistoryCompactor``."""

    model: str
    history: ConversationHistory

    def call(self, history: ConversationHistory) -> str:
        """Generate one response for an isolated summary conversation."""
        ...


class HistoryCompactor:
    """LLM-owned service for compacting live conversation history.

    The compactor keeps history algorithms and summary generation out of the
    base LLM class. It retains a reference to its owning LLM rather than a
    specific history object because agents may replace ``llm.history`` when
    loading persistent sessions.

    Compaction is not exposed to the model as a built-in tool and is never
    appended to the model prompt. Applications and the Agent runtime call this
    component directly when they receive an explicit control-plane request.

    Applications normally access this component through ``llm.compactor`` or
    the convenience facade ``llm.compact_history()``.
    """

    __slots__ = ("_llm",)

    def __init__(self, llm: _CompactionTarget) -> None:
        """Attach the compactor to an LLM-compatible owner."""
        self._llm = llm

    def compact(
        self,
        strategy: HistoryCompactionStrategy = "recent",
        *,
        max_messages: int = 20,
        max_tokens: int = 4_000,
        preserve_recent: int = 6,
        summary_max_tokens: int = 512,
    ) -> HistoryCompactionResult:
        """Compact the owner's live history in place.

        ``recent`` keeps the system prompt and newest messages without a model
        call. ``tokens`` keeps the newest chronological suffix under an
        estimated token budget without a model call. ``summary`` makes one
        isolated model call with a dedicated summarization prompt to replace
        older messages with durable context while preserving recent messages
        verbatim.

        Args:
            strategy: ``"recent"``, ``"tokens"``, or ``"summary"``.
            max_messages: Retained-message limit for ``"recent"``, including
                the leading system prompt when one exists.
            max_tokens: Estimated ceiling for ``"tokens"``. The leading system
                prompt and protected recent messages may exceed it.
            preserve_recent: Newest non-system messages protected by
                ``"tokens"`` and ``"summary"``.
            summary_max_tokens: Requested maximum summary length.

        Returns:
            Structured before/after message and estimated-token counts.

        Notes:
            Summary generation uses a temporary ``ConversationHistory``. The
            live history is replaced only after a non-empty summary returns.
            The normal agent inference loop, tool registry, and system prompt
            are not involved.
        """
        summarizer = self._summarize_messages if strategy == "summary" else None
        return _compact_conversation_history(
            self._llm.history,
            strategy=strategy,
            model=self._llm.model,
            max_messages=max_messages,
            max_tokens=max_tokens,
            preserve_recent=preserve_recent,
            summary_max_tokens=summary_max_tokens,
            summarizer=summarizer,
        )

    def _summarize_messages(
        self,
        messages: list[dict[str, Any]],
        summary_max_tokens: int,
    ) -> str:
        """Summarize older messages through one isolated owner call."""
        summary_history = _build_summary_history(messages, summary_max_tokens)
        return _extract_summary(self._llm.call(summary_history))


def _build_summary_history(
    messages: list[dict[str, Any]],
    summary_max_tokens: int,
) -> ConversationHistory:
    """Build an isolated conversation that asks a provider for compact JSON."""
    summary_history = ConversationHistory(
        system_prompt=(
            "Compact the supplied conversation into durable context. Preserve decisions, requirements, "
            "constraints, unresolved work, important facts, and named entities. Remove repetition and filler. "
            f"Keep the summary under approximately {summary_max_tokens} tokens. Return exactly one JSON object "
            'with a non-empty string field named "summary".'
        )
    )
    summary_history.add_user(
        json.dumps(
            _provider_messages(messages),
            ensure_ascii=False,
            default=json_history_default,
        )
    )
    return summary_history


def _extract_summary(raw_summary: str) -> str:
    """Extract a summary from JSON while tolerating plain-text providers."""
    raw_summary = raw_summary.strip()
    if not raw_summary:
        return ""
    try:
        parsed = json.loads(raw_summary, strict=False)
    except json.JSONDecodeError:
        start = raw_summary.find("{")
        end = raw_summary.rfind("}")
        if start == -1 or end <= start:
            return raw_summary
        try:
            parsed = json.loads(raw_summary[start : end + 1], strict=False)
        except json.JSONDecodeError:
            return raw_summary
    if isinstance(parsed, dict):
        for key in ("summary", "content"):
            value = parsed.get(key)
            if isinstance(value, str):
                return value.strip()
    return raw_summary


def _compact_conversation_history(
    history: ConversationHistory,
    *,
    strategy: HistoryCompactionStrategy = "recent",
    model: str | None = None,
    max_messages: int = 20,
    max_tokens: int = 4_000,
    preserve_recent: int = 6,
    summary_max_tokens: int = 512,
    summarizer: HistorySummarizer | None = None,
) -> HistoryCompactionResult:
    """Compact a conversation in place using one of three strategies.

    ``recent`` keeps the leading system prompt and the newest messages.
    ``tokens`` walks backward from the newest protected messages until adding
    another message would exceed ``max_tokens``. ``summary`` replaces older
    messages with one system summary and keeps ``preserve_recent`` messages
    verbatim.

    The leading system prompt and protected recent messages are never removed,
    so the token strategy treats ``max_tokens`` as a soft ceiling when those
    messages alone exceed it. Summary compaction is atomic: the source history
    is replaced only after the summarizer returns a non-empty string.

    Args:
        history: Conversation to mutate in place.
        strategy: ``"recent"``, ``"tokens"``, or ``"summary"``.
        model: Optional model identifier used by token estimation.
        max_messages: Maximum retained messages for ``recent``, including the
            leading system prompt when present.
        max_tokens: Estimated token ceiling for ``tokens``.
        preserve_recent: Number of newest non-system messages protected by the
            ``tokens`` and ``summary`` strategies.
        summary_max_tokens: Requested maximum size of the generated summary.
        summarizer: Required callback for ``summary`` compaction.

    Returns:
        A structured before/after report.

    Raises:
        ValueError: If arguments are invalid or a summary is empty.
    """
    _validate_options(
        strategy=strategy,
        max_messages=max_messages,
        max_tokens=max_tokens,
        preserve_recent=preserve_recent,
        summary_max_tokens=summary_max_tokens,
        summarizer=summarizer,
    )

    original = history.to_list()
    before_tokens = estimate_token_count(_provider_messages(original), model=model)
    leading_system, body = _split_leading_system(original)
    summary_created = False
    removed_messages = 0

    if strategy == "recent":
        body_capacity = max(max_messages - len(leading_system), 0)
        compacted = leading_system + (body[-body_capacity:] if body_capacity else [])
        removed_messages = max(len(original) - len(compacted), 0)
    elif strategy == "tokens":
        compacted = _compact_to_token_budget(
            leading_system,
            body,
            max_tokens=max_tokens,
            preserve_recent=preserve_recent,
            model=model,
        )
        removed_messages = max(len(original) - len(compacted), 0)
    else:
        recent_count = min(preserve_recent, len(body))
        older = body[:-recent_count] if recent_count else body
        recent = body[-recent_count:] if recent_count else []
        if not older:
            compacted = original
        else:
            assert summarizer is not None  # validated above
            summary = summarizer(older, summary_max_tokens).strip()
            if not summary:
                raise ValueError("history summarizer returned an empty summary")
            summary_message = LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=f"Compacted conversation summary:\n{summary}",
                metadata={"protolink_history_compaction": "summary"},
            ).to_dict()
            compacted = [*leading_system, summary_message, *recent]
            summary_created = True
            removed_messages = len(older)

    if compacted != original:
        history.replace(compacted)

    after_tokens = estimate_token_count(_provider_messages(compacted), model=model)
    return HistoryCompactionResult(
        strategy=strategy,
        before_messages=len(original),
        after_messages=len(compacted),
        removed_messages=removed_messages,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        summary_created=summary_created,
    )


def _compact_to_token_budget(
    leading_system: list[dict[str, Any]],
    body: list[dict[str, Any]],
    *,
    max_tokens: int,
    preserve_recent: int,
    model: str | None,
) -> list[dict[str, Any]]:
    """Keep the newest chronological suffix that fits the token budget."""
    protected_count = min(preserve_recent, len(body))
    protected = body[-protected_count:] if protected_count else []
    remaining = body[:-protected_count] if protected_count else body
    kept = list(protected)

    for message in reversed(remaining):
        candidate = [*leading_system, message, *kept]
        if estimate_token_count(_provider_messages(candidate), model=model) > max_tokens:
            break
        kept.insert(0, message)

    return leading_system + kept


def _split_leading_system(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate the canonical leading system prompt from conversation turns."""
    if messages and messages[0].get("role") == LLMMessageRole.SYSTEM.value:
        return messages[:1], messages[1:]
    return [], messages


def _provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project full persisted messages into provider-visible fields."""
    return [
        {
            "role": message.get("role", ""),
            "content": message.get("content", ""),
            **({"name": message["name"]} if message.get("name") else {}),
        }
        for message in messages
    ]


def _validate_options(
    *,
    strategy: str,
    max_messages: int,
    max_tokens: int,
    preserve_recent: int,
    summary_max_tokens: int,
    summarizer: HistorySummarizer | None,
) -> None:
    """Validate compaction options before any history or model mutation."""
    if strategy not in {"recent", "tokens", "summary"}:
        raise ValueError("strategy must be one of: recent, tokens, summary")
    if max_messages < 2:
        raise ValueError("max_messages must be >= 2")
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")
    if preserve_recent < 1:
        raise ValueError("preserve_recent must be >= 1")
    if summary_max_tokens < 1:
        raise ValueError("summary_max_tokens must be >= 1")
    if strategy == "summary" and summarizer is None:
        raise ValueError("summary strategy requires a summarizer")
