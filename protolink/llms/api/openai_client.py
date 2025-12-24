from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

from protolink.llms._deps import require_openai
from protolink.llms.api.base import APILLM
from protolink.llms.base import LLMProvider
from protolink.models import Message, Part
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OpenAILLM(APILLM):
    """OpenAI API implementation of the LLM interface."""

    provider: LLMProvider = "openai"
    model: str = "gpt-4o-mini"
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
        openai, _, _ = require_openai()
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

    def _to_message(self, response: Any) -> Message:
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

        return Message(
            role="assistant",
            parts=[Part("assistant", output_text)],
            timestamp=response.created_at,
        )

    def generate_response(self, messages: list[Message]) -> Message:
        """Generate a single response from the model."""
        response = self._client.responses.create(
            model=self.model, input=self._format_messages(messages), **self.model_params
        )
        return self._to_message(response)

    def generate_stream_response(self, messages: list[Message]) -> Iterable[Message]:
        """Generate a streaming response using OpenAI Responses API."""

        stream = self._client.responses.create(
            model=self.model,
            input=self._format_messages(messages),
            stream=True,
            **self.model_params,
        )

        current_content = ""

        for event in stream:
            # We only care about output text deltas
            if event.type != "response.output_text.delta":
                continue

            # event.delta is a string chunk
            current_content += event.delta

            yield Message(
                role="assistant",
                parts=[Part("assistant", current_content)],
            )

    def validate_connection(self) -> bool:
        try:
            # Check that the configured model is available / accessible
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"OpenAI connection validation failed for model {self.model}: {e}")
            return False
