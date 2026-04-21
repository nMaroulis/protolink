from collections.abc import Callable

from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget

from .base import Flow


class Router(Flow):
    """A flow step that enforces conditional branching based on task state.

    Calculates dynamic routing explicitly instead of relying on unpredictable LLM inference.
    Similar to LangChain's RunnableBranch or conditional routing mechanisms.

    Routing destinations can be:
    - **Agent instances**: Local execution.
    - **URL strings**: Remote A2A execution.
    - **Nested Flows**: Sub-orchestration logic.
    """

    def __init__(
        self,
        routes: dict[str, FlowTarget],
        condition_fn: Callable[[Task], str],
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize the dynamic router.

        Args:
            routes: A dictionary mapping potential string conditions to their respective
                Agent, URLs, or nested nested Flows.
            condition_fn: A synchronous callable that receives the current `Task` and
                evaluates it, returning a mapped string key that must exist in `routes`.
            client: Optional `AgentClient` for executing remote paths.
            registry: Optional registry configuration for discovery.
        """
        super().__init__(client=client, registry=registry)
        self.routes = routes
        self.condition_fn = condition_fn

    async def execute(self, task: Task) -> Task:
        """Execute the conditionally chosen branch.

        Args:
            task: The active `Task` state used for condition evaluation.

        Returns:
            The resulting `Task` object post-execution on the chosen route.

        Raises:
            ValueError: If the interpreted condition maps to an undefined route.
        """
        # Determine exactly which route to pursue
        next_route_key = self.condition_fn(task)

        self._logger.info(f"Router evaluated condition: routing to '{next_route_key}'")

        if next_route_key not in self.routes:
            raise ValueError(
                f"Router 'condition_fn' produced a key '{next_route_key}' "
                f"which does not exist in mapped routes: {list(self.routes.keys())}"
            )

        route_destination = self.routes[next_route_key]
        return await self._execute_target(route_destination, task)
