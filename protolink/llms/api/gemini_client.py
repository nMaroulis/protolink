from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from protolink.llms._deps import require_gemini
from protolink.llms.actions import FinalAction, LLMActionResult, action_to_json
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.llms.metrics import usage_metadata
from protolink.llms.tool_calling import (
    gemini_function_declarations,
    native_tool_call_to_action,
    should_include_agent_tools,
)
from protolink.tools import BaseTool
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class GeminiLLM(APILLM):
    """Google Gemini API implementation of the LLM interface."""

    provider: ClassVar[LLMProvider] = "gemini"

    # Pick a stable or "latest" model alias from Gemini API
    DEFAULT_MODEL: ClassVar[str] = "gemini-3-flash-preview"  # stable, high-quality text gen
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        # Google GenAI SDK specifics:
        # You can pass config dicts such as temperature, thinking budgets, etc.
        "temperature": 1.0,  # sampling randomness
        "top_p": 1.0,  # nucleus sampling
        # You may add other config options via the SDK's GenerateContentConfig
    }

    @property
    def uses_native_action_prompt(self) -> bool:
        """Gemini uses native function declarations for runtime actions."""
        return True

    @property
    def supports_native_action_stream(self) -> bool:
        """Gemini streams text chunks and native function-call parts."""
        return True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> None:
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

        genai, GenerateContentConfig = require_gemini()  # noqa: N806
        # Initialize the Gemini (GenAI) client
        self._client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
        # Store the config type class for later use
        self._GenerateContentConfig = GenerateContentConfig

        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming response from Gemini."""
        prompt = "\n".join(msg["content"] for msg in history.messages)

        params = dict(self._model_params)
        config = self._GenerateContentConfig(**params)

        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text  # The SDK exposes a .text attribute

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response using Gemini's streaming endpoint."""
        prompt = "\n".join(msg["content"] for msg in history.messages)

        params = dict(self._model_params)
        config = self._GenerateContentConfig(**params)
        stream = self._client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=config,
        )

        for chunk in stream:
            # Each chunk has a `.text` field with incremental text
            yield chunk.text

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action using Gemini function declarations.

        Gemini receives Protolink tools as native function declarations. A
        returned ``function_call`` is normalized into the runtime action union;
        regular text becomes a final answer unless it validates as fallback
        JSON.
        """
        prompt = "\n".join(msg["content"] for msg in history.messages)
        params = dict(self._model_params)
        declarations = gemini_function_declarations(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        if declarations:
            params["tools"] = [{"function_declarations": declarations}]

        config = self._GenerateContentConfig(**params)
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
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
        """Return one action from Gemini's streaming endpoint."""
        prompt = "\n".join(msg["content"] for msg in history.messages)
        params = dict(self._model_params)
        declarations = gemini_function_declarations(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        if declarations:
            params["tools"] = [{"function_declarations": declarations}]

        config = self._GenerateContentConfig(**params)
        stream = self._client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=config,
        )

        output_text: list[str] = []
        function_name: str | None = None
        function_args: dict[str, Any] | None = None

        for chunk in stream:
            for candidate in getattr(chunk, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    function_call = getattr(part, "function_call", None)
                    if function_call is not None:
                        function_name = str(function_call.name)
                        function_args = dict(getattr(function_call, "args", {}) or {})

            text = str(getattr(chunk, "text", "") or "")
            if text:
                output_text.append(text)
                if chunk_callback is not None:
                    await chunk_callback(text)

        if function_name:
            action = native_tool_call_to_action(function_name, function_args or {})
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "gemini", "streaming": True},
            )

        text = "".join(output_text).strip()
        if not text:
            raise ValueError("Gemini stream did not contain text or a function call")
        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(action=action, raw_response=text, native=False, metadata={"provider": "gemini"})
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata={"provider": "gemini", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        try:
            # Lightweight validation by listing or getting the model
            _ = self._client.models.get(model=self.model)
            # If no exception, connection & model exist
            return True
        except Exception as e:
            logger.warning(f"Gemini connection validation failed for model {self.model}: {e}")
            return False

    def _action_from_response(self, response: Any) -> LLMActionResult:
        """Normalize a Gemini response into one Protolink action."""
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                function_call = getattr(part, "function_call", None)
                if function_call is None:
                    continue
                args = dict(getattr(function_call, "args", {}) or {})
                action = native_tool_call_to_action(str(function_call.name), args)
                return LLMActionResult(
                    action=action,
                    raw_response=action_to_json(action),
                    native=True,
                    metadata=usage_metadata({"provider": "gemini"}, response),
                )

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("Gemini response did not contain text or a function call")

        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=False,
                metadata=usage_metadata({"provider": "gemini"}, response),
            )
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata=usage_metadata({"provider": "gemini"}, response),
            )
