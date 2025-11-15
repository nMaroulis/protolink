from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Literal, TypeAlias

from protolink.core.message import Message

LLMType: TypeAlias = Literal["api", "local", "remote"]
LLMProvider: TypeAlias = Literal["openai", "anthropic", "google", "llama.cpp"]


class LLM(ABC):
    """Base class for LLMs."""

    def __init__(self, model_type: LLMType, provider: LLMProvider, model_name: str | None = None) -> None:
        self.model_type = model_type
        self.provider = provider
        self.model_name = model_name

    @abstractmethod
    def generate(self, messages: list[Message]) -> Message:
        """Generate a response from the LLM."""
        raise NotImplementedError

    @abstractmethod
    def generate_stream(self, messages: list[Message]) -> Iterable[Message]:
        """Generate a response from the LLM."""
        raise NotImplementedError
