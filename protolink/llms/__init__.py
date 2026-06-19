from __future__ import annotations

import importlib
from typing import Any

__all__ = ["LLMModelProfile", "LMStudioLLM", "MockLLM", "OpenAICompatibleLLM", "create_llm"]

_EXPORTS = {
    "LLMModelProfile": "protolink.llms.metrics.LLMModelProfile",
    "LMStudioLLM": "protolink.llms.server.openai_compatible_client.LMStudioLLM",
    "MockLLM": "protolink.llms.mock_client.MockLLM",
    "OpenAICompatibleLLM": "protolink.llms.server.openai_compatible_client.OpenAICompatibleLLM",
    "create_llm": "protolink.llms.factory.create_llm",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_path, attr = _EXPORTS[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value
