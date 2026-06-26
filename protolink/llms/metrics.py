"""Provider-agnostic LLM usage, context, latency, and cost helpers.

The helpers in this module keep observability concerns out of provider
adapters and the inference loop. They intentionally avoid mandatory tokenizer
or pricing dependencies: provider-reported usage is preferred when available,
``tiktoken`` is used only if it is already installed, and a small character
heuristic is used as the final fallback.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from protolink.llms.serialization import json_history_default


@dataclass(frozen=True)
class LLMModelProfile:
    """Optional model budget metadata used for context and cost reporting.

    Prices and context windows change over time, so Protolink does not require
    or assume a global pricing catalog. Applications can pass a profile for the
    model they selected, and Protolink will compute percentages and estimated
    costs from normalized usage metadata. Capability fields are intentionally
    descriptive rather than catalog-backed: applications can tell Protolink what
    the selected model supports without requiring a live pricing/model database.
    """

    context_window: int | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    currency: str = "USD"
    provider: str | None = None
    model: str | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    supports_json_schema: bool | None = None
    tokenizer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolved(self, *, provider: str | None = None, model: str | None = None) -> LLMModelProfile:
        """Return a profile with provider/model defaults filled in."""
        return LLMModelProfile(
            context_window=self.context_window,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            currency=self.currency,
            provider=self.provider or provider,
            model=self.model or model,
            supports_tools=self.supports_tools,
            supports_streaming=self.supports_streaming,
            supports_json_schema=self.supports_json_schema,
            tokenizer=self.tokenizer,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the profile for telemetry metadata."""
        return asdict(self)


@dataclass(frozen=True)
class LLMUsage:
    """Normalized token usage for one provider call."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated: bool = False
    source: str = "provider"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize token usage into a stable dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated": self.estimated,
            "source": self.source,
            "details": self.details,
        }


@dataclass(frozen=True)
class LLMContextUsage:
    """Context-window pressure for one LLM call."""

    used_tokens: int
    window_tokens: int | None = None
    used_percent: float | None = None
    available_tokens: int | None = None
    estimated: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize context usage into a stable dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class LLMCost:
    """Estimated cost for one LLM call."""

    input_cost: float | None = None
    output_cost: float | None = None
    total_cost: float | None = None
    currency: str = "USD"
    estimated: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize cost details into a stable dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class LLMCallMetrics:
    """Complete normalized metrics for one inference-loop LLM call."""

    step: int
    provider: str | None
    model: str | None
    latency_ms: float
    usage: LLMUsage
    context: LLMContextUsage
    cost: LLMCost | None = None
    streaming: bool = False
    native: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the metrics payload emitted to telemetry and callbacks."""
        return {
            "step": self.step,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "usage": self.usage.to_dict(),
            "context": self.context.to_dict(),
            "cost": self.cost.to_dict() if self.cost else None,
            "streaming": self.streaming,
            "native": self.native,
        }


def profile_from_value(
    value: LLMModelProfile | dict[str, Any] | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> LLMModelProfile | None:
    """Normalize a user-supplied profile object or dictionary."""
    if value is None:
        return None
    if isinstance(value, LLMModelProfile):
        return value.resolved(provider=provider, model=model)
    return LLMModelProfile(
        context_window=_coerce_int(value.get("context_window")),
        input_cost_per_million=_coerce_float(value.get("input_cost_per_million")),
        output_cost_per_million=_coerce_float(value.get("output_cost_per_million")),
        currency=str(value.get("currency") or "USD"),
        provider=str(value.get("provider") or provider) if value.get("provider") or provider else None,
        model=str(value.get("model") or model) if value.get("model") or model else None,
        supports_tools=_coerce_optional_bool(value.get("supports_tools")),
        supports_streaming=_coerce_optional_bool(value.get("supports_streaming")),
        supports_json_schema=_coerce_optional_bool(value.get("supports_json_schema")),
        tokenizer=str(value.get("tokenizer")) if value.get("tokenizer") else None,
        metadata=dict(value.get("metadata") or {}),
    )


def estimate_token_count(value: Any, *, model: str | None = None) -> int:
    """Estimate token count without introducing a mandatory tokenizer package.

    If ``tiktoken`` is installed, Protolink uses it for a closer estimate. If
    not, a four-character heuristic is used. The fallback is intentionally not
    billing-grade, but it gives CLIs and local traces a useful signal.
    """
    text = _stringify_for_count(value)
    if not text:
        return 0

    encoder = _optional_tiktoken_encoder(model)
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass

    return max(1, (len(text) + 3) // 4)


def estimate_usage(input_value: Any, output_value: Any | None = None, *, model: str | None = None) -> LLMUsage:
    """Estimate input/output usage for providers that do not report tokens."""
    input_tokens = estimate_token_count(input_value, model=model)
    output_tokens = estimate_token_count(output_value, model=model) if output_value is not None else None
    total_tokens = input_tokens + output_tokens if output_tokens is not None else input_tokens
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated=True,
        source="estimate",
    )


def normalize_provider_usage(source: Any) -> LLMUsage | None:
    """Normalize token usage reported by common provider SDK response objects."""
    usage_source = _extract_usage_source(source)
    if usage_source is None:
        return None

    input_tokens = _first_int(
        usage_source,
        "input_tokens",
        "prompt_tokens",
        "prompt_token_count",
        "prompt_eval_count",
    )
    output_tokens = _first_int(
        usage_source,
        "output_tokens",
        "completion_tokens",
        "candidates_token_count",
        "eval_count",
    )
    total_tokens = _first_int(usage_source, "total_tokens", "total_token_count")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None

    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated=False,
        source="provider",
        details=_to_jsonable(usage_source),
    )


