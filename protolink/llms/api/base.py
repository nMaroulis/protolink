from typing import Any, ClassVar

from protolink.llms.base import LLM
from protolink.types import LLMType


class APILLM(LLM):
    """Base class for API-based LLM implementations."""

    model_type: ClassVar[LLMType] = "api"

    def __init__(
        self,
        *,
        model: str,
        model_params: dict[str, Any],
        base_url: str | None = None,
    ) -> None:
        self.base_url = base_url
        super().__init__(
            model=model,
            model_params=model_params,
        )

    def validate_connection(self) -> bool:
        """Validate API connection - to be implemented by subclasses."""
        raise NotImplementedError
