from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

from ollama import Client

from protolink.core.part import Part
from protolink.llms.base import LLMProvider
from protolink.llms.server.base import ServerLLM
from protolink.models import Message
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OllamaLLM(ServerLLM):
    """Ollama Server implementation of the LLM interface."""

    provider: LLMProvider = "ollama"
    model: str = "gemma3"
    model_params: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    system_prompt: str = """You are a helpful AI assistant."""

    def __init__(
        self,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        if model_params is None:
            model_params = {}

        if base_url is None:
            base_url = os.getenv("OLLAMA_HOST")
            if base_url is None:
                raise ValueError(
                    "Ollama base URL not provided. Set OLLAMA_HOST environment variable or pass the base_url parameter."
                )
        if headers is None:
            headers = (
                {"Authorization": "Bearer " + os.environ.get("OLLAMA_API_KEY")} if os.getenv("OLLAMA_API_KEY") else {}
            )

        super().__init__(base_url=base_url)

        self._client = Client(host=self.base_url, headers=headers)

        if model:
            self.model = model

        self.model_params.update(model_params)

    def _format_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        formatted: list[dict[str, str]] = []

        if self.system_prompt:
            formatted.append({"role": "system", "content": self.system_prompt})

        for msg in messages:
            if not msg.parts:
                continue
            formatted.append({"role": msg.role, "content": msg.parts[0].content})

        return formatted

    def _to_message(self, content: str) -> Message:
        return Message(role="assistant", parts=[Part.text(content)])

    def generate_response(self, messages: list[Message]) -> Message:
        formatted_messages = self._format_messages(messages)

        response: dict[str, Any] = self._client.chat(
            model=self.model,
            messages=formatted_messages,
            **self.model_params,
        )

        content = response.get("message", {}).get("content", "")
        return self._to_message(content)

    def generate_stream_response(self, messages: list[Message]) -> Iterable[Message]:
        formatted_messages = self._format_messages(messages)

        stream = self._client.chat(
            model=self.model,
            messages=formatted_messages,
            stream=True,
            **self.model_params,
        )

        current_content = ""
        for chunk in stream:
            message = chunk.get("message")
            if not message:
                continue

            delta = message.get("content", "")
            if not delta:
                continue

            current_content += delta
            yield self._to_message(current_content)

    def validate_connection(self) -> bool:
        """Validate that the Ollama server is reachable and the model is available."""
        try:
            # Check if the model exists
            self._client.list()
            return True
        except Exception as e:
            logger.warning(f"Ollama connection failed: {e}")
            return False
