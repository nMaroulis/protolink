import asyncio
import copy

from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget

from .base import Flow


class Parallel(Flow):
    """A Flow that executes multiple targets concurrently.

    Similar to LangChain's RunnableParallel, this allows fan-out/fan-in execution.
    The primary Task is sent identically to all requested branches simultaneously.
    Once all branches complete their processing, their resulting Artifacts and
    Messages are aggregated back into the single original Task instance.

    Key Features:
    - **Safe Fan-in**: Uses unique `id` tracking for Messages and Artifacts to ensure
      that only strictly new additions from each branch are merged, avoiding data
      duplication or array index collisions.
    - **Nested Execution**: Branches can be local Agents, remote URLs, or nested
      Flows (e.g., a Pipeline inside a Parallel branch).
    """

    def __init__(
        self,
        branches: list[FlowTarget],
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the parallel flow.

        Args:
            branches: A list of `Agent` instances, agent names/URLs as strings,
                or nested `Flow` instances to be executed concurrently.
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

        # Find strictly new items by ID diffing
        existing_message_ids = {m.id for m in task.messages}
        existing_artifact_ids = {a.id for a in task.artifacts}

        # Fix #4: Deep-copy the task for each branch to prevent race conditions
        cors = [self._execute_target(branch, copy.deepcopy(task)) for branch in self.branches]

        # Execute all coroutines concurrently
        results: list[Task] = await asyncio.gather(*cors, return_exceptions=False)

        # Aggregate logic: Merge newly appended artifacts/messages from all branches
        # back into the original 'task' effectively fanning-in.
        for result_task in results:
            for msg in result_task.messages:
                if msg.id not in existing_message_ids:
                    task.add_message(msg)
                    existing_message_ids.add(msg.id)

            for art in result_task.artifacts:
                if art.id not in existing_artifact_ids:
                    task.add_artifact(art)
                    existing_artifact_ids.add(art.id)

            # Merge metadata
            task.metadata.update(result_task.metadata)

        self._logger.info("Parallel flow fan-in complete.")
        return task
