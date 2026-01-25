from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

from protolink.llms._deps import require_anthropic
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class AnthropicLLM(APILLM):
    """Anthropic API implementation of the LLM interface."""

    provider: ClassVar[LLMProvider] = "anthropic"

    DEFAULT_MODEL: ClassVar[str] = "claude-sonnet-4-20250514"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
        "top_p": 1.0,
        "max_tokens": 1024,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> None:
        # Vars passed to parent
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

        anthropic, _ = require_anthropic()
        self._client = anthropic.Anthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            base_url=base_url,
        )

        if not self.validate_connection():
            raise ValueError("Anthropic API key not provided. Set ANTHROPIC_API_KEY env var or pass api_key.")

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response from the model."""
        response = self._client.messages.create(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(history),
            stream=False,
            **self._model_params,
        )

        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> Iterable[str]:
        """Generate a streaming response using Anthropic Messages API."""

        with self._client.messages.stream(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(history),
            **self._model_params,
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue

                delta = event.delta
                if delta.type == "text_delta":
                    yield delta.text

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def _to_anthropic_messages(self, history: ConversationHistory) -> list[dict[str, Any]]:
        """
        Convert ConversationHistory to Anthropic message format.

        Anthropic does NOT want system messages inside messages[].
        """
        messages: list[dict[str, Any]] = []

        for msg in history.messages:
            if msg["role"] == "system":
                continue

            messages.append(
                {
                    "role": msg["role"],
                    "content": msg["content"],
                }
            )

        return messages

    def _parse_output(self, response: Any) -> str:
        """Convert Anthropic response to plain text."""

        output_text = ""
        for block in response.content:
            if block.type == "text":
                output_text += block.text

        return output_text

    def validate_connection(self) -> bool:
        try:
            # Lightweight validation call
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"Anthropic connection validation failed for model {self.model}: {e}")
            return False
