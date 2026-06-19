from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from protolink.llms._deps import require_anthropic
from protolink.llms.actions import FinalAction, LLMActionResult, action_to_json
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.llms.metrics import usage_metadata
from protolink.llms.serialization import json_history_default
from protolink.llms.tool_calling import (
    anthropic_tools,
    native_tool_call_to_action,
    parse_json_arguments,
    should_include_agent_tools,
)
from protolink.tools import BaseTool
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

    @property
    def uses_native_action_prompt(self) -> bool:
        """Anthropic Messages uses native ``tool_use`` blocks for actions."""
        return True

    @property
    def supports_native_action_stream(self) -> bool:
        """Anthropic streams text deltas and ``tool_use`` input JSON deltas."""
        return True

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
        params = dict(self._model_params)

        response = self._client.messages.create(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(history),
            stream=False,
            **params,
        )

        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response using Anthropic Messages API."""
        params = dict(self._model_params)

        with self._client.messages.stream(
            model=self.model,
            system=self.system_prompt,
            messages=self._to_anthropic_messages(history),
            **params,
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue

                delta = event.delta
                if delta.type == "text_delta":
                    yield delta.text
                elif delta.type == "input_json_delta":
                    yield delta.partial_json

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action using Anthropic's native ``tool_use`` blocks.

        Each Protolink tool becomes an Anthropic tool declaration with its own
        input schema. Claude may emit a ``tool_use`` block, which is mapped into
        the runtime action protocol, or regular text, which becomes a final
        answer unless it validates as fallback JSON.
        """
        params = dict(self._model_params)
        tool_specs = anthropic_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        request: dict[str, Any] = {
            "model": self.model,
            "system": self.system_prompt,
            "messages": self._to_anthropic_messages(history),
            "stream": False,
            **params,
        }
        if tool_specs:
            request["tools"] = tool_specs

        response = self._client.messages.create(**request)
        return self._action_from_response(response)

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from an Anthropic Messages streaming call.

        Claude streams regular answer text as ``text_delta`` events and native
        tool arguments as ``input_json_delta`` fragments. The runtime emits text
        deltas immediately, but buffers tool JSON until the tool request is
        complete so validation still happens exactly once at the Protolink
        action boundary.
        """
        params = dict(self._model_params)
        tool_specs = anthropic_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        request: dict[str, Any] = {
            "model": self.model,
            "system": self.system_prompt,
            "messages": self._to_anthropic_messages(history),
            **params,
        }
        if tool_specs:
            request["tools"] = tool_specs

        output_text: list[str] = []
        tool_name: str | None = None
        tool_use_id: str | None = None
        tool_input_chunks: list[str] = []
        tool_input_obj: dict[str, Any] | None = None

        with self._client.messages.stream(**request) as stream:
            for event in stream:
                event_type = str(getattr(event, "type", ""))
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", None) == "tool_use":
                        tool_name = str(getattr(block, "name", "") or "")
                        tool_use_id = getattr(block, "id", None)
                        initial_input = getattr(block, "input", None)
                        if isinstance(initial_input, dict):
                            tool_input_obj = initial_input
                    continue

                if event_type != "content_block_delta":
                    continue

                delta = getattr(event, "delta", None)
                delta_type = getattr(delta, "type", None)
                if delta_type == "text_delta":
                    text = str(getattr(delta, "text", "") or "")
                    if text:
                        output_text.append(text)
                        if chunk_callback is not None:
                            await chunk_callback(text)
                elif delta_type == "input_json_delta":
                    partial = str(getattr(delta, "partial_json", "") or "")
                    if partial:
                        tool_input_chunks.append(partial)

        if tool_name:
            args = tool_input_obj if tool_input_obj is not None else parse_json_arguments("".join(tool_input_chunks))
            action = native_tool_call_to_action(tool_name, args)
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "anthropic", "tool_use_id": tool_use_id, "streaming": True},
            )

        text = "".join(output_text).strip()
        if not text:
            raise ValueError("Anthropic stream did not contain text or a tool_use block")
        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(action=action, raw_response=text, native=False, metadata={"provider": "anthropic"})
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata={"provider": "anthropic", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Agent-LLM Interface - A2A Operations
    # ----------------------------------------------------------------------

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
                },
                default=json_history_default,
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
                },
                default=json_history_default,
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
        """Convert Anthropic text blocks to plain text."""
        output_text = ""
        for block in response.content:
            if block.type == "text":
                output_text += block.text

        return output_text

    def _action_from_response(self, response: Any) -> LLMActionResult:
        """Normalize Anthropic text/tool blocks into one Protolink action."""
        output_text = ""
        for block in response.content:
            if block.type == "tool_use":
                action = native_tool_call_to_action(str(block.name), dict(block.input or {}))
                metadata = usage_metadata(
                    {"provider": "anthropic", "tool_use_id": getattr(block, "id", None)},
                    response,
                )
                return LLMActionResult(
                    action=action,
                    raw_response=action_to_json(action),
                    native=True,
                    metadata=metadata,
                )
            if block.type == "text":
                output_text += block.text

        text = output_text.strip()
        if not text:
            raise ValueError("Anthropic response did not contain text or a tool_use block")

        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=False,
                metadata=usage_metadata({"provider": "anthropic"}, response),
            )
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata=usage_metadata({"provider": "anthropic"}, response),
            )

    def validate_connection(self) -> bool:
        try:
            # Lightweight validation call
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"Anthropic connection validation failed for model {self.model}: {e}")
            return False
