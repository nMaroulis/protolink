import http.client
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar
from urllib.parse import urlparse

from protolink.llms.actions import AgentCallAction, FinalAction, LLMActionResult, ToolCallAction, action_to_json
from protolink.llms.history import ConversationHistory
from protolink.llms.metrics import usage_metadata
from protolink.llms.server.base import ServerLLM
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


class LlamaCPPServerLLM(ServerLLM):
    """Llama.cpp Server implementation of the LLM interface. Communicates directly with the `llama-server` via HTTP."""

    provider: ClassVar[LLMProvider] = "llama.cpp-server"
    DEFAULT_MODEL: ClassVar[str] = "gemma4:e4b"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    REQUEST_TIMEOUT: ClassVar[int] = 90

    def __init__(
        self,
        *,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        supports_tool_calling: bool = False,
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}

        resolved_base_url = base_url or os.getenv("LLAMACPP_SERVER_URL", "http://localhost:8080")

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=resolved_base_url,
            supports_tool_calling=supports_tool_calling,
        )

        self.base_url = resolved_base_url
        self.headers = headers or {}
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "application/json"

        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError("Invalid URL: missing hostname")

        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._client: http.client.HTTPConnection | None = None

        try:
            self._client = http.client.HTTPConnection(self._host, self._port, timeout=300)
        except Exception as e:
            logger.exception(f"LLM Client initilization failed :: Llama.cpp connection failed: {e}")

        _ = self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming response from `llama-server`."""
        if self._client is None:
            raise ValueError("Llama.cpp client not connected")

        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
            **self._model_params,
        }

        self._client.request(
            method="POST",
            url="/v1/chat/completions",
            body=json.dumps(payload),
            headers=self.headers,
        )

        response = self._client.getresponse()
        data = response.read().decode("utf-8")

        self._client.close()

        result = json.loads(data)
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        raise RuntimeError(f"Unexpected response from llama-server: {result}")

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response from `llama-server`."""
        if self._client is None:
            raise ValueError("Llama.cpp client not connected")

        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
            **self._model_params,
        }

        self._client.request("POST", "/v1/chat/completions", json.dumps(payload), self.headers)

        response = self._client.getresponse()

        for line in response:
            line_str = line.decode("utf-8").strip()
            if not line_str or line_str == "data: [DONE]":
                continue

            if line_str.startswith("data: "):
                chunk_str = line_str[6:]
                try:
                    chunk = json.loads(chunk_str)
                    if "choices" in chunk and len(chunk["choices"]) > 0:
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                except json.JSONDecodeError:
                    pass

        self._client.close()

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action from llama.cpp server.

        Native tool calling is opt-in because llama.cpp behavior depends on the
        selected model, chat template, and server build. When disabled, Protolink
        uses the prompt JSON fallback. When enabled, this method sends
        Chat-Completions-style tools and normalizes returned tool calls.
        """
        if not self._supports_tool_calling:
            return super().call_action(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            )
        if self._client is None:
            raise ValueError("Llama.cpp client not connected")

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
        self._client.request(
            method="POST",
            url="/v1/chat/completions",
            body=json.dumps(payload),
            headers=self.headers,
        )
        response = self._client.getresponse()
        data = response.read().decode("utf-8")
        self._client.close()
        return self._action_from_chat_result(json.loads(data))

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from a streaming ``llama-server`` response.

        The server exposes an OpenAI-compatible streaming shape, where content
        and tool calls arrive as incremental ``delta`` objects. Protolink
        accumulates those deltas until one complete tool call can be validated.
        If native tool calling is not explicitly enabled, the method delegates
        to the base JSON-stream fallback for small/local model friendliness.
        """
        if not self._supports_tool_calling:
            return await super().call_action_stream(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
                chunk_callback=chunk_callback,
            )
        if self._client is None:
            raise ValueError("Llama.cpp client not connected")

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

        self._client.request("POST", "/v1/chat/completions", json.dumps(payload), self.headers)
        response = self._client.getresponse()

        output_text: list[str] = []
        tool_accumulator = ChatCompletionStreamAccumulator()
        try:
            for line in response:
                line_str = line.decode("utf-8").strip()
                if not line_str or line_str == "data: [DONE]":
                    continue
                if line_str.startswith("data: "):
                    line_str = line_str[6:]
                try:
                    chunk = json.loads(line_str)
                except json.JSONDecodeError:
                    continue
                text, tool_call_deltas = chat_completion_stream_delta(chunk)
                if text:
                    output_text.append(text)
                    if chunk_callback is not None:
                        await chunk_callback(text)
                for tool_call_delta in tool_call_deltas:
                    tool_accumulator.add_delta(tool_call_delta)
        finally:
            self._client.close()

        action = tool_accumulator.to_action()
        if action is not None:
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata={"provider": "llama.cpp-server", "streaming": True},
            )

        content = "".join(output_text).strip()
        if not content:
            raise ValueError("llama.cpp server stream did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=False,
                metadata={"provider": "llama.cpp-server"},
            )
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=True,
                metadata={"provider": "llama.cpp-server", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        """Validate llama-server connectivity."""
        try:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=self.REQUEST_TIMEOUT)
            conn.request("GET", "/health")

            response = conn.getresponse()
            conn.close()

            if response.status != 200:
                logger.error(f"Llama.cpp Server unhealthy (HTTP {response.status})")
                return False

            return True

        except ConnectionRefusedError:
            logger.exception("Cannot connect to Llama.cpp Server (connection refused)")
            return False
        except TimeoutError:
            logger.exception("Connection to Llama.cpp Server timed out")
            return False
        except Exception as e:
            logger.exception(f"{e}")
            return False

    def _action_from_chat_result(self, payload: dict[str, Any]) -> LLMActionResult:
        """Normalize a llama.cpp chat-completion payload into one action."""
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError("llama.cpp server response did not contain choices")
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            action = self._action_from_tool_call(tool_calls[0])
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata=usage_metadata({"provider": "llama.cpp-server"}, payload),
            )

        content = str(message.get("content") or "").strip()
        if not content:
            raise ValueError("llama.cpp server response did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=False,
                metadata=usage_metadata({"provider": "llama.cpp-server"}, payload),
            )
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=True,
                metadata=usage_metadata({"provider": "llama.cpp-server"}, payload),
            )

    @staticmethod
    def _action_from_tool_call(call: Any) -> ToolCallAction | AgentCallAction:
        """Convert one chat-completion tool call into a Protolink action."""
        function = call.get("function", {}) if isinstance(call, dict) else getattr(call, "function", {})
        name = function.get("name") if isinstance(function, dict) else getattr(function, "name", None)
        raw_args = function.get("arguments") if isinstance(function, dict) else getattr(function, "arguments", None)
        return native_tool_call_to_action(str(name), parse_json_arguments(raw_args))
