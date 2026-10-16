import contextvars
import os
import uuid
from dataclasses import dataclass, replace
from typing import Any

from protolink.models import Part, Task
from protolink.telemetry._deps import require_langsmith
from protolink.telemetry.base import Telemetry
from protolink.utils.logging import get_logger

logger = get_logger("protolink.telemetry.langsmith")


@dataclass(frozen=True)
class _TaskRuns:
    run: Any = None
    llm: Any = None
    tool: Any = None


class LangSmithTelemetry(Telemetry):
    """LangSmith implementation for Protolink telemetry.

    This class tracks agent tasks as runs using the LangSmith `RunTree` API,
    creating a hierarchical execution tree. It automatically handles child runs
    for LLM inferences and tool executions, utilizing `contextvars` to manage
    asynchronous state without modifying agent method signatures.
    """

    def __init__(self, api_key: str | None = None, project_name: str | None = None) -> None:
        """Initializes the LangSmith telemetry tracker.

        Args:
            api_key (str | None): The LangSmith API key. Defaults to `LANGSMITH_API_KEY`, then `LANGCHAIN_API_KEY`.
            project_name (str | None): Defaults to `LANGSMITH_PROJECT`, then `LANGCHAIN_PROJECT` or "default".

        Raises:
            ImportError: If the `langsmith` package is not installed.
        """
        _, client, _ = require_langsmith()

        self.client = client(
            api_key=api_key or os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
        )
        self.project_name = (
            project_name or os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT", "default")
        )
        # Immutable task frames isolate tracker instances and copied async
        # contexts, while restoring the caller after a nested task completes.
        self._tasks = contextvars.ContextVar[tuple[_TaskRuns, ...]]("langsmith_tasks", default=())

    def _current(self) -> _TaskRuns:
        tasks = self._tasks.get()
        return tasks[-1] if tasks else _TaskRuns()

    def _update_current(self, **changes: Any) -> None:
        tasks = self._tasks.get()
        if tasks:
            self._tasks.set((*tasks[:-1], replace(tasks[-1], **changes)))

    async def on_task_start(self, task: Task, agent_name: str) -> Any:
        """Starts a new LangSmith run for the given task.

        Args:
            task (Task): The task being processed.
            agent_name (str): The name of the agent handling the task.

        Returns:
            Any: None.
        """
        _, _, run_tree = require_langsmith()
        # A failed child start must not leave hooks attached to an outer task.
        self._tasks.set((*self._tasks.get(), _TaskRuns()))
        try:
            run = run_tree(
                name=f"Task: {agent_name}",
                run_type="chain",
                project_name=self.project_name,
                inputs={"task_id": task.id if hasattr(task, "id") else str(uuid.uuid4())},
                extra={"metadata": {"agent_name": agent_name}},
                client=self.client,
            )
            run.post()
            self._update_current(run=run)
        except Exception as e:
            logger.warning(f"Failed to start LangSmith run: {e}")

    async def on_task_end(self, task: Task, result: Task, agent_name: str) -> Any:
        """Ends the active LangSmith run and updates it with the final task output.

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
        run = tasks[-1].run
        self._tasks.set(tasks[:-1])
        if run is None:
            return
        try:
            run.end(outputs=result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)})
            run.patch()
        except Exception as e:
            logger.warning(f"Failed to end LangSmith run: {e}")

    async def on_llm_start(
        self,
        prompt: str,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Starts a child run for an LLM inference within the active task's run.

        Args:
            prompt (str): The input prompt for the LLM.
            model (str | None): The model identifier.

        Returns:
            Any: None.
        """
        parent_run = self._current().run
        if parent_run is None:
            return
        self._update_current(llm=None)
        try:
            llm_run = parent_run.create_child(
                name="LLM Call",
                run_type="llm",
                inputs={"prompt": prompt, "model": model, "metadata": metadata or {}},
            )
            llm_run.post()
            self._update_current(llm=llm_run)
        except Exception as e:
            logger.warning(f"Failed to start LangSmith LLM run: {e}")

    async def on_llm_end(self, response: Part) -> Any:
        """Ends the active LLM child run and logs the generated response.

        Args:
            response (Part): The response part generated by the LLM.

        Returns:
            Any: None.
        """
        llm_run = self._current().llm
        if llm_run is None:
            return
        self._update_current(llm=None)
        try:
            output = response.content if hasattr(response, "content") else str(response)
            llm_run.end(outputs={"response": output})
            llm_run.patch()
        except Exception as e:
            logger.warning(f"Failed to end LangSmith LLM run: {e}")

    async def on_tool_start(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Starts a child run for a tool execution within the active task's run.

        Args:
            tool_name (str): The name of the tool.
            args (dict[str, Any]): The arguments provided to the tool.

        Returns:
            Any: None.
        """
        parent_run = self._current().run
        if parent_run is None:
            return
        self._update_current(tool=None)
        try:
            tool_run = parent_run.create_child(
                name=f"Tool: {tool_name}",
                run_type="tool",
                inputs=args,
            )
            tool_run.post()
            self._update_current(tool=tool_run)
        except Exception as e:
            logger.warning(f"Failed to start LangSmith tool run: {e}")

    async def on_tool_end(self, tool_name: str, result: Any, error: str | None = None) -> Any:
        """Ends the active tool child run, logging the result or error.

        Args:
            tool_name (str): The name of the tool.
            result (Any): The output of the tool execution.
            error (str | None): Any error message if the tool failed.

        Returns:
            Any: None.
        """
        tool_run = self._current().tool
        if tool_run is None:
            return
        self._update_current(tool=None)
        try:
            if error:
                tool_run.end(error=error)
            else:
                tool_run.end(outputs={"result": result})
            tool_run.patch()
        except Exception as e:
            logger.warning(f"Failed to end LangSmith tool run: {e}")
