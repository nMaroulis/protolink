from __future__ import annotations

import os
from collections.abc import AsyncIterable
from typing import Any, ClassVar

from protolink.llms._deps import require_hugging_face
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class HuggingFaceLLM(APILLM):
    """HuggingFace Inference API LLM implementation."""

    provider: ClassVar[LLMProvider] = "huggingface"
    DEFAULT_MODEL: ClassVar[str] = ""
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "max_new_tokens": 512,
        "temperature": 1.0,
        "top_p": 1.0,
        "repetition_penalty": 1.0,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}
        super().__init__(model=resolved_model, model_params=merged_params)

        # Initialize HuggingFace InferenceClient
        hf_inference_client = require_hugging_face()
        token = api_key or os.getenv("HF_API_TOKEN")

        if not token:
            logger.warning("No HF_API_TOKEN provided. Some models may not be available.")

        self._client = hf_inference_client(token=token)

        # Skip validation for now to avoid initialization issues
        # User can validate manually if needed

    # ----------------------------------------------------------------------
    # LLM calling
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        prompt = "\n".join(msg["content"] for msg in history.messages)

        try:
            logger.info(f"Calling HuggingFace API with model: {self.model}")
            response = self._client.chat_completion(
                prompt,
                model=self.model,
                temperature=self._model_params.get("temperature", 1.0),
            )
            logger.info(f"Response type: {type(response)}")

            # HF text_generation returns a string directly
            if isinstance(response, str):
                return response
            # HF text_generation can also return a list of dicts
            elif isinstance(response, list) and response:
                return response[0].get("generated_text", "")
            else:
                logger.warning(f"Unexpected response format: {type(response)}")
                return str(response) if response else ""
        except StopIteration as e:
            logger.error(
                f"StopIteration error in HuggingFace API call. "
                f"This may indicate a provider mapping issue. Model: {self.model}"
            )
            raise ValueError(
                f"HuggingFace API provider mapping failed for model '{self.model}'. "
                f"The model may not be available or there's a configuration issue."
            ) from e
        except Exception as e:
            logger.error(f"Error in HuggingFace API call: {e}")
            raise

    async def call_stream(self, history: ConversationHistory) -> AsyncIterable[str]:
        # TODO: Implement streaming
        yield ""

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        try:
            # Try a simple API call to validate connection
            self._client.text_generation("test", model=self.model, max_new_tokens=1)
            return True
        except Exception:
            return False
