from __future__ import annotations

import http.client
import json
import os
from collections.abc import Iterable
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
    DEFAULT_MODEL: ClassVar[str] = "llama3:8b"
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
    ) -> None:
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}

        super().__init__(model=resolved_model, model_params=merged_params, base_url=base_url)

        # Resolve base_url and headers
        self.base_url = base_url or os.getenv("OLLAMA_HOST")
        if not self.base_url:
            raise ValueError(
                "Ollama base URL not provided. Set OLLAMA_HOST environment variable or pass the base_url parameter."
            )

        if headers is None:
            api_key = os.getenv("OLLAMA_API_KEY")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        # Initialize the client
        parsed = urlparse(self.base_url)

        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)

        self._client = http.client.HTTPConnection(self._host, self._port, timeout=300)

        if not self.validate_connection():
            raise ValueError("Ollama connection failed. Check OLLAMA_HOST, OLLAMA_API_KEY, or server availability.")

    # ----------------------------------------------------------------------
    # LLM calling (invocation)
    # ----------------------------------------------------------------------

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming response from Ollama."""
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

    async def call_stream(self, history: ConversationHistory) -> Iterable[str]:
        """Generate a streaming response from Ollama."""

        payload = {
            "model": self.model,
            "messages": self.history.messages,
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
