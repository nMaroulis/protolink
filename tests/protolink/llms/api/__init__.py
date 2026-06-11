from __future__ import annotations

import importlib
from typing import Any

__all__ = ["AnthropicLLM", "DeepSeekLLM", "GeminiLLM", "GrokLLM", "HuggingFaceLLM", "OpenAILLM"]

_EXPORTS = {
    "AnthropicLLM": "protolink.llms.api.anthropic_client.AnthropicLLM",
    "DeepSeekLLM": "protolink.llms.api.deepseek_client.DeepSeekLLM",
    "GeminiLLM": "protolink.llms.api.gemini_client.GeminiLLM",
    "GrokLLM": "protolink.llms.api.grok_client.GrokLLM",
    "HuggingFaceLLM": "protolink.llms.api.hugging_face_client.HuggingFaceLLM",
    "OpenAILLM": "protolink.llms.api.openai_client.OpenAILLM",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_path, attr = _EXPORTS[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value
