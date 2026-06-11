from abc import ABC, abstractmethod
from typing import Any

from protolink.models import Part, Task


class Telemetry(ABC):
    """Abstract base class for all telemetry implementations in Protolink.

    This class defines the standard hooks for tracing tasks, LLM inferences,
    and tool executions. Implementations of this class should use context
    variables (`contextvars`) or similar mechanisms to manage state and hierarchy,
    ensuring a non-invasive integration with the agent's core execution loop.
    """

    @abstractmethod
    async def on_task_start(self, task: Task, agent_name: str) -> Any:
        """Called when an agent starts processing a task.

        Args:
            task (Task): The task object that the agent is about to process.
            agent_name (str): The name of the agent processing the task.

        Returns:
            Any: An optional provider-specific context or identifier (e.g., a Trace object).
        """
        pass

    @abstractmethod
    async def on_task_end(self, task: Task, result: Task, agent_name: str) -> Any:
        """Called when an agent finishes processing a task.

        Args:
            task (Task): The original task object that was processed.
            result (Task): The resulting task object after processing, containing the outcome.
            agent_name (str): The name of the agent that processed the task.

        Returns:
            Any: An optional provider-specific context or identifier.
        """
        pass

    @abstractmethod
    async def on_llm_start(self, prompt: str, model: str | None = None) -> Any:
        """Called before making an inference call to an LLM.

        Args:
            prompt (str): The complete prompt string being sent to the LLM.
            model (str | None): The identifier of the model being invoked, if available.

        Returns:
            Any: An optional provider-specific context or identifier (e.g., a Generation object).
        """
        pass

    @abstractmethod
    async def on_llm_end(self, response: Part) -> Any:
        """Called after an inference call to an LLM completes.

        Args:
            response (Part): The generated response part returned by the LLM.

        Returns:
            Any: An optional provider-specific context or identifier.
        """
        pass

    @abstractmethod
    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Called before executing a tool.

        Args:
            tool_name (str): The registered name of the tool being executed.
            args (dict[str, Any]): The keyword arguments passed to the tool.

        Returns:
            Any: An optional provider-specific context or identifier (e.g., a Span object).
        """
        pass

    @abstractmethod
    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
        """Called after a tool execution completes.

        Args:
            tool_name (str): The registered name of the tool that was executed.
            result (Any): The output returned by the tool execution. Will be None if an error occurred.
            error (str | None): A string representation of the error if the execution failed, else None.

        Returns:
            Any: An optional provider-specific context or identifier.
        """
        pass
