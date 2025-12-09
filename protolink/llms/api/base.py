from typing import Any

from protolink.llms.base import LLM, LLMProvider, LLMType


class APILLM(LLM):
    """Base class for API-based LLM implementations."""

    model_type: LLMType = "api"
    base_url: str | None = None
    provider: LLMProvider

    def __init__(self) -> None:
        self.model_type = self.__class__.model_type
        self.provider = self.__class__.provider

    def set_model_params(self, model_params: dict[str, Any]) -> None:
        """Update existing model parameters, ignoring any extra keys."""
        valid_params = {k: v for k, v in model_params.items() if k in self.model_params}
        self.model_params.update(valid_params)

    def set_system_prompt(self, system_prompt: str) -> None:
        """Set the system prompt for the model."""
        self.system_prompt = system_prompt

    def validate_connection(self) -> bool:
        """Validate API connection - to be implemented by subclasses."""
        raise NotImplementedError
