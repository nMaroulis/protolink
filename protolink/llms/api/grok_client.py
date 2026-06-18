"""Grok LLM - xAI's Grok API implementation using HTTP client."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

import httpx

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


class GrokLLM(APILLM):
    """xAI Grok API implementation using direct HTTP requests.

    Uses the xAI chat completions API at api.x.ai/v1/chat/completions.

    Docs:
        https://docs.x.ai/developers/api-reference

    Example:
        >>> from protolink.llms.api import GrokLLM
        >>> llm = GrokLLM(api_key="xai-...")
        >>> response = llm.chat("Hello, Grok!")
    """

    provider: ClassVar[LLMProvider] = "grok"
    DEFAULT_MODEL: ClassVar[str] = "grok-4-latest"
    DEFAULT_BASE_URL: ClassVar[str] = "https://api.x.ai/v1"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    REQUEST_TIMEOUT: ClassVar[int] = 90

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
        supports_tool_calling: bool = True,
    ) -> None:
        """Initialize the Grok LLM client.

        Args:
            api_key: xAI API key. Falls back to XAI_API_KEY or GROK_API_KEY env var.
            model: Model identifier. Defaults to "grok-4-latest".
            model_params: Generation parameters (temperature, top_p, etc.).
            base_url: API base URL. Defaults to "https://api.x.ai/v1".
        """
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}
        resolved_base_url = base_url or self.DEFAULT_BASE_URL

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=resolved_base_url,
        )

        self._api_key = api_key or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
        self._supports_tool_calling = supports_tool_calling
        if not self._api_key:
            logger.warning("No API key provided for Grok. Set XAI_API_KEY or GROK_API_KEY env var.")

        self._client = httpx.Client(timeout=self.REQUEST_TIMEOUT)
        self._async_client = httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT)

        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    @property
    def uses_native_action_prompt(self) -> bool:
        """Use native prompts only when Grok tool calling is enabled."""
        return bool(getattr(self, "_supports_tool_calling", False))

    @property
    def supports_native_action_stream(self) -> bool:
        """Use native streamed tool deltas only when Grok tool calling is enabled."""
        return bool(getattr(self, "_supports_tool_calling", False))

    @property
    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response from Grok."""
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
            **self._model_params,
        }

        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response from Grok."""
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
            **self._model_params,
        }

        async with self._async_client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Remove "data: " prefix
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    continue

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action using xAI native tool calls when enabled."""
        if not self._supports_tool_calling:
            return super().call_action(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            )

        tool_specs = chat_completion_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
            **self._model_params,
        }
        if tool_specs:
            payload["tools"] = tool_specs
            payload["tool_choice"] = "auto"
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        )
        response.raise_for_status()
        return self._action_from_chat_result(response.json())

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from a Grok streaming chat completion."""
        if not self._supports_tool_calling:
            return await super().call_action_stream(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
                chunk_callback=chunk_callback,
            )

        tool_specs = chat_completion_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
            **self._model_params,
        }
        if tool_specs:
            payload["tools"] = tool_specs
            payload["tool_choice"] = "auto"

        output_text: list[str] = []
        tool_accumulator = ChatCompletionStreamAccumulator()
        async with self._async_client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                text, tool_call_deltas = chat_completion_stream_delta(data)
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
                metadata={"provider": "grok", "streaming": True},
            )

        text = "".join(output_text).strip()
        if not text:
            raise ValueError("Grok stream did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(action=action, raw_response=text, native=False, metadata={"provider": "grok"})
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata={"provider": "grok", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        """Validate the connection to the Grok API."""
        try:
            response = self._client.get(
                f"{self.base_url}/models",
                headers=self._headers,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Grok connection validation failed: {e}")
            return False

    def __del__(self) -> None:
        """Cleanup HTTP clients on deletion."""
        if hasattr(self, "_client"):
            self._client.close()

    def _action_from_chat_result(self, payload: dict[str, Any]) -> LLMActionResult:
        """Normalize an xAI chat-completion response into one action."""
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError("Grok response did not contain choices")
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            function = call.get("function", {})
            action = native_tool_call_to_action(
                str(function.get("name")),
                parse_json_arguments(function.get("arguments")),
            )
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "grok"},
            )

        content = str(message.get("content") or "").strip()
        if not content:
            raise ValueError("Grok response did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(action=action, raw_response=content, native=False, metadata={"provider": "grok"})
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(action=action, raw_response=content, native=True, metadata={"provider": "grok"})
