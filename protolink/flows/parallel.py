import asyncio

from protolink.agents.base import Agent
from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task

from .base import Flow


class Parallel(Flow):
    """A Flow that executes multiple agents concurrently.

    Similar to LangChain's RunnableParallel, this allows fan-out/fan-in execution.
    The primary Task is sent identically to all requested agents simultaneously.
    Once all agents complete their processing, their resulting Artifacts and
    Messages are aggregated back into the single original Task instance.
    """

    def __init__(
        self,
        branches: list[Agent | str],
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the parallel flow.

        Args:
            branches: A list of `Agent` instances or string agent names/URLs to be
                executed concurrently.
            client: Optional `AgentClient` for resolving remote string-based agents.
            registry: Optional registry configuration for discovering agent dependencies.
        """
        super().__init__(client=client, registry=registry)
        self.branches = branches

    async def execute(self, task: Task) -> Task:
        """Execute the task concurrently across all branches.

        Args:
            task: The `Task` to be processed. Passed independently to all branches.

        Returns:
            A unified `Task` object containing the aggregated messages and artifacts
            from all branches. The objects are appended in the order the branches
            were defined.
        """
        self._logger.info(f"Parallel flow fanning out to {len(self.branches)} branches...")

        # We need to guarantee remote clients are prepared
        if any(isinstance(b, str) for b in self.branches):
            self._ensure_client()

        cors = []
        for branch in self.branches:
            if isinstance(branch, Agent):
                cors.append(self._execute_local(branch, task))
            elif isinstance(branch, str):
                cors.append(self._execute_remote(branch, task))
            else:
                raise ValueError(f"Invalid parallel branch type: {type(branch)}")

        # Execute all coroutines concurrently
        results: list[Task] = await asyncio.gather(*cors, return_exceptions=False)

        # Aggregate logic: Merge newly appended artifacts/messages from all branches
        # back into the original 'task' effectively fanning-in.

        # Calculate exactly which items were added by comparing lengths
        original_messages_len = len(task.messages)
        original_artifacts_len = len(task.artifacts)

        for result_task in results:
            # Note: task state may diverge across forks, but we fetch precisely what were NEW additions
            if len(result_task.messages) > original_messages_len:
                for msg in result_task.messages[original_messages_len:]:
                    task.add_message(msg)

            if len(result_task.artifacts) > original_artifacts_len:
                for art in result_task.artifacts[original_artifacts_len:]:
                    task.add_artifact(art)

        self._logger.info("Parallel flow fan-in complete.")
        return task

    async def _execute_local(self, agent: Agent, task: Task) -> Task:
        """Helper to cleanly wrap local execution."""
        return await agent.handle_task(task)

    async def _execute_remote(self, name_or_url: str, task: Task) -> Task:
        """Helper to cleanly wrap remote execution."""
        url = await self._resolve_agent_url(name_or_url)
        assert self.client is not None
        return await self.client.send_task(url, task)
