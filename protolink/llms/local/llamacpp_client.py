import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from protolink.llms._deps import require_llama_cpp
from protolink.llms.actions import AgentCallAction, FinalAction, LLMActionResult, ToolCallAction, action_to_json
from protolink.llms.history import ConversationHistory
from protolink.llms.local.base import LocalLLM
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


class LlamaCPPLocalLLM(LocalLLM):
    """Local Llama.cpp implementation of the LLM interface running inside the local Python process."""

    provider: ClassVar[LLMProvider] = "llama.cpp-local"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 0.8,
        "max_tokens": 1024,
    }

    def __init__(
        self,
        *,
        model: str,
        model_params: dict[str, Any] | None = None,
        supports_tool_calling: bool = False,
    ) -> None:
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}
        super().__init__(model=model, model_params=merged_params)
        self._supports_tool_calling = supports_tool_calling

        llama_cpp = require_llama_cpp()

        if not os.path.exists(self.model):
            raise FileNotFoundError(f"Model file not found at {self.model}")

        self._client = llama_cpp.Llama(model_path=self.model, verbose=False)
        self.validate_connection()

    @property
    def uses_native_action_prompt(self) -> bool:
        """Use native prompts only when local llama.cpp tool calling is enabled."""
        return bool(getattr(self, "_supports_tool_calling", False))

    @property
    def supports_native_action_stream(self) -> bool:
        """Use native streaming tool calls only for opted-in llama.cpp models."""
        return bool(getattr(self, "_supports_tool_calling", False))

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single response using local llama_cpp python bindings."""
        response = self._client.create_chat_completion(
            messages=history.messages,
            stream=False,
            **self._model_params,
        )
        return response["choices"][0]["message"]["content"]

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response natively evaluating local model generations."""
        stream = self._client.create_chat_completion(
            messages=history.messages,
            stream=True,
            **self._model_params,
        )

        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            if "content" in delta:
                yield delta["content"]

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action from local llama-cpp-python.

        Local function calling is opt-in because it depends on both the model
        and the chat handler/template used by llama-cpp-python. Disabled mode
        uses the prompt JSON fallback; enabled mode passes native tool
        declarations and normalizes any returned tool call.
        """
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
        response = self._client.create_chat_completion(
            messages=history.messages,
            stream=False,
            **params,
        )
        return self._action_from_chat_result(response)

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from a local llama-cpp-python streaming call.

        llama-cpp-python follows the Chat Completions streaming shape when a
        chat handler supports tools. This method accumulates streamed tool-call
        deltas into one validated Protolink action. Models that are not opted
        into native tools continue through the base JSON streaming fallback.
        """
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

        stream = self._client.create_chat_completion(
            messages=history.messages,
            stream=True,
            **params,
        )

        output_text: list[str] = []
        tool_accumulator = ChatCompletionStreamAccumulator()
        for chunk in stream:
            text, tool_call_deltas = chat_completion_stream_delta(chunk)
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
                metadata={"provider": "llama.cpp-local", "streaming": True},
            )

        content = "".join(output_text).strip()
        if not content:
            raise ValueError("llama-cpp-python stream did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=False,
                metadata={"provider": "llama.cpp-local"},
            )
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=True,
                metadata={"provider": "llama.cpp-local", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        if self._client is not None:
            return True
        logger.error(f"Cannot instantiate local model at {self.model}")
        return False

    def _action_from_chat_result(self, payload: dict[str, Any]) -> LLMActionResult:
        """Normalize a llama-cpp-python chat-completion payload into one action."""
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError("llama-cpp-python response did not contain choices")
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            action = self._action_from_tool_call(tool_calls[0])
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "llama.cpp-local"},
            )

        content = str(message.get("content") or "").strip()
        if not content:
            raise ValueError("llama-cpp-python response did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=False,
                metadata={"provider": "llama.cpp-local"},
            )
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=True,
                metadata={"provider": "llama.cpp-local"},
            )

    @staticmethod
    def _action_from_tool_call(call: Any) -> ToolCallAction | AgentCallAction:
        """Convert one llama-cpp-python tool-call payload into a runtime action."""
        function = call.get("function", {}) if isinstance(call, dict) else getattr(call, "function", {})
        name = function.get("name") if isinstance(function, dict) else getattr(function, "name", None)
        raw_args = function.get("arguments") if isinstance(function, dict) else getattr(function, "arguments", None)
        return native_tool_call_to_action(str(name), parse_json_arguments(raw_args))
