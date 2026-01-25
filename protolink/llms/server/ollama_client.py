from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

from protolink.llms._deps import require_ollama
from protolink.llms.history import ConversationHistory
from protolink.llms.server.base import ServerLLM
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OllamaLLM(ServerLLM):
    """Ollama Server implementation of the LLM interface using ConversationHistory."""

    provider: ClassVar[LLMProvider] = "ollama"
    DEFAULT_MODEL: ClassVar[str] = "llama3.2"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    system_prompt: str = "You are a helpful AI assistant."

    def __init__(
        self,
        *,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}

        super().__init__(model=resolved_model, model_params=merged_params, base_url=base_url)

        # Resolve base_url and headers
        self.base_url = base_url or os.getenv("OLLAMA_HOST")
        if not self.base_url:
            raise ValueError(
                "Ollama base URL not provided. Set OLLAMA_HOST environment variable or pass the base_url parameter."
            )

        if headers is None:
            api_key = os.getenv("OLLAMA_API_KEY")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        # Initialize the client
        ollama_client = require_ollama()
        self._client = ollama_client(host=self.base_url, headers=headers)

        if not self.validate_connection():
            raise ValueError("Ollama connection failed. Check OLLAMA_HOST, OLLAMA_API_KEY, or server availability.")

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming response from Ollama."""
        formatted_messages = self._format_history(history)

        response: dict[str, Any] = self._client.chat(
            model=self.model,
            messages=formatted_messages,
            **self._model_params,
        )

        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> Iterable[str]:
        """Generate a streaming response from Ollama."""
        formatted_messages = self._format_history(history)

        stream = self._client.chat(
            model=self.model,
            messages=formatted_messages,
            stream=True,
            **self._model_params,
        )

        for chunk in stream:
            delta = chunk.get("message", {}).get("content", "")
            if not delta:
                continue
            yield delta

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def _format_history(self, history: ConversationHistory) -> list[dict[str, str]]:
        """Convert ConversationHistory to Ollama chat messages format."""
        formatted: list[dict[str, str]] = []

        if self.system_prompt:
            formatted.append({"role": "system", "content": self.system_prompt})

        for msg in history.messages:
            formatted.append({"role": msg.role, "content": msg.content})

        return formatted

    def _parse_output(self, response: dict[str, Any]) -> str:
        """Extract the assistant's text from Ollama response."""
        return response.get("message", {}).get("content", "")

    def validate_connection(self) -> bool:
        """Validate Ollama server connectivity and model availability."""
        try:
            self._client.list()  # lightweight check
            return True
        except Exception as e:
            logger.warning(f"Ollama connection failed: {e}")
            return False
