from __future__ import annotations

import http.client
import json
import os
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urlparse

from protolink.llms.history import ConversationHistory
from protolink.llms.server.base import ServerLLM
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OllamaLLM(ServerLLM):
    """Ollama Server implementation of the LLM interface. Uses the http client to make requests to the Ollama server."""

    provider: ClassVar[LLMProvider] = "ollama"
    DEFAULT_MODEL: ClassVar[str] = "llama3:8b"  # lightweight model
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    REQUEST_TIMEOUT: ClassVar[int] = 30

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
        resolved_base_url = base_url or os.getenv("OLLAMA_HOST")
        if not resolved_base_url:
            raise ValueError(
                "Ollama base URL not provided. Set OLLAMA_HOST environment variable or pass the base_url parameter."
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

        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
        }

        headers = {
            "Content-Type": "application/json",
        }

        self._client.request(
            method="POST",
            url="/api/chat",
            body=json.dumps(payload),
            headers=headers,
        )

        response = self._client.getresponse()
        data = response.read().decode("utf-8")

        self._client.close()

        result = json.loads(data)
        return result["message"]["content"]

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming response from Ollama."""
        if self._client is None:
            raise ValueError("Ollama client not connected")

        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
        }

        headers = {"Content-Type": "application/json"}

        self._client.request("POST", "/api/chat", json.dumps(payload), headers)

        response = self._client.getresponse()

        for line in response:
            if not line:
                continue

            chunk = json.loads(line.decode("utf-8"))
            if "message" in chunk:
                yield chunk["message"]["content"]

    # ----------------------------------------------------------------------
    # Agent-LLM Interface - A2A Operations
    # ----------------------------------------------------------------------

    def _inject_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], tool_result: Any):
        """
        Inject a completed tool invocation into the conversation history using Ollama's native tool-calling message
        format.

        Ollama follows a Chat Completions-style protocol for tool usage:
        - The assistant declares a tool invocation via a ``tool_calls`` field
        - The tool result is returned as a separate message with ``role="tool"`` and the corresponding ``tool_name``

        Unlike OpenAI's Responses API, Ollama does not require a tool call correlation identifier. Tool results are
        associated with their invocation implicitly by message order.

        This method adapts the completed tool execution into Ollama's expected message format while keeping the base
        inference loop provider-agnostic.

        Conditional behavior:
        ---------------------
        If ``self._supports_tool_calling`` is set to ``False``, this method delegates to the base ``LLM`` implementation
        instead of emitting Ollama-specific tool messages. In that case, tool results are injected using the
        provider-agnostic fallback format defined by the base class (typically as a serialized system message).

        This allows:
        - Disabling native tool calling for models that do not reliably support it (e.g. some LLaMA variants)
        - Preserving a single, deterministic inference loop
        - Avoiding provider-specific branching outside this hook

        When ``self._supports_tool_calling`` is ``True``, this method emits Ollama-native messages to enable structured
        tool calling behavior.

        Documentation: https://docs.ollama.com/capabilities/tool-calling

        Args:
            tool_name (str):
                The name of the tool invoked by the model.

            tool_args (dict[str, Any]):
                The arguments supplied by the model for the tool invocation.

            tool_result (Any):
                The result returned by the tool. The value must be JSON-serializable, as it is injected directly into
                the tool message content.

        Returns:
            None
        """

        # Fallback to provider-agnostic behavior if native tool calling is disabled
        if not self._supports_tool_calling:
            return super()._inject_tool_call(
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=tool_result,
            )

        # Assistant declares the tool call
        self.history.add_raw(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_args,
                        },
                    }
                ],
            }
        )

        # Tool provides the execution result
        self.history.add_raw(
            {
                "role": "tool",
                "tool_name": tool_name,
                "content": json.dumps(tool_result),
            }
        )

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
