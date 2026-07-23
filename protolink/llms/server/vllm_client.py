from __future__ import annotations

from typing import Any, ClassVar

from protolink.llms.server.openai_compatible_client import OpenAICompatibleLLM
from protolink.types import LLMProvider


class VLLMLLM(OpenAICompatibleLLM):
    """vLLM client using its OpenAI-compatible server.

    The model name is required because vLLM uses the model passed to
    ``vllm serve`` (or its configured served-model alias) as the request id.
    Native tool calling remains opt-in because it also depends on the served
    model and vLLM's tool-call parser configuration.
    """

    provider: ClassVar[LLMProvider] = "vllm"
    DEFAULT_BASE_URL: ClassVar[str] = "http://localhost:8000/v1"
    BASE_URL_ENV: ClassVar[str] = "VLLM_URL"
    API_KEY_ENV: ClassVar[str] = "VLLM_API_KEY"

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        model_params: dict[str, Any] | None = None,
        supports_tool_calling: bool = False,
    ) -> None:
        """Create a client for a vLLM OpenAI-compatible server.

        Args:
            model: Model id or served-model alias exposed by vLLM.
            base_url: Server URL. Reads ``VLLM_URL`` before falling back to
                ``http://localhost:8000/v1``.
            api_key: Optional bearer token. Reads ``VLLM_API_KEY`` when omitted.
            headers: Extra request headers merged into every request.
            model_params: Generation parameters forwarded to vLLM.
            supports_tool_calling: Whether the vLLM server and model are
                configured for native tool calling.
        """
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            headers=headers,
            model=model,
            model_params=model_params,
            supports_tool_calling=supports_tool_calling,
        )
