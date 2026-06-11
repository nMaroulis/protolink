import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from protolink.llms._deps import require_llama_cpp
from protolink.llms.history import ConversationHistory
from protolink.llms.local.base import LocalLLM
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class LlamaCPPLocalLLM(LocalLLM):
    """Local Llama.cpp implementation of the LLM interface running inside the local Python process."""

    provider: ClassVar[LLMProvider] = "llama.cpp-local"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 0.8,
        "max_tokens": 1024,
    }

    def __init__(
        self,
        *,
        model: str,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}
        super().__init__(model=model, model_params=merged_params)

        llama_cpp = require_llama_cpp()

        if not os.path.exists(self.model):
            raise FileNotFoundError(f"Model file not found at {self.model}")

        self._client = llama_cpp.Llama(model_path=self.model, verbose=False)
        self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response using local llama_cpp python bindings."""
        response = self._client.create_chat_completion(
            messages=history.messages,
            stream=False,
            **self._model_params,
        )
        return response["choices"][0]["message"]["content"]

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response natively evaluating local model generations."""
        stream = self._client.create_chat_completion(
            messages=history.messages,
            stream=True,
            **self._model_params,
        )

        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            if "content" in delta:
                yield delta["content"]

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        if self._client is not None:
            return True
        logger.error(f"Cannot instantiate local model at {self.model}")
        return False
