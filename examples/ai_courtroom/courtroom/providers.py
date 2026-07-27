"""Provider selection for the reference fixture and optional live models."""

from __future__ import annotations

from typing import Any

from protolink import create_llm
from protolink.llms.base import LLM

from .reference_llm import ReferenceCourtroomLLM

SUPPORTED_PROVIDERS = (
    "reference",
    "openai",
    "anthropic",
    "gemini",
    "ollama",
    "openai-compatible",
)


def model_for_role(
    provider: str,
    *,
    role: str,
    seed: int,
    model: str | None,
    base_url: str | None,
    temperature: float,
) -> LLM:
    """Build a fresh model instance for exactly one agent role."""
    if provider == "reference":
        return ReferenceCourtroomLLM(role=role, seed=seed)

    kwargs: dict[str, Any] = {"model_params": {"temperature": temperature}}
    if model:
        kwargs["model"] = model
    if base_url:
        kwargs["base_url"] = base_url
    if provider == "ollama" and not base_url:
        # The adapter also accepts OLLAMA_URL. Keeping this call explicit makes
        # the resulting error immediately actionable when neither is supplied.
        kwargs.pop("base_url", None)
    return create_llm(provider, **kwargs)
