from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from protolink.llms._deps import require_openai
from protolink.llms.actions import FinalAction, LLMActionResult, action_to_json
from protolink.llms.api.base import APILLM
from protolink.llms.history import ConversationHistory
from protolink.llms.tool_calling import (
    native_tool_call_to_action,
    openai_responses_tools,
    parse_json_arguments,
    should_include_agent_tools,
)
from protolink.tools import BaseTool
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OpenAILLM(APILLM):
    """OpenAI API implementation of the LLM API interface."""

    provider: ClassVar[LLMProvider] = "openai"
    DEFAULT_MODEL: ClassVar[str] = "gpt-4o-mini"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,  # Sampling randomness (0-2)
        "top_p": 1.0,  # Nucleus sampling
        "top_logprobs": None,  # Number of logprobs to return (optional)
        "truncation": "disabled",  # How to handle inputs exceeding model context; "disabled" or "auto"
    }

    @property
    def uses_native_action_prompt(self) -> bool:
        """OpenAI Responses uses native function tools for runtime actions."""
        return True

    @property
    def supports_native_action_stream(self) -> bool:
        """OpenAI Responses streams text deltas and function-call events."""
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

        # Set OpenAI API Client
        openai, _, _ = require_openai()
        self._client = openai.OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
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
        response = self._client.responses.create(model=self.model, input=history.messages, **params)
        return self._parse_output(response)

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response using OpenAI Responses API."""
        params = dict(self._model_params)
        stream = self._client.responses.create(
            model=self.model,
            input=history.messages,
            stream=True,
            **params,
        )

        for event in stream:
            # We only care about output text deltas
            if event.type != "response.output_text.delta":
                continue

            # event.delta is a string chunk - yield only the new chunk
            yield event.delta

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action using OpenAI Responses native function tools.

        Protolink exposes each local tool as an OpenAI Responses function tool.
        The model may either return a ``function_call`` output item, which is
        normalized into ``ToolCallAction``/``AgentCallAction``, or regular text,
        which is treated as a final answer unless it is valid fallback JSON.
        This avoids the fragile generic action-schema response format and lets
        OpenAI validate real tool arguments against each tool's own schema.
        """
        params = dict(self._model_params)
        tool_specs = openai_responses_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        if tool_specs:
            params.setdefault("tools", tool_specs)
            params.setdefault("tool_choice", "auto")
            params.setdefault("parallel_tool_calls", False)

        response = self._client.responses.create(model=self.model, input=history.messages, **params)
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
        """Return one action from an OpenAI Responses streaming call.

        Text deltas are forwarded to ``chunk_callback`` for user-visible
        streaming. Function-call argument deltas are accumulated privately until
        OpenAI finishes the streamed call, then normalized into a Protolink
        action before the runtime dispatches it.
        """
        params = dict(self._model_params)
        tool_specs = openai_responses_tools(
            tools,
            include_agent_tools=should_include_agent_tools(
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            ),
        )
        if tool_specs:
            params.setdefault("tools", tool_specs)
            params.setdefault("tool_choice", "auto")
            params.setdefault("parallel_tool_calls", False)

        stream = self._client.responses.create(model=self.model, input=history.messages, stream=True, **params)
        output_text: list[str] = []
        function_name: str | None = None
        function_args: list[str] = []
        call_id: str | None = None

        for event in stream:
            event_type = str(getattr(event, "type", ""))
            if event_type == "response.output_text.delta":
                delta = str(getattr(event, "delta", "") or "")
                if delta:
                    output_text.append(delta)
                    if chunk_callback is not None:
                        await chunk_callback(delta)
                continue

            if "function_call_arguments" in event_type:
                delta = getattr(event, "delta", None)
                if delta:
                    function_args.append(str(delta))
                arguments = getattr(event, "arguments", None)
                if arguments:
                    function_args = [str(arguments)]

            item = getattr(event, "item", None)
            if getattr(item, "type", None) == "function_call":
                function_name = str(getattr(item, "name", "") or function_name or "")
                call_id = getattr(item, "call_id", call_id)
                arguments = getattr(item, "arguments", None)
                if arguments:
                    function_args = [str(arguments)]

        if function_name:
            action = native_tool_call_to_action(function_name, parse_json_arguments("".join(function_args) or "{}"))
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "openai", "call_id": call_id, "streaming": True},
            )

        text = "".join(output_text).strip()
        if not text:
            raise ValueError("OpenAI stream did not contain text or a function call")
        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(action=action, raw_response=text, native=False, metadata={"provider": "openai"})
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(
                action=action,
                raw_response=text,
                native=True,
                metadata={"provider": "openai", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Agent-LLM Interface - A2A Operations
    # ----------------------------------------------------------------------

    def _inject_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], tool_result: Any):
        """Inject a completed OpenAI-native tool call as a runtime observation.

        ``call_action`` already consumes OpenAI's native ``function_call`` item
        and converts it into a Protolink ``ToolCallAction``. After the runtime
        executes the tool, we intentionally use the provider-neutral observation
        format from ``LLM`` rather than fabricating a Responses API
        ``function_call_output`` message without a persisted response id. This
        keeps continuation deterministic and prevents invalid mixed-protocol
        chat history.
        """
        return super()._inject_tool_call(tool_name=tool_name, tool_args=tool_args, tool_result=tool_result)

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def _parse_output(self, response: Any) -> str:
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

        return output_text

    def _action_from_response(self, response: Any) -> LLMActionResult:
        """Normalize an OpenAI Responses payload into one Protolink action."""
        output_text: str = ""
        for item in response.output or []:
            if getattr(item, "type", None) == "function_call":
                args = parse_json_arguments(getattr(item, "arguments", None))
                action = native_tool_call_to_action(str(item.name), args)
                return LLMActionResult(
                    action=action,
                    raw_response=action_to_json(action),
                    native=True,
                    metadata={"provider": "openai", "call_id": getattr(item, "call_id", None)},
                )
            if getattr(item, "type", None) != "message" or getattr(item, "role", None) != "assistant":
                continue
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "output_text":
                    output_text += content.text

        text = output_text.strip()
        if not text:
            raise ValueError("OpenAI response did not contain text or a function call")

        try:
            action = self._parse_infer_response(text)
            return LLMActionResult(action=action, raw_response=text, native=False, metadata={"provider": "openai"})
        except ValueError:
            action = FinalAction(content=text)
            return LLMActionResult(action=action, raw_response=text, native=True, metadata={"provider": "openai"})

    def validate_connection(self) -> bool:
        try:
            # Check that the configured model is available / accessible
            self._client.models.retrieve(self.model)
            return True
        except Exception as e:
            logger.warning(f"OpenAI connection validation failed for model {self.model}: {e}")
            return False
