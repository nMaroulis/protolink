from enum import Enum
from typing import ClassVar

from protolink.llms.api.anthropic_client import AnthropicLLM
from protolink.llms.api.deepseek_client import DeepSeekLLM
from protolink.llms.api.gemini_client import GeminiLLM
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.base import LLM
from protolink.llms.local.llamacpp_client import LlamaCPPLocalLLM
from protolink.llms.server.llamacpp_client import LlamaCPPServerLLM
from protolink.llms.server.ollama_client import OllamaLLM


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    LLAMACPP_LOCAL = "llama.cpp-local"
    LLAMACPP_SERVER = "llama.cpp-server"
    OLLAMA = "ollama"
    OPENAI = "openai"


class LLMFactory:
    """
    Factory for creating LLM client instances.

    This factory abstracts the instantiation of different LLM providers,
    providing a uniform interface for creating LLM clients.
    """

    _clients: ClassVar[dict[str, type[LLM]]] = {
        LLMProvider.ANTHROPIC: AnthropicLLM,
        LLMProvider.DEEPSEEK: DeepSeekLLM,
        LLMProvider.GEMINI: GeminiLLM,
        LLMProvider.LLAMACPP_LOCAL: LlamaCPPLocalLLM,
        LLMProvider.LLAMACPP_SERVER: LlamaCPPServerLLM,
        LLMProvider.OLLAMA: OllamaLLM,
        LLMProvider.OPENAI: OpenAILLM,
    }

    @classmethod
    def create(cls, provider: str | LLMProvider, **kwargs) -> LLM:
        """
        Create an LLM client instance.

        Args:
            provider (str | LLMProvider): The name of the LLM provider
                (e.g., "openai", "ollama", "anthropic", "llama.cpp-server").
            **kwargs: Additional keyword arguments passed to the LLM constructor.

        Returns:
            LLM: An instance of the requested LLM client.

        Raises:
            ValueError: If the provider name is unknown.
        """
        try:
            # Ensure provider is a string for lookup
            provider_key = str(provider).lower()
        except Exception as err:
            raise ValueError(f"Invalid provider type: {type(provider)}") from err

        client_class = cls._clients.get(provider_key)
        if not client_class:
            valid_providers = ", ".join(sorted(cls._clients.keys()))
            raise ValueError(f"Unknown LLM provider: '{provider}'. Available providers: {valid_providers}")

        return client_class(**kwargs)


def create_llm(provider: str | LLMProvider, **kwargs) -> LLM:
    """
    Convenience function to create an LLM client.

    See LLMFactory.create for details.
    """
    return LLMFactory.create(provider, **kwargs)
