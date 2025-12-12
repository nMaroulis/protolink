from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from protolink.models import Message
from protolink.types import LLMProvider, LLMType


class LLM(ABC):
    """Base class for all LLM implementations."""

    model_type: LLMType
    provider: LLMProvider
    model: str
    model_params: dict[str, Any]
    system_prompt: str

    def __init__(self) -> None:
        self.model_type = self.__class__.model_type
        self.provider = self.__class__.provider
        self.model = self.__class__.model
        self.model_params = self.__class__.model_params
        self.system_prompt = self.__class__.system_prompt

    @abstractmethod
    def generate_response(self, messages: list[Message]) -> Message:
        raise NotImplementedError

    @abstractmethod
    def generate_stream_response(self, messages: list[Message]) -> Iterable[Message]:
        raise NotImplementedError

    @abstractmethod
    def set_model_params(self, model_params: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_system_prompt(self, system_prompt: str) -> None:
        raise NotImplementedError

    def __str__(self) -> str:
        return f"{self.provider} {self.model_type}"

    def __repr__(self) -> str:
        return self.__str__()

    @abstractmethod
    def validate_connection(self) -> bool:
        """Validate the connection to the LLM API, should handle the logging."""
        raise NotImplementedError
