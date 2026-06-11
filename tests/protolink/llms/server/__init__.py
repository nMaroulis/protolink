from __future__ import annotations

import importlib
from typing import Any

__all__ = ["LMStudioLLM", "LlamaCPPServerLLM", "OllamaLLM", "OpenAICompatibleLLM"]

_EXPORTS = {
    "LMStudioLLM": "protolink.llms.server.openai_compatible_client.LMStudioLLM",
    "LlamaCPPServerLLM": "protolink.llms.server.llamacpp_client.LlamaCPPServerLLM",
    "OllamaLLM": "protolink.llms.server.ollama_client.OllamaLLM",
    "OpenAICompatibleLLM": "protolink.llms.server.openai_compatible_client.OpenAICompatibleLLM",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_path, attr = _EXPORTS[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value
