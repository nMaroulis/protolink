from typing import ClassVar

from protolink.llms.api.anthropic_client import AnthropicLLM
from protolink.llms.api.openai_client import OpenAILLM
from protolink.llms.base import LLM
from protolink.llms.server.ollama_client import OllamaLLM


class LLMClientFactory:
    _clients: ClassVar[dict[str, type[LLM]]] = {"openai": OpenAILLM, "anthropic": AnthropicLLM, "ollama": OllamaLLM}

    @classmethod
    def get_client(cls, llm_client: str, **kwargs) -> LLM:
        client_class = cls._clients.get(llm_client.lower())
        if not client_class:
            raise ValueError(f"Unknown LLM API name: {llm_client}")
        return client_class(**kwargs)
