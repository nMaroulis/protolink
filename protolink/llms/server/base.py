from typing import Any, ClassVar

from protolink.llms.base import LLM, LLMType


class ServerLLM(LLM):
    """Base class for server-based LLM implementations.

    This is for models that run on a self-hosted or remote server rather than via an API library.
    """

    model_type: ClassVar[LLMType] = "server"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url
        merged_params = model_params or {}
        super().__init__(model=model, model_params=merged_params)

    def validate_connection(self) -> bool:
        """Validate LLM Server connection - to be implemented by subclasses."""
        raise NotImplementedError
