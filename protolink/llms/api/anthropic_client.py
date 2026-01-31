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
        Inject a completed tool invocation into the conversation history as a USER message.

        This implementation diverges from the `LLM` base class (which uses system messages) to accommodate
        Anthropic's specific conversational constraints:

        1. **System Message Filtering**: Anthropic models (e.g., Claude) filter out system messages from the end
           of the conversation history or treat them as separate from the dialogue flow. Injecting tool results
           as system messages often results in the model "ignoring" the outcome, leading to infinite loops where
           the model retries the same tool.

        2. **Protocol Mismatch**: Protolink uses a text-based JSON protocol (`agent_call`) rather than Anthropic's
           native `assistant:tool_use`/`user:tool_result` content blocks. Injecting structured tool messages without a
           corresponding API-level `tools` definition would cause validation errors or model confusion.

        By injecting the result as a standard **USER** message containing the serialized JSON result, we ensure:
        - The model treats the output as new, actionable context provided by the environment.
        - The message is preserved in the history and visible to the inference engine.
        - We maintain a unified, provider-agnostic inference loop without complex protocol branching.

        Args:
            tool_name (str): The name of the tool that was executed.
            tool_args (dict[str, Any]): The arguments passed to the tool (for context/logging).
            tool_result (Any): The return value of the tool execution, which will be serialized to JSON.
        """
        import json

        self.history.add_user(
            json.dumps(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "result": tool_result,
                }
            )
        )

    def _inject_agent_call(
        self,
        *,
        agent_name: str,
        agent_action: str,
        agent_result: Any,
    ) -> None:
        """
        Inject a completed agent delegation into the conversation history as a USER message.
        """
        import json

        self.history.add_user(
            json.dumps(
                {
                    "type": "agent_result",
                    "agent": agent_name,
                    "action": agent_action,
                    "result": agent_result,
                }
            )
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
