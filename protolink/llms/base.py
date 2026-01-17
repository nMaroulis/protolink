from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from protolink.llms.prompts import AGENT_LIST_PROMPT, BASE_INSTRUCTIONS, BASE_SYSTEM_PROMPT, TOOL_CALL_PROMPT
from protolink.models import Message, Part
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
        # Initiate System Prompt
        self.system_prompt = self.build_system_prompt()

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

    @abstractmethod
    def infer_model(self, query: str) -> Part:
        """Generate a response using the infer model.

        Should return a Part with PartType 'infer_result'
        """
        raise NotImplementedError

    def build_system_prompt(
        self,
        user_instructions: str | None = None,
        agent_cards: str | None = None,
        tools: str | None = None,
        *,
        override_system_prompt: bool = False,
    ) -> str:
        """
        Build the final system prompt for the LLM.

        This function combines:
        - Base agent instructions
        - Tool calling prompt
        - Agent delegation prompt
        - User-provided instructions

        If any of the optional parameters are not provided, they will be omitted from the final prompt.

        Args:
            user_instructions: Optional instructions from the user to customize behavior.
            agent_cards: JSON/text describing available agents for delegation.
            tools: JSON/text describing available tools for this agent.
            override_system_prompt: Whether to override comletely the system prompt with the user defined prompt.

        Returns:
            A fully assembled, machine-readable prompt string suitable for sending to the LLM.

        Example:
            >>> user_instructions = "Always use the weather tool first if the user asks about weather."
            >>> agent_cards = '[{"name": "weather_forecaster", "tools": ["get_weather"]}]'
            >>> tools = '[{"name": "get_weather", "args": ["location"]}]'
            >>> prompt = build_system_prompt(user_instructions, agent_cards, tools)
            >>> print(prompt[:500])  # preview the first 500 characters
        """

        if override_system_prompt:
            self.system_prompt = user_instructions
        else:
            self.system_prompt = BASE_SYSTEM_PROMPT.format(
                base_instructions=BASE_INSTRUCTIONS,
                tool_call_prompt=TOOL_CALL_PROMPT.replace("{{tools}}", tools) if tools else "",
                agent_call_prompt=AGENT_LIST_PROMPT.replace("{{agent_cards_from_registry}}", agent_cards)
                if agent_cards
                else "",
                user_instructions=user_instructions or "",
            )
        return self.system_prompt
