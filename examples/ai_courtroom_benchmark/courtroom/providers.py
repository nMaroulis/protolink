"""Fresh model construction for benchmark actors and reference fixtures."""

from __future__ import annotations

from typing import Any

from protolink import create_llm
from protolink.llms.base import LLM

from .config import CaseConfig
from .reference_llm import SUPPORTED_REFERENCE_MODELS, ReferenceBenchmarkLLM

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
    case_config: CaseConfig,
    seed: int,
    model: str | None,
    base_url: str | None,
    temperature: float,
) -> LLM:
    """Build a fresh model instance for one benchmark role.

    API credentials intentionally are not accepted here. Live provider adapters
    obtain credentials through their normal environment variables.
    """
    if provider == "reference":
        style = model or "reference-evidence"
        if style not in SUPPORTED_REFERENCE_MODELS:
            allowed = ", ".join(SUPPORTED_REFERENCE_MODELS)
            raise ValueError(f"Unknown reference model `{style}`; choose one of: {allowed}")
        return ReferenceBenchmarkLLM(
            role=role,
            case_config=case_config,
            seed=seed,
            model_style=style,
        )

    kwargs: dict[str, Any] = {"model_params": {"temperature": temperature}}
    if model:
        kwargs["model"] = model
    if base_url:
        kwargs["base_url"] = base_url
    return create_llm(provider, **kwargs)


__all__ = ["SUPPORTED_PROVIDERS", "SUPPORTED_REFERENCE_MODELS", "model_for_role"]
