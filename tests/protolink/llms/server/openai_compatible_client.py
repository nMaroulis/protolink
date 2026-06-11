from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from protolink.llms.history import ConversationHistory
from protolink.llms.server.base import ServerLLM
from protolink.types import LLMProvider
from protolink.utils.logging import get_logger

logger = get_logger(__name__)


class OpenAICompatibleLLM(ServerLLM):
    """OpenAI-compatible Chat Completions client for local or custom servers.

    This client targets servers that expose ``/v1/chat/completions`` and
    ``/v1/models`` without requiring the official OpenAI SDK. It is useful for
    LM Studio, llama.cpp server, vLLM, LocalAI, and similar local-first runtimes.
    """

    provider: ClassVar[LLMProvider] = "openai-compatible"
    DEFAULT_MODEL: ClassVar[str] = "local-model"
    DEFAULT_BASE_URL: ClassVar[str] = "http://localhost:1234/v1"
    DEFAULT_MODEL_PARAMS: ClassVar[dict[str, Any]] = {
        "temperature": 1.0,
    }
    REQUEST_TIMEOUT: ClassVar[int] = 300

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        supports_tool_calling: bool = False,
    ) -> None:
        """Create a client for an OpenAI-compatible chat completions server.

        Args:
            base_url: Base server URL. If omitted, reads
                ``OPENAI_COMPATIBLE_BASE_URL`` and falls back to
                ``http://localhost:1234/v1``.
            api_key: Optional bearer token. If omitted, reads
                ``OPENAI_COMPATIBLE_API_KEY``.
            headers: Extra request headers merged into every request.
            model: Model id passed to the server.
            model_params: Generation parameters such as ``temperature``.
            supports_tool_calling: Whether this server can consume native tool
                calling payloads.
        """
        resolved_model = model or self.DEFAULT_MODEL
        merged_params = {**self.DEFAULT_MODEL_PARAMS, **(model_params or {})}
        resolved_base_url = (base_url or os.getenv("OPENAI_COMPATIBLE_BASE_URL") or self.DEFAULT_BASE_URL).rstrip("/")

        super().__init__(
            model=resolved_model,
            model_params=merged_params,
            base_url=resolved_base_url,
            supports_tool_calling=supports_tool_calling,
        )

        self.base_url = resolved_base_url
        self.api_key = api_key or os.getenv("OPENAI_COMPATIBLE_API_KEY")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        }
        if self.api_key:
            self.headers.setdefault("Authorization", f"Bearer {self.api_key}")

        _ = self.validate_connection()

    def call(self, history: ConversationHistory) -> str:
        """Generate a single non-streaming chat completion."""
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": False,
            **self._model_params,
        }
        result = self._post_json(self._chat_completions_url, payload)
        return self._extract_message_content(result)

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Generate a streaming chat completion."""
        payload = {
            "model": self.model,
            "messages": history.messages,
            "stream": True,
            **self._model_params,
        }
        request = urllib.request.Request(
            self._chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = self._extract_delta_content(chunk)
                    if content:
                        yield content
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible stream failed with HTTP {exc.code}: {detail}") from exc

    def validate_connection(self) -> bool:
        """Validate that the configured server exposes a models endpoint."""
        request = urllib.request.Request(self._models_url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return 200 <= response.status < 300
        except Exception as exc:
            logger.warning(f"OpenAI-compatible connection validation failed for {self.base_url}: {exc}")
            return False

    @property
    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    @property
    def _models_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/models"
        return f"{self.base_url}/v1/models"

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible request failed with HTTP {exc.code}: {detail}") from exc

    def _extract_message_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return str(content)

    def _extract_delta_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if content is None:
            content = (choices[0].get("message") or {}).get("content")
        return str(content or "")


class LMStudioLLM(OpenAICompatibleLLM):
    """LM Studio client using its OpenAI-compatible local server."""

    provider: ClassVar[LLMProvider] = "lmstudio"
    DEFAULT_BASE_URL: ClassVar[str] = "http://localhost:1234/v1"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        supports_tool_calling: bool = False,
    ) -> None:
        """Create an LM Studio client using its local OpenAI-compatible API.

        Args:
            base_url: LM Studio server URL. If omitted, reads ``LMSTUDIO_URL``
                and falls back to ``http://localhost:1234/v1``.
            api_key: Optional bearer token. LM Studio accepts any value for
                local use, so ``"lm-studio"`` is used when no key is supplied.
            headers: Extra request headers merged into every request.
            model: Model id selected in LM Studio.
            model_params: Generation parameters such as ``temperature``.
            supports_tool_calling: Whether this model/server setup supports
                native tool calling.
        """
        super().__init__(
            base_url=base_url or os.getenv("LMSTUDIO_URL") or self.DEFAULT_BASE_URL,
            api_key=api_key or os.getenv("LMSTUDIO_API_KEY") or "lm-studio",
            headers=headers,
            model=model,
            model_params=model_params,
            supports_tool_calling=supports_tool_calling,
        )
