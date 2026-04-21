from protolink.agents.base import Agent
from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task

from .base import Flow


class Pipeline(Flow):
    """A linear pipeline that passes a Task through a sequence of Agents deterministically.

    This provides functionality similar to LangChain's chains, allowing structured,
    fixed-path flows without LLM overhead. It ensures the task state is consecutively
    passed and enriched by each step in the pipeline.
    """

    def __init__(
        self,
        steps: list[Agent | str],
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the linear pipeline with a sequence of steps.

        Args:
            steps: An ordered list of `Agent` instances for local execution, or agent names/URLs
                as strings for remote remote A2A calls.
            client: An optional `AgentClient` for making remote calls. If omitting and making
                remote calls, it will attempt to infer from the registry.
            registry: Optional registry configuration to discover string-based agents by name.
        """
        super().__init__(client=client, registry=registry)
        self.steps = steps

    async def execute(self, task: Task) -> Task:
        """Execute the task sequentially through the defined steps.

        Args:
            task: The initial state `Task` object.

        Returns:
            The fully processed `Task` object containing all accumulated artifacts and messages
            appended by each sequential step in the pipeline.
        """
        current_task = task

        for step in self.steps:
            if isinstance(step, Agent):
                self._logger.info(f"Pipeline executing local agent -> {step.card.name}")
                current_task = await step.handle_task(current_task)
            elif isinstance(step, str):
                self._ensure_client()

                agent_url = await self._resolve_agent_url(step)
                self._logger.info(f"Pipeline delegating task to remote agent -> {agent_url}")
                assert self.client is not None
                current_task = await self.client.send_task(agent_url, current_task)
            else:
                raise ValueError(f"Invalid pipeline step type: {type(step)}")

        return current_task
