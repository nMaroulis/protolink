"""Grok LLM - xAI's Grok API implementation using HTTP client."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx

from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class GrokLLM(APILLM):
    """xAI Grok API implementation using direct HTTP requests.

    Uses the xAI chat completions API at api.x.ai/v1/chat/completions.

    Docs:
        https://docs.x.ai/developers/api-reference

    Example:
        >>> from protolink.llms.api import GrokLLM
        >>> llm = GrokLLM(api_key="xai-...")
        >>> response = llm.chat("Hello, Grok!")
    """

    provider: ClassVar[LLMProvider] = "grok"
    DEFAULT_MODEL: ClassVar[str] = "grok-4-latest"
    DEFAULT_BASE_URL: ClassVar[str] = "https://api.x.ai/v1"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    REQUEST_TIMEOUT: ClassVar[int] = 90

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> None:
        """Initialize the Grok LLM client.

        Args:
            api_key: xAI API key. Falls back to XAI_API_KEY or GROK_API_KEY env var.
            model: Model identifier. Defaults to "grok-4-latest".
            model_params: Generation parameters (temperature, top_p, etc.).
            base_url: API base URL. Defaults to "https://api.x.ai/v1".
        """
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}
        resolved_base_url = base_url or self.DEFAULT_BASE_URL

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=resolved_base_url,
        )

        self._api_key = api_key or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
        if not self._api_key:
            logger.warning("No API key provided for Grok. Set XAI_API_KEY or GROK_API_KEY env var.")

        self._client = httpx.Client(timeout=self.REQUEST_TIMEOUT)
        self._async_client = httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT)

        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    @property
    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response from Grok."""
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
            **self._model_params,
        }

        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response from Grok."""
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
            **self._model_params,
        }

        async with self._async_client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Remove "data: " prefix
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    continue

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        """Validate the connection to the Grok API."""
        try:
            response = self._client.get(
                f"{self.base_url}/models",
                headers=self._headers,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Grok connection validation failed: {e}")
            return False

    def __del__(self) -> None:
        """Cleanup HTTP clients on deletion."""
        if hasattr(self, "_client"):
            self._client.close()
