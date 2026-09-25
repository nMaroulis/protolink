import contextvars
import os
from dataclasses import dataclass, replace
from typing import Any

from protolink.models import Part, Task
from protolink.telemetry._deps import require_langfuse
from protolink.telemetry.base import Telemetry
from protolink.utils.logging import get_logger

logger = get_logger("protolink.telemetry.langfuse")


@dataclass(frozen=True)
class _TaskObservations:
    span: Any = None
    generation: Any = None
    tool: Any = None


class LangfuseTelemetry(Telemetry):
    """Langfuse implementation for Protolink telemetry.

    This class tracks agent tasks as traces, and LLM/Tool executions as spans or
    generations within those traces. It utilizes `contextvars` to manage the active
    trace and span states asynchronously, ensuring a non-invasive integration
    without the need to pass context objects through the execution chain.
    """

    def __init__(self, public_key: str | None = None, secret_key: str | None = None, host: str | None = None) -> None:
        """Initializes the Langfuse telemetry tracker.

        Args:
            public_key (str | None): The Langfuse public key. Defaults to the `LANGFUSE_PUBLIC_KEY` environment variable
            secret_key (str | None): The Langfuse secret key. Defaults to the `LANGFUSE_SECRET_KEY` environment variable
            host (str | None): API URL. Defaults to `LANGFUSE_BASE_URL`, then `LANGFUSE_HOST`, then Langfuse Cloud.

        Raises:
            ImportError: If the `langfuse` package is not installed.
        """
        _, langfuse = require_langfuse()

        self.langfuse = langfuse(
            public_key=public_key or os.environ.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=secret_key or os.environ.get("LANGFUSE_SECRET_KEY"),
            base_url=host
            or os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        # Immutable frames keep copied async contexts independent. A stack also
        # restores the caller's observations after a nested agent task completes.
        self._tasks = contextvars.ContextVar[tuple[_TaskObservations, ...]]("langfuse_tasks", default=())

    def _current(self) -> _TaskObservations:
        tasks = self._tasks.get()
        return tasks[-1] if tasks else _TaskObservations()

    def _update_current(self, **changes: Any) -> None:
        tasks = self._tasks.get()
        if tasks:
            self._tasks.set((*tasks[:-1], replace(tasks[-1], **changes)))

    async def on_task_start(self, task: Task, agent_name: str) -> Any:
        """Starts a new Langfuse trace for the given task.

        Args:
            task (Task): The task being processed.
            agent_name (str): The name of the agent handling the task.

        Returns:
            Any: None.
        """
        # Push even if the SDK fails, so child hooks cannot attach to an outer task.
        self._tasks.set((*self._tasks.get(), _TaskObservations()))
        try:
            trace = self.langfuse.start_observation(
                name=f"Task: {agent_name}",
                as_type="span",
                trace_context={"trace_id": self.langfuse.create_trace_id(seed=task.id)},
                metadata={"agent_name": agent_name, "task_id": task.id},
            )
            self._update_current(span=trace)
        except Exception as e:
            logger.warning(f"Failed to start Langfuse trace: {e}")

    async def on_task_end(self, task: Task, result: Task, agent_name: str) -> Any:
        """Ends the active Langfuse trace and logs the final output.

        Args:
            task (Task): The original task.
            result (Task): The completed task containing the output.
            agent_name (str): The name of the agent.

        Returns:
            Any: None.
        """
        tasks = self._tasks.get()
        if not tasks:
            return
        trace = tasks[-1].span
        self._tasks.set(tasks[:-1])
        if trace is None:
            return
        try:
            try:
                trace.update(output=result.to_dict() if hasattr(result, "to_dict") else str(result))
            finally:
                trace.end()
            self.langfuse.flush()
        except Exception as e:
            logger.warning(f"Failed to end Langfuse trace: {e}")

    async def on_llm_start(
        self,
        prompt: str,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Starts a new generation span within the active Langfuse trace.

        Args:
            prompt (str): The input prompt for the LLM.
            model (str | None): The model identifier.

        Returns:
            Any: None.
        """
        trace = self._current().span
        if trace is None:
            return
        self._update_current(generation=None)
        try:
            generation = trace.start_observation(
                name="LLM Call",
                as_type="generation",
                model=model,
                input=prompt,
                metadata=metadata or None,
            )
            self._update_current(generation=generation)
        except Exception as e:
            logger.warning(f"Failed to start Langfuse LLM generation: {e}")

    async def on_llm_end(self, response: Part) -> Any:
        """Ends the active LLM generation span and logs the response.

        Args:
            response (Part): The response part generated by the LLM.

        Returns:
            Any: None.
        """
        generation = self._current().generation
        if generation is None:
            return
        self._update_current(generation=None)
        try:
            try:
                output = response.content if hasattr(response, "content") else str(response)
                generation.update(output=output)
            finally:
                generation.end()
        except Exception as e:
            logger.warning(f"Failed to end Langfuse LLM generation: {e}")

    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Starts a new tool execution span within the active Langfuse trace.

        Args:
            tool_name (str): The name of the tool.
            args (dict[str, Any]): The arguments provided to the tool.

        Returns:
            Any: None.
        """
        trace = self._current().span
        if trace is None:
            return
        self._update_current(tool=None)
        try:
            span = trace.start_observation(
                name=f"Tool: {tool_name}",
                as_type="span",
                input=args,
            )
            self._update_current(tool=span)
        except Exception as e:
            logger.warning(f"Failed to start Langfuse tool span: {e}")

    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
        """Ends the active tool span, logging the result or error.

        Args:
            tool_name (str): The name of the tool.
            result (Any): The output of the tool execution.
            error (str | None): Any error message if the tool failed.

        Returns:
            Any: None.
        """
        span = self._current().tool
        if span is None:
            return
        self._update_current(tool=None)
        try:
            try:
                if error:
                    span.update(level="ERROR", status_message=error)
                else:
                    span.update(output=result)
            finally:
                span.end()
        except Exception as e:
            logger.warning(f"Failed to end Langfuse tool span: {e}")
