from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "VLLMLLM",
    "ContextItem",
    "ContextManifest",
    "HistoryCompactionRequest",
    "HistoryCompactionResult",
    "HistoryCompactionStrategy",
    "HistoryCompactor",
    "InferParseError",
    "LLMModelProfile",
    "LMStudioLLM",
    "MockLLM",
    "OpenAICompatibleLLM",
    "build_context_manifest",
    "create_llm",
]

_EXPORTS = {
    "ContextItem": "protolink.llms.context.ContextItem",
    "ContextManifest": "protolink.llms.context.ContextManifest",
    "HistoryCompactionRequest": "protolink.llms.compaction.HistoryCompactionRequest",
    "HistoryCompactionResult": "protolink.llms.compaction.HistoryCompactionResult",
    "HistoryCompactionStrategy": "protolink.llms.compaction.HistoryCompactionStrategy",
    "HistoryCompactor": "protolink.llms.compaction.HistoryCompactor",
    "InferParseError": "protolink.llms.errors.InferParseError",
    "LLMModelProfile": "protolink.llms.metrics.LLMModelProfile",
    "LMStudioLLM": "protolink.llms.server.openai_compatible_client.LMStudioLLM",
    "MockLLM": "protolink.llms.mock_client.MockLLM",
    "OpenAICompatibleLLM": "protolink.llms.server.openai_compatible_client.OpenAICompatibleLLM",
    "VLLMLLM": "protolink.llms.server.vllm_client.VLLMLLM",
    "build_context_manifest": "protolink.llms.context.build_context_manifest",
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
