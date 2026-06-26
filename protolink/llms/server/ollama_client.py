from __future__ import annotations

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
    chat_completion_tools,
    native_tool_call_to_action,
    parse_json_arguments,
    should_include_agent_tools,
)
from protolink.tools import BaseTool
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OllamaLLM(ServerLLM):
    """Ollama Server implementation of the LLM interface. Uses the http client to make requests to the Ollama server."""

    provider: ClassVar[LLMProvider] = "ollama"
    DEFAULT_MODEL: ClassVar[str] = "gemma4:e4b"  # lightweight model
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
        "num_predict": 8192,
        "num_ctx": 8192,  # Prevent truncated JSON output
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

        # Resolve base_url first (before super().__init__)
        resolved_base_url = base_url or os.getenv("OLLAMA_URL")
        if not resolved_base_url:
            raise ValueError(
                "Ollama base URL not provided. Set OLLAMA_URL environment variable or pass the base_url parameter."
            )

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=resolved_base_url,
            supports_tool_calling=supports_tool_calling,
        )

        self.base_url = resolved_base_url

        if headers is None:
            api_key = os.getenv("OLLAMA_API_KEY")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        # Initialize the client
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
        except Exception:
            logger.exception("LLM Client initilization failed :: Ollama connection failed: {e}")

        # Non-blocking validation - just log if connection fails
        _ = self.validate_connection()

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming response from Ollama."""
        if self._client is None:
            raise ValueError("Ollama client not connected")

        # Translate max_tokens to num_predict for Ollama options compatibility
        options = dict(self._model_params)
        if "max_tokens" in options:
            options["num_predict"] = options.pop("max_tokens")

        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
            "format": "json",
            "options": options,
        }

        headers = {"Content-Type": "application/json"}

        try:
            self._client.request(
                method="POST",
                url="/api/chat",
                body=json.dumps(payload),
                headers=headers,
            )

            response = self._client.getresponse()
            data = response.read().decode("utf-8")
        finally:
            self._client.close()

        if response.status != 200:
            raise RuntimeError(f"Ollama API request failed with status {response.status}: {data}")

        try:
            result = json.loads(data)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to decode Ollama response as JSON: {data}") from e

        if "error" in result:
            raise RuntimeError(f"Ollama API returned an error: {result['error']}")

        if "message" not in result or "content" not in result["message"]:
            raise RuntimeError(f"Unexpected Ollama response format. Missing 'message' or 'content': {result}")

        return result["message"]["content"]

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response from Ollama."""
        if self._client is None:
            raise ValueError("Ollama client not connected")

        # Translate max_tokens to num_predict for Ollama options compatibility
        options = dict(self._model_params)
        if "max_tokens" in options:
            options["num_predict"] = options.pop("max_tokens")

        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
            "format": "json",
            "options": options,
        }

        headers = {"Content-Type": "application/json"}

        self._client.request("POST", "/api/chat", json.dumps(payload), headers)

        response = self._client.getresponse()

        if response.status != 200:
            error_data = response.read().decode("utf-8")
            self._client.close()
            raise RuntimeError(f"Ollama API streaming request failed with status {response.status}: {error_data}")

        try:
            for line in response:
                if not line:
                    continue

                try:
                    chunk = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                if "error" in chunk:
                    raise RuntimeError(f"Ollama API returned an error during stream: {chunk['error']}")

                if "message" in chunk and "content" in chunk["message"]:
                    yield chunk["message"]["content"]
        finally:
            self._client.close()

    def call_action(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
    ) -> LLMActionResult:
        """Return one typed action from Ollama.

        By default Ollama uses the simple JSON prompt protocol because local
        model tool-calling reliability varies substantially. When
        ``supports_tool_calling=True`` is set for a model known to support
        tools, Protolink sends native ``tools`` declarations and normalizes
        returned tool calls into the same action protocol.
        """
        if not self._supports_tool_calling:
            return super().call_action(
                history,
                tools=tools,
                agent_callback_available=agent_callback_available,
                agent_cards=agent_cards,
            )
        if self._client is None:
            raise ValueError("Ollama client not connected")

        options = dict(self._model_params)
        if "max_tokens" in options:
            options["num_predict"] = options.pop("max_tokens")

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
            "options": options,
        }
        if tool_specs:
            payload["tools"] = tool_specs
        headers = {"Content-Type": "application/json"}
        try:
            self._client.request(
                method="POST",
                url="/api/chat",
                body=json.dumps(payload),
                headers=headers,
            )
            response = self._client.getresponse()
            data = response.read().decode("utf-8")
        finally:
            self._client.close()

        if response.status != 200:
            raise RuntimeError(f"Ollama API request failed with status {response.status}: {data}")
        result = json.loads(data)
        return self._action_from_chat_result(result)

    async def call_action_stream(
        self,
        history: ConversationHistory,
        *,
        tools: dict[str, BaseTool],
        agent_callback_available: bool = False,
        agent_cards: list[Any] | None = None,
        chunk_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMActionResult:
        """Return one action from an Ollama streaming chat response.

        Ollama's ordinary Protolink path still streams plain JSON text and lets
        the base class parse it after the stream finishes. When a caller opts a
        known tool-capable model into ``supports_tool_calling=True``, this
        method sends Ollama ``tools`` declarations and watches streamed
        ``message.tool_calls`` events. Text deltas are forwarded immediately,
        while the first tool call is normalized into the typed action protocol
        once the response has been drained.
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
            raise ValueError("Ollama client not connected")

        options = dict(self._model_params)
        if "max_tokens" in options:
            options["num_predict"] = options.pop("max_tokens")

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
            "options": options,
        }
        if tool_specs:
            payload["tools"] = tool_specs

        headers = {"Content-Type": "application/json"}
        output_text: list[str] = []
        native_action: ToolCallAction | AgentCallAction | None = None

        self._client.request("POST", "/api/chat", json.dumps(payload), headers)
        response = self._client.getresponse()

        if response.status != 200:
            error_data = response.read().decode("utf-8")
            self._client.close()
            raise RuntimeError(f"Ollama API streaming request failed with status {response.status}: {error_data}")

        try:
            for line in response:
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                if "error" in chunk:
                    raise RuntimeError(f"Ollama API returned an error during stream: {chunk['error']}")

                message = chunk.get("message") or {}
                content = str(message.get("content") or "")
                if content:
                    output_text.append(content)
                    if chunk_callback is not None:
                        await chunk_callback(content)

                tool_calls = message.get("tool_calls") or []
                if tool_calls and native_action is None:
                    native_action = self._action_from_tool_call(tool_calls[0])
        finally:
            self._client.close()

        if native_action is not None:
            return LLMActionResult(
                action=native_action,
                raw_response=action_to_json(native_action),
                native=True,
                metadata={"provider": "ollama", "streaming": True},
            )

        content = "".join(output_text).strip()
        if not content:
            raise ValueError("Ollama stream did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(action=action, raw_response=content, native=False, metadata={"provider": "ollama"})
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=True,
                metadata={"provider": "ollama", "streaming": True},
            )

    # ----------------------------------------------------------------------
    # Agent-LLM Interface - A2A Operations
    # ----------------------------------------------------------------------

    def _inject_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], tool_result: Any):
        """Inject an Ollama tool result using the provider-neutral observation format."""
        return super()._inject_tool_call(tool_name=tool_name, tool_args=tool_args, tool_result=tool_result)

    # ----------------------------------------------------------------------
    # Utils
    # ----------------------------------------------------------------------

    def validate_connection(self) -> bool:
        """Validate Ollama deamon connectivity and model availability."""
        try:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=self.REQUEST_TIMEOUT)
            conn.request("GET", "/api/tags")

            response = conn.getresponse()
            conn.close()

            if response.status != 200:
                logger.error(f"Ollama unhealthy (HTTP {response.status})")
                return False

            return True

        except ConnectionRefusedError:
            logger.exception("Cannot connect to Ollama (connection refused)")
            return False
        except TimeoutError:
            logger.exception("Connection to Ollama timed out")
            return False
        except Exception as e:
            logger.exception(f"{e}")
            return False

    def _action_from_chat_result(self, payload: dict[str, Any]) -> LLMActionResult:
        """Normalize an Ollama chat response into one Protolink action."""
        message = payload.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            action = self._action_from_tool_call(tool_calls[0])
            return LLMActionResult(
                action=action,
                raw_response=action_to_json(action),
                native=True,
                metadata=usage_metadata({"provider": "ollama"}, payload),
            )

        content = str(message.get("content") or "").strip()
        if not content:
            raise ValueError("Ollama response did not contain content or tool_calls")
        try:
            action = self._parse_infer_response(content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=False,
                metadata=usage_metadata({"provider": "ollama"}, payload),
            )
        except ValueError:
            action = FinalAction(content=content)
            return LLMActionResult(
                action=action,
                raw_response=content,
                native=True,
                metadata=usage_metadata({"provider": "ollama"}, payload),
            )

    @staticmethod
    def _action_from_tool_call(call: Any) -> ToolCallAction | AgentCallAction:
        """Convert one Ollama tool-call payload into a Protolink action."""
        function = call.get("function", {}) if isinstance(call, dict) else getattr(call, "function", {})
        name = function.get("name") if isinstance(function, dict) else getattr(function, "name", None)
        raw_args = function.get("arguments") if isinstance(function, dict) else getattr(function, "arguments", None)
        return native_tool_call_to_action(str(name), parse_json_arguments(raw_args))
