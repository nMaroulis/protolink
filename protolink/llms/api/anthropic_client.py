from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, ClassVar

import anthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types.message_param import MessageParam
from anthropic.types.message_stream_event import MessageStreamEvent

from protolink.llms.api.base import APILLM
from protolink.llms.base import LLMProvider
from protolink.models import Message
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class AnthropicLLM(APILLM):
    """Anthropic API implementation of the LLM interface."""

    provider: LLMProvider = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    model_params: ClassVar[dict[str, Any]] = {
        "max_tokens": 4096,  # Default max tokens
        "temperature": 1.0,  # Default is 1.0 (0.0 to 1.0)
        "top_p": 1.0,  # Default is 1.0
        "top_k": None,  # Anthropic specific parameter
        "stop_sequences": None,  # Default is None
        "metadata": None,  # Default is None
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
        self.base_url = base_url
        super().__init__()
        self._client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"), base_url=base_url)
        if model:
            self.model = model
        self.model_params.update(model_params)
        if not self._client.api_key:
            raise ValueError(
                "Anthropic API key not provided. Set ANTHROPIC_API_KEY environment variable or pass the api_key parameter."  # noqa: E501
            )

    def _format_messages(self, messages: list[Message]) -> list[MessageParam]:
        """Convert internal Message format to Anthropic's format."""
        formatted = []
        system_content = self.system_prompt

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                formatted.append({"role": msg.role, "content": msg.content})

        return formatted, system_content

    def _to_message(self, response: AnthropicMessage) -> Message:
        """Convert Anthropic response to internal Message format."""
        return Message(
            role="assistant",
            content=response.content[0].text,
            finish_reason=response.stop_reason,
        )

    def generate_response(self, messages: list[Message]) -> Message:
        """Generate a single response from the model."""
        formatted_messages, system_content = self._format_messages(messages)

        response = self._client.messages.create(
            model=self.model,
            messages=formatted_messages,
            system=system_content,
            **{k: v for k, v in self.model_params.items() if v is not None},
        )
        return self._to_message(response)

    def generate_stream_response(self, messages: list[Message]) -> Iterable[Message]:
        """Generate a streaming response from the model."""
        formatted_messages, system_content = self._format_messages(messages)

        with self._client.messages.stream(
            model=self.model,
            messages=formatted_messages,
            system=system_content,
            **{k: v for k, v in self.model_params.items() if v is not None},
        ) as stream:
            current_content = ""
            for chunk in stream:
                if isinstance(chunk, MessageStreamEvent) and chunk.type == "content_block_delta":
                    current_content += chunk.delta.text
                    yield Message(
                        role="assistant",
                        content=current_content,
                        finish_reason=None,
                    )

    def validate_connection(self) -> bool:
        try:
            # Check that the configured model is available / accessible
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"Anthropic connection validation failed for model {self.model}: {e}")
            return False
