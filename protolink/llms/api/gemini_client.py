from __future__ import annotations

import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from google.generativeai.types import GenerateContentResponse, GenerationConfig

from protolink.llms._deps import require_gemini
from protolink.llms.api.base import APILLM
from protolink.llms.base import LLMProvider
from protolink.models import Message
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class GeminiLLM(APILLM):
    """Google Gemini API implementation of the LLM interface."""

    provider: LLMProvider = "gemini"
    model: str = "gemini-1.5-pro"
    model_params: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,  # Default is 1.0 (0.0 to 2.0)
        "top_p": 1.0,  # Default is 1.0
        "top_k": None,  # Default is None
        "max_output_tokens": None,  # Default is None (inf)
        "stop_sequences": None,  # Default is None
        "candidate_count": 1,  # Default is 1
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

        # Initialize the Gemini client
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "Gemini API key not provided. Set GEMINI_API_KEY environment variable or pass the api_key parameter."
            )

        genai, _, _ = require_gemini()
        genai.configure(api_key=api_key)
        if model:
            self.model = model
        self._client = genai.GenerativeModel(self.model)
        self.model_params = model_params

    def _format_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        """Convert internal Message format to Gemini's format."""
        formatted = []

        # Add system prompt as first message if present
        if self.system_prompt:
            formatted.append({"role": "user", "parts": [{"text": f"System: {self.system_prompt}"}]})

        for msg in messages:
            formatted.append({"role": msg.role, "content": msg.parts[0].content})

        return formatted

    def _to_message(self, response: GenerateContentResponse) -> Message:
        """Convert Gemini response to internal Message format."""
        content = ""
        finish_reason = None

        if response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                content = candidate.content.parts[0].text
            finish_reason = candidate.finish_reason.name.lower() if candidate.finish_reason else None

        return Message(
            role="assistant",
            content=content,
            finish_reason=finish_reason,
        )

    def generate_response(self, messages: list[Message]) -> Message:
        """Generate a single response from the model."""
        formatted_messages = self._format_messages(messages)

        # Convert the format for Gemini API
        contents = []
        for msg in formatted_messages:
            contents.append({"role": msg["role"], "parts": msg["parts"]})

        # Create generation config from model_params
        gen_config = GenerationConfig(
            temperature=self.model_params.get("temperature", 1.0),
            top_p=self.model_params.get("top_p", 1.0),
            top_k=self.model_params.get("top_k"),
            max_output_tokens=self.model_params.get("max_output_tokens"),
            stop_sequences=self.model_params.get("stop_sequences"),
            candidate_count=self.model_params.get("candidate_count", 1),
        )

        response = self._client.generate_content(
            contents=contents,
            generation_config=gen_config,
            max_tokens=2048,
            suffix=".",
        )

        return self._to_message(response)

    def generate_stream_response(self, messages: list[Message]) -> Iterable[Message]:
        """Generate a streaming response from the model."""
        formatted_messages = self._format_messages(messages)

        # Convert the format for Gemini API
        contents = []
        for msg in formatted_messages:
            contents.append({"role": msg["role"], "parts": msg["parts"]})

        # Create generation config from model_params
        gen_config = GenerationConfig(
            temperature=self.model_params.get("temperature", 1.0),
            top_p=self.model_params.get("top_p", 1.0),
            top_k=self.model_params.get("top_k"),
            max_output_tokens=self.model_params.get("max_output_tokens"),
            stop_sequences=self.model_params.get("stop_sequences"),
            candidate_count=self.model_params.get("candidate_count", 1),
        )

        current_content = ""
        response = self._client.generate_content(
            contents=contents,
            generation_config=gen_config,
            stream=True,
        )

        for chunk in response:
            if chunk.text:
                current_content += chunk.text
                yield Message(
                    role="assistant",
                    content=current_content,
                    finish_reason=None,
                )

    def validate_connection(self) -> bool:
        """Validate Gemini API connection."""
        try:
            # Test with a simple generation
            response = self._client.generate_content("Hello")
            return bool(response.candidates)
        except Exception as e:
            logger.warning(f"Gemini connection validation failed for model {self.model}: {e}")
            return False
