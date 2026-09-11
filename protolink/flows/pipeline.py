from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget

from .base import Flow
from .limits import WorkflowLimitError, workflow_execution


class Pipeline(Flow):
    """A linear pipeline that passes a Task through a sequence of steps deterministically.

    This provides functionality similar to LangChain's chains, allowing structured,
    fixed-path flows without LLM overhead. It ensures the task state is consecutively
    passed and enriched by each step in the pipeline.

    Steps can be:
    - **Local Agents**: Direct method calls to an `Agent` instance.
    - **Remote Agents**: Identifiers resolved via registry and called through a configured transport.
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
        *,
        max_steps: int | None = None,
    ) -> None:
        """Initialize the linear pipeline with a sequence of steps.

        Args:
            steps: An ordered list of `Agent` instances, agent names/URLs as strings,
                or nested `Flow` instances.
            client: An optional `AgentClient` for making remote calls. If omitting and making
                remote calls, it will attempt to infer from the registry.
            registry: Optional registry configuration to discover string-based agents by name.
            max_steps: Optional traversal ceiling checked before dispatching another step.
                This is separate from the shared native RunBudget step counter.
        """
        super().__init__(client=client, registry=registry)
        self.steps = steps or []
        if max_steps is not None and max_steps < 0:
            raise ValueError("max_steps cannot be negative")
        self.max_steps = max_steps

    def add_step(self, step: FlowTarget) -> "Pipeline":
        """Add a step to the pipeline.

        Args:
            step: The agent, URL, or nested flow to add to the pipeline.

        Returns:
            The Pipeline instance for chaining.
        """
        self.steps.append(step)
        return self

    @workflow_execution
    async def execute(self, task: Task) -> Task:
        """Execute the task sequentially through the defined steps.

        This method implements Semantic Context Injection. Before executing each step, the Pipeline analyzes the
        topology to identify the subsequent step. It pre-builds a context-aware LLM prompt using `_build_flow_prompt`
        and populates `task.flow_state["prompt"]`. This allows the executing agent to dynamically format its
        output specifically for the downstream receiver without knowing the flow's internal structure.

        Args:
            task: The initial state `Task` object.

        Returns:
            The fully processed `Task` object containing all accumulated artifacts and messages
            appended by each sequential step in the pipeline.
        """
        current_task = task

        for idx, step in enumerate(self.steps):
            if self.max_steps is not None and idx >= self.max_steps:
                raise WorkflowLimitError(limit=self.max_steps, observed=idx + 1)
            # Check if there is a subsequent target step
            next_target = None
            if idx + 1 < len(self.steps):
                next_target = self.steps[idx + 1]

            # Populate task flow_state with pre-built flow instructions
            # This ensures flow_state is perfectly JSON-serializable and prevents deepcopy bugs.
            current_task.flow_state.clear()

            if next_target:
                current_task.flow_state["prompt"] = await self._build_flow_prompt(next_target=next_target)
            else:
                current_task.flow_state["prompt"] = await self._build_flow_prompt(is_final=True)

            current_task = await self._execute_target(step, current_task)
            if current_task.state.value in {"failed", "canceled", "input_required"}:
                return current_task

        return current_task
