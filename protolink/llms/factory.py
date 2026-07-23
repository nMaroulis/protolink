from __future__ import annotations

import importlib
from enum import Enum
from typing import Any, ClassVar

from protolink.llms.base import LLM
from protolink.llms.metrics import LLMModelProfile


class LLMProvider(str, Enum):
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
                (e.g., "openai", "ollama", "lmstudio", "vllm").
            **kwargs: Additional keyword arguments passed to the LLM constructor.

        Returns:
            LLM: An instance of the requested LLM client.

        Raises:
            ValueError: If the provider name is unknown.
        """
        metrics_profile: LLMModelProfile | dict[str, Any] | None = kwargs.pop("metrics_profile", None)
        metrics_enabled: bool | None = kwargs.pop("metrics_enabled", None)

        try:
            provider_key = str(provider).lower()
        except Exception as err:
            raise ValueError(f"Invalid provider type: {type(provider)}") from err

        client_class = cls._resolve_client(provider_key)
        llm = client_class(**kwargs)
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
