from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from protolink.llms._deps import require_openai
from protolink.llms.actions import FinalAction, LLMActionResult, action_to_json
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.llms.tool_calling import (
    ChatCompletionStreamAccumulator,
    chat_completion_stream_delta,
    chat_completion_tools,
    native_tool_call_to_action,
    parse_json_arguments,
    should_include_agent_tools,
)
from protolink.tools import BaseTool
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class DeepSeekLLM(APILLM):
    """DeepSeek API implementation using OpenAI-compatible SDK."""

    provider: ClassVar[LLMProvider] = "deepseek"
    DEFAULT_MODEL: ClassVar[str] = "deepseek-chat"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
        "top_p": 1.0,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = "https://api.deepseek.com",
        supports_tool_calling: bool = True,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=base_url,
        )

        openai, _, _ = require_openai()
        self._client = openai.OpenAI(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
            base_url=base_url,
        )
        self._supports_tool_calling = supports_tool_calling

        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    @property
    def uses_native_action_prompt(self) -> bool:
        """Use native prompts only when DeepSeek tool calling is enabled."""
        return bool(getattr(self, "_supports_tool_calling", False))

    @property
    def supports_native_action_stream(self) -> bool:
        """DeepSeek streams OpenAI-compatible tool-call deltas when enabled."""
        return bool(getattr(self, "_supports_tool_calling", False))

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=history.messages,
            stream=False,
            **self._model_params,
        )
        return response.choices[0].message.content

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=history.messages,
            stream=True,
            **self._model_params,
        )

        for event in stream:
            # Only yield text deltas
            delta = getattr(event.choices[0].delta, "content", None)
            if delta:
                yield delta

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action using DeepSeek native tool calls when enabled."""
        if not self._supports_tool_calling:
            return super().call_action(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            )

        params = dict(self._model_params)
        tool_specs = chat_completion_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        if tool_specs:
            params["tools"] = tool_specs
            params["tool_choice"] = "auto"
        response = self._client.chat.completions.create(
            model=self.model,
            messages=history.messages,
            stream=False,
            **params,
        )
        return self._action_from_chat_response(response)

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from a DeepSeek streaming chat completion."""
        if not self._supports_tool_calling:
            return await super().call_action_stream(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
                chunk_callback=chunk_callback,
            )

        params = dict(self._model_params)
        tool_specs = chat_completion_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        if tool_specs:
            params["tools"] = tool_specs
            params["tool_choice"] = "auto"
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=history.messages,
            stream=True,
            **params,
        )

        output_text: list[str] = []
        tool_accumulator = ChatCompletionStreamAccumulator()
        for event in stream:
            text, tool_call_deltas = chat_completion_stream_delta(event)
            if text:
                output_text.append(text)
                if chunk_callback is not None:
                    await chunk_callback(text)
            for tool_call_delta in tool_call_deltas:
                tool_accumulator.add_delta(tool_call_delta)

        action = tool_accumulator.to_action()
        if action is not None:
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "deepseek", "streaming": True},
            )

        text = "".join(output_text).strip()
        if not text:
            raise ValueError("DeepSeek stream did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(action=action, raw_response=text, native=False, metadata={"provider": "deepseek"})
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata={"provider": "deepseek", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        try:
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"DeepSeek connection validation failed for model {self.model}: {e}")
            return False

    def _action_from_chat_response(self, response: Any) -> LLMActionResult:
        """Normalize a DeepSeek chat-completion response into one action."""
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            function = tool_calls[0].function
            action = native_tool_call_to_action(str(function.name), parse_json_arguments(function.arguments))
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "deepseek"},
            )

        content = (message.content or "").strip()
        if not content:
            raise ValueError("DeepSeek response did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(action=action, raw_response=content, native=False, metadata={"provider": "deepseek"})
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(action=action, raw_response=content, native=True, metadata={"provider": "deepseek"})
