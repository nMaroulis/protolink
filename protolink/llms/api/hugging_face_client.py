from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from protolink.llms._deps import require_hugging_face
from protolink.llms._streaming import threaded_stream
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
        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        messages = [{"role": msg["role"], "content": msg["content"]} for msg in history.messages]

        try:
            logger.info(f"Calling HuggingFace API with model: {self.model}")
            response = self._client.chat_completion(
                messages,
                model=self.model,
                temperature=self._model_params.get("temperature", 1.0),
            )
            logger.info(f"Response type: {type(response)}")

            if hasattr(response, "choices") and response.choices:
                try:
                    content = response.choices[0].message.content
                    return content if content is not None else ""
                except AttributeError:
                    pass

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

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Yield text while synchronous SDK reads run on a dedicated worker.

        The event loop stays available to consumers. Close this iterator when
        stopping early; cleanup waits for any in-progress SDK operation to
        return on the worker. Text parsing happens on the caller's event loop.
        """
        messages = [{"role": msg["role"], "content": msg["content"]} for msg in history.messages]

        try:
            logger.info(f"Calling HuggingFace streaming API with model: {self.model}")
            async with threaded_stream(
                lambda: self._client.chat_completion(
                    messages,
                    model=self.model,
                    stream=True,
                    temperature=self._model_params.get("temperature", 1.0),
                )
            ) as stream:
                async for chunk in stream:
                    if hasattr(chunk, "choices") and chunk.choices:
                        delta = getattr(chunk.choices[0], "delta", None)
                        content = getattr(delta, "content", None) if delta is not None else None
                        if content:
                            yield content
                    elif isinstance(chunk, dict) and "choices" in chunk:
                        choices = chunk.get("choices", [])
                        if choices and isinstance(choices[0], dict):
                            delta = choices[0].get("delta", {})
                            content = (
                                delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
                            )
                            if content:
                                yield content
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
            logger.error(f"Error in HuggingFace streaming API call: {e}")
            raise

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        try:
            # Try a simple API call to validate connection
            self._client.text_generation("test", model=self.model, max_new_tokens=1)
            return True
        except Exception as e:
            logger.warning(f"HuggingFace connection validation failed for model {self.model}: {e}")
            return False
