from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget

from .base import Flow


class Pipeline(Flow):
    """A linear pipeline that passes a Task through a sequence of steps deterministically.

    This provides functionality similar to LangChain's chains, allowing structured,
    fixed-path flows without LLM overhead. It ensures the task state is consecutively
    passed and enriched by each step in the pipeline.

    Steps can be:
    - **Local Agents**: Direct method calls to an `Agent` instance.
    - **Remote Agents**: Identifiers (strings) resolved via registry and called via A2A.
    - **Nested Flows**: Other `Flow` instances (e.g., `Parallel`, `Router`) enabling
      complex hierachical orchestration.

    Pipeline supports both upfront initialization via `steps` and dynamic chaining
    via the `add_step` fluid API.
    """

    def __init__(
        self,
        steps: list[FlowTarget] | None = None,
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the linear pipeline with a sequence of steps.

        Args:
            steps: An ordered list of `Agent` instances, agent names/URLs as strings,
                or nested `Flow` instances.
            client: An optional `AgentClient` for making remote calls. If omitting and making
                remote calls, it will attempt to infer from the registry.
            registry: Optional registry configuration to discover string-based agents by name.
        """
        super().__init__(client=client, registry=registry)
        self.steps = steps or []

    def add_step(self, step: FlowTarget) -> "Pipeline":
        """Add a step to the pipeline.

        Args:
            step: The agent, URL, or nested flow to add to the pipeline.

        Returns:
            The Pipeline instance for chaining.
        """
        self.steps.append(step)
        return self

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
            current_task = await self._execute_target(step, current_task)

        return current_task