def usage_metadata(metadata: dict[str, Any], response: Any) -> dict[str, Any]:
    """Attach normalized provider usage metadata when the response exposes it."""
    usage = normalize_provider_usage(response)
    if usage is None:
        return metadata
    return {**metadata, "usage": usage.to_dict()}


def context_usage_from_tokens(
    used_tokens: int,
    profile: LLMModelProfile | None = None,
    *,
    estimated: bool = True,
) -> LLMContextUsage:
    """Compute context-window pressure for a known input token count."""
    window = profile.context_window if profile else None
    used_percent = round((used_tokens / window) * 100, 3) if window else None
    available_tokens = max(window - used_tokens, 0) if window else None
    return LLMContextUsage(
        used_tokens=used_tokens,
        window_tokens=window,
        used_percent=used_percent,
        available_tokens=available_tokens,
        estimated=estimated,
    )


def calculate_cost(usage: LLMUsage, profile: LLMModelProfile | None = None) -> LLMCost | None:
    """Estimate call cost from normalized usage and an optional model profile."""
    if profile is None:
        return None

    input_cost = None
    output_cost = None
    if usage.input_tokens is not None and profile.input_cost_per_million is not None:
        input_cost = round((usage.input_tokens / 1_000_000) * profile.input_cost_per_million, 8)
    if usage.output_tokens is not None and profile.output_cost_per_million is not None:
        output_cost = round((usage.output_tokens / 1_000_000) * profile.output_cost_per_million, 8)

    if input_cost is None and output_cost is None:
        return None

    total_cost = round((input_cost or 0.0) + (output_cost or 0.0), 8)
    return LLMCost(
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        currency=profile.currency,
        estimated=usage.estimated,
    )


def build_call_metrics(
    *,
    step: int,
    provider: str | None,
    model: str | None,
    latency_ms: float,
    input_value: Any,
    output_value: Any,
    profile: LLMModelProfile | None,
    provider_usage: Any = None,
    streaming: bool = False,
    native: bool = False,
) -> LLMCallMetrics:
    """Build the canonical metrics payload for one LLM call."""
    estimated = estimate_usage(input_value, output_value, model=model)
    usage = _fill_missing_usage(normalize_provider_usage(provider_usage), estimated)
    input_tokens = usage.input_tokens if usage.input_tokens is not None else estimated.input_tokens
    if input_tokens is None:
        input_tokens = 0
    context = context_usage_from_tokens(input_tokens, profile, estimated=usage.estimated)
    return LLMCallMetrics(
        step=step,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        usage=usage,
        context=context,
        cost=calculate_cost(usage, profile),
        streaming=streaming,
        native=native,
    )


def _fill_missing_usage(provider_usage: LLMUsage | None, estimated_usage: LLMUsage) -> LLMUsage:
    """Fill partial provider usage with local estimates without discarding provenance."""
    if provider_usage is None:
        return estimated_usage

    input_tokens = provider_usage.input_tokens
    output_tokens = provider_usage.output_tokens
    estimated = provider_usage.estimated
    source = provider_usage.source

    if input_tokens is None:
        input_tokens = estimated_usage.input_tokens
        estimated = True
        source = "provider+estimate"
    if output_tokens is None:
        output_tokens = estimated_usage.output_tokens
        estimated = True
        source = "provider+estimate"

    total_tokens = provider_usage.total_tokens
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    elif total_tokens is None:
        total_tokens = estimated_usage.total_tokens

    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated=estimated,
        source=source,
        details=provider_usage.details,
    )


def _optional_tiktoken_encoder(model: str | None) -> Any | None:
    """Return a tiktoken encoder when the optional package is installed."""
    try:
        tiktoken = importlib.import_module("tiktoken")
    except ImportError:
        return None

    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:
            pass

    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _extract_usage_source(source: Any) -> Any | None:
    """Find the usage object inside common SDK response shapes."""
    if source is None:
        return None
    if isinstance(source, LLMUsage):
        return source
    if isinstance(source, dict):
        return source.get("usage") or source.get("usage_metadata") or source

    usage = getattr(source, "usage", None)
    if usage is not None:
        return usage
    usage_metadata = getattr(source, "usage_metadata", None)
    if usage_metadata is not None:
        return usage_metadata
    return source


def _first_int(source: Any, *names: str) -> int | None:
    """Return the first integer-like field found in a dict or object."""
    for name in names:
        value = _get_value(source, name)
        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced
    return None


def _get_value(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return bool(value)


def _stringify_for_count(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=json_history_default)
    except TypeError:
        return str(value)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, LLMUsage):
        return value.to_dict()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
