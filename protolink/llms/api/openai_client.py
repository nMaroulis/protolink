from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

import openai
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from protolink.llms.api.base import APILLM
from protolink.llms.base import LLMProvider
from protolink.models import Message
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OpenAILLM(APILLM):
    """OpenAI API implementation of the LLM interface."""

    provider: LLMProvider = "openai"
    model: str = "gpt-5"
    model_params: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,  # Default is 1.0 (0.0 to 2.0)
        "top_p": 1.0,  # Default is 1.0
        "n": 1,  # Default number of completions
        "stream": False,  # Default is False
        "stop": None,  # Default is None (can be str, list[str], or None)
        "max_tokens": None,  # Default is None (inf)
        "presence_penalty": 0.0,  # Default is 0.0 (-2.0 to 2.0)
        "frequency_penalty": 0.0,  # Default is 0.0 (-2.0 to 2.0)
        "logit_bias": None,  # Default is None
    }
    system_prompt: str = """You are a helpful AI assistant."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ):
        if model_params is None:
            model_params = {}
        if model:
            self.model = model
        self.base_url = base_url
        super().__init__()
        self._client = openai.OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"), base_url=base_url)
        self.model_params = model_params
        if not self._client.api_key:
            raise ValueError(
                "OpenAI API key not provided. Set OPENAI_API_KEY environment variable or pass the api_key parameter."
            )

    def _format_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        """Convert internal Message format to OpenAI's format."""
        formatted = []
        # Add system message if we have a system prompt
        if self.system_prompt:
            formatted.append({"role": "system", "content": self.system_prompt})

        for msg in messages:
            formatted.append({"role": msg.role, "content": msg.parts[0].content})
        return formatted

    def _to_message(self, completion: ChatCompletion) -> Message:
        """Convert OpenAI completion to internal Message format."""
        choice = completion.choices[0]
        return Message(
            role=choice.message.role,
            content=choice.message.content or "",
            finish_reason=choice.finish_reason,
            timestamp=choice.created,
        )

    def generate_response(self, messages: list[Message]) -> Message:
        """Generate a single response from the model."""
        response = self._client.responses.create(
            model=self.model, messages=self._format_messages(messages), **self.model_params
        )
        return self._to_message(response)

    def generate_stream_response(self, messages: list[Message]) -> Iterable[Message]:
        """Generate a streaming response from the model."""
        stream = self._client.responses.create(
            model=self.model, messages=self._format_messages(messages), stream=True, **self.model_params
        )
        # Handle streaming response
        current_content = ""
        for chunk in stream:
            if not isinstance(chunk, ChatCompletionChunk):
                continue

            delta = chunk.choices[0].delta
            if delta.content:
                current_content += delta.content
                yield Message(role="assistant", content=current_content, finish_reason=None)

    def validate_connection(self) -> bool:
        try:
            # Check that the configured model is available / accessible
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"OpenAI connection validation failed for model {self.model}: {e}")
            return False
