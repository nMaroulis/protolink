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


class OpenAILLM(APILLM):
    """OpenAI API implementation of the LLM API interface."""

    provider: ClassVar[LLMProvider] = "openai"
    DEFAULT_MODEL: ClassVar[str] = "gpt-4o-mini"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,  # Sampling randomness (0-2)
        "top_p": 1.0,  # Nucleus sampling
        "top_logprobs": None,  # Number of logprobs to return (optional)
        "truncation": "disabled",  # How to handle inputs exceeding model context; "disabled" or "auto"
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

        # Set OpenAI API Client
        openai, _, _ = require_openai()
        self._client = openai.OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url,
        )
        if not self.validate_connection():
            raise ValueError(
                "OpenAI API key not provided. Set OPENAI_API_KEY environment variable or pass the api_key parameter."
            )

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response from the model."""

        response = self._client.responses.create(model=self.model, input=history.messages, **self._model_params)
        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> Iterable[str]:
        """Generate a streaming response using OpenAI Responses API."""

        stream = self._client.responses.create(
            model=self.model,
            input=history.messages,
            stream=True,
            **self._model_params,
        )

        for event in stream:
            # We only care about output text deltas
            if event.type != "response.output_text.delta":
                continue

            # event.delta is a string chunk - yield only the new chunk
            yield event.delta

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def _parse_output(self, response: Any) -> str:
        """Convert OpenAI completion to internal Message format."""

        output_text: str = ""
        for item in response.output or []:
            # item: ResponseOutputMessage
            if item.type != "message":
                continue
            if item.role != "assistant":
                continue

            for content in item.content:
                # content: ResponseOutputText (or other types later)
                if content.type == "output_text":
                    output_text += content.text

        return output_text

    def validate_connection(self) -> bool:
        try:
            # Check that the configured model is available / accessible
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"OpenAI connection validation failed for model {self.model}: {e}")
            return False
