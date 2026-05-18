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
