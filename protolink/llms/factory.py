from __future__ import annotations

import importlib
from enum import StrEnum
from typing import Any, ClassVar

from protolink.llms.base import LLM
from protolink.llms.metrics import LLMModelProfile


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    GROK = "grok"
    HUGGINGFACE = "huggingface"
    LLAMACPP_LOCAL = "llama.cpp-local"
    LLAMACPP_SERVER = "llama.cpp-server"
    LMSTUDIO = "lmstudio"
    OLLAMA = "ollama"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai-compatible"
    VLLM = "vllm"
    MOCK = "mock"


class LLMFactory:
    """
    Factory for creating LLM client instances.

    Provider classes are imported lazily so optional SDK dependencies are only
    required when the selected provider actually needs them.
    """

    _clients: ClassVar[dict[str, type[LLM] | str]] = {
        LLMProvider.ANTHROPIC.value: "protolink.llms.api.anthropic_client.AnthropicLLM",
        LLMProvider.DEEPSEEK.value: "protolink.llms.api.deepseek_client.DeepSeekLLM",
        LLMProvider.GEMINI.value: "protolink.llms.api.gemini_client.GeminiLLM",
        LLMProvider.GROK.value: "protolink.llms.api.grok_client.GrokLLM",
        LLMProvider.HUGGINGFACE.value: "protolink.llms.api.hugging_face_client.HuggingFaceLLM",
        LLMProvider.LLAMACPP_LOCAL.value: "protolink.llms.local.llamacpp_client.LlamaCPPLocalLLM",
        LLMProvider.LLAMACPP_SERVER.value: "protolink.llms.server.llamacpp_client.LlamaCPPServerLLM",
        LLMProvider.LMSTUDIO.value: "protolink.llms.server.openai_compatible_client.LMStudioLLM",
        LLMProvider.OLLAMA.value: "protolink.llms.server.ollama_client.OllamaLLM",
        LLMProvider.OPENAI.value: "protolink.llms.api.openai_client.OpenAILLM",
        LLMProvider.OPENAI_COMPATIBLE.value: "protolink.llms.server.openai_compatible_client.OpenAICompatibleLLM",
        LLMProvider.VLLM.value: "protolink.llms.server.vllm_client.VLLMLLM",
        LLMProvider.MOCK.value: "protolink.llms.mock_client.MockLLM",
    }

    @classmethod
    def create(cls, provider: str | LLMProvider, **kwargs) -> LLM:
        """
        Create an LLM client instance.

        Args:
            provider (str | LLMProvider): The name of the LLM provider
                (e.g., "openai", "ollama", "lmstudio", "vllm"), or a
                "provider:model" string. Only the first colon separates the
                provider; the model's case, tags, paths, and further colons are retained.
            **kwargs: Additional provider constructor arguments. ProtoLink
                runtime options such as ``metrics_profile``,
                ``metrics_enabled``, and ``max_parse_failures`` are consumed by
                the factory and are not forwarded to provider request options.

        Returns:
            LLM: An instance of the requested LLM client.

        Raises:
            ValueError: If the provider name is unknown.
        """
        metrics_profile: LLMModelProfile | dict[str, Any] | None = kwargs.pop("metrics_profile", None)
        metrics_enabled: bool | None = kwargs.pop("metrics_enabled", None)
        max_parse_failures: int | None = kwargs.pop("max_parse_failures", None)

        if not isinstance(provider, str):
            raise ValueError("provider must be a provider alias or 'provider:model' string")
        provider_name, separator, model = provider.partition(":")
        provider_key = provider_name.strip().lower()
        if not provider_key or (separator and not model.strip()):
            raise ValueError("Use a non-empty provider alias or 'provider:model' string")
        if separator:
            if "model" in kwargs:
                raise ValueError("Specify the model either in 'provider:model' or model=, not both")
            kwargs["model"] = model

        client_class = cls._resolve_client(provider_key)
        llm = client_class(**kwargs)
        if max_parse_failures is not None:
            llm.max_parse_failures = max_parse_failures
        if metrics_profile is not None:
            llm.configure_metrics(metrics_profile)
        if metrics_enabled is not None:
            llm.metrics_enabled = metrics_enabled
        return llm

    @classmethod
    def _resolve_client(cls, provider_key: str) -> type[LLM]:
        client = cls._clients.get(provider_key)
        if not client:
            valid_providers = ", ".join(sorted(cls._clients.keys()))
            raise ValueError(f"Unknown LLM provider: '{provider_key}'. Available providers: {valid_providers}")

        if isinstance(client, str):
            module_path, class_name = client.rsplit(".", 1)
            module = importlib.import_module(module_path)
            client = getattr(module, class_name)
            cls._clients[provider_key] = client

        return client


def create_llm(provider: str | LLMProvider, **kwargs) -> LLM:
    """
    Convenience function to create an LLM client.

    See LLMFactory.create for details.
    """
    return LLMFactory.create(provider, **kwargs)
