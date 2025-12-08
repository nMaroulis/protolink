from typing import Any

from protolink.llms.base import LLM, LLMProvider, LLMType


class ServerLLM(LLM):
    """Base class for Server-based LLM implementations."""

    model_type: LLMType = "server"
    provider: LLMProvider
    base_url: str

    def __init__(self, base_url: str) -> None:
        self.model_type = self.__class__.model_type
        self.provider = self.__class__.provider
        self.base_url = base_url

    def set_model_params(self, model_params: dict[str, Any]) -> None:
        """Update existing model parameters, ignoring any extra keys."""
        valid_params = {k: v for k, v in model_params.items() if k in self.model_params}
        self.model_params.update(valid_params)

    def set_system_prompt(self, system_prompt: str) -> None:
        """Set the system prompt for the model."""
        self.system_prompt = system_prompt

    def validate_connection(self) -> bool:
        """Validate that the server is reachable."""
        return True
