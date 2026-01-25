from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

from protolink.llms._deps import require_openai
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class DeepSeekLLM(APILLM):
    """DeepSeek API implementation using OpenAI-compatible SDK."""

    provider: ClassVar[LLMProvider] = "deepseek"
    DEFAULT_MODEL: ClassVar[str] = "deepseek-chat"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
        "top_p": 1.0,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = "https://api.deepseek.com",
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=base_url,
        )

        openai, _, _ = require_openai()
        self._client = openai.OpenAI(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
            base_url=base_url,
        )

        if not self.validate_connection():
            raise ValueError(
                "DeepSeek API key not provided or connection failed. "
                "Set DEEPSEEK_API_KEY environment variable or pass api_key parameter."
            )

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=history.messages,
            stream=False,
            **self._model_params,
        )
        return response.choices[0].message.content

    async def call_stream(self, history: ConversationHistory) -> Iterable[str]:
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=history.messages,
            stream=True,
            **self._model_params,
        )

        for event in stream:
            # Only yield text deltas
            delta = getattr(event.choices[0].delta, "content", None)
            if delta:
                yield delta

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        try:
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"DeepSeek connection validation failed for model {self.model}: {e}")
            return False
