from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from protolink.llms._deps import require_anthropic
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class AnthropicLLM(APILLM):
    """Anthropic API implementation of the LLM interface."""

    provider: ClassVar[LLMProvider] = "anthropic"

    DEFAULT_MODEL: ClassVar[str] = "claude-sonnet-4-20250514"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
        "top_p": 1.0,
        "max_tokens": 1024,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> None:
        # Vars passed to parent
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

        anthropic, _ = require_anthropic()
        self._client = anthropic.Anthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            base_url=base_url,
        )

        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response from the model."""
        response = self._client.messages.create(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(history),
            stream=False,
            **self._model_params,
        )

        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response using Anthropic Messages API."""

        with self._client.messages.stream(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(history),
            **self._model_params,
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue

                delta = event.delta
                if delta.type == "text_delta":
                    yield delta.text

    def _inject_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], tool_result: Any):
        """
        Inject a completed tool invocation into the conversation history using Anthropic's native tool-use message
        protocol.

        Anthropic models represent tool interactions as structured content blocks rather than dedicated message roles.
        A complete tool round-trip is expressed as two consecutive messages:

        1. An ``assistant`` message containing a ``tool_use`` content block, which declares:
           - The name of the tool being invoked
           - The structured input arguments provided by the model

        2. A subsequent ``user`` message containing a ``tool_result`` content block, which supplies:
           - The identifier of the originating tool use
           - The tool execution result

        This message pattern mirrors the conversational contract expected by Anthropic models, where tool outputs are
        provided information rather than a distinct system role.

        This method encapsulates all Anthropic-specific message formatting and role semantics, allowing the base ``LLM``
        inference loop to remain provider-agnostic and free of protocol-specific branching.

        Args:
            tool_name (str):
                The name of the tool invoked by the model.

            tool_args (dict[str, Any]):
                The structured input arguments supplied for the tool execution.

            tool_result (Any):
                The result returned by the tool. The value must be serializable
                into a format accepted by Anthropic content blocks.

        Returns:
            None

        Notes:
            - Anthropic does not require an explicit tool call identifier in the same sense as OpenAI; tool correlation
            is handled via content block semantics.
            - Tool execution is performed externally by the runtime; this method is responsible solely for injecting the
            declared tool usage and its result into the conversation history.
            - No system or tool roles are introduced here, as Anthropic enforces a different conversational model than
            OpenAI.
        """
        self.history.add_raw(
            {
                "role": "assistant",
                "content": f"""[
                    {{
                        "type": "tool_use",
                        "name": {tool_name},
                        "input": {tool_args},
                    }}
                ]""",
            }
        )

        self.history.add_raw(
            {
                "role": "user",
                "content": f"""[
                    {{
                        "type": "tool_result",
                        "tool_use_id": {tool_name},
                        "content": {tool_result},
                    }}
                ]""",
            }
        )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def _to_anthropic_messages(self, history: ConversationHistory) -> list[dict[str, Any]]:
        """
        Convert ConversationHistory to Anthropic message format.

        Anthropic does NOT want system messages inside messages[].
        """
        messages: list[dict[str, Any]] = []

        for msg in history.messages:
            if msg["role"] == "system":
                continue

            messages.append(
                {
                    "role": msg["role"],
                    "content": msg["content"],
                }
            )

        return messages

    def _parse_output(self, response: Any) -> str:
        """Convert Anthropic response to plain text."""

        output_text = ""
        for block in response.content:
            if block.type == "text":
                output_text += block.text

        return output_text

    def validate_connection(self) -> bool:
        try:
            # Lightweight validation call
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"Anthropic connection validation failed for model {self.model}: {e}")
            return False
