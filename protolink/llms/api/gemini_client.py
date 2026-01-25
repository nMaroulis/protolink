from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

from protolink.llms._deps import require_gemini
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class GeminiLLM(APILLM):
    """Google Gemini API implementation of the LLM interface."""

    provider: ClassVar[LLMProvider] = "gemini"

    # Pick a stable or "latest" model alias from Gemini API
    DEFAULT_MODEL: ClassVar[str] = "gemini-3-flash-preview"  # stable, high-quality text gen
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        # Google GenAI SDK specifics:
        # You can pass config dicts such as temperature, thinking budgets, etc.
        "temperature": 1.0,  # sampling randomness
        "top_p": 1.0,  # nucleus sampling
        # You may add other config options via the SDK's GenerateContentConfig
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {
            **self.DEFAULT_MODEL_PARAMS,
            **(model_params or {}),
        }

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=base_url,
        )

        genai, GenerateContentConfig = require_gemini()  # noqa: N806
        # Initialize the Gemini (GenAI) client
        self._client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        # Store the config type class for later use
        self._GenerateContentConfig = GenerateContentConfig
        if not self.validate_connection:
            raise ValueError("Gemini API key not provided. Set GEMINI_API_KEY env var or pass api_key parameter.")

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming response from Gemini."""
        # The Gemini API uses “contents” for text input; we join the conversation
        # messages into a single string. You could use more structured formats if needed.
        prompt = "\n".join(msg["content"] for msg in history.messages)

        # Build a config object from model_params
        config = self._GenerateContentConfig(**self._model_params)

        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text  # The SDK exposes a .text attribute

    async def call_stream(self, history: ConversationHistory) -> Iterable[str]:
        """Generate a streaming response using Gemini's streaming endpoint."""
        prompt = "\n".join(msg["content"] for msg in history.messages)

        config = self._GenerateContentConfig(**self._model_params)
        stream = self._client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=config,
        )

        for chunk in stream:
            # Each chunk has a `.text` field with incremental text
            yield chunk.text

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        try:
            # Lightweight validation by listing or getting the model
            _ = self._client.models.get(model=self.model)
            # If no exception, connection & model exist
            return True
        except Exception as e:
            logger.warning(f"Gemini connection validation failed for model {self.model}: {e}")
            return False
